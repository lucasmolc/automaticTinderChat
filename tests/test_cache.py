"""
Testes para o módulo utils/cache.py.
Testa LRUCache, SingletonCache e funções de conveniência.
"""

import time
from datetime import datetime
from threading import Thread

import pytest


class TestLRUCache:
    """Testes para o LRUCache."""
    
    @pytest.fixture
    def cache(self):
        """Cria instância do cache."""
        from utils.cache import LRUCache
        return LRUCache(ttl_seconds=10, max_size=5)
    
    def test_set_and_get(self, cache):
        """Testa set e get básicos."""
        cache.set("key1", {"data": "value1"})
        
        result = cache.get("key1")
        
        assert result == {"data": "value1"}
    
    def test_get_nonexistent_key(self, cache):
        """Testa get de chave inexistente."""
        result = cache.get("nonexistent")
        
        assert result is None
    
    def test_expired_entry(self):
        """Testa que entrada expirada retorna None."""
        from utils.cache import LRUCache
        cache = LRUCache(ttl_seconds=1, max_size=5)
        
        cache.set("key1", "value1")
        time.sleep(1.5)
        
        result = cache.get("key1")
        
        assert result is None
    
    def test_custom_max_age(self, cache):
        """Testa max_age personalizado no get."""
        cache.set("key1", "value1")
        
        # Com max_age muito curto, deve expirar após espera
        import time
        time.sleep(0.05)  # Espera 50ms
        result = cache.get("key1", max_age_seconds=0.01)  # 10ms de max_age
        
        assert result is None
    
    def test_lru_eviction(self):
        """Testa evicção LRU quando cache está cheio."""
        from utils.cache import LRUCache
        cache = LRUCache(ttl_seconds=3600, max_size=3)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # Acessar key1 para torná-lo mais recente
        cache.get("key1")
        
        # Adicionar key4, deve remover key2 (LRU)
        cache.set("key4", "value4")
        
        assert cache.get("key1") is not None  # Mais recente
        assert cache.get("key2") is None      # Evicted (LRU)
        assert cache.get("key3") is not None
        assert cache.get("key4") is not None
    
    def test_invalidate(self, cache):
        """Testa invalidação de item."""
        cache.set("key1", "value1")
        
        existed = cache.invalidate("key1")
        
        assert existed is True
        assert cache.get("key1") is None
    
    def test_invalidate_nonexistent(self, cache):
        """Testa invalidação de item inexistente."""
        existed = cache.invalidate("nonexistent")
        
        assert existed is False
    
    def test_clear(self, cache):
        """Testa limpeza do cache."""
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        count = cache.clear()
        
        assert count == 2
        assert len(cache) == 0
    
    def test_cleanup_expired(self):
        """Testa limpeza de itens expirados."""
        from utils.cache import LRUCache
        cache = LRUCache(ttl_seconds=1, max_size=100)
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        time.sleep(1.5)
        cache.set("key3", "value3")  # Ainda válido
        
        removed = cache.cleanup_expired()
        
        assert removed == 2
        assert cache.get("key3") is not None
    
    def test_stats(self, cache):
        """Testa estatísticas do cache."""
        cache.set("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss
        
        stats = cache.get_stats()
        
        assert stats['size'] == 1
        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert 'hit_rate' in stats
    
    def test_len(self, cache):
        """Testa __len__."""
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        assert len(cache) == 2
    
    def test_contains(self, cache):
        """Testa __contains__."""
        cache.set("key1", "value1")
        
        assert "key1" in cache
        assert "key2" not in cache
    
    def test_thread_safety(self):
        """Testa thread safety do cache."""
        from utils.cache import LRUCache
        cache = LRUCache(ttl_seconds=3600, max_size=1000)
        
        def writer(thread_id):
            for i in range(100):
                cache.set(f"key_{thread_id}_{i}", f"value_{i}")
        
        def reader(thread_id):
            for i in range(100):
                cache.get(f"key_{thread_id}_{i}")
        
        threads = []
        for i in range(5):
            threads.append(Thread(target=writer, args=(i,)))
            threads.append(Thread(target=reader, args=(i,)))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Se chegou aqui sem exceção, é thread-safe
        assert True


class TestSingletonCache:
    """Testes para o SingletonCache."""
    
    def test_get_instance_creates_cache(self):
        """Testa criação de instância singleton."""
        from utils.cache import SingletonCache
        
        cache1 = SingletonCache.get_instance("test_singleton1")
        cache2 = SingletonCache.get_instance("test_singleton1")
        
        assert cache1 is cache2
        
        # Limpar
        SingletonCache.reset_instance("test_singleton1")
    
    def test_different_names_different_instances(self):
        """Testa que nomes diferentes criam instâncias diferentes."""
        from utils.cache import SingletonCache
        
        cache1 = SingletonCache.get_instance("test_a")
        cache2 = SingletonCache.get_instance("test_b")
        
        assert cache1 is not cache2
        
        # Limpar
        SingletonCache.reset_instance("test_a")
        SingletonCache.reset_instance("test_b")
    
    def test_reset_instance(self):
        """Testa reset de instância singleton."""
        from utils.cache import SingletonCache
        
        cache1 = SingletonCache.get_instance("test_reset")
        cache1.set("key", "value")
        
        SingletonCache.reset_instance("test_reset")
        
        cache2 = SingletonCache.get_instance("test_reset")
        assert cache2.get("key") is None
        
        # Limpar
        SingletonCache.reset_instance("test_reset")
    
    def test_get_all_stats(self):
        """Testa get_all_stats."""
        from utils.cache import SingletonCache
        
        SingletonCache.get_instance("stats_test1")
        SingletonCache.get_instance("stats_test2")
        
        stats = SingletonCache.get_all_stats()
        
        assert "stats_test1" in stats
        assert "stats_test2" in stats
        
        # Limpar
        SingletonCache.reset_instance("stats_test1")
        SingletonCache.reset_instance("stats_test2")


class TestConvenienceFunctions:
    """Testes para funções de conveniência."""
    
    def test_get_profile_cache(self):
        """Testa get_profile_cache."""
        from utils.cache import get_profile_cache
        
        cache1 = get_profile_cache()
        cache2 = get_profile_cache()
        
        assert cache1 is cache2
    
    def test_get_api_response_cache(self):
        """Testa get_api_response_cache."""
        from utils.cache import get_api_response_cache
        
        cache1 = get_api_response_cache()
        cache2 = get_api_response_cache()
        
        assert cache1 is cache2
    
    def test_reset_all_caches(self):
        """Testa reset_all_caches."""
        from utils.cache import get_profile_cache, reset_all_caches
        
        cache = get_profile_cache()
        cache.set("test_key", "test_value")
        
        reset_all_caches()
        
        # Depois do reset, cache deve estar vazio
        # (ou ser nova instância)
        new_cache = get_profile_cache()
        # O valor pode estar None porque é nova instância
        # ou porque foi limpo
        assert new_cache.get("test_key") is None
