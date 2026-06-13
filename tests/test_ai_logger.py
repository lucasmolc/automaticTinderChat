"""
Testes para o helper centralizado de logging de interações com IA (AILogger).

Testa funcionalidades de:
- Context manager AIInteractionLogger
- Registro de interações bem-sucedidas
- Registro de erros em interações
- Funções helper log_ai_interaction e log_ai_error
"""

from unittest.mock import Mock, patch

import pytest


class TestAIInteractionLoggerContextManager:
    """Testes para AIInteractionLogger como context manager."""
    
    def test_creates_interaction_on_enter(self):
        """Testa que cria interação no __enter__."""
        from utils.ai_logger import AIInteractionLogger
        
        mock_session = Mock()
        
        with patch('database.AIInteractionRepository') as mock_repo:
            mock_instance = Mock()
            mock_instance.create.return_value = Mock(id=1)
            mock_repo.return_value = mock_instance
            
            with AIInteractionLogger(
                session=mock_session,
                interaction_type="test",
                model_used="gpt-4"
            ) as ai_logger:
                ai_logger.result = {"response": "test", "_metadata": {"prompt_tokens": 10}}
            
            mock_instance.create.assert_called_once()
    
    def test_records_failure_on_exception(self):
        """Testa que registra falha quando há exceção."""
        from utils.ai_logger import AIInteractionLogger
        
        mock_session = Mock()
        
        with patch('database.AIInteractionRepository') as mock_repo:
            mock_instance = Mock()
            mock_instance.create.return_value = Mock(id=1)
            mock_repo.return_value = mock_instance
            
            try:
                with AIInteractionLogger(
                    session=mock_session,
                    interaction_type="test",
                    model_used="gpt-4"
                ):
                    raise ValueError("Test error")
            except ValueError:
                pass
            
            mock_instance.fail.assert_called_once()


class TestAIInteractionHelperFunctions:
    """Testes para funções helper de AI logging."""
    
    def test_log_ai_interaction_creates_and_completes(self):
        """Testa que log_ai_interaction cria e completa interação."""
        from utils.ai_logger import log_ai_interaction
        
        mock_session = Mock()
        
        # Patch no database onde AIInteractionRepository é definido
        with patch('database.AIInteractionRepository') as mock_repo:
            mock_instance = Mock()
            mock_instance.create.return_value = Mock(id=1)
            mock_instance.calculate_cost.return_value = 0.001
            mock_repo.return_value = mock_instance
            
            log_ai_interaction(
                interaction_type="test",
                model_used="gpt-4",
                ai_result={"response": "ok", "_metadata": {"prompt_tokens": 10}},
                session=mock_session
            )
            
            mock_instance.create.assert_called_once()
            mock_instance.complete.assert_called_once()
    
    def test_log_ai_error_creates_and_fails(self):
        """Testa que log_ai_error cria interação e registra falha."""
        from utils.ai_logger import log_ai_error
        
        mock_session = Mock()
        
        # Patch no database onde AIInteractionRepository é definido
        with patch('database.AIInteractionRepository') as mock_repo:
            mock_instance = Mock()
            mock_instance.create.return_value = Mock(id=1)
            mock_repo.return_value = mock_instance
            
            log_ai_error(
                interaction_type="test",
                error_message="Test error",
                model_used="gpt-4",
                session=mock_session
            )
            
            mock_instance.create.assert_called_once()
            mock_instance.fail.assert_called_once()
