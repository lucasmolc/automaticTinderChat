"""
Testes para o serviço ML Adaptive e Scheduler.
"""

import pytest
from unittest.mock import MagicMock, patch
import tempfile
from pathlib import Path


class TestPromptPerformance:
    """Testes para PromptPerformance dataclass."""
    
    def test_creation(self):
        """Testa criação de PromptPerformance."""
        from services.ml_adaptive import PromptPerformance
        
        perf = PromptPerformance(
            variant_name='test',
            experiment_name='test_exp',
            total_uses=100,
            responses=30
        )
        
        assert perf.variant_name == 'test'
        assert perf.experiment_name == 'test_exp'
        assert perf.total_uses == 100
        assert perf.responses == 30
    
    def test_response_rate(self):
        """Testa cálculo de taxa de resposta."""
        from services.ml_adaptive import PromptPerformance
        
        perf = PromptPerformance(
            variant_name='test',
            experiment_name='test',
            total_uses=100,
            responses=30
        )
        
        assert perf.response_rate() == 0.3
    
    def test_response_rate_zero_uses(self):
        """Testa taxa de resposta com zero usos."""
        from services.ml_adaptive import PromptPerformance
        
        perf = PromptPerformance(
            variant_name='test',
            experiment_name='test',
            total_uses=0,
            responses=0
        )
        
        assert perf.response_rate() == 0.0
    
    def test_success_rate(self):
        """Testa cálculo de taxa de sucesso."""
        from services.ml_adaptive import PromptPerformance
        
        perf = PromptPerformance(
            variant_name='test',
            experiment_name='test',
            total_uses=100,
            whatsapp=10,
            dates=5
        )
        
        assert perf.success_rate() == 0.15
    
    def test_thompson_sampling(self):
        """Testa amostragem Thompson."""
        from services.ml_adaptive import PromptPerformance
        
        perf = PromptPerformance(
            variant_name='test',
            experiment_name='test',
            alpha=10,
            beta=2
        )
        
        # Amostrar várias vezes
        samples = [perf.sample_thompson() for _ in range(100)]
        
        # Com alpha > beta, média deve ser > 0.5
        avg = sum(samples) / len(samples)
        assert avg > 0.5
    
    def test_update_thompson_success(self):
        """Testa atualização Thompson com sucesso."""
        from services.ml_adaptive import PromptPerformance
        
        perf = PromptPerformance(
            variant_name='test',
            experiment_name='test',
            alpha=1.0,
            beta=1.0
        )
        
        initial_alpha = perf.alpha
        perf.update_thompson(success=True)
        
        assert perf.alpha == initial_alpha + 1
    
    def test_update_thompson_failure(self):
        """Testa atualização Thompson com falha."""
        from services.ml_adaptive import PromptPerformance
        
        perf = PromptPerformance(
            variant_name='test',
            experiment_name='test',
            alpha=1.0,
            beta=1.0
        )
        
        initial_beta = perf.beta
        perf.update_thompson(success=False)
        
        assert perf.beta == initial_beta + 1


class TestConversationPattern:
    """Testes para ConversationPattern dataclass."""
    
    def test_creation(self):
        """Testa criação de ConversationPattern."""
        from services.ml_adaptive import ConversationPattern
        
        pattern = ConversationPattern(
            pattern_type='opening',
            keywords=['oi', 'olá'],
            tone='casual'
        )
        
        assert pattern.pattern_type == 'opening'
        assert pattern.tone == 'casual'
        assert 'oi' in pattern.keywords


class TestSchedulerService:
    """Testes para SchedulerService."""
    
    @pytest.fixture
    def scheduler(self):
        """Cria instância de SchedulerService para testes."""
        from services.scheduler_service import SchedulerService
        return SchedulerService()
    
    def test_scheduler_creation(self, scheduler):
        """Testa criação do scheduler."""
        assert scheduler is not None
        assert hasattr(scheduler, 'register_task')
        assert hasattr(scheduler, 'start')
        assert hasattr(scheduler, 'stop')
    
    def test_register_task(self, scheduler):
        """Testa registro de tarefa."""
        task_func = MagicMock()
        
        scheduler.register_task(
            name='new_test_task',
            func=task_func,
            interval_hours=1,
            enabled=True
        )
        
        assert 'new_test_task' in scheduler._tasks
    
    def test_run_task_now(self, scheduler):
        """Testa execução imediata de tarefa."""
        task_func = MagicMock()
        
        scheduler.register_task(
            name='immediate_task',
            func=task_func,
            interval_hours=1,
            enabled=True
        )
        
        result = scheduler.run_task_now('immediate_task')
        
        assert result is True
        task_func.assert_called_once()
    
    def test_run_nonexistent_task(self, scheduler):
        """Testa execução de tarefa inexistente."""
        result = scheduler.run_task_now('nonexistent_task')
        assert result is False
    
    def test_get_status(self, scheduler):
        """Testa obtenção de status."""
        status = scheduler.get_status()
        
        assert 'running' in status
        assert 'tasks' in status
    
    def test_default_tasks_exist(self, scheduler):
        """Testa que existem tarefas padrão."""
        # Deve ter pelo menos algumas tarefas registradas
        assert len(scheduler._tasks) > 0


class TestMLAdaptiveServiceBasic:
    """Testes básicos para MLAdaptiveService."""
    
    def test_service_import(self):
        """Testa que o serviço pode ser importado."""
        from services.ml_adaptive import MLAdaptiveService, get_ml_service, reset_ml_service
        
        assert MLAdaptiveService is not None
        assert get_ml_service is not None
        assert reset_ml_service is not None
    
    def test_prompt_performance_import(self):
        """Testa que PromptPerformance pode ser importado."""
        from services.ml_adaptive import PromptPerformance
        
        assert PromptPerformance is not None
    
    def test_conversation_pattern_import(self):
        """Testa que ConversationPattern pode ser importado."""
        from services.ml_adaptive import ConversationPattern
        
        assert ConversationPattern is not None


class TestEmbeddingsCacheIntegration:
    """Testes de integração para EmbeddingsCache."""
    
    @pytest.fixture
    def temp_cache_dir(self, tmp_path):
        """Cria diretório temporário para cache."""
        return tmp_path / 'cache'
    
    def test_cache_import(self):
        """Testa que o cache pode ser importado."""
        from services.embeddings_cache import EmbeddingsCache, get_embeddings_cache
        
        assert EmbeddingsCache is not None
        assert get_embeddings_cache is not None
    
    def test_cache_set_get(self, temp_cache_dir):
        """Testa set/get básico do cache."""
        from services.embeddings_cache import EmbeddingsCache
        
        cache = EmbeddingsCache(cache_dir=str(temp_cache_dir))
        
        # Armazena
        cache.set("test text", [0.1, 0.2, 0.3], "model")
        
        # Recupera
        result = cache.get("test text", "model")
        
        assert result is not None
        assert len(result) == 3
    
    def test_cache_miss(self, temp_cache_dir):
        """Testa cache miss."""
        from services.embeddings_cache import EmbeddingsCache
        
        cache = EmbeddingsCache(cache_dir=str(temp_cache_dir))
        
        result = cache.get("nonexistent", "model")
        
        assert result is None
    
    def test_cache_stats(self, temp_cache_dir):
        """Testa estatísticas do cache."""
        from services.embeddings_cache import EmbeddingsCache
        
        cache = EmbeddingsCache(cache_dir=str(temp_cache_dir))
        
        stats = cache.get_stats()
        
        assert 'hits' in stats
        assert 'misses' in stats
        assert 'writes' in stats
