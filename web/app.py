"""
Interface Web para o Automatic Tinder Chat.
Interface completa com visualização E controle da automação.

Funcionalidades:
- WebSocket para notificações em tempo real
- Métricas Prometheus para observabilidade
- A/B Testing para otimização de mensagens
- Audit Logging para segurança
"""

import asyncio
import os
import sys
import threading
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from loguru import logger

# Rate limiting
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    RATE_LIMITING_ENABLED = True
except ImportError:
    RATE_LIMITING_ENABLED = False
    logger.warning("flask-limiter não instalado. Rate limiting desabilitado.")

# WebSocket support
# Nota: O erro "write() before start_response" no Werkzeug pode ser ignorado
# É um problema do servidor de desenvolvimento, não afeta a funcionalidade
try:
    from web.websocket import create_socketio, get_websocket_notifier
    WEBSOCKET_ENABLED = True
except ImportError as e:
    WEBSOCKET_ENABLED = False
    logger.warning(f"WebSocket não disponível: {e}. Usando polling.")
except Exception as e:
    WEBSOCKET_ENABLED = False
    logger.warning(f"WebSocket erro: {type(e).__name__}: {e}. Usando polling.")

# Prometheus metrics
try:
    from utils.metrics import get_metrics_collector, init_metrics
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    logger.warning("Prometheus metrics não disponível.")

# A/B Testing
try:
    from utils.ab_testing import get_ab_manager, setup_default_experiments
    AB_TESTING_ENABLED = True
except ImportError:
    AB_TESTING_ENABLED = False
    logger.warning("A/B Testing não disponível.")

# Audit logging
try:
    from utils.audit_log import (
        AuditAction,
        audit_automation_start,
        audit_automation_stop,
        get_audit_logger,
    )
    AUDIT_ENABLED = True
except ImportError:
    AUDIT_ENABLED = False
    logger.warning("Audit logging não disponível.")

# Background Tasks (alternativa leve ao Celery)
try:
    from utils.background_tasks import get_task_manager, schedule_task, submit_task
    BACKGROUND_TASKS_ENABLED = True
except ImportError:
    BACKGROUND_TASKS_ENABLED = False
    logger.warning("Background Tasks não disponível.")

# Adicionar diretório pai ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import desc, func

from automation.state_manager import get_state_manager
from database import DatabaseManager, MatchRepository, MessageRepository, MyProfileRepository
from database.models import Match, Message, MyProfile
from utils.helpers import clean_message_preview
from utils.notifications import get_notification_manager

# ----------------------------------------------------------------------
# App e estado compartilhado — ver web/extensions.py e web/factory.py
# ----------------------------------------------------------------------
from web import extensions
from web.extensions import (
    add_log,
    automation_state,
    db,
    emit_automation_status,
    emit_notification,
    emit_stats_update,
    rate_limit,
    _sync_matches_task,
)
from web.factory import create_app

app = create_app()
socketio = extensions.socketio
limiter = extensions.limiter


# ===================== PÁGINAS =====================

@app.route('/')
def index():
    """Página principal - Dashboard."""
    return render_template('index.html')


@app.route('/matches')
def matches_page():
    """Página de matches."""
    return render_template('matches.html')


@app.route('/messages')
def messages_page():
    """Página de mensagens."""
    return render_template('messages.html')


@app.route('/analytics')
def analytics_page():
    """Página de analytics."""
    return render_template('analytics.html')


@app.route('/control')
def control_page():
    """Página de controle da automação."""
    return render_template('control.html')

@app.route('/health')
def health_check():
    """
    Endpoint de health check para monitoramento.
    Verifica saúde do banco de dados e componentes críticos.
    """
    checks = {
        'database': False,
        'openai_configured': False,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    # Verificar banco de dados
    try:
        checks['database'] = db.health_check()
    except Exception as e:
        logger.error(f"Health check - DB falhou: {e}")
        checks['database'] = False
        checks['database_error'] = str(e)
    
    # Verificar se OpenAI está configurada
    try:
        from config import get_settings
        settings = get_settings()
        checks['openai_configured'] = bool(settings.openai_api_key and len(settings.openai_api_key) > 10)
    except Exception:
        checks['openai_configured'] = False
    
    # Status geral: o banco é o componente crítico. A chave de IA é opcional
    # (pode ser configurada pela interface), então sua ausência não torna o
    # serviço indisponível — fica apenas registrada em checks para observabilidade.
    is_healthy = checks['database']
    status = 'healthy' if is_healthy else 'unhealthy'

    return jsonify({
        'status': status,
        'checks': checks
    }), 200 if is_healthy else 503


@app.route('/api/health')
def api_health():
    """Alias para /health com prefixo de API."""
    return health_check()


def run_web_server(host='0.0.0.0', port=5000, debug=False):
    """Inicia o servidor web com suporte a WebSocket."""
    logger.warning(f"🌐 Servidor web iniciado em http://{host}:{port}")
    
    # Usar SocketIO se disponível para WebSocket support
    if WEBSOCKET_ENABLED and socketio is not None:
        logger.debug("🔌 WebSocket ativado via SocketIO")
        socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
    else:
        logger.debug("📡 Modo polling (sem WebSocket)")
        app.run(host=host, port=port, debug=debug, threaded=True)


# ===================== API - CONTROLE DA AUTOMAÇÃO =====================


# Blueprints de rotas (registrados após os globais estarem definidos)
from web.blueprints.matches_messages import bp_matches_messages  # noqa: E402
from web.blueprints.operations import bp_operations  # noqa: E402
from web.blueprints.api_extra import bp_api_extra  # noqa: E402
app.register_blueprint(bp_matches_messages)
app.register_blueprint(bp_operations)
app.register_blueprint(bp_api_extra)

if __name__ == '__main__':
    run_web_server(debug=True)
