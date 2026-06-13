"""
Serviço de Analytics do Automatic Tinder Chat.
Centraliza métricas, estatísticas e análises de dados.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from database import get_db_manager
from database.models import AIInteraction, ExecutionLog, Match, Message
from services.ml_adaptive import get_ml_service
from utils.ab_testing import get_ab_manager
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ConversationMetrics:
    """Métricas de uma conversa."""
    match_id: int
    total_messages: int
    my_messages: int
    their_messages: int
    avg_response_time: Optional[float]
    conversation_duration_days: int
    temperature: str
    has_whatsapp: bool
    has_date: bool


@dataclass
class DailyStats:
    """Estatísticas diárias."""
    date: str
    new_matches: int
    messages_sent: int
    messages_received: int
    responses_rate: float
    whatsapp_obtained: int
    dates_confirmed: int
    ai_cost: float


class AnalyticsService:
    """
    Serviço centralizado de analytics.
    Fornece métricas, estatísticas e insights sobre o sistema.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._db = get_db_manager()
        self._ab_manager = get_ab_manager()
        self._ml_service = get_ml_service()
        self._initialized = True
    
    def get_overview_stats(self) -> Dict[str, Any]:
        """
        Retorna estatísticas gerais do sistema.
        """
        with self._db.get_session() as session:
            total_matches = session.query(Match).filter(
                Match.is_unmatched == False
            ).count()
            
            active_conversations = session.query(Match).filter(
                Match.has_messages == True,
                Match.is_blocked == False,
                Match.is_unmatched == False,
                Match.whatsapp_obtained == False,
                Match.date_confirmed == False
            ).count()
            
            whatsapp_obtained = session.query(Match).filter(
                Match.whatsapp_obtained == True
            ).count()
            
            dates_confirmed = session.query(Match).filter(
                Match.date_confirmed == True
            ).count()
            
            total_messages = session.query(Message).count()
            my_messages = session.query(Message).filter(
                Message.is_from_me == True
            ).count()
            
            # Taxa de resposta
            matches_with_first_msg = session.query(Match).filter(
                Match.first_message_sent == True
            ).count()
            
            matches_with_response = session.query(Match).filter(
                Match.first_message_sent == True,
                Match.has_messages == True
            ).count()
            
            response_rate = (
                matches_with_response / matches_with_first_msg * 100
                if matches_with_first_msg > 0 else 0
            )
            
            # Custo de IA (últimos 30 dias)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            ai_cost = session.query(AIInteraction).filter(
                AIInteraction.created_at >= thirty_days_ago
            ).with_entities(
                # Importar func do SQLAlchemy
            ).all()
            
            # Calcular custo total
            total_cost = sum(
                interaction.estimated_cost or 0
                for interaction in session.query(AIInteraction).filter(
                    AIInteraction.created_at >= thirty_days_ago
                ).all()
            )
            
            return {
                'total_matches': total_matches,
                'active_conversations': active_conversations,
                'whatsapp_obtained': whatsapp_obtained,
                'dates_confirmed': dates_confirmed,
                'total_messages': total_messages,
                'my_messages': my_messages,
                'their_messages': total_messages - my_messages,
                'response_rate': round(response_rate, 1),
                'ai_cost_30d': round(total_cost, 2),
                'funnel': {
                    'matches': total_matches,
                    'first_message_sent': matches_with_first_msg,
                    'got_response': matches_with_response,
                    'whatsapp': whatsapp_obtained,
                    'dates': dates_confirmed
                }
            }
    
    def get_ab_testing_summary(self) -> Dict[str, Any]:
        """
        Retorna resumo dos experimentos A/B com insights de ML.
        """
        experiments = self._ab_manager.get_all_experiments()
        ml_stats = self._ml_service.get_stats()
        
        summaries = []
        for exp_name, exp_data in experiments.items():
            ml_insights = self._ml_service.get_experiment_insights(exp_name)
            
            summaries.append({
                'name': exp_name,
                'description': exp_data.get('description', ''),
                'is_active': exp_data.get('is_active', True),
                'total_impressions': exp_data.get('total_impressions', 0),
                'variants': exp_data.get('variants', []),
                'ml_insights': {
                    'winner': ml_insights.get('winner'),
                    'statistical_significance': ml_insights.get('statistical_significance'),
                    'recommendation': ml_insights.get('recommendation')
                }
            })
        
        return {
            'experiments': summaries,
            'ml_stats': ml_stats
        }
    
    def get_conversation_funnel(self, days: int = 30) -> Dict[str, Any]:
        """
        Retorna funil de conversão detalhado.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        with self._db.get_session() as session:
            # Matches no período
            matches = session.query(Match).filter(
                Match.created_at >= cutoff
            ).all()
            
            funnel = {
                'period_days': days,
                'total_matches': len(matches),
                'stages': {
                    'matched': len(matches),
                    'first_message_sent': sum(1 for m in matches if m.first_message_sent),
                    'got_response': sum(1 for m in matches if m.has_messages and m.first_message_sent),
                    'warm_conversation': sum(1 for m in matches if m.conversation_temperature in ('warm', 'hot')),
                    'hot_conversation': sum(1 for m in matches if m.conversation_temperature == 'hot'),
                    'whatsapp_obtained': sum(1 for m in matches if m.whatsapp_obtained),
                    'date_confirmed': sum(1 for m in matches if m.date_confirmed)
                }
            }
            
            # Calcular taxas de conversão entre estágios
            stages = funnel['stages']
            funnel['conversion_rates'] = {}
            
            prev_value = stages['matched']
            for stage_name, value in stages.items():
                if prev_value > 0:
                    funnel['conversion_rates'][stage_name] = round(value / prev_value * 100, 1)
                else:
                    funnel['conversion_rates'][stage_name] = 0
                prev_value = value if value > 0 else prev_value
            
            return funnel
    
    def get_temperature_distribution(self) -> Dict[str, int]:
        """
        Retorna distribuição de temperaturas das conversas.
        """
        with self._db.get_session() as session:
            matches = session.query(Match).filter(
                Match.has_messages == True,
                Match.is_unmatched == False
            ).all()
            
            distribution = {
                'cold': 0,
                'warm': 0,
                'hot': 0,
                'unknown': 0
            }
            
            for match in matches:
                temp = match.conversation_temperature or 'unknown'
                if temp in distribution:
                    distribution[temp] += 1
                else:
                    distribution['unknown'] += 1
            
            return distribution
    
    def get_ai_usage_stats(self, days: int = 30) -> Dict[str, Any]:
        """
        Retorna estatísticas de uso de IA.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        with self._db.get_session() as session:
            interactions = session.query(AIInteraction).filter(
                AIInteraction.created_at >= cutoff
            ).all()
            
            by_type = {}
            by_provider = {}
            total_cost = 0
            total_tokens = 0
            
            for interaction in interactions:
                # Por tipo
                itype = interaction.interaction_type or 'unknown'
                if itype not in by_type:
                    by_type[itype] = {'count': 0, 'cost': 0, 'tokens': 0}
                by_type[itype]['count'] += 1
                by_type[itype]['cost'] += interaction.estimated_cost or 0
                by_type[itype]['tokens'] += interaction.total_tokens or 0
                
                # Por provedor
                provider = interaction.provider or 'unknown'
                if provider not in by_provider:
                    by_provider[provider] = {'count': 0, 'cost': 0, 'tokens': 0}
                by_provider[provider]['count'] += 1
                by_provider[provider]['cost'] += interaction.estimated_cost or 0
                by_provider[provider]['tokens'] += interaction.total_tokens or 0
                
                total_cost += interaction.estimated_cost or 0
                total_tokens += interaction.total_tokens or 0
            
            return {
                'period_days': days,
                'total_interactions': len(interactions),
                'total_cost': round(total_cost, 2),
                'total_tokens': total_tokens,
                'avg_cost_per_interaction': round(total_cost / len(interactions), 4) if interactions else 0,
                'by_type': by_type,
                'by_provider': by_provider
            }


# Singleton
_analytics_service: Optional[AnalyticsService] = None


def get_analytics_service() -> AnalyticsService:
    """Retorna instância singleton do AnalyticsService."""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AnalyticsService()
    return _analytics_service
