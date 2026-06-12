"""
Sistema de métricas e observabilidade com Prometheus.
Coleta métricas de aplicação, automação e performance.

Métricas expostas:
- HTTP requests (latência, contagem, erros)
- Automação (mensagens enviadas, matches processados)
- AI (tokens usados, latência, custo)
- Conversão (WhatsApp, encontros)
- WebSocket (conexões ativas)

Endpoint: /metrics
"""

import os
import time
from typing import Dict, Optional, Callable
from functools import wraps
from datetime import datetime
from loguru import logger

# Prometheus metrics
try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Summary, Info,
        generate_latest, CONTENT_TYPE_LATEST,
        CollectorRegistry, multiprocess, REGISTRY
    )
    from prometheus_flask_exporter import PrometheusMetrics
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus-client não instalado. Métricas desabilitadas.")


# Registry customizado para permitir multiplos workers
if PROMETHEUS_AVAILABLE:
    # Usar multiprocess registry se em ambiente de produção
    if 'prometheus_multiproc_dir' in os.environ:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = REGISTRY


class MetricsCollector:
    """
    Coletor centralizado de métricas.
    Singleton thread-safe para uso em toda aplicação.
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
            
        self._initialized = True
        self._enabled = PROMETHEUS_AVAILABLE
        
        if not self._enabled:
            return
        
        # ==========================================
        # Métricas de Automação
        # ==========================================
        
        self.automation_messages_sent = Counter(
            'automation_messages_sent_total',
            'Total de mensagens enviadas pela automação',
            ['match_temperature', 'ai_generated']
        )
        
        self.automation_matches_processed = Counter(
            'automation_matches_processed_total',
            'Total de matches processados',
            ['status']  # new, awaiting, active
        )
        
        self.automation_cycles = Counter(
            'automation_cycles_total',
            'Total de ciclos de automação executados',
            ['result']  # success, error
        )
        
        self.automation_running = Gauge(
            'automation_running',
            'Indica se automação está rodando (1=sim, 0=não)'
        )
        
        self.automation_last_run = Gauge(
            'automation_last_run_timestamp',
            'Timestamp da última execução da automação'
        )
        
        # ==========================================
        # Métricas de AI
        # ==========================================
        
        self.ai_requests = Counter(
            'ai_requests_total',
            'Total de requisições à API de IA',
            ['provider', 'operation', 'status']
        )
        
        self.ai_tokens_used = Counter(
            'ai_tokens_used_total',
            'Total de tokens consumidos',
            ['provider', 'token_type']  # prompt, completion
        )
        
        self.ai_latency = Histogram(
            'ai_request_latency_seconds',
            'Latência das requisições de IA',
            ['provider', 'operation'],
            buckets=[0.5, 1, 2, 5, 10, 30, 60]
        )
        
        self.ai_cost = Counter(
            'ai_cost_dollars_total',
            'Custo total estimado de IA em dólares',
            ['provider']
        )
        
        # ==========================================
        # Métricas de Conversão
        # ==========================================
        
        self.conversion_whatsapp = Counter(
            'conversion_whatsapp_total',
            'Total de WhatsApps obtidos'
        )
        
        self.conversion_dates = Counter(
            'conversion_dates_total',
            'Total de encontros confirmados'
        )
        
        self.conversion_funnel = Gauge(
            'conversion_funnel_count',
            'Contagem em cada etapa do funil',
            ['stage']  # match, first_message, response, whatsapp, date
        )
        
        # ==========================================
        # Métricas de Performance
        # ==========================================
        
        self.request_latency = Histogram(
            'http_request_latency_seconds',
            'Latência de requisições HTTP',
            ['method', 'endpoint', 'status'],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
        )
        
        self.active_websocket_connections = Gauge(
            'websocket_connections_active',
            'Conexões WebSocket ativas'
        )
        
        self.database_query_latency = Histogram(
            'database_query_latency_seconds',
            'Latência de queries no banco',
            ['operation'],
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1]
        )
        
        # ==========================================
        # Métricas de Temperatura
        # ==========================================
        
        self.temperature_distribution = Gauge(
            'conversation_temperature_distribution',
            'Distribuição de temperaturas de conversa',
            ['temperature']  # cold, warm, hot
        )
        
        self.avg_response_time_by_temp = Gauge(
            'avg_response_time_hours_by_temperature',
            'Tempo médio de resposta por temperatura (em horas)',
            ['temperature']
        )
        
        # ==========================================
        # Info da aplicação
        # ==========================================
        
        self.app_info = Info(
            'app',
            'Informações da aplicação'
        )
        self.app_info.info({
            'name': 'automatic_dating_chat',
            'version': '1.0.0'
        })
        
        logger.debug("📊 MetricsCollector inicializado")
    
    # ==========================================
    # Métodos de coleta
    # ==========================================
    
    def record_message_sent(self, temperature: str = 'unknown', ai_generated: bool = False):
        """Registra mensagem enviada."""
        if self._enabled:
            self.automation_messages_sent.labels(
                match_temperature=temperature,
                ai_generated=str(ai_generated).lower()
            ).inc()
    
    def record_match_processed(self, status: str):
        """Registra match processado."""
        if self._enabled:
            self.automation_matches_processed.labels(status=status).inc()
    
    def record_automation_cycle(self, success: bool):
        """Registra ciclo de automação."""
        if self._enabled:
            result = 'success' if success else 'error'
            self.automation_cycles.labels(result=result).inc()
            self.automation_last_run.set(time.time())
    
    def set_automation_running(self, running: bool):
        """Define status da automação."""
        if self._enabled:
            self.automation_running.set(1 if running else 0)
    
    def record_ai_request(
        self,
        provider: str,
        operation: str,
        success: bool,
        latency_seconds: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost: float = 0.0
    ):
        """Registra requisição de IA."""
        if self._enabled:
            status = 'success' if success else 'error'
            self.ai_requests.labels(
                provider=provider,
                operation=operation,
                status=status
            ).inc()
            
            self.ai_latency.labels(
                provider=provider,
                operation=operation
            ).observe(latency_seconds)
            
            if prompt_tokens:
                self.ai_tokens_used.labels(
                    provider=provider,
                    token_type='prompt'
                ).inc(prompt_tokens)
            
            if completion_tokens:
                self.ai_tokens_used.labels(
                    provider=provider,
                    token_type='completion'
                ).inc(completion_tokens)
            
            if cost:
                self.ai_cost.labels(provider=provider).inc(cost)
    
    def record_whatsapp_obtained(self):
        """Registra WhatsApp obtido."""
        if self._enabled:
            self.conversion_whatsapp.inc()
    
    def record_date_confirmed(self):
        """Registra encontro confirmado."""
        if self._enabled:
            self.conversion_dates.inc()
    
    def update_funnel_metrics(self, funnel_data: Dict[str, int]):
        """Atualiza métricas do funil de conversão."""
        if self._enabled:
            for stage, count in funnel_data.items():
                self.conversion_funnel.labels(stage=stage).set(count)
    
    def set_websocket_connections(self, count: int):
        """Define número de conexões WebSocket."""
        if self._enabled:
            self.active_websocket_connections.set(count)
    
    def update_temperature_distribution(self, distribution: Dict[str, int]):
        """Atualiza distribuição de temperaturas."""
        if self._enabled:
            for temp, count in distribution.items():
                self.temperature_distribution.labels(temperature=temp).set(count)
    
    def update_response_time_by_temp(self, times: Dict[str, float]):
        """Atualiza tempo médio de resposta por temperatura."""
        if self._enabled:
            for temp, avg_time in times.items():
                self.avg_response_time_by_temp.labels(temperature=temp).set(avg_time)
    
    def record_db_query(self, operation: str, latency_seconds: float):
        """Registra latência de query no banco."""
        if self._enabled:
            self.database_query_latency.labels(operation=operation).observe(latency_seconds)


# Instância global
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Retorna instância global do coletor de métricas."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def init_metrics(app):
    """
    Inicializa métricas Prometheus na aplicação Flask.
    
    Adiciona:
    - Endpoint /metrics para scraping do Prometheus
    - Middleware para métricas HTTP automáticas
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning("Prometheus não disponível, métricas desabilitadas")
        return None
    
    # Usar PrometheusMetrics para métricas HTTP automáticas
    metrics = PrometheusMetrics(app, defaults_prefix='http')
    
    # Expor endpoint /metrics
    @app.route('/metrics')
    def metrics_endpoint():
        from flask import Response
        return Response(generate_latest(registry), mimetype=CONTENT_TYPE_LATEST)
    
    logger.debug("✅ Prometheus metrics inicializado em /metrics")
    
    return metrics


def track_time(operation: str):
    """
    Decorator para medir tempo de execução de funções.
    
    Uso:
        @track_time('generate_message')
        def generate_message(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.time() - start
                logger.debug(f"⏱️ {operation}: {elapsed:.3f}s")
        return wrapper
    return decorator


# ==========================================
# Métricas agregadas para dashboard
# ==========================================

def collect_dashboard_metrics(db_session) -> Dict:
    """
    Coleta métricas agregadas para o dashboard.
    Chamado periodicamente para atualizar métricas.
    """
    from database.models import Match, Message
    from sqlalchemy import func
    
    metrics = {}
    
    try:
        # Distribuição de temperatura
        temp_dist = db_session.query(
            Match.conversation_temperature,
            func.count(Match.id)
        ).filter(
            Match.conversation_temperature.isnot(None)
        ).group_by(Match.conversation_temperature).all()
        
        metrics['temperature_distribution'] = {
            temp or 'unknown': count for temp, count in temp_dist
        }
        
        # Funil de conversão
        total_matches = db_session.query(func.count(Match.id)).scalar() or 0
        with_messages = db_session.query(func.count(Match.id)).filter(
            Match.has_messages == True
        ).scalar() or 0
        awaiting = db_session.query(func.count(Match.id)).filter(
            Match.awaiting_my_response == True
        ).scalar() or 0
        whatsapp = db_session.query(func.count(Match.id)).filter(
            Match.whatsapp_obtained == True
        ).scalar() or 0
        dates = db_session.query(func.count(Match.id)).filter(
            Match.date_confirmed == True
        ).scalar() or 0
        
        metrics['funnel'] = {
            'match': total_matches,
            'first_message': with_messages,
            'response': awaiting,
            'whatsapp': whatsapp,
            'date': dates
        }
        
        # Atualizar métricas Prometheus
        collector = get_metrics_collector()
        collector.update_temperature_distribution(metrics['temperature_distribution'])
        collector.update_funnel_metrics(metrics['funnel'])
        
    except Exception as e:
        logger.error(f"Erro ao coletar métricas: {e}")
    
    return metrics
