"""
Sistema de notificações web com persistência no banco de dados.
As notificações são salvas no banco e carregadas quando o dropdown é aberto.
"""

import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class NotificationType(Enum):
    """Tipos de notificação suportados."""
    NEW_MESSAGE = "new_message"
    WHATSAPP_POSSIBLE = "whatsapp_possible"
    WHATSAPP_CONFIRMED = "whatsapp_confirmed"
    DATE_POSSIBLE = "date_possible"
    DATE_CONFIRMED = "date_confirmed"
    HOT_CONVERSATION = "hot_conversation"
    NEW_MATCH = "new_match"
    UNMATCH = "unmatch"
    AUTOMATION_COMPLETE = "automation_complete"
    AUTOMATION_STARTED = "automation_started"
    REPORT_GENERATED = "report_generated"
    ERROR = "error"
    INFO = "info"


# Configuração de ícones e cores por tipo
NOTIFICATION_CONFIG = {
    NotificationType.NEW_MESSAGE.value: {
        "icon": "<i class='bi bi-chat-dots-fill'></i>",
        "color": "primary",
        "title": "Nova Mensagem"
    },
    NotificationType.WHATSAPP_POSSIBLE.value: {
        "icon": "<i class='bi bi-whatsapp'></i>",
        "color": "info",
        "title": "Possível WhatsApp"
    },
    NotificationType.WHATSAPP_CONFIRMED.value: {
        "icon": "<i class='bi bi-whatsapp'></i>",
        "color": "success",
        "title": "WhatsApp Confirmado!"
    },
    NotificationType.DATE_POSSIBLE.value: {
        "icon": "<i class='bi bi-calendar-event'></i>",
        "color": "warning",
        "title": "Possível Encontro"
    },
    NotificationType.DATE_CONFIRMED.value: {
        "icon": "<i class='bi bi-calendar-check-fill'></i>",
        "color": "success",
        "title": "Encontro Confirmado!"
    },
    NotificationType.HOT_CONVERSATION.value: {
        "icon": "<i class='bi bi-fire'></i>",
        "color": "danger",
        "title": "Conversa Quente!"
    },
    NotificationType.NEW_MATCH.value: {
        "icon": "<i class='bi bi-heart-fill'></i>",
        "color": "success",
        "title": "Novo Match"
    },
    NotificationType.UNMATCH.value: {
        "icon": "<i class='bi bi-heartbreak-fill'></i>",
        "color": "secondary",
        "title": "Unmatch"
    },
    NotificationType.AUTOMATION_COMPLETE.value: {
        "icon": "<i class='bi bi-check-circle-fill'></i>",
        "color": "success",
        "title": "Automação Concluída"
    },
    NotificationType.AUTOMATION_STARTED.value: {
        "icon": "<i class='bi bi-play-circle-fill'></i>",
        "color": "primary",
        "title": "Automação Iniciada"
    },
    NotificationType.REPORT_GENERATED.value: {
        "icon": "<i class='bi bi-file-earmark-text-fill'></i>",
        "color": "info",
        "title": "Relatório Gerado"
    },
    NotificationType.ERROR.value: {
        "icon": "<i class='bi bi-exclamation-triangle-fill'></i>",
        "color": "danger",
        "title": "Erro"
    },
    NotificationType.INFO.value: {
        "icon": "<i class='bi bi-info-circle-fill'></i>",
        "color": "info",
        "title": "Informação"
    },
}


class WebNotificationManager:
    """Gerencia notificações com persistência no banco de dados."""
    
    def __init__(self):
        self._db = None
        self._max_notifications = 200  # Manter últimas 200 no banco
    
    def _get_db(self):
        """Obtém conexão com o banco de dados (lazy loading)."""
        if self._db is None:
            from database import get_db_manager
            self._db = get_db_manager()
        return self._db
    
    def _generate_id(self) -> str:
        """Gera ID único curto para notificação."""
        return str(uuid.uuid4())[:8]
    
    def add(
        self,
        notification_type: str,
        message: str,
        match_id: Optional[int] = None,
        match_name: Optional[str] = None,
        data: Optional[Dict] = None
    ) -> Dict:
        """
        Adiciona nova notificação no banco de dados.
        
        Args:
            notification_type: Tipo da notificação (ver NotificationType)
            message: Mensagem descritiva
            match_id: ID do match relacionado (opcional)
            match_name: Nome do match (opcional)
            data: Dados adicionais (opcional)
            
        Returns:
            Dict com a notificação criada
        """
        config = NOTIFICATION_CONFIG.get(notification_type, {
            "icon": "<i class='bi bi-bell-fill'></i>",
            "color": "secondary",
            "title": "Notificação"
        })
        
        notification_id = self._generate_id()
        now = datetime.utcnow()
        
        try:
            from database.models import Notification
            db = self._get_db()
            
            with db.get_session() as session:
                notification = Notification(
                    notification_id=notification_id,
                    notification_type=notification_type,
                    title=config["title"],
                    message=message[:500],  # Limitar tamanho
                    icon=config["icon"],
                    color=config["color"],
                    match_id=match_id,
                    match_name=match_name,
                    extra_data=json.dumps(data) if data else None,
                    is_read=False,
                    created_at=now
                )
                session.add(notification)
                session.commit()
                
                # Limpar notificações antigas se necessário
                self._cleanup_old_notifications(session)
                
                logger.debug(f"🔔 Notificação: {config['icon']} {message[:50]}...")
                
                return {
                    "id": notification_id,
                    "type": notification_type,
                    "title": config["title"],
                    "icon": config["icon"],
                    "color": config["color"],
                    "message": message,
                    "match_id": match_id,
                    "match_name": match_name,
                    "data": data or {},
                    "read": False,
                    "created_at": now.isoformat(),
                    "timestamp": now.strftime("%H:%M")
                }
                
        except Exception as e:
            logger.error(f"Erro ao salvar notificação: {e}")
            # Retornar notificação mesmo sem persistir
            return {
                "id": notification_id,
                "type": notification_type,
                "title": config["title"],
                "icon": config["icon"],
                "color": config["color"],
                "message": message,
                "match_id": match_id,
                "match_name": match_name,
                "data": data or {},
                "read": False,
                "created_at": now.isoformat(),
                "timestamp": now.strftime("%H:%M")
            }
    
    def _cleanup_old_notifications(self, session):
        """Remove notificações antigas mantendo apenas as mais recentes."""
        try:
            from sqlalchemy import func

            from database.models import Notification
            
            count = session.query(func.count(Notification.id)).scalar()
            
            if count > self._max_notifications:
                # Pegar IDs das notificações mais antigas para deletar
                oldest = session.query(Notification.id).order_by(
                    Notification.created_at.desc()
                ).offset(self._max_notifications).all()
                
                if oldest:
                    ids_to_delete = [n.id for n in oldest]
                    session.query(Notification).filter(
                        Notification.id.in_(ids_to_delete)
                    ).delete(synchronize_session=False)
                    session.commit()
                    
        except Exception as e:
            logger.debug(f"Cleanup de notificações: {e}")
    
    def get_all(self, limit: int = 50) -> List[Dict]:
        """Retorna todas as notificações (mais recentes primeiro) do banco."""
        try:
            from database.models import Notification
            db = self._get_db()
            
            with db.get_session() as session:
                notifications = session.query(Notification).order_by(
                    Notification.created_at.desc()
                ).limit(limit).all()
                
                return [self._notification_to_dict(n) for n in notifications]
                
        except Exception as e:
            logger.error(f"Erro ao buscar notificações: {e}")
            return []
    
    def get_unread(self) -> List[Dict]:
        """Retorna apenas notificações não lidas do banco."""
        try:
            from database.models import Notification
            db = self._get_db()
            
            with db.get_session() as session:
                notifications = session.query(Notification).filter(
                    Notification.is_read == False
                ).order_by(Notification.created_at.desc()).all()
                
                return [self._notification_to_dict(n) for n in notifications]
                
        except Exception as e:
            logger.error(f"Erro ao buscar notificações não lidas: {e}")
            return []
    
    def get_unread_count(self) -> int:
        """Retorna contagem de não lidas do banco."""
        try:
            from sqlalchemy import func

            from database.models import Notification
            db = self._get_db()
            
            with db.get_session() as session:
                count = session.query(func.count(Notification.id)).filter(
                    Notification.is_read == False
                ).scalar()
                return count or 0
                
        except Exception as e:
            logger.error(f"Erro ao contar notificações: {e}")
            return 0
    
    def mark_as_read(self, notification_id: str) -> bool:
        """Marca notificação como lida no banco."""
        try:
            from database.models import Notification
            db = self._get_db()
            
            with db.get_session() as session:
                notification = session.query(Notification).filter(
                    Notification.notification_id == notification_id
                ).first()
                
                if notification:
                    notification.is_read = True
                    notification.read_at = datetime.utcnow()
                    session.commit()
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Erro ao marcar notificação como lida: {e}")
            return False
    
    def mark_all_as_read(self) -> int:
        """Marca todas como lidas no banco. Retorna quantidade marcada."""
        try:
            from database.models import Notification
            db = self._get_db()
            
            with db.get_session() as session:
                count = session.query(Notification).filter(
                    Notification.is_read == False
                ).update({
                    "is_read": True,
                    "read_at": datetime.utcnow()
                }, synchronize_session=False)
                session.commit()
                return count
                
        except Exception as e:
            logger.error(f"Erro ao marcar todas como lidas: {e}")
            return 0
    
    def delete(self, notification_id: str) -> bool:
        """Remove notificação do banco."""
        try:
            from database.models import Notification
            db = self._get_db()
            
            with db.get_session() as session:
                result = session.query(Notification).filter(
                    Notification.notification_id == notification_id
                ).delete(synchronize_session=False)
                session.commit()
                return result > 0
                
        except Exception as e:
            logger.error(f"Erro ao remover notificação: {e}")
            return False
    
    def clear_all(self) -> int:
        """Remove todas as notificações do banco. Retorna quantidade removida."""
        try:
            from database.models import Notification
            db = self._get_db()
            
            with db.get_session() as session:
                count = session.query(Notification).delete(synchronize_session=False)
                session.commit()
                return count
                
        except Exception as e:
            logger.error(f"Erro ao limpar notificações: {e}")
            return 0
    
    def _notification_to_dict(self, notification) -> Dict:
        """Converte modelo Notification para dicionário."""
        try:
            extra_data = json.loads(notification.extra_data) if notification.extra_data else {}
        except:
            extra_data = {}
        
        return {
            "id": notification.notification_id,
            "type": notification.notification_type,
            "title": notification.title,
            "icon": notification.icon or "📢",
            "color": notification.color or "secondary",
            "message": notification.message,
            "match_id": notification.match_id,
            "match_name": notification.match_name,
            "data": extra_data,
            "read": notification.is_read,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
            "timestamp": notification.created_at.strftime("%H:%M") if notification.created_at else ""
        }
    
    # =========================================
    # Métodos de conveniência por tipo
    # =========================================
    
    def notify_new_message(self, match_name: str, match_id: int, preview: str):
        """Notifica nova mensagem recebida."""
        return self.add(
            NotificationType.NEW_MESSAGE.value,
            f"{match_name}: {preview[:50]}{'...' if len(preview) > 50 else ''}",
            match_id=match_id,
            match_name=match_name,
            data={"preview": preview}
        )
    
    def notify_whatsapp_possible(self, match_name: str, match_id: int, phone: str):
        """Notifica possível número de WhatsApp detectado."""
        return self.add(
            NotificationType.WHATSAPP_POSSIBLE.value,
            f"Possível WhatsApp de {match_name}: {phone}",
            match_id=match_id,
            match_name=match_name,
            data={"phone": phone}
        )
    
    def notify_whatsapp_confirmed(self, match_name: str, match_id: int, phone: str):
        """Notifica WhatsApp confirmado."""
        return self.add(
            NotificationType.WHATSAPP_CONFIRMED.value,
            f"WhatsApp de {match_name}: {phone}",
            match_id=match_id,
            match_name=match_name,
            data={"phone": phone}
        )
    
    def notify_date_possible(self, match_name: str, match_id: int, context: str = ""):
        """Notifica possível interesse em encontro."""
        return self.add(
            NotificationType.DATE_POSSIBLE.value,
            f"{match_name} demonstrou interesse em sair",
            match_id=match_id,
            match_name=match_name,
            data={"context": context}
        )
    
    def notify_date_confirmed(self, match_name: str, match_id: int, details: str = ""):
        """Notifica encontro confirmado."""
        msg = f"Encontro marcado com {match_name}!"
        if details:
            msg += f" {details}"
        return self.add(
            NotificationType.DATE_CONFIRMED.value,
            msg,
            match_id=match_id,
            match_name=match_name,
            data={"details": details}
        )
    
    def notify_hot_conversation(self, match_name: str, match_id: int, temperature: float):
        """Notifica conversa quente."""
        return self.add(
            NotificationType.HOT_CONVERSATION.value,
            f"Conversa quente com {match_name}! 🌡️ {temperature}/10",
            match_id=match_id,
            match_name=match_name,
            data={"temperature": temperature}
        )
    
    def notify_new_match(self, match_name: str, match_id: int):
        """Notifica novo match."""
        return self.add(
            NotificationType.NEW_MATCH.value,
            f"Novo match: {match_name}",
            match_id=match_id,
            match_name=match_name
        )
    
    def notify_unmatch(self, match_name: str, match_id: int):
        """Notifica unmatch."""
        return self.add(
            NotificationType.UNMATCH.value,
            f"{match_name} deu unmatch",
            match_id=match_id,
            match_name=match_name
        )
    
    def notify_automation_started(self):
        """Notifica início da automação."""
        return self.add(
            NotificationType.AUTOMATION_STARTED.value,
            "Ciclo de automação iniciado"
        )
    
    def notify_automation_complete(self, messages_sent: int, matches_processed: int, errors: int = 0):
        """Notifica conclusão da automação."""
        return self.add(
            NotificationType.AUTOMATION_COMPLETE.value,
            f"Enviadas: {messages_sent} | Processados: {matches_processed} | Erros: {errors}",
            data={
                "messages_sent": messages_sent,
                "matches_processed": matches_processed,
                "errors": errors
            }
        )
    
    def notify_error(self, error_message: str):
        """Notifica erro."""
        return self.add(
            NotificationType.ERROR.value,
            error_message[:200],
            data={"error": error_message}
        )
    
    def notify_info(self, message: str):
        """Notifica informação geral."""
        return self.add(
            NotificationType.INFO.value,
            message[:200]
        )


# Singleton global
_notification_manager: Optional[WebNotificationManager] = None


def get_notification_manager() -> WebNotificationManager:
    """Retorna instância singleton do gerenciador de notificações."""
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = WebNotificationManager()
    return _notification_manager


# Função de conveniência para uso assíncrono (compatibilidade com código existente)
async def notify(event_type: str, data: Dict) -> bool:
    """
    Função de conveniência para adicionar notificação.
    Mantém compatibilidade com código existente.
    
    Args:
        event_type: Tipo do evento
        data: Dados do evento
        
    Returns:
        True (sempre sucesso, persistido no banco)
    """
    manager = get_notification_manager()
    
    match_id = data.get('match_id')
    match_name = data.get('name', data.get('match_name', 'Match'))
    
    if event_type == 'whatsapp_received':
        manager.notify_whatsapp_confirmed(match_name, match_id, data.get('phone', ''))
    elif event_type == 'whatsapp_possible':
        manager.notify_whatsapp_possible(match_name, match_id, data.get('phone', ''))
    elif event_type == 'date_confirmed':
        manager.notify_date_confirmed(match_name, match_id, data.get('message', ''))
    elif event_type == 'date_possible':
        manager.notify_date_possible(match_name, match_id, data.get('context', ''))
    elif event_type == 'hot_conversation':
        manager.notify_hot_conversation(match_name, match_id, data.get('temperature', 0))
    elif event_type == 'new_message':
        manager.notify_new_message(match_name, match_id, data.get('message', ''))
    elif event_type == 'new_match':
        manager.notify_new_match(match_name, match_id)
    elif event_type == 'unmatch':
        manager.notify_unmatch(match_name, match_id)
    elif event_type == 'error':
        manager.notify_error(data.get('error', 'Erro desconhecido'))
    elif event_type == 'automation_complete':
        manager.notify_automation_complete(
            data.get('messages_sent', 0),
            data.get('matches_processed', 0),
            data.get('errors', 0)
        )
    elif event_type == 'automation_started':
        manager.notify_automation_started()
    else:
        # Evento genérico
        manager.add(event_type, str(data)[:100], match_id=match_id, match_name=match_name, data=data)
    
    return True
