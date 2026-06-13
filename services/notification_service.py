"""
Serviço de Notificações do Automatic Tinder Chat.
Gerencia notificações em tempo real via WebSocket.
"""

from utils.notifications import NotificationType, WebNotificationManager, get_notification_manager

# Alias para compatibilidade
NotificationManager = WebNotificationManager

__all__ = [
    "NotificationManager",
    "WebNotificationManager",
    "get_notification_manager",
    "NotificationType"
]
