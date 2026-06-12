"""
Rate Limiter Configuration - Suporte a Redis e storage em memória.
Permite persistência de rate limits entre restarts quando usando Redis.
"""

import os
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)


def get_rate_limiter_storage_uri() -> str:
    """
    Retorna a URI de storage para o rate limiter.
    
    Prioridade:
    1. REDIS_URL do ambiente
    2. RATE_LIMITER_STORAGE do ambiente
    3. memory:// como fallback
    
    Returns:
        URI de storage (redis://... ou memory://)
    """
    # Verificar se Redis está configurado
    redis_url = os.environ.get('REDIS_URL')
    if redis_url:
        logger.debug("Rate limiter usando Redis para storage")
        return redis_url
    
    # Verificar storage customizado
    custom_storage = os.environ.get('RATE_LIMITER_STORAGE')
    if custom_storage:
        logger.debug(f"Rate limiter usando storage customizado: {custom_storage}")
        return custom_storage
    
    # Fallback para memória
    logger.debug("Rate limiter usando storage em memória (não persiste entre restarts)")
    return "memory://"


def check_redis_available() -> bool:
    """
    Verifica se Redis está disponível.
    
    Returns:
        True se Redis está conectável, False caso contrário
    """
    try:
        import redis
        redis_url = os.environ.get('REDIS_URL')
        if not redis_url:
            return False
        
        r = redis.from_url(redis_url)
        r.ping()
        return True
    except ImportError:
        logger.warning("redis package não instalado. Use 'pip install redis' para suporte a Redis.")
        return False
    except Exception as e:
        logger.warning(f"Redis não disponível: {e}")
        return False


class RateLimitConfig:
    """Configurações centralizadas de rate limiting."""
    
    # Limites padrão para API web
    DEFAULT_DAILY_LIMIT = "200 per day"
    DEFAULT_HOURLY_LIMIT = "50 per hour"
    
    # Limites para endpoints de automação (mais restritivos)
    AUTOMATION_START_LIMIT = "5 per hour"
    AUTOMATION_STOP_LIMIT = "10 per hour"
    
    # Limites para endpoints de dados
    DATA_FETCH_LIMIT = "100 per hour"
    
    # Limites para ações de match
    MATCH_ACTION_LIMIT = "30 per hour"
    
    @classmethod
    def get_default_limits(cls) -> list:
        """Retorna limites padrão para a API."""
        return [cls.DEFAULT_DAILY_LIMIT, cls.DEFAULT_HOURLY_LIMIT]
    
    @classmethod
    def get_storage_uri(cls) -> str:
        """Retorna URI de storage configurada."""
        return get_rate_limiter_storage_uri()


# ===================== INSTRUÇÕES DE CONFIGURAÇÃO =====================
"""
Para usar Redis como backend do rate limiter:

1. Instale o pacote redis:
   pip install redis

2. Configure a variável de ambiente:
   - Windows: set REDIS_URL=redis://localhost:6379/0
   - Linux/Mac: export REDIS_URL=redis://localhost:6379/0
   - .env: REDIS_URL=redis://localhost:6379/0

3. Para Redis com autenticação:
   REDIS_URL=redis://:password@hostname:6379/0

4. Para Redis Cluster (produção):
   REDIS_URL=redis://hostname:6379/0?cluster=true

Benefícios do Redis:
- Rate limits persistem entre restarts do servidor
- Funciona em ambientes com múltiplas instâncias
- Melhor para produção
"""
