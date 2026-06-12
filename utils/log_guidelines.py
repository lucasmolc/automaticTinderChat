"""
Logging Guidelines - Padrões para uso de níveis de log no projeto.

Este módulo define constantes e helpers para logging consistente.
"""

from enum import Enum
from typing import Optional, Dict, Any
from functools import wraps
import traceback

from utils.logger import get_logger

logger = get_logger(__name__)


# ===================== LOG LEVEL GUIDELINES =====================
"""
GUIDELINES PARA USO DE NÍVEIS DE LOG
====================================

DEBUG (logger.debug)
--------------------
Quando usar:
- Informações detalhadas para debugging
- Valores de variáveis durante execução
- Passos intermediários de algoritmos
- Rastreamento de fluxo de execução

Exemplos:
- "Navegando para URL: https://..."
- "Extração retornou: {...}"
- "Cache hit para chave: xyz"

NÃO usar para:
- Informações que seriam úteis em produção
- Erros ou avisos


INFO (logger.info)
------------------
Quando usar:
- Eventos normais de operação
- Início/fim de processos importantes
- Marcos de progresso
- Ações do usuário

Exemplos:
- "Automação iniciada"
- "Sincronização completa: 50 matches processados"
- "Mensagem enviada para match XYZ"

NÃO usar para:
- Debugging detalhado
- Erros ou condições inesperadas


WARNING (logger.warning)
------------------------
Quando usar:
- Situação inesperada MAS não é erro
- Operação continuou mas com problemas
- Configuração subótima
- Deprecation notices
- Rate limits próximos

Exemplos:
- "Match não encontrado, pulando..."
- "Elemento não localizado, tentando seletor alternativo"
- "Cache expirado, buscando novamente"
- "Redis não disponível, usando memória para rate limiting"

NÃO usar para:
- Erros que precisam de ação
- Situações normais de operação


ERROR (logger.error)
--------------------
Quando usar:
- Falha em operação específica
- Exceção capturada
- Violação de regra de negócio
- Problema que precisa de investigação

Exemplos:
- "Erro ao enviar mensagem: Connection refused"
- "Falha na extração de perfil: Timeout"
- "IA retornou resposta inválida"

NÃO usar para:
- Situações recuperáveis automaticamente
- Informações de debugging


CRITICAL (logger.critical)
--------------------------
Quando usar:
- Sistema não pode continuar
- Falha catastrófica
- Perda de dados
- Violação de segurança

Exemplos:
- "Banco de dados inacessível"
- "API key inválida"
- "Corrupção de dados detectada"

Quase nunca usar - reservado para emergências.
"""


class LogContext(Enum):
    """Contextos padronizados para logging."""
    AUTOMATION = "automation"
    BROWSER = "browser"
    DATABASE = "database"
    AI = "ai"
    WEB = "web"
    EXTRACTION = "extraction"
    SYNC = "sync"


def log_operation(
    context: LogContext,
    operation: str,
    success: bool = True,
    details: Optional[Dict[str, Any]] = None,
    error: Optional[Exception] = None
) -> None:
    """
    Helper para logging padronizado de operações.
    
    Args:
        context: Contexto da operação (AUTOMATION, BROWSER, etc)
        operation: Nome da operação
        success: Se a operação foi bem sucedida
        details: Detalhes adicionais (opcional)
        error: Exceção se houver (opcional)
    """
    prefix = f"[{context.value.upper()}]"
    
    if success:
        message = f"{prefix} {operation}"
        if details:
            message += f" | {details}"
        logger.info(message)
    else:
        message = f"{prefix} {operation} FAILED"
        if error:
            message += f" | Error: {error}"
        if details:
            message += f" | Details: {details}"
        logger.error(message)


def log_with_context(context: LogContext):
    """
    Decorator para adicionar contexto a logs de uma função.
    
    Uso:
        @log_with_context(LogContext.AUTOMATION)
        async def send_messages():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            func_name = func.__name__
            logger.debug(f"[{context.value.upper()}] Starting: {func_name}")
            try:
                result = await func(*args, **kwargs)
                logger.debug(f"[{context.value.upper()}] Completed: {func_name}")
                return result
            except Exception as e:
                logger.error(f"[{context.value.upper()}] Error in {func_name}: {e}")
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            func_name = func.__name__
            logger.debug(f"[{context.value.upper()}] Starting: {func_name}")
            try:
                result = func(*args, **kwargs)
                logger.debug(f"[{context.value.upper()}] Completed: {func_name}")
                return result
            except Exception as e:
                logger.error(f"[{context.value.upper()}] Error in {func_name}: {e}")
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def log_exception_with_trace(
    context: LogContext,
    operation: str,
    exception: Exception,
    include_trace: bool = True
) -> None:
    """
    Loga exceção com stack trace completo.
    
    Args:
        context: Contexto da operação
        operation: Nome da operação
        exception: Exceção ocorrida
        include_trace: Se deve incluir stack trace
    """
    prefix = f"[{context.value.upper()}]"
    message = f"{prefix} Exception in {operation}: {type(exception).__name__}: {exception}"
    
    if include_trace:
        trace = traceback.format_exc()
        message += f"\nStack trace:\n{trace}"
    
    logger.error(message)


# ===================== QUICK REFERENCE =====================
"""
RESUMO RÁPIDO:
- DEBUG: Só para desenvolvedores, detalhes técnicos
- INFO: Eventos normais de operação
- WARNING: Algo inesperado mas não falhou
- ERROR: Algo falhou
- CRITICAL: Sistema comprometido

REGRA DE OURO:
Se você acordasse às 3h da manhã por causa desse log, qual seria?
- DEBUG/INFO: Nunca deveria te acordar
- WARNING: Poderia esperar até amanhã
- ERROR: Precisa olhar em horário comercial
- CRITICAL: Acorda às 3h da manhã
"""
