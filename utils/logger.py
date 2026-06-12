"""
Sistema de logging centralizado com Loguru.

ARQUITETURA DE LOGS:
- Console → Visão operacional em tempo real (INFO+)
- Arquivo → Visão detalhada para debug/análise (DEBUG+)

Console exibe:
- Início/fim de execução
- Progresso do sync
- Processamento de cada match
- Decisões tomadas (enviou/ignorou)
- Erros críticos

Arquivo contém:
- Tudo do console + dados técnicos
- Payloads completos
- Stack traces
- Decisões da IA detalhadas
"""

import sys
from pathlib import Path
from datetime import datetime
from loguru import logger

from config import LOGS_DIR, get_settings


# ==================== CONSTANTES DE FORMATAÇÃO ====================

# Emojis padronizados para console
EMOJI = {
    "start": "🚀",
    "stop": "🛑",
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "sync": "🔄",
    "message": "💬",
    "sent": "📤",
    "skip": "⏭️",
    "match": "👤",
    "processing": "⚙️",
    "waiting": "⏳",
    "complete": "🏁",
    "database": "🗄️",
    "whatsapp": "📱",
    "cycle": "🔁",
}


def setup_logger():
    """Configura o sistema de logging."""
    settings = get_settings()
    
    # Remover handler padrão
    logger.remove()
    
    # Formato para console - limpo e legível
    console_format = (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<level>{message}</level>"
    )
    
    # Formato para arquivo - detalhado com contexto
    file_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    # Handler para console - INFO+ (visão operacional)
    # Permite acompanhar execução em tempo real
    logger.add(
        sys.stdout,
        format=console_format,
        level="INFO",
        colorize=True,
        filter=lambda record: (
            # Não mostrar decisões detalhadas da IA no console
            "ai_decision" not in record["extra"] and
            # Não mostrar logs marcados como file_only
            not record["extra"].get("file_only", False)
        )
    )
    
    # Handler para arquivo geral - tudo (DEBUG+)
    logger.add(
        LOGS_DIR / "app_{time:YYYY-MM-DD}.log",
        format=file_format,
        level="DEBUG",
        rotation="00:00",
        retention=f"{settings.log_retention_days} days",
        compression="zip",
        encoding="utf-8"
    )
    
    # Handler para erros (arquivo separado)
    logger.add(
        LOGS_DIR / "errors_{time:YYYY-MM-DD}.log",
        format=file_format,
        level="ERROR",
        rotation="00:00",
        retention=f"{settings.log_retention_days} days",
        compression="zip",
        encoding="utf-8"
    )
    
    # Handler para decisões da IA (arquivo separado, não no console)
    logger.add(
        LOGS_DIR / "ai_decisions_{time:YYYY-MM-DD}.log",
        format=file_format,
        level="INFO",
        filter=lambda record: "ai_decision" in record["extra"],
        rotation="00:00",
        retention=f"{settings.log_retention_days} days",
        encoding="utf-8"
    )
    
    # Handler para requests/responses brutos da IA (arquivo separado)
    # Grava exatamente o que foi enviado e recebido de cada provedor
    logger.add(
        LOGS_DIR / "ai_raw_{time:YYYY-MM-DD}.log",
        format=file_format,
        level="DEBUG",
        filter=lambda record: "ai_raw" in record["extra"],
        rotation="00:00",
        retention=f"{settings.log_retention_days} days",
        encoding="utf-8"
    )
    
    logger.bind(file_only=True).debug("Sistema de logging inicializado")


def get_logger(name: str = None):
    """Retorna logger configurado com contexto."""
    return logger.bind(module=name) if name else logger


# ==================== LOGS DE CONSOLE (OPERACIONAL) ====================

def console_log(message: str, emoji_key: str = None):
    """
    Log que aparece no console para acompanhamento em tempo real.
    Usa nível INFO para garantir visibilidade.
    
    Args:
        message: Mensagem curta e objetiva
        emoji_key: Chave do emoji (opcional)
    """
    prefix = EMOJI.get(emoji_key, "") + " " if emoji_key else ""
    logger.info(f"{prefix}{message}")


def console_start(component: str):
    """Log de início de componente/processo."""
    logger.info(f"{EMOJI['start']} INICIANDO: {component}")


def console_stop(component: str, reason: str = ""):
    """Log de parada de componente/processo."""
    msg = f"{EMOJI['stop']} PARANDO: {component}"
    if reason:
        msg += f" ({reason})"
    logger.info(msg)


def console_complete(component: str, summary: str = ""):
    """Log de conclusão bem-sucedida."""
    msg = f"{EMOJI['complete']} CONCLUÍDO: {component}"
    if summary:
        msg += f" | {summary}"
    logger.info(msg)


def console_sync_start(sync_type: str):
    """Log de início de sincronização."""
    logger.info(f"{EMOJI['sync']} Sync iniciado: {sync_type}")


def console_sync_complete(sync_type: str, stats: dict = None):
    """Log de conclusão de sincronização."""
    msg = f"{EMOJI['success']} Sync concluído: {sync_type}"
    if stats:
        parts = []
        if "new" in stats:
            parts.append(f"{stats['new']} novos")
        if "updated" in stats:
            parts.append(f"{stats['updated']} atualizados")
        if "total" in stats:
            parts.append(f"{stats['total']} total")
        if parts:
            msg += f" ({', '.join(parts)})"
    logger.info(msg)


def console_matches_loaded(count: int, source: str = "banco"):
    """Log de matches carregados."""
    logger.info(f"{EMOJI['database']} {count} matches do {source}")


def console_processing_match(name: str, action: str = None):
    """Log de início de processamento de um match."""
    action_part = f" [{action}]" if action else ""
    logger.info(f"{EMOJI['match']} {name}{action_part}")


def console_message_sent(name: str, preview: str = None):
    """Log de mensagem enviada com sucesso."""
    msg = f"{EMOJI['sent']} Mensagem enviada para {name}"
    if preview:
        # Mostrar preview curto (primeiros 30 chars)
        short = preview[:30] + "..." if len(preview) > 30 else preview
        msg += f': "{short}"'
    logger.info(msg)


def console_message_skipped(name: str, reason: str):
    """Log de mensagem ignorada/pulada."""
    logger.info(f"{EMOJI['skip']} Ignorado {name}: {reason}")


def console_error(message: str, error: Exception = None):
    """Log de erro visível no console."""
    msg = f"{EMOJI['error']} {message}"
    if error:
        msg += f": {type(error).__name__}"
    logger.error(msg)


def console_warning(message: str):
    """Log de aviso visível no console."""
    logger.warning(f"{EMOJI['warning']} {message}")


def console_cycle(cycle_num: int, status: str = "iniciando"):
    """Log de ciclo de automação."""
    logger.info(f"{EMOJI['cycle']} Ciclo #{cycle_num}: {status}")


def console_waiting(seconds: int, reason: str = ""):
    """Log de espera."""
    msg = f"{EMOJI['waiting']} Aguardando {seconds}s"
    if reason:
        msg += f" ({reason})"
    logger.info(msg)


def console_whatsapp_detected(name: str):
    """Log de WhatsApp detectado."""
    logger.info(f"{EMOJI['whatsapp']} WhatsApp detectado: {name}")


def console_stats(stats: dict):
    """Log de estatísticas resumidas."""
    parts = []
    if stats.get("messages_sent"):
        parts.append(f"{stats['messages_sent']} msgs enviadas")
    if stats.get("matches_processed"):
        parts.append(f"{stats['matches_processed']} matches")
    if stats.get("errors"):
        parts.append(f"{stats['errors']} erros")
    if stats.get("whatsapp_detected"):
        parts.append(f"{stats['whatsapp_detected']} WhatsApp")
    
    if parts:
        logger.info(f"📊 Resumo: {' | '.join(parts)}")


# ==================== LOGS DE ARQUIVO (TÉCNICO/DEBUG) ====================

def log_ai_decision(decision_type: str, context: dict, decision: str, reasoning: str = None):
    """Log específico para decisões da IA (apenas arquivo ai_decisions)."""
    logger.bind(ai_decision=True).info(
        f"[AI Decision] Type: {decision_type} | Decision: {decision} | "
        f"Context: {context} | Reasoning: {reasoning or 'N/A'}"
    )


def log_ai_raw_request(interaction_type: str, messages: list, temperature: float = None, max_tokens: int = None, provider: str = None, model: str = None):
    """
    Grava o request bruto enviado para a IA (apenas arquivo ai_raw).
    Registra exatamente o payload que foi enviado ao provedor.
    """
    import json
    raw_logger = logger.bind(ai_raw=True, file_only=True)
    
    raw_logger.info(
        f"\n{'='*80}\n"
        f"[AI RAW REQUEST]\n"
        f"Type: {interaction_type}\n"
        f"Provider: {provider or 'N/A'} | Model: {model or 'N/A'}\n"
        f"Temperature: {temperature} | Max Tokens: {max_tokens}\n"
        f"{'─'*80}\n"
        f"MESSAGES:\n{json.dumps(messages, ensure_ascii=False, indent=2)}\n"
        f"{'='*80}"
    )


def log_ai_raw_response(interaction_type: str, response_content: str, provider: str = None, model: str = None, tokens: int = None, cost: float = None, response_time_ms: int = None):
    """
    Grava a response bruta recebida da IA (apenas arquivo ai_raw).
    Registra exatamente o que o provedor retornou.
    """
    raw_logger = logger.bind(ai_raw=True, file_only=True)
    
    raw_logger.info(
        f"\n{'='*80}\n"
        f"[AI RAW RESPONSE]\n"
        f"Type: {interaction_type}\n"
        f"Provider: {provider or 'N/A'} | Model: {model or 'N/A'}\n"
        f"Tokens: {tokens or 'N/A'} | Cost: ${(cost if cost else 0):.6f} | Time: {response_time_ms or 'N/A'}ms\n"
        f"{'─'*80}\n"
        f"CONTENT:\n{response_content}\n"
        f"{'='*80}"
    )


def log_ai_raw_error(interaction_type: str, error: str, messages: list = None):
    """
    Grava erro bruto de chamada à IA (apenas arquivo ai_raw).
    """
    import json
    raw_logger = logger.bind(ai_raw=True, file_only=True)
    
    messages_str = ""
    if messages:
        messages_str = f"\nMESSAGES SENT:\n{json.dumps(messages, ensure_ascii=False, indent=2)}"
    
    raw_logger.error(
        f"\n{'='*80}\n"
        f"[AI RAW ERROR]\n"
        f"Type: {interaction_type}\n"
        f"Error: {error}{messages_str}\n"
        f"{'='*80}"
    )


def log_automation_step(step: str, details: dict = None):
    """Log técnico para passos da automação (apenas arquivo)."""
    logger.bind(file_only=True).debug(f"[Automation] {step} | Details: {details or {}}")


def log_file_only(message: str, level: str = "debug"):
    """
    Log que vai APENAS para arquivo (não aparece no console).
    Use para dados técnicos, payloads, etc.
    """
    # Garantir que level é string (proteção contra chamadas incorretas)
    if not isinstance(level, str):
        # Se passaram um dict ou outro tipo como level, incluir na mensagem
        message = f"{message} | Details: {level}"
        level = "debug"
    log_func = getattr(logger.bind(file_only=True), level.lower(), logger.debug)
    log_func(message)


def log_error_with_context(error: Exception, context: dict = None):
    """Log de erro com contexto adicional (arquivo + console)."""
    logger.error(
        f"[Error] {type(error).__name__}: {error} | Context: {context or {}}"
    )


# ==================== LEGADO (MANTER COMPATIBILIDADE) ====================

def log_console(message: str, level: str = "info"):
    """
    [LEGADO] Mantido para compatibilidade.
    Prefira usar console_log() ou funções específicas.
    """
    log_func = getattr(logger.opt(colors=True), level.lower(), logger.info)
    log_func(f"<bold>{message}</bold>")


# Inicializar logger na importação
setup_logger()
