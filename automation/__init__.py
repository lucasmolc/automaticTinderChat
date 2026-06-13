"""
Módulo de automação do Automatic Tinder Chat.
"""

# Cache centralizado (em utils/)
from utils.cache import LRUCache as ProfileCache
from utils.cache import get_profile_cache
from utils.cache import reset_all_caches as reset_profile_cache

from .browser import BrowserController, get_browser, reset_browser

# DataValidationService: Valida dados antes de persistir (usado pelo SYNC)
from .data_validation_service import DataValidationService, get_validation_service

# ExecutionService: Executa ações usando APENAS dados do banco
from .execution_service import ExecutionService, get_execution_service
from .extractors import TinderDataExtractor

# === IDEMPOTÊNCIA E SEGURANÇA ===
from .idempotency import (
    IdempotencyCheckResult,
    IdempotencyError,
    IdempotencyGuard,
    get_idempotency_guard,
    verify_first_message_allowed,
)

# === NOVOS SERVIÇOS DA ARQUITETURA REFATORADA ===
# MatchDataService: Fornece dados APENAS do banco para execução
from .match_data_service import MatchDataService, get_match_data_service
from .match_fetching import (
    MatchDataFetcher,
    extract_complete_profile,
    retry_with_backoff,
    validate_and_clean_name,  # Validação de nomes de matches
)

# Módulos especializados de match helpers
from .match_validation import (
    BAD_MESSAGE_PATTERNS,
    SKIP_REASONS,
    MatchValidator,
    get_skip_reason,
    is_match_processable,
    validate_ai_message,
)
from .orchestrator import AutomationOrchestrator, run_automation, sync_matches_only
from .profile_syncer import ProfileSyncer
from .state_manager import AutomationStateManager, get_state_manager

# Funções compartilhadas de scraping do Tinder
from .tinder_scraping import (
    EXTRACT_BIO_JS,
    EXTRACT_MATCHES_LIST_JS,
    EXTRACT_PHOTOS_JS,
    extract_bio_from_page,
    extract_date_from_text,
    extract_matches_list_from_page,
    extract_photos_from_page,
    filter_valid_photos,
    navigate_to_match_chat,
    navigate_to_matches_page,
    validate_match_id,
)

__all__ = [
    # Browser
    "BrowserController",
    "get_browser",
    "reset_browser",
    # Extractors
    "TinderDataExtractor",
    # Orchestrator
    "AutomationOrchestrator",
    "run_automation",
    "sync_matches_only",
    # State
    "AutomationStateManager",
    "get_state_manager",
    # Profile syncer
    "ProfileSyncer",
    # === NOVOS SERVIÇOS (Arquitetura Refatorada) ===
    "MatchDataService",      # Dados APENAS do banco
    "get_match_data_service",
    "ExecutionService",      # Execução usando APENAS banco
    "get_execution_service",
    "DataValidationService", # Validação para SYNC
    "get_validation_service",
    # Match validation
    "MatchValidator",
    "SKIP_REASONS",
    "BAD_MESSAGE_PATTERNS",
    "validate_ai_message",
    "is_match_processable",
    "get_skip_reason",
    # Match fetching
    "MatchDataFetcher",
    "retry_with_backoff",
    "extract_complete_profile",
    "validate_and_clean_name",
    # Cache
    "ProfileCache",
    "get_profile_cache",
    "reset_profile_cache",
    # Tinder scraping functions
    "EXTRACT_PHOTOS_JS",
    "EXTRACT_BIO_JS",
    "EXTRACT_MATCHES_LIST_JS",
    "extract_photos_from_page",
    "extract_bio_from_page",
    "extract_matches_list_from_page",
    "extract_date_from_text",
    "filter_valid_photos",
    "validate_match_id",
    "navigate_to_match_chat",
    "navigate_to_matches_page"
]
