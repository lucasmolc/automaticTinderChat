"""
Helpers centralizados para processamento de matches.

NOTA: Este módulo agora serve como facade de compatibilidade.
A lógica foi dividida em módulos especializados:
- match_validation.py: Validação de matches e mensagens
- match_fetching.py: Busca de dados com retry e cache
- utils/cache.py: Sistema de cache genérico

Para novos códigos, prefira importar diretamente dos módulos especializados.
"""

# ===================== RE-EXPORTS DE COMPATIBILIDADE =====================

# Validação de matches
# Cache (agora em utils/)
from utils.cache import LRUCache as ProfileCache  # Alias para compatibilidade
from utils.cache import SingletonCache, get_profile_cache
from utils.cache import reset_all_caches as reset_profile_cache

# Busca de dados
from .match_fetching import MatchDataFetcher, extract_complete_profile, retry_with_backoff
from .match_validation import (
    BAD_MESSAGE_PATTERNS,
    GREETING_PATTERNS,
    SKIP_REASONS,
    MatchValidator,
    get_skip_reason,
    is_match_processable,
    validate_ai_message,
    validate_ai_message_with_context,
)

__all__ = [
    # Validation
    'MatchValidator',
    'SKIP_REASONS',
    'BAD_MESSAGE_PATTERNS',
    'validate_ai_message',
    'is_match_processable',
    'get_skip_reason',
    # Fetching
    'MatchDataFetcher',
    'retry_with_backoff',
    'extract_complete_profile',
    # Cache (compatibilidade)
    'ProfileCache',
    'get_profile_cache',
    'reset_profile_cache',
    'SingletonCache',
]
