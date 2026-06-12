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
from .match_validation import (
    MatchValidator,
    SKIP_REASONS,
    BAD_MESSAGE_PATTERNS,
    GREETING_PATTERNS,
    validate_ai_message,
    validate_ai_message_with_context,
    is_match_processable,
    get_skip_reason
)

# Busca de dados
from .match_fetching import (
    MatchDataFetcher,
    retry_with_backoff,
    extract_complete_profile
)

# Cache (agora em utils/)
from utils.cache import (
    LRUCache as ProfileCache,  # Alias para compatibilidade
    get_profile_cache,
    reset_all_caches as reset_profile_cache,
    SingletonCache
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
