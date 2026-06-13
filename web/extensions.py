"""
Estado compartilhado e helpers da camada web.

Centraliza o que antes vivia no topo de ``web/app.py`` para que os blueprints
e o app factory consumam de um único lugar, sem dependências circulares:

- ``db``: gerenciador de banco (singleton, inicializado na importação)
- ``automation_state``: estado em memória de dados não-críticos (logs/resultados)
- ``add_log``: registro de logs da UI
- ``rate_limit``: decorator condicional de rate limiting
- ``emit_*``: notificações via WebSocket (quando disponível)
- flags de funcionalidades opcionais (rate limiting, websocket, métricas, etc.)

``limiter`` e ``socketio`` dependem do app Flask e são atribuídos pelo
``create_app()`` (em ``web/__init__.py``) após a criação do app.
"""

from datetime import datetime

from loguru import logger

from database import DatabaseManager

# ----------------------------------------------------------------------
# Flags de funcionalidades opcionais (determinadas por imports disponíveis)
# ----------------------------------------------------------------------
try:
    from flask_limiter import Limiter  # noqa: F401
    from flask_limiter.util import get_remote_address  # noqa: F401

    RATE_LIMITING_ENABLED = True
except ImportError:
    RATE_LIMITING_ENABLED = False
    logger.warning("flask-limiter não instalado. Rate limiting desabilitado.")

try:
    from web.websocket import create_socketio, get_websocket_notifier  # noqa: F401

    WEBSOCKET_ENABLED = True
except ImportError as e:
    WEBSOCKET_ENABLED = False
    logger.warning(f"WebSocket não disponível: {e}. Usando polling.")
except Exception as e:
    WEBSOCKET_ENABLED = False
    logger.warning(f"WebSocket erro: {type(e).__name__}: {e}. Usando polling.")

try:
    from utils.metrics import get_metrics_collector, init_metrics  # noqa: F401

    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    logger.warning("Prometheus metrics não disponível.")

try:
    from utils.ab_testing import get_ab_manager, setup_default_experiments  # noqa: F401

    AB_TESTING_ENABLED = True
except ImportError:
    AB_TESTING_ENABLED = False
    logger.warning("A/B Testing não disponível.")

try:
    from utils.audit_log import (  # noqa: F401
        AuditAction,
        audit_automation_start,
        audit_automation_stop,
        get_audit_logger,
    )

    AUDIT_ENABLED = True
except ImportError:
    AUDIT_ENABLED = False
    logger.warning("Audit logging não disponível.")

try:
    from utils.background_tasks import (  # noqa: F401
        get_task_manager,
        schedule_task,
        submit_task,
    )

    BACKGROUND_TASKS_ENABLED = True
except ImportError:
    BACKGROUND_TASKS_ENABLED = False
    logger.warning("Background Tasks não disponível.")


# ----------------------------------------------------------------------
# Banco de dados (singleton, inicializado na importação)
# ----------------------------------------------------------------------
db = DatabaseManager()
db.initialize()


# ----------------------------------------------------------------------
# Extensões atribuídas pelo create_app() (dependem do app Flask)
# ----------------------------------------------------------------------
limiter = None
socketio = None


def rate_limit(limit_string):
    """Decorator condicional de rate limiting (no-op se limiter ausente)."""

    def decorator(f):
        if limiter:
            return limiter.limit(limit_string)(f)
        return f

    return decorator


# ----------------------------------------------------------------------
# Estado em memória para dados NÃO-CRÍTICOS (logs, resultados)
# O estado de is_running/is_syncing é gerenciado pelo AutomationStateManager
# (persistido em arquivo); aqui ficam apenas dados efêmeros.
# ----------------------------------------------------------------------
automation_state = {
    "is_running": False,
    "is_syncing": False,
    "last_result": None,
    "last_sync_result": None,
    "logs": [],
}


def add_log(message: str, level: str = "info"):
    """Adiciona log ao estado em memória e ao logger persistente."""
    automation_state["logs"].append(
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "level": level,
        }
    )
    if len(automation_state["logs"]) > 100:
        automation_state["logs"] = automation_state["logs"][-100:]

    if level == "error":
        logger.error(f"[UI] {message}")
    elif level == "warning":
        logger.warning(f"[UI] {message}")
    elif level == "success":
        logger.success(f"[UI] {message}")
    else:
        logger.info(f"[UI] {message}")


# ----------------------------------------------------------------------
# Eventos WebSocket
# ----------------------------------------------------------------------
def emit_notification(notification_type: str, data: dict):
    """Emite notificação via WebSocket se disponível."""
    if WEBSOCKET_ENABLED and socketio:
        try:
            get_websocket_notifier().notify(notification_type, data)
        except Exception as e:
            logger.warning(f"Erro ao emitir WebSocket: {e}")


def emit_stats_update(stats: dict):
    """Emite atualização de estatísticas."""
    if WEBSOCKET_ENABLED and socketio:
        try:
            get_websocket_notifier().broadcast_stats(stats)
        except Exception as e:
            logger.warning(f"Erro ao emitir stats: {e}")


def emit_automation_status(status: dict):
    """Emite status da automação."""
    if WEBSOCKET_ENABLED and socketio:
        try:
            get_websocket_notifier().broadcast_automation_status(status)
        except Exception as e:
            logger.warning(f"Erro ao emitir automation status: {e}")


def _sync_matches_task():
    """Task de sincronização de matches para execução em background."""
    import asyncio

    from automation import sync_matches_only

    automation_state["is_syncing"] = True
    add_log("🔄 [Background] Sincronização iniciada...", "info")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(sync_matches_only())
        loop.close()

        automation_state["last_sync_result"] = result

        if result.get("success"):
            add_log(
                f"✅ [Background] Sync concluído! Matches: {result.get('total_matches', 0)}, "
                f"Novos: {result.get('new_matches', 0)}",
                "success",
            )
            if WEBSOCKET_ENABLED:
                try:
                    get_websocket_notifier().emit_notification(
                        {
                            "type": "sync_completed",
                            "title": "Sincronização Concluída",
                            "message": f"Encontrados {result.get('new_matches', 0)} novos matches!",
                            "data": result,
                        }
                    )
                except Exception:
                    pass
        else:
            add_log(f"❌ [Background] Erro no sync: {result.get('error', 'Desconhecido')}", "error")
        return result

    except Exception as e:
        error_result = {"success": False, "error": str(e)}
        automation_state["last_sync_result"] = error_result
        add_log(f"❌ [Background] Erro: {str(e)}", "error")
        return error_result

    finally:
        automation_state["is_syncing"] = False
