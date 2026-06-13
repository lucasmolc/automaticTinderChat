"""
Módulo de utilitários do Automatic Tinder Chat.
"""

from .ai_logger import AIInteractionLogger, log_ai_error, log_ai_interaction
from .cache import (
    LRUCache,
    SingletonCache,
    get_api_response_cache,
    get_profile_cache,
    reset_all_caches,
)
from .helpers import (
    async_random_delay,
    calculate_days_since,
    extract_json_from_text,
    format_datetime,
    random_delay,
    safe_json_dumps,
    safe_json_loads,
    sanitize_text,
    truncate_text,
)
from .log_cleaner import (
    CleanupStats,
    LogCleaner,
    cleanup_logs_now,
    get_logs_status,
    start_log_cleaner,
    stop_log_cleaner,
)
from .logger import (
    console_complete,
    console_cycle,
    console_error,
    # Console logging functions
    console_log,
    console_matches_loaded,
    console_message_sent,
    console_message_skipped,
    console_processing_match,
    console_start,
    console_stats,
    console_stop,
    console_sync_complete,
    console_sync_start,
    console_waiting,
    console_warning,
    console_whatsapp_detected,
    get_logger,
    log_ai_decision,
    log_automation_step,
    log_error_with_context,
    log_file_only,
)

__all__ = [
    # Logger
    "get_logger",
    "log_ai_decision",
    "log_automation_step",
    "log_error_with_context",
    "log_file_only",
    
    # Console logging
    "console_log",
    "console_start",
    "console_stop",
    "console_complete",
    "console_sync_start",
    "console_sync_complete",
    "console_matches_loaded",
    "console_processing_match",
    "console_message_sent",
    "console_message_skipped",
    "console_error",
    "console_warning",
    "console_cycle",
    "console_waiting",
    "console_whatsapp_detected",
    "console_stats",
    
    # Helpers
    "random_delay",
    "async_random_delay",
    "safe_json_loads",
    "safe_json_dumps",
    "extract_json_from_text",
    "format_datetime",
    "truncate_text",
    "calculate_days_since",
    "sanitize_text",
    
    # AI Logger
    "AIInteractionLogger",
    "log_ai_interaction",
    "log_ai_error",
    
    # Log Cleaner
    "LogCleaner",
    "CleanupStats",
    "start_log_cleaner",
    "stop_log_cleaner",
    "cleanup_logs_now",
    "get_logs_status",
    
    # Cache
    "LRUCache",
    "SingletonCache",
    "get_profile_cache",
    "get_api_response_cache",
    "reset_all_caches"
]
