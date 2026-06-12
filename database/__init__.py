"""
Módulo de banco de dados do Automatic Tinder Chat.
"""

from .connection import DatabaseManager, get_db_manager, get_session
from .models import (
    Base,
    MyProfile, MyProfilePhoto, MyProfileInterest,
    Match, MatchPhoto, MatchInterest, Message,
    ExecutionLog, AIInteraction, Analytics, MatchReport
)
from .repositories import (
    MyProfileRepository,
    MatchRepository,
    MessageRepository,
    ExecutionLogRepository,
    AIInteractionRepository,
    AnalyticsRepository,
    MatchReportRepository
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
