"""
Handler para envio e resposta de mensagens.
Extraído do orchestrator para melhor organização.
"""

import random
import asyncio
from datetime import datetime
from typing import Optional, List, Dict

from config import get_settings
from database import (
    get_db_manager, MatchRepository, MessageRepository, 
    AIInteractionRepository, MyProfileRepository
)
from ai import get_openai_client
from utils.logger import get_logger, log_automation_step
from utils.helpers import safe_json_dumps
from utils.whatsapp_detector import analyze_message_for_progression
from utils.notifications import get_notification_manager, notify
from .match_helpers import get_profile_cache, validate_ai_message

logger = get_logger(__name__)


class MessageHandler:
    """
    Gerencia envio e resposta de mensagens.
    
    Responsabilidades:
    - Enviar primeiras mensagens para novos matches
    - Responder mensagens recebidas
    - Detectar progressão (WhatsApp/encontros)
    - Validar mensagens da IA antes do envio
    """
    
    def __init__(self, extractor, db_manager, openai_client, notification_manager):
        """
        Inicializa o handler.
        
        Args:
            extractor: TinderDataExtractor para enviar mensagens
            db_manager: DatabaseManager para persistência
            openai_client: Cliente OpenAI para gerar mensagens
            notification_manager: Gerenciador de notificações
        """
        self.extractor = extractor
        self.db = db_manager
        self.openai = openai_client
        self.notification_manager = notification_manager
        self.settings = get_settings()
        self._profile_cache = get_profile_cache()
        
        # Estatísticas
        self.stats = {
            "messages_sent": 0,
            "whatsapp_detected": 0,
            "date_confirmations": 0,
            "errors": 0
        }
    
    def _validate_ai_message(self, message: str) -> bool:
        """Valida se mensagem da IA é adequada para envio."""
        is_valid, reason = validate_ai_message(message)
        if not is_valid:
            logger.warning(f"Mensagem rejeitada: {reason}")
        return is_valid
    
    def get_my_profile_data(self) -> Dict:
        """
        Obtém dados do meu perfil (do cache singleton ou banco).
        
        Returns:
            Dict com dados do perfil
        """
        # Tentar cache singleton primeiro
        cached = self._profile_cache.get("my_profile")
        if cached:
            return cached
        
        with self.db.get_session() as session:
            repo = MyProfileRepository(session)
            profile = repo.get_or_create()
            
            profile_data = {
                "name": profile.name,
                "age": profile.age,
                "bio": profile.bio,
                "interests": [i.interest_name for i in profile.interests]
            }
            
            # Salvar no cache singleton
            self._profile_cache.set("my_profile", profile_data)
            return profile_data
    
    async def send_first_message(
        self, 
        match, 
        match_repo: MatchRepository,
        msg_repo: MessageRepository,
        ai_repo: AIInteractionRepository
    ) -> Dict:
        """
        Envia primeira mensagem para um match.
        
        Args:
            match: Objeto Match do banco
            match_repo: Repository de matches
            msg_repo: Repository de mensagens
            ai_repo: Repository de interações AI
            
        Returns:
            Dict com resultado da operação
        """
        result = {
            "match_id": match.tinder_match_id,
            "name": match.name,
            "success": False,
            "message": None,
            "error": None
        }
        
        try:
            # Montar dados do match
            match_profile = {
                "name": match.name,
                "age": match.age,
                "bio": match.bio,
                "distance_km": match.distance_km,
                "job_title": match.job_title,
                "school": match.school,
                "interests": match_repo.get_interests(match),
                "photos_count": match.photos_count
            }
            
            # Gerar mensagem com IA
            ai_result = self.openai.generate_first_message(
                match_profile=match_profile
            )
            
            message = ai_result.get("message", "")
            
            # Validar e enviar
            if message and self._validate_ai_message(message):
                success = await self.extractor.send_message(
                    match.tinder_match_id,
                    message
                )
                
                if success:
                    # Registrar no banco
                    msg_repo.create(
                        match_id=match.id,
                        content=message,
                        is_from_me=True,
                        message_type="first_message",
                        ai_generated=True,
                        sent_at=datetime.utcnow()
                    )
                    
                    match_repo.update(
                        match,
                        has_messages=True,
                        first_message_sent=True,
                        awaiting_my_response=False,
                        last_message_text=message[:200] if message else None,
                        last_message_from_me=True,
                        last_message_at=datetime.utcnow(),
                        last_interaction_at=datetime.utcnow()
                    )
                    
                    self.stats["messages_sent"] += 1
                    result["success"] = True
                    result["message"] = message
                    
                    log_automation_step(f"✅ Mensagem enviada para {match.name}")
                else:
                    result["error"] = "Falha ao enviar via Tinder"
            else:
                result["error"] = "Mensagem inválida gerada pela IA"
            
            # Registrar uso da IA
            metadata = ai_result.get("_metadata", {})
            interaction = ai_repo.create(
                interaction_type="first_message",
                model_used=metadata.get("model", self.settings.openai_model),
                match_id=match.id,
                prompt_template="first_message"
            )
            ai_repo.complete(
                interaction,
                response_content=safe_json_dumps(ai_result),
                prompt_tokens=metadata.get("prompt_tokens", 0),
                completion_tokens=metadata.get("completion_tokens", 0),
                response_time_ms=metadata.get("response_time_ms", 0)
            )
            
        except Exception as e:
            logger.error(f"Erro ao enviar primeira mensagem para {match.name}: {e}")
            result["error"] = str(e)
            self.stats["errors"] += 1
        
        return result
    
    def analyze_received_message(self, message_content: str, match, match_repo: MatchRepository) -> Dict:
        """
        Analisa mensagem recebida para detectar WhatsApp/encontro.
        
        Args:
            message_content: Texto da mensagem
            match: Objeto Match
            match_repo: Repository de matches
            
        Returns:
            Dict com análise da mensagem
        """
        progression = analyze_message_for_progression(message_content)
        
        if progression['has_whatsapp'] and progression['whatsapp_number']:
            match_repo.update_whatsapp(match, progression['whatsapp_number'])
            self.stats["whatsapp_detected"] += 1
            
            # Notificar
            asyncio.create_task(notify('whatsapp_received', {
                'name': match.name,
                'phone': progression['whatsapp_number']
            }))
            
            log_automation_step(f"🎉 WhatsApp detectado de {match.name}")
        
        if progression['date_confirmation']:
            match_repo.confirm_date(match)
            self.stats["date_confirmations"] += 1
            
            asyncio.create_task(notify('date_confirmed', {
                'name': match.name,
                'message': message_content[:100]
            }))
            
            log_automation_step(f"🎉 Encontro confirmado com {match.name}!")
        
        return progression
    
    def reset_stats(self):
        """Reseta estatísticas."""
        self.stats = {
            "messages_sent": 0,
            "whatsapp_detected": 0,
            "date_confirmations": 0,
            "errors": 0
        }
