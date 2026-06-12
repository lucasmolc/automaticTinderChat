"""
Testes para configuração de rate limiting com suporte a Redis.

Testa funcionalidades de:
- URI de storage padrão (memória)
- URI de storage com Redis configurado
- Limites padrão de rate limiting
- Verificação de disponibilidade do Redis
"""

import pytest
from unittest.mock import patch


class TestRateLimiterStorageConfiguration:
    """Testes para configuração de storage do rate limiter."""
    
    def test_get_storage_uri_returns_memory_by_default(self):
        """Testa que URI padrão é memória quando Redis não configurado."""
        from utils.rate_limiter import RateLimitConfig
        
        with patch.dict('os.environ', {}, clear=True):
            uri = RateLimitConfig.get_storage_uri()
            assert uri == "memory://"
    
    def test_get_storage_uri_returns_redis_when_configured(self):
        """Testa que URI é Redis quando REDIS_URL está configurado."""
        from utils.rate_limiter import RateLimitConfig
        
        with patch.dict('os.environ', {'REDIS_URL': 'redis://localhost:6379'}):
            uri = RateLimitConfig.get_storage_uri()
            assert uri == "redis://localhost:6379"
    
    def test_check_redis_available_returns_false_without_url(self):
        """Testa que Redis não disponível sem REDIS_URL."""
        from utils.rate_limiter import check_redis_available
        
        with patch.dict('os.environ', {}, clear=True):
            result = check_redis_available()
            assert result is False


class TestRateLimiterLimits:
    """Testes para limites de rate limiting."""
    
    def test_get_default_limits_returns_list(self):
        """Testa que limites padrão são uma lista."""
        from utils.rate_limiter import RateLimitConfig
        
        limits = RateLimitConfig.get_default_limits()
        
        assert isinstance(limits, list)
        assert len(limits) > 0
