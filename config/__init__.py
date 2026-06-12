"""
Módulo de configuração do Automatic Tinder Chat.
"""

from .settings import (
    Settings,
    get_settings,
    PROJECT_ROOT,
    CONFIG_DIR,
    LOGS_DIR,
    REPORTS_DIR,
    BROWSER_DATA_DIR,
    PROMPTS_DIR,
    TINDER_URL,
    TINDER_APP_URL,
    TINDER_MATCHES_URL,
    TINDER_MESSAGES_URL,
    CONVERSATION_TEMPERATURE,
    PROFILE_SCORE_WEIGHTS
)

__all__ = [
    "Settings",
    "get_settings",
    "PROJECT_ROOT",
    "CONFIG_DIR",
    "LOGS_DIR",
    "REPORTS_DIR",
    "BROWSER_DATA_DIR",
    "PROMPTS_DIR",
    "TINDER_URL",
    "TINDER_APP_URL",
    "TINDER_MATCHES_URL",
    "TINDER_MESSAGES_URL",
    "CONVERSATION_TEMPERATURE",
    "PROFILE_SCORE_WEIGHTS"
]
