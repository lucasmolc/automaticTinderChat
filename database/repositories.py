"""
Repositórios para operações com o banco de dados.
Implementa padrão Repository para cada entidade.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from utils.logger import get_logger

from .models import (
    AIInteraction,
    Analytics,
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

# Importar validação de nome do módulo de fetching
try:
    from automation.match_fetching import validate_and_clean_name
except ImportError:
    # Fallback se não conseguir importar
    def validate_and_clean_name(name, fallback="Unknown"):
        if not name or len(str(name).strip()) < 2:
            return fallback
        name = str(name).strip()
        if len(name) > 50 or ':' in name or 'match' in name.lower():
            return fallback
        return name

# Importar limpeza de cidade
try:
    from utils.helpers import clean_city
except ImportError:
    # Fallback se não conseguir importar
    import re
    def clean_city(text):
        if not text:
            return ""
        text = re.sub(r'\s*/.*$', '', str(text).strip())
        return text if len(text) > 2 and len(text) < 100 else ""

logger = get_logger(__name__)


# ===================== FILTROS COMPARTILHADOS =====================

def active_match_filter():
    """
    Filtro reutilizável para matches ativos.
    Exclui: bloqueados, unmatched, com WhatsApp obtido, com encontro confirmado.
    
    Uso:
        query.filter(active_match_filter())
    """
    return and_(
        or_(Match.is_blocked == False, Match.is_blocked == None),
        or_(Match.is_unmatched == False, Match.is_unmatched == None),
        or_(Match.whatsapp_obtained == False, Match.whatsapp_obtained == None),
        or_(Match.date_confirmed == False, Match.date_confirmed == None)
    )


def pending_first_message_filter():
    """
    Filtro para matches que precisam de primeira mensagem.
    """
    return and_(
        Match.has_messages == False,
        Match.first_message_sent == False,
        active_match_filter()
    )


def awaiting_response_filter():
    """
    Filtro para matches aguardando minha resposta.
    """
    return and_(
        Match.awaiting_my_response == True,
        active_match_filter()
    )


def pending_resend_filter():
    """
    Filtro para matches marcados para reenvio de mensagem.
    Matches que tiveram mensagem incompleta/cortada e precisam de complemento.
    """
    return and_(
        Match.pending_resend == True,
        active_match_filter()
    )


class MyProfileRepository:
    """Repositório para operações com meu perfil."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_or_create(self) -> MyProfile:
        """Obtém o perfil existente ou cria um novo."""
        profile = self.session.query(MyProfile).first()
        if not profile:
            profile = MyProfile()
            self.session.add(profile)
            self.session.flush()
            logger.debug("Novo perfil criado no banco.")
        return profile
    
    def update(self, profile: MyProfile, **kwargs) -> MyProfile:
        """Atualiza campos do perfil."""
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.updated_at = datetime.utcnow()
        return profile
    
    def add_photo(self, profile: MyProfile, photo_url: str, order: int, description: str = None) -> MyProfilePhoto:
        """Adiciona foto ao perfil."""
        photo = MyProfilePhoto(
            profile_id=profile.id,
            photo_url=photo_url,
            photo_order=order,
            description=description
        )
        self.session.add(photo)
        return photo
    
    def clear_photos(self, profile: MyProfile) -> None:
        """Remove todas as fotos do perfil."""
        self.session.query(MyProfilePhoto).filter(
            MyProfilePhoto.profile_id == profile.id
        ).delete()
    
    def add_interest(self, profile: MyProfile, interest_name: str) -> MyProfileInterest:
        """Adiciona interesse ao perfil."""
        interest = MyProfileInterest(
            profile_id=profile.id,
            interest_name=interest_name
        )
        self.session.add(interest)
        return interest
    
    def clear_interests(self, profile: MyProfile) -> None:
        """Remove todos os interesses do perfil."""
        self.session.query(MyProfileInterest).filter(
            MyProfileInterest.profile_id == profile.id
        ).delete()


class MatchRepository:
    """Repositório para operações com matches."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_tinder_id(self, tinder_match_id: str, eager_load: bool = True) -> Optional[Match]:
        """
        Busca match pelo ID do Tinder.
        
        Args:
            tinder_match_id: ID do match no Tinder
            eager_load: Se True, carrega mensagens e interesses junto (default: True)
        """
        query = self.session.query(Match)
        if eager_load:
            query = query.options(
                joinedload(Match.messages),
                joinedload(Match.interests)
            )
        return query.filter(Match.tinder_match_id == tinder_match_id).first()
    
    def create(self, tinder_match_id: str, **kwargs) -> Match:
        """
        Cria novo match com valores padrão importantes.
        
        Args:
            tinder_match_id: ID do match no Tinder
            **kwargs: Campos adicionais
            
        Returns:
            Match criado
        """
        # Garantir que last_interaction_at seja inicializado para evitar bloqueio por inatividade
        if 'last_interaction_at' not in kwargs:
            kwargs['last_interaction_at'] = datetime.utcnow()
        if 'created_at' not in kwargs:
            kwargs['created_at'] = datetime.utcnow()
            
        match = Match(tinder_match_id=tinder_match_id, **kwargs)
        self.session.add(match)
        self.session.flush()
        logger.debug(f"Novo match criado: {match.name or tinder_match_id}")
        return match
    
    def get_or_create(self, tinder_match_id: str, **kwargs) -> tuple[Match, bool]:
        """Obtém match existente ou cria novo. Retorna (match, created)."""
        match = self.get_by_tinder_id(tinder_match_id)
        if match:
            return match, False
        return self.create(tinder_match_id, **kwargs), True
    
    def update(self, match: Match, **kwargs) -> Match:
        """Atualiza campos do match."""
        for key, value in kwargs.items():
            if hasattr(match, key):
                setattr(match, key, value)
        match.updated_at = datetime.utcnow()
        return match
    
    def update_from_profile(self, match: Match, profile_data: Dict, overwrite: bool = False) -> Dict[str, any]:
        """
        Atualiza match com dados extraídos do perfil de forma centralizada.
        
        Substitui código duplicado em:
        - sync_matches_only() seção 3 (matches novos)
        - sync_matches_only() seção 4 (mensagens)
        - send_first_messages()
        - respond_to_messages()
        
        Args:
            match: Match a ser atualizado
            profile_data: Dict com dados extraídos (name, age, bio, photos, interests, etc)
            overwrite: Se True, sobrescreve mesmo se já tiver valor. Default False.
        
        Returns:
            Dict com campos que foram atualizados
        """
        updated_fields = {}
        
        # Mapeamento de campos do profile para campos do match
        field_mapping = {
            'name': 'name',
            'age': 'age',
            'bio': 'bio',
            'distance_km': 'distance_km',
            'job_title': 'job_title',
            'school': 'school',
            'gender': 'gender',
            'city': 'city',
            'relationship_intent': 'relationship_intent',
            'relationship_type': 'relationship_type',
            'lifestyle_info': 'lifestyle_info',
            'sexual_orientations': 'sexual_orientations',
            'matched_at': 'matched_at',
        }
        
        # Atualizar campos simples
        for profile_key, match_key in field_mapping.items():
            value = profile_data.get(profile_key)
            if value:
                current = getattr(match, match_key, None)
                
                # Validação especial para o campo nome
                if match_key == 'name':
                    # Usar função centralizada de validação de nome
                    validated_name = validate_and_clean_name(value, fallback=None)
                    if not validated_name:
                        continue  # Nome inválido, pular
                    if current and current != 'Unknown' and not overwrite:
                        continue  # Já tem nome válido, não sobrescrever
                    value = validated_name
                
                # Validação especial para o campo cidade
                if match_key == 'city':
                    # Usar função de limpeza de cidade
                    cleaned_city = clean_city(value)
                    if not cleaned_city:
                        continue  # Cidade inválida, pular
                    value = cleaned_city
                
                # Só atualiza se: overwrite=True OU campo está vazio OU é "Unknown"
                if overwrite or not current or current == 'Unknown':
                    setattr(match, match_key, value)
                    updated_fields[match_key] = value
        
        # Campo verified/is_verified
        if profile_data.get('verified') or profile_data.get('is_verified'):
            match.is_verified = True
            updated_fields['is_verified'] = True
        
        # Foto de perfil - com verificação de duplicação
        photo_url = profile_data.get('profile_photo_url')
        if photo_url and (overwrite or not match.profile_photo_url):
            # Verificar duplicação
            duplicate = self.find_by_profile_photo(photo_url, exclude_match_id=match.id)
            if not duplicate:
                match.profile_photo_url = photo_url
                updated_fields['profile_photo_url'] = photo_url
            else:
                # Foto duplicada - tentar usar alternativa das fotos do perfil
                photos = profile_data.get('photos', [])
                for photo in photos:
                    alt_url = photo.get('url')
                    if alt_url and alt_url != photo_url:
                        dup = self.find_by_profile_photo(alt_url, exclude_match_id=match.id)
                        if not dup:
                            match.profile_photo_url = alt_url
                            updated_fields['profile_photo_url'] = alt_url
                            break
        
        # Fotos do perfil
        photos = profile_data.get('photos', [])
        if photos:
            self.clear_photos(match)
            for photo in photos:
                self.add_photo(match, photo.get('url'), photo.get('order', 0))
            match.photos_count = len(photos)
            updated_fields['photos_count'] = len(photos)
        
        # Interesses
        interests = profile_data.get('interests', [])
        if interests:
            my_interests = profile_data.get('my_interests', [])
            self.update_interests(match, interests, my_interests)
            updated_fields['interests'] = interests
        
        match.updated_at = datetime.utcnow()
        return updated_fields

    def update_interests(self, match: Match, interests: List[str], my_interests: List[str] = None) -> None:
        """Atualiza interesses do match (remove antigos e adiciona novos)."""
        # Limpar interesses antigos
        self.session.query(MatchInterest).filter(
            MatchInterest.match_id == match.id
        ).delete()
        
        # Adicionar novos
        my_interests_set = set(my_interests) if my_interests else set()
        for interest_name in interests:
            if interest_name and interest_name.strip():
                is_common = interest_name in my_interests_set
                interest = MatchInterest(
                    match_id=match.id,
                    interest_name=interest_name.strip(),
                    is_common=is_common
                )
                self.session.add(interest)
        
        match.interests_count = len(interests)
        match.updated_at = datetime.utcnow()
    
    def add_interest(self, match: Match, interest_name: str, is_common: bool = False) -> MatchInterest:
        """Adiciona um interesse ao match."""
        interest = MatchInterest(
            match_id=match.id,
            interest_name=interest_name,
            is_common=is_common
        )
        self.session.add(interest)
        return interest
    
    def get_interests(self, match: Match) -> List[str]:
        """Retorna lista de interesses do match."""
        return [i.interest_name for i in match.interests] if match.interests else []
    
    def get_matches_without_messages(self) -> List[Match]:
        """
        Retorna matches que ainda não receberam nenhuma mensagem (exceto bloqueados/finalizados).
        Usa eager loading para carregar mensagens e interesses em uma única query.
        """
        return self.session.query(Match).options(
            joinedload(Match.messages),
            joinedload(Match.interests)
        ).filter(
            pending_first_message_filter()
        ).all()
    
    def get_matches_awaiting_my_response(self) -> List[Match]:
        """
        Retorna matches aguardando minha resposta (exceto bloqueados/finalizados).
        Usa eager loading para carregar mensagens e interesses em uma única query.
        """
        return self.session.query(Match).options(
            joinedload(Match.messages),
            joinedload(Match.interests)
        ).filter(
            awaiting_response_filter()
        ).all()
    
    def block_match(self, match: Match, reason: str = None) -> Match:
        """Bloqueia um match para não receber mensagens automáticas."""
        match.is_blocked = True
        match.blocked_reason = reason
        match.blocked_at = datetime.utcnow()
        match.updated_at = datetime.utcnow()
        logger.debug(f"Match bloqueado: {match.name or match.tinder_match_id} - Motivo: {reason or 'Não informado'}")
        return match
    
    def unblock_match(self, match: Match) -> Match:
        """Desbloqueia um match."""
        match.is_blocked = False
        match.blocked_reason = None
        match.blocked_at = None
        match.updated_at = datetime.utcnow()
        logger.debug(f"Match desbloqueado: {match.name or match.tinder_match_id}")
        return match
    
    def get_blocked_matches(self) -> List[Match]:
        """Retorna todos os matches bloqueados."""
        return self.session.query(Match).filter(
            Match.is_blocked == True
        ).all()
    
    def get_by_id(self, match_id: int, eager_load: bool = True) -> Optional[Match]:
        """
        Busca match pelo ID interno.
        
        Args:
            match_id: ID do match
            eager_load: Se True, carrega mensagens e interesses junto (default: True)
        """
        query = self.session.query(Match)
        if eager_load:
            query = query.options(
                joinedload(Match.messages),
                joinedload(Match.interests)
            )
        return query.filter(Match.id == match_id).first()
    
    def get_matches_with_recent_interaction(self, days: int = 7) -> List[Match]:
        """Retorna matches com interação recente."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        return self.session.query(Match).filter(
            Match.last_interaction_at >= cutoff_date
        ).all()
    
    def get_inactive_matches(self, days: int = 7) -> List[Match]:
        """Retorna matches sem interação há X dias."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        return self.session.query(Match).filter(
            or_(
                Match.last_interaction_at < cutoff_date,
                Match.last_interaction_at.is_(None)
            )
        ).all()
    
    def get_all(self, limit: int = None, eager_load: bool = False) -> List[Match]:
        """
        Retorna todos os matches.
        
        Args:
            limit: Limite de resultados
            eager_load: Se True, carrega mensagens e interesses junto
        """
        query = self.session.query(Match)
        if eager_load:
            query = query.options(
                joinedload(Match.messages),
                joinedload(Match.interests)
            )
        query = query.order_by(Match.created_at.desc())
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def count_total(self) -> int:
        """Conta total de matches."""
        return self.session.query(func.count(Match.id)).scalar()
    
    def count_without_messages(self) -> int:
        """Conta matches que ainda não receberam mensagem."""
        return self.session.query(func.count(Match.id)).filter(
            pending_first_message_filter()
        ).scalar() or 0
    
    def count_awaiting_response(self) -> int:
        """Conta matches aguardando minha resposta."""
        return self.session.query(func.count(Match.id)).filter(
            awaiting_response_filter()
        ).scalar() or 0
    
    def get_matches_pending_resend(self) -> List[Match]:
        """
        Retorna matches marcados para reenvio de mensagem (mensagem incompleta).
        Usa eager loading para carregar mensagens e interesses em uma única query.
        """
        return self.session.query(Match).options(
            joinedload(Match.messages),
            joinedload(Match.interests)
        ).filter(
            pending_resend_filter()
        ).all()
    
    def count_pending_resend(self) -> int:
        """Conta matches marcados para reenvio."""
        return self.session.query(func.count(Match.id)).filter(
            pending_resend_filter()
        ).scalar() or 0
    
    def mark_for_resend(self, match: Match, reason: str = None) -> Match:
        """Marca um match para reenvio de mensagem."""
        from datetime import datetime
        match.pending_resend = True
        match.resend_reason = reason or 'Mensagem incompleta'
        match.resend_at = datetime.utcnow()
        match.updated_at = datetime.utcnow()
        logger.debug(f"Match marcado para reenvio: {match.name or match.tinder_match_id} - Motivo: {match.resend_reason}")
        return match
    
    def clear_resend(self, match: Match) -> Match:
        """Remove flag de reenvio de um match."""
        from datetime import datetime
        match.pending_resend = False
        match.resend_reason = None
        match.resend_at = None
        match.updated_at = datetime.utcnow()
        logger.debug(f"Flag de reenvio removida: {match.name or match.tinder_match_id}")
        return match
    
    def find_by_profile_photo(self, photo_url: str, exclude_match_id: int = None) -> Match:
        """
        Busca match por URL de foto de perfil.
        Usado para detectar duplicação de fotos.
        
        Args:
            photo_url: URL da foto de perfil
            exclude_match_id: ID do match a excluir da busca (o próprio)
        
        Returns:
            Match com a mesma foto ou None
        """
        query = self.session.query(Match).filter(
            Match.profile_photo_url == photo_url
        )
        if exclude_match_id:
            query = query.filter(Match.id != exclude_match_id)
        return query.first()
    
    def add_photo(self, match: Match, photo_url: str, order: int, description: str = None) -> MatchPhoto:
        """Adiciona foto ao match."""
        photo = MatchPhoto(
            match_id=match.id,
            photo_url=photo_url,
            photo_order=order,
            description=description
        )
        self.session.add(photo)
        return photo
    
    def clear_photos(self, match: Match) -> None:
        """Remove todas as fotos do match."""
        self.session.query(MatchPhoto).filter(
            MatchPhoto.match_id == match.id
        ).delete()
    
    def add_interest(self, match: Match, interest_name: str, is_common: bool = False) -> MatchInterest:
        """Adiciona interesse ao match."""
        interest = MatchInterest(
            match_id=match.id,
            interest_name=interest_name,
            is_common=is_common
        )
        self.session.add(interest)
        return interest
    
    def clear_interests(self, match: Match) -> None:
        """Remove todos os interesses do match."""
        self.session.query(MatchInterest).filter(
            MatchInterest.match_id == match.id
        ).delete()
    
    def delete_old_matches(self, days: int = 365) -> int:
        """
        Exclui matches mais antigos que X dias (baseado em matched_at ou created_at).
        
        Args:
            days: Número de dias para considerar antigo (default: 365 = 1 ano)
            
        Returns:
            Quantidade de matches excluídos
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Buscar matches antigos (usando matched_at se disponível, senão created_at)
        old_matches = self.session.query(Match).filter(
            or_(
                and_(Match.matched_at.isnot(None), Match.matched_at < cutoff_date),
                and_(Match.matched_at.is_(None), Match.created_at < cutoff_date)
            )
        ).all()
        
        deleted_count = 0
        for match in old_matches:
            # Primeiro deletar registros relacionados em TODAS as tabelas que referenciam match
            from .models import AIInteraction, Message
            self.session.query(AIInteraction).filter(AIInteraction.match_id == match.id).delete()
            self.session.query(Message).filter(Message.match_id == match.id).delete()
            self.session.query(MatchPhoto).filter(MatchPhoto.match_id == match.id).delete()
            self.session.query(MatchInterest).filter(MatchInterest.match_id == match.id).delete()
            
            # Deletar o match
            self.session.delete(match)
            deleted_count += 1
            logger.debug(f"Match antigo excluído: {match.name or match.tinder_match_id} (data: {match.matched_at or match.created_at})")
        
        return deleted_count
    
    def mark_as_unmatched(self, match: Match) -> Match:
        """Marca match como unmatch (pessoa desfez o match)."""
        match.is_unmatched = True
        match.unmatched_at = datetime.utcnow()
        match.updated_at = datetime.utcnow()
        logger.debug(f"Match marcado como unmatch: {match.name or match.tinder_match_id}")
        return match
    
    def get_active_matches(self) -> List[Match]:
        """Retorna matches ativos (não unmatched, não bloqueados)."""
        return self.session.query(Match).filter(
            or_(Match.is_unmatched == False, Match.is_unmatched == None),
            or_(Match.is_blocked == False, Match.is_blocked == None)
        ).all()
    
    def update_whatsapp(self, match: Match, phone_number: str) -> Match:
        """Atualiza informações de WhatsApp obtido."""
        match.whatsapp_obtained = True
        match.whatsapp_number = phone_number
        match.updated_at = datetime.utcnow()
        logger.debug(f"WhatsApp obtido de {match.name}: {phone_number}")
        return match
    
    def confirm_date(self, match: Match) -> Match:
        """Marca encontro como confirmado."""
        match.date_confirmed = True
        match.updated_at = datetime.utcnow()
        logger.debug(f"Encontro confirmado com {match.name}")
        return match
    
    def update_temperature_history(self, match: Match, temperature: str, score: float) -> Match:
        """Adiciona entrada no histórico de temperatura."""
        import json
        
        history = []
        if match.temperature_history:
            try:
                history = json.loads(match.temperature_history)
            except:
                history = []
        
        # Adicionar nova entrada
        history.append({
            "temp": temperature,
            "score": score,
            "at": datetime.utcnow().isoformat()
        })
        
        # Manter apenas últimos 20 registros
        if len(history) > 20:
            history = history[-20:]
        
        match.temperature_history = json.dumps(history)
        match.conversation_temperature = temperature
        match.temperature_score = score
        match.updated_at = datetime.utcnow()
        return match
    
    def get_matches_by_temperature(self, temperature: str) -> List[Match]:
        """Retorna matches por temperatura (cold, warm, hot)."""
        return self.session.query(Match).filter(
            Match.conversation_temperature == temperature,
            or_(Match.is_unmatched == False, Match.is_unmatched == None),
            or_(Match.is_blocked == False, Match.is_blocked == None)
        ).all()
    
    def get_hot_conversations(self) -> List[Match]:
        """Retorna matches com conversas quentes (temperatura >= 7)."""
        return self.session.query(Match).filter(
            Match.temperature_score >= 7,
            or_(Match.is_unmatched == False, Match.is_unmatched == None),
            or_(Match.is_blocked == False, Match.is_blocked == None)
        ).all()


class MessageRepository:
    """Repositório para operações com mensagens."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_tinder_id(self, tinder_message_id: str) -> Optional[Message]:
        """Busca mensagem pelo ID do Tinder."""
        return self.session.query(Message).filter(
            Message.tinder_message_id == tinder_message_id
        ).first()
    
    def create(self, match_id: int, content: str, is_from_me: bool, **kwargs) -> Message:
        """Cria nova mensagem."""
        message = Message(
            match_id=match_id,
            content=content,
            is_from_me=is_from_me,
            **kwargs
        )
        self.session.add(message)
        self.session.flush()
        return message
    
    def get_messages_for_match(self, match_id: int, limit: int = 10) -> List[Message]:
        """Retorna últimas mensagens de um match ordenadas por ID (mais recentes primeiro)."""
        return self.session.query(Message).filter(
            Message.match_id == match_id
        ).order_by(Message.id.desc()).limit(limit).all()
    
    def get_last_message(self, match_id: int) -> Optional[Message]:
        """Retorna última mensagem de um match."""
        return self.session.query(Message).filter(
            Message.match_id == match_id
        ).order_by(Message.id.desc()).first()
    
    def count_messages_for_match(self, match_id: int) -> int:
        """Conta mensagens de um match."""
        return self.session.query(func.count(Message.id)).filter(
            Message.match_id == match_id
        ).scalar()
    
    def count_my_messages(self) -> int:
        """Conta total de mensagens enviadas por mim."""
        return self.session.query(func.count(Message.id)).filter(
            Message.is_from_me == True
        ).scalar()


class ExecutionLogRepository:
    """Repositório para logs de execução."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create(self, execution_type: str) -> ExecutionLog:
        """Cria novo log de execução."""
        log = ExecutionLog(
            execution_type=execution_type,
            status="started"
        )
        self.session.add(log)
        self.session.flush()
        return log
    
    def complete(self, log: ExecutionLog, **kwargs) -> ExecutionLog:
        """Marca execução como completa."""
        log.status = "completed"
        log.completed_at = datetime.utcnow()
        
        if log.started_at:
            duration = (log.completed_at - log.started_at).total_seconds()
            log.duration_seconds = duration
        
        for key, value in kwargs.items():
            if hasattr(log, key):
                setattr(log, key, value)
        
        return log
    
    def fail(self, log: ExecutionLog, error_message: str) -> ExecutionLog:
        """Marca execução como falha."""
        log.status = "failed"
        log.completed_at = datetime.utcnow()
        log.error_message = error_message
        return log
    
    def get_recent(self, limit: int = 10) -> List[ExecutionLog]:
        """Retorna execuções recentes."""
        return self.session.query(ExecutionLog).order_by(
            ExecutionLog.started_at.desc()
        ).limit(limit).all()


class AIInteractionRepository:
    """Repositório para interações com IA."""
    
    # Mapeamento de tipos de interação para labels amigáveis
    INTERACTION_TYPE_LABELS = {
        'first_message': 'Primeira Mensagem',
        'message_generation': 'Geração de Mensagem',
        'response': 'Resposta',
        'profile_analysis': 'Análise de Perfil',
        'conversation_response': 'Resposta de Conversa',
        'analytics_insights': 'Insights Analíticos',
        'match_report': 'Relatório de Match',
        'report': 'Relatório',
        'analysis': 'Análise',
        'unknown': 'Outros',
        'test': 'Teste',
    }
    
    # Preços por modelo (USD por 1M tokens)
    MODEL_PRICING = {
        # OpenAI
        'gpt-4o-mini': {'input': 0.15, 'output': 0.60},
        'gpt-4o': {'input': 2.50, 'output': 10.00},
        'gpt-4-turbo': {'input': 10.00, 'output': 30.00},
        'gpt-3.5-turbo': {'input': 0.50, 'output': 1.50},
        # DeepSeek
        'deepseek-chat': {'input': 0.14, 'output': 0.28},
        'deepseek-reasoner': {'input': 0.55, 'output': 2.19},
    }
    
    def __init__(self, session: Session):
        self.session = session
    
    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """
        Calcula o custo estimado de uma chamada de IA.
        
        Args:
            model: Nome do modelo usado
            prompt_tokens: Tokens do prompt (input)
            completion_tokens: Tokens da resposta (output)
            
        Returns:
            Custo estimado em USD
        """
        model_name = model or 'gpt-4o-mini'
        pricing = self.MODEL_PRICING.get(model_name, self.MODEL_PRICING['gpt-4o-mini'])
        
        input_cost = (prompt_tokens / 1_000_000) * pricing['input']
        output_cost = (completion_tokens / 1_000_000) * pricing['output']
        
        return input_cost + output_cost
    
    def create(
        self,
        interaction_type: str,
        model_used: str,
        match_id: int = None,
        prompt_template: str = None,
        provider: str = None
    ) -> AIInteraction:
        """Cria novo registro de interação."""
        # Detectar provider pelo modelo se não especificado
        if not provider:
            if model_used and 'deepseek' in model_used.lower():
                provider = 'deepseek'
            else:
                provider = 'openai'
        
        interaction = AIInteraction(
            interaction_type=interaction_type,
            model_used=model_used,
            match_id=match_id,
            prompt_template=prompt_template,
            provider=provider
        )
        self.session.add(interaction)
        self.session.flush()
        return interaction
    
    def complete(
        self,
        interaction: AIInteraction,
        response_content: str,
        prompt_tokens: int,
        completion_tokens: int,
        response_time_ms: int
    ) -> AIInteraction:
        """Completa registro com resposta."""
        interaction.response_content = response_content
        interaction.prompt_tokens = prompt_tokens
        interaction.completion_tokens = completion_tokens
        interaction.total_tokens = prompt_tokens + completion_tokens
        interaction.response_time_ms = response_time_ms
        interaction.success = True
        
        # Calcular custo estimado baseado no modelo
        model = interaction.model_used or 'gpt-4o-mini'
        pricing = self.MODEL_PRICING.get(model, self.MODEL_PRICING['gpt-4o-mini'])
        
        input_cost = (prompt_tokens / 1_000_000) * pricing['input']
        output_cost = (completion_tokens / 1_000_000) * pricing['output']
        interaction.estimated_cost = input_cost + output_cost
        
        return interaction
    
    def fail(self, interaction: AIInteraction, error_message: str) -> AIInteraction:
        """Marca interação como falha."""
        interaction.success = False
        interaction.error_message = error_message
        return interaction
    
    def get_total_cost(self, days: int = 30) -> float:
        """Retorna custo total dos últimos X dias."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        result = self.session.query(func.sum(AIInteraction.estimated_cost)).filter(
            AIInteraction.created_at >= cutoff_date
        ).scalar()
        return result or 0.0
    
    def get_total_tokens(self, days: int = 30) -> int:
        """Retorna total de tokens dos últimos X dias."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        result = self.session.query(func.sum(AIInteraction.total_tokens)).filter(
            AIInteraction.created_at >= cutoff_date
        ).scalar()
        return result or 0
    
    def get_cost_by_provider(self, days: int = 30) -> dict:
        """
        Retorna custo total agrupado por provedor.
        
        Returns:
            Dict com provider -> custo total
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        try:
            results = self.session.query(
                AIInteraction.provider,
                func.sum(AIInteraction.estimated_cost).label('total_cost'),
                func.sum(AIInteraction.total_tokens).label('total_tokens'),
                func.count(AIInteraction.id).label('request_count')
            ).filter(
                AIInteraction.created_at >= cutoff_date,
                AIInteraction.success == True
            ).group_by(AIInteraction.provider).all()
            
            return {
                (r.provider or 'openai'): {
                    'cost': float(r.total_cost or 0),
                    'tokens': int(r.total_tokens or 0),
                    'requests': int(r.request_count or 0)
                }
                for r in results
            }
        except Exception:
            # Fallback se a coluna provider não existir
            result = self.session.query(
                func.sum(AIInteraction.estimated_cost).label('total_cost'),
                func.sum(AIInteraction.total_tokens).label('total_tokens'),
                func.count(AIInteraction.id).label('request_count')
            ).filter(
                AIInteraction.created_at >= cutoff_date,
                AIInteraction.success == True
            ).first()
            
            return {
                'openai': {
                    'cost': float(result.total_cost or 0) if result else 0,
                    'tokens': int(result.total_tokens or 0) if result else 0,
                    'requests': int(result.request_count or 0) if result else 0
                }
            }
    
    def get_cost_by_type(self, provider: str = None, days: int = 30) -> list:
        """
        Retorna custo agrupado por tipo de interação, ordenado do maior para menor.
        
        Args:
            provider: Filtrar por provedor específico (opcional)
            days: Número de dias a considerar
            
        Returns:
            Lista de dicts ordenada por custo decrescente
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        query = self.session.query(
            AIInteraction.interaction_type,
            func.sum(AIInteraction.estimated_cost).label('total_cost'),
            func.sum(AIInteraction.total_tokens).label('total_tokens'),
            func.count(AIInteraction.id).label('request_count'),
            func.avg(AIInteraction.response_time_ms).label('avg_response_time')
        ).filter(
            AIInteraction.created_at >= cutoff_date,
            AIInteraction.success == True
        )
        
        if provider:
            query = query.filter(AIInteraction.provider == provider)
        
        results = query.group_by(AIInteraction.interaction_type)\
            .order_by(func.sum(AIInteraction.estimated_cost).desc())\
            .all()
        
        return [
            {
                'type': r.interaction_type,
                'label': self.INTERACTION_TYPE_LABELS.get(r.interaction_type, r.interaction_type),
                'cost': float(r.total_cost or 0),
                'tokens': int(r.total_tokens or 0),
                'requests': int(r.request_count or 0),
                'avg_response_time_ms': int(r.avg_response_time or 0)
            }
            for r in results
        ]
    
    def get_detailed_stats(self, days: int = 30) -> dict:
        """
        Retorna estatísticas detalhadas de uso de IA.
        
        Returns:
            Dict com estatísticas completas por provedor e tipo
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Custo total
        total_cost = self.get_total_cost(days)
        total_tokens = self.get_total_tokens(days)
        
        # Por provedor
        by_provider = self.get_cost_by_provider(days)
        
        # Por tipo (todos os provedores)
        by_type = self.get_cost_by_type(days=days)
        
        # Por provedor com detalhamento por tipo
        providers_detailed = {}
        for provider in by_provider.keys():
            providers_detailed[provider] = {
                **by_provider[provider],
                'by_type': self.get_cost_by_type(provider=provider, days=days)
            }
        
        # Série temporal (últimos 7 dias)
        daily_costs = []
        for i in range(min(7, days)):
            day = datetime.utcnow().date() - timedelta(days=i)
            day_start = datetime.combine(day, datetime.min.time())
            day_end = datetime.combine(day, datetime.max.time())
            
            day_cost = self.session.query(func.sum(AIInteraction.estimated_cost)).filter(
                AIInteraction.created_at >= day_start,
                AIInteraction.created_at <= day_end,
                AIInteraction.success == True
            ).scalar() or 0
            
            daily_costs.append({
                'date': day.isoformat(),
                'cost': float(day_cost)
            })
        
        return {
            'total_cost': total_cost,
            'total_tokens': total_tokens,
            'by_provider': providers_detailed,
            'by_type': by_type,
            'daily_costs': list(reversed(daily_costs)),
            'period_days': days
        }


class AnalyticsRepository:
    """Repositório para métricas analíticas."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_or_create_for_date(self, date: datetime = None) -> Analytics:
        """Obtém ou cria registro de analytics para uma data."""
        if date is None:
            date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        analytics = self.session.query(Analytics).filter(
            func.date(Analytics.date) == date.date()
        ).first()
        
        if not analytics:
            analytics = Analytics(date=date)
            self.session.add(analytics)
            self.session.flush()
        
        return analytics
    
    def update(self, analytics: Analytics, **kwargs) -> Analytics:
        """Atualiza métricas."""
        for key, value in kwargs.items():
            if hasattr(analytics, key):
                setattr(analytics, key, value)
        return analytics
    
    def get_range(self, start_date: datetime, end_date: datetime) -> List[Analytics]:
        """Retorna analytics em um período."""
        return self.session.query(Analytics).filter(
            Analytics.date >= start_date,
            Analytics.date <= end_date
        ).order_by(Analytics.date).all()
    
    def get_summary(self, days: int = 30) -> dict:
        """Retorna resumo das métricas dos últimos X dias."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        result = self.session.query(
            func.sum(Analytics.new_matches).label("total_new_matches"),
            func.sum(Analytics.first_messages_sent).label("total_first_messages"),
            func.sum(Analytics.responses_received).label("total_responses"),
            func.sum(Analytics.whatsapp_conversions).label("total_whatsapp"),
            func.sum(Analytics.dates_confirmed).label("total_dates"),
            func.avg(Analytics.response_rate).label("avg_response_rate"),
            func.sum(Analytics.total_ai_cost).label("total_ai_cost")
        ).filter(Analytics.date >= cutoff_date).first()
        
        return {
            "total_new_matches": result.total_new_matches or 0,
            "total_first_messages": result.total_first_messages or 0,
            "total_responses": result.total_responses or 0,
            "total_whatsapp": result.total_whatsapp or 0,
            "total_dates": result.total_dates or 0,
            "avg_response_rate": result.avg_response_rate or 0,
            "total_ai_cost": result.total_ai_cost or 0
        }

class MatchReportRepository:
    """Repositório para relatórios de match."""
    
    def __init__(self, session: Session):
        self.session = session
    
    def create(self, match_id: int, **kwargs) -> MatchReport:
        """Cria um novo relatório para o match."""
        report = MatchReport(match_id=match_id, **kwargs)
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report
    
    def get_latest_by_match(self, match_id: int) -> Optional[MatchReport]:
        """Retorna o relatório mais recente de um match."""
        return self.session.query(MatchReport).filter(
            MatchReport.match_id == match_id
        ).order_by(MatchReport.created_at.desc()).first()
    
    def get_all_by_match(self, match_id: int) -> List[MatchReport]:
        """Retorna todos os relatórios de um match."""
        return self.session.query(MatchReport).filter(
            MatchReport.match_id == match_id
        ).order_by(MatchReport.created_at.desc()).all()
    
    def update(self, report: MatchReport, **kwargs) -> MatchReport:
        """Atualiza um relatório existente."""
        for key, value in kwargs.items():
            if hasattr(report, key):
                setattr(report, key, value)
        report.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(report)
        return report
    
    def delete_old_reports(self, match_id: int, keep_last: int = 5):
        """Mantém apenas os N relatórios mais recentes de um match."""
        reports = self.get_all_by_match(match_id)
        if len(reports) > keep_last:
            for report in reports[keep_last:]:
                self.session.delete(report)
            self.session.commit()