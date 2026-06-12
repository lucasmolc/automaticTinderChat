"""
Serviço de Notificações do Automatic Tinder Chat.
Gerencia notificações em tempo real via WebSocket.
"""

from utils.notifications import (
    WebNotificationManager,
    get_notification_manager,
    NotificationType
)

# Alias para compatibilidade
NotificationManager = WebNotificationManager

__all__ = [
    "NotificationManager",
    "WebNotificationManager",
    "get_notification_manager",
    "NotificationType"
]
