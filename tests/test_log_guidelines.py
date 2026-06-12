"""
Testes para helpers de padronização de níveis de log (LogGuidelines).

Testa funcionalidades de:
- Enum LogContext com valores corretos
- Função log_operation
- Decorator log_with_context
"""

import pytest


class TestLogContextEnum:
    """Testes para o enum LogContext."""
    
    def test_automation_context_value(self):
        """Testa valor do contexto AUTOMATION."""
        from utils.log_guidelines import LogContext
        
        assert LogContext.AUTOMATION.value == "automation"
    
    def test_database_context_value(self):
        """Testa valor do contexto DATABASE."""
        from utils.log_guidelines import LogContext
        
        assert LogContext.DATABASE.value == "database"
    
    def test_ai_context_value(self):
        """Testa valor do contexto AI."""
        from utils.log_guidelines import LogContext
        
        assert LogContext.AI.value == "ai"
    
    def test_web_context_value(self):
        """Testa valor do contexto WEB."""
        from utils.log_guidelines import LogContext
        
        assert LogContext.WEB.value == "web"


class TestLogOperationFunction:
    """Testes para a função log_operation."""
    
    def test_log_operation_with_success(self):
        """Testa log_operation sem erro (sucesso)."""
        from utils.log_guidelines import log_operation, LogContext
        
        # Não deve levantar exceção
        log_operation(
            context=LogContext.AUTOMATION,
            operation="test_operation",
            details={"key": "value"}
        )
    
    def test_log_operation_with_failure(self):
        """Testa log_operation com erro (falha)."""
        from utils.log_guidelines import log_operation, LogContext
        
        log_operation(
            context=LogContext.DATABASE,
            operation="test_operation",
            success=False,
            error=ValueError("Test error message")
        )


class TestLogWithContextDecorator:
    """Testes para o decorator log_with_context."""
    
    def test_decorated_function_returns_result(self):
        """Testa que função decorada retorna resultado."""
        from utils.log_guidelines import log_with_context, LogContext
        
        @log_with_context(LogContext.AI)
        def sample_function():
            return "expected_result"
        
        result = sample_function()
        
        assert result == "expected_result"
    
    def test_decorated_function_propagates_exception(self):
        """Testa que função decorada propaga exceções."""
        from utils.log_guidelines import log_with_context, LogContext
        
        @log_with_context(LogContext.AI)
        def error_function():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            error_function()
