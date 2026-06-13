"""
Módulo de banco de dados do Automatic Tinder Chat.
"""

from .connection import DatabaseManager, get_db_manager, get_session
from .models import (
    AIInteraction,
    Analytics,
    Base,
    ExecutionLog,
    Match,
    MatchInterest,
    MatchPhoto,
    MatchReport,
    Message,
    MyProfile,
    MyProfileInterest,
    MyProfilePhoto,
)
from .repositories import (
    AIInteractionRepository,
    AnalyticsRepository,
    ExecutionLogRepository,
    MatchReportRepository,
    MatchRepository,
    MessageRepository,
    MyProfileRepository,
)

__all__ = [
    # Connection
    "DatabaseManager",
    "get_db_manager",
    "get_session",
    
    # Models
    "Base",
    "MyProfile",
    "MyProfilePhoto",
    "MyProfileInterest",
    "Match",
    "MatchPhoto",
    "MatchInterest",
    "Message",
    "ExecutionLog",
    "AIInteraction",
    "Analytics",
    "MatchReport",
    
    # Repositories
    "MyProfileRepository",
    "MatchRepository",
    "MessageRepository",
    "ExecutionLogRepository",
    "AIInteractionRepository",
    "AnalyticsRepository",
    "MatchReportRepository"
]
