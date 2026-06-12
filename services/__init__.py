"""
Módulo de Serviços do Automatic Tinder Chat.
Contém serviços de alto nível para funcionalidades específicas.

Arquitetura de Serviços:
- MLAdaptiveService: Machine Learning para otimização de prompts
- AnalyticsService: Métricas, estatísticas e análises
- NotificationService: Notificações em tempo real
- SchedulerService: Agendamento de tarefas
- EmbeddingsCache: Cache de embeddings para performance

Uso:
    from services import get_ml_service, get_analytics_service
    
    ml = get_ml_service()
    analytics = get_analytics_service()
"""

from .ml_adaptive import (
    MLAdaptiveService,
    get_ml_service,
    reset_ml_service,
    PromptPerformance,
    ConversationPattern
)

from .analytics_service import (
    AnalyticsService,
    get_analytics_service,
    ConversationMetrics,
    DailyStats
)

from .notification_service import (
    get_notification_manager,
    NotificationType
)

from .scheduler_service import (
    SchedulerService,
    get_scheduler,
    start_scheduler,
    stop_scheduler
)

from .embeddings_cache import (
    EmbeddingsCache,
    get_embeddings_cache,
    create_embedding_with_cache,
    batch_create_embeddings_with_cache
)

__all__ = [
    # ML Adaptive
    "MLAdaptiveService",
    "get_ml_service", 
    "reset_ml_service",
    "PromptPerformance",
    "ConversationPattern",
    # Analytics
    "AnalyticsService",
    "get_analytics_service",
    "ConversationMetrics",
    "DailyStats",
    # Notifications
    "get_notification_manager",
    "NotificationType",
    # Scheduler
    "SchedulerService",
    "get_scheduler",
    "start_scheduler",
    "stop_scheduler",
    # Embeddings Cache
    "EmbeddingsCache",
    "get_embeddings_cache",
    "create_embedding_with_cache",
    "batch_create_embeddings_with_cache"
]


