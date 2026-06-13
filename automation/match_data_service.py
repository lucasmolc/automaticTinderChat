"""
MatchDataService - Serviço centralizado para fornecimento de dados de matches.

Este serviço é responsável por:
- Fornecer dados de matches EXCLUSIVAMENTE do banco de dados
- NÃO realizar nenhuma operação de scraping/tela
- Formatar dados para consumo pela IA
- Calcular interesses em comum

PRINCÍPIO: A execução NUNCA deve buscar dados da tela.
           Todos os dados devem vir do banco (previamente sincronizados).
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from database import Match, MatchRepository, MyProfileRepository
from utils.logger import get_logger

from .match_fetching import validate_and_clean_name

logger = get_logger(__name__)


class MatchDataService:
    """
    Serviço para fornecimento de dados de matches para execução.
    
    Diferente do MatchDataFetcher (usado no SYNC), este serviço:
    - NÃO acessa a tela/UI em nenhum momento
    - Retorna APENAS dados do banco de dados
    - Retorna None se dados insuficientes (sinal para sincronizar primeiro)
    """
    
    def __init__(self, session):
        """
        Args:
            session: Sessão do SQLAlchemy
        """
        self.session = session
        self.match_repo = MatchRepository(session)
        self.my_profile_repo = MyProfileRepository(session)
        self._my_profile_cache: Optional[Dict] = None
        self._my_interests_cache: Optional[set] = None
    
    def get_my_profile_data(self) -> Dict:
        """
        Obtém dados do meu perfil do banco.
        
        Returns:
            Dict com dados do perfil
        """
        if self._my_profile_cache:
            return self._my_profile_cache
        
        profile = self.my_profile_repo.get_or_create()
        
        self._my_profile_cache = {
            "id": profile.id,
            "name": profile.name,
            "age": profile.age,
            "bio": profile.bio,
            "job_title": profile.job_title,
            "school": profile.school,
            "interests": [i.interest_name for i in profile.interests] if profile.interests else []
        }
        
        self._my_interests_cache = set(self._my_profile_cache.get("interests", []))
        
        return self._my_profile_cache
    
    def get_match_profile_for_ai(self, match: Match) -> Tuple[Optional[Dict], str]:
        """
        Obtém dados do match formatados para enviar para IA.
        Retorna APENAS dados do banco - não acessa tela.
        
        Args:
            match: Objeto Match do banco
            
        Returns:
            Tuple (profile_data, status):
            - (Dict, "ok") - Dados completos disponíveis
            - (Dict, "incomplete") - Dados incompletos (nome=Unknown ou sem bio)
            - (None, "unmatched") - Match marcado como unmatch
            - (None, "blocked") - Match bloqueado
        """
        # Verificar estados de bloqueio
        if match.is_unmatched:
            return None, "unmatched"
        
        if match.is_blocked:
            return None, "blocked"
        
        # Validar nome (pode estar incorreto no banco)
        validated_name = validate_and_clean_name(match.name, "Unknown")
        
        # Buscar interesses do match
        interests = self.match_repo.get_interests(match)
        
        profile_data = {
            "name": validated_name,
            "age": match.age,
            "bio": match.bio,
            "distance_km": match.distance_km,
            "job_title": match.job_title,
            "school": match.school,
            "gender": match.gender,
            "city": match.city,
            "relationship_intent": match.relationship_intent,
            "sexual_orientations": match.sexual_orientations,
            "interests": interests,
            "photos_count": match.photos_count,
            "is_verified": match.is_verified,
            "matched_at": match.matched_at,
        }
        
        # Verificar se dados estão completos para IA
        # NOTA: Relaxado para aceitar matches apenas com nome válido
        # Para matches sem bio/job, a IA usará mensagem genérica
        is_incomplete = validated_name == "Unknown"  # Apenas nome inválido bloqueia
        
        # Flag para indicar que precisa de mensagem genérica
        profile_data["needs_generic_message"] = (
            not match.bio and not match.job_title  # Sem contexto sobre a pessoa
        )
        
        status = "incomplete" if is_incomplete else "ok"
        
        return profile_data, status
    
    def get_common_interests(self, match_interests: List[str]) -> List[str]:
        """
        Calcula interesses em comum entre meu perfil e o match.
        
        Args:
            match_interests: Lista de interesses do match
            
        Returns:
            Lista de interesses em comum
        """
        if self._my_interests_cache is None:
            self.get_my_profile_data()  # Popula o cache
        
        match_interests_set = set(match_interests or [])
        return list(self._my_interests_cache & match_interests_set)
    
    def get_matches_for_first_message(self, limit: int = 10) -> List[Match]:
        """
        Obtém matches elegíveis para primeira mensagem.
        
        Retorna apenas matches que:
        - Não têm mensagens
        - Não estão bloqueados/unmatched
        - Têm dados suficientes para gerar mensagem
        
        Args:
            limit: Número máximo de matches
            
        Returns:
            Lista de objetos Match
        """
        matches = self.match_repo.get_matches_without_messages()[:limit]
        
        # Filtrar matches com dados suficientes
        valid_matches = []
        for match in matches:
            profile, status = self.get_match_profile_for_ai(match)
            if status == "ok":
                valid_matches.append(match)
            elif status == "incomplete":
                logger.debug(
                    f"Match {match.name} ({match.tinder_match_id[:12]}...) "
                    f"com dados incompletos - precisa sync"
                )
        
        return valid_matches
    
    def get_matches_awaiting_response(self, limit: int = 10) -> List[Match]:
        """
        Obtém matches aguardando minha resposta.
        
        Args:
            limit: Número máximo de matches
            
        Returns:
            Lista de objetos Match
        """
        return self.match_repo.get_matches_awaiting_my_response()[:limit]
    
    def get_match_messages(self, match: Match, limit: int = 20) -> List[Dict]:
        """
        Obtém histórico de mensagens de um match do banco.
        
        Args:
            match: Objeto Match
            limit: Número máximo de mensagens
            
        Returns:
            Lista de dicts com mensagens ordenadas por data
        """
        from database import MessageRepository
        msg_repo = MessageRepository(self.session)
        
        messages = msg_repo.get_messages_for_match(match.id, limit=limit)
        
        return [
            {
                "content": msg.content,
                "is_from_me": msg.is_from_me,
                "sent_at": msg.sent_at,
                "message_type": msg.message_type
            }
            for msg in messages
        ]
    
    def has_sufficient_data(self, match: Match) -> bool:
        """
        Verifica se o match tem dados suficientes para interação.
        
        Args:
            match: Objeto Match
            
        Returns:
            True se tem dados suficientes
        """
        _, status = self.get_match_profile_for_ai(match)
        return status == "ok"
    
    def get_incomplete_matches(self, limit: int = 50) -> List[Match]:
        """
        Retorna matches que precisam de sincronização (dados incompletos).
        
        Útil para disparar mini-sync direcionado.
        
        Args:
            limit: Número máximo de matches
            
        Returns:
            Lista de matches com dados incompletos
        """
        incomplete = []
        
        # Buscar matches ativos
        matches = self.match_repo.get_active_matches()[:limit * 2]
        
        for match in matches:
            profile, status = self.get_match_profile_for_ai(match)
            if status == "incomplete":
                incomplete.append(match)
                if len(incomplete) >= limit:
                    break
        
        return incomplete


def get_match_data_service(session) -> MatchDataService:
    """
    Factory function para criar MatchDataService.
    
    Args:
        session: Sessão do SQLAlchemy
        
    Returns:
        Instância de MatchDataService
    """
    return MatchDataService(session)
