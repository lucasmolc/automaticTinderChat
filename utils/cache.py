"""
Sistema de cache genérico com TTL e LRU eviction.
Reutilizável em todo o projeto para evitar duplicação de código.
"""

from datetime import datetime
from typing import Optional, Dict, List, Any
from threading import Lock

from utils.logger import get_logger

logger = get_logger(__name__)


class LRUCache:
    """
    Cache genérico com TTL e eviction LRU (Least Recently Used).
    Thread-safe para uso em aplicações multi-thread.
    
    Uso:
        cache = LRUCache(ttl_seconds=3600, max_size=100)
        cache.set("key", {"data": "value"})
        data = cache.get("key")
    """
    
    def __init__(self, ttl_seconds: int = 3600, max_size: int = 500):
        """
        Args:
            ttl_seconds: Tempo de vida do cache em segundos (default: 1 hora)
            max_size: Número máximo de entradas no cache (default: 500)
        """
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._cache: Dict[str, Any] = {}
        self._timestamps: Dict[str, datetime] = {}
        self._access_order: List[str] = []
        self._lock = Lock()
        
        # Estatísticas
        self._hits = 0
        self._misses = 0
    
    def _update_access_order(self, key: str) -> None:
        """Atualiza ordem de acesso para LRU (não thread-safe, usar dentro de lock)."""
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
    
    def _evict_lru(self) -> int:
        """
        Remove entradas menos recentemente usadas até atingir max_size.
        Não thread-safe, usar dentro de lock.
        
        Returns:
            Número de entradas removidas
        """
        evicted = 0
        while len(self._cache) >= self.max_size and self._access_order:
            lru_key = self._access_order.pop(0)
            self._cache.pop(lru_key, None)
            self._timestamps.pop(lru_key, None)
            evicted += 1
            logger.debug(f"LRU eviction: removido '{lru_key}' do cache")
        return evicted
    
    def get(self, key: str, max_age_seconds: Optional[int] = None) -> Optional[Any]:
        """
        Obtém valor do cache se válido.
        
        Args:
            key: Chave do cache
            max_age_seconds: Idade máxima em segundos (sobrescreve ttl_seconds se fornecido)
            
        Returns:
            Valor cacheado ou None se expirado/inexistente
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            timestamp = self._timestamps.get(key)
            if not timestamp:
                self._misses += 1
                return None
            
            ttl = max_age_seconds if max_age_seconds is not None else self.ttl_seconds
            age = (datetime.utcnow() - timestamp).total_seconds()
            
            if age > ttl:
                # Expirado, remover
                self._cache.pop(key, None)
                self._timestamps.pop(key, None)
                if key in self._access_order:
                    self._access_order.remove(key)
                self._misses += 1
                return None
            
            self._update_access_order(key)
            self._hits += 1
            return self._cache[key]
    
    def set(self, key: str, value: Any) -> None:
        """
        Armazena valor no cache com eviction LRU se necessário.
        
        Args:
            key: Chave do cache
            value: Valor a armazenar
        """
        with self._lock:
            if key not in self._cache:
                self._evict_lru()
            
            self._cache[key] = value
            self._timestamps[key] = datetime.utcnow()
            self._update_access_order(key)
    
    def invalidate(self, key: str) -> bool:
        """
        Remove item do cache.
        
        Returns:
            True se item existia e foi removido
        """
        with self._lock:
            existed = key in self._cache
            self._cache.pop(key, None)
            self._timestamps.pop(key, None)
            if key in self._access_order:
                self._access_order.remove(key)
            return existed
    
    def clear(self) -> int:
        """
        Limpa todo o cache.
        
        Returns:
            Número de itens removidos
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._timestamps.clear()
            self._access_order.clear()
            return count
    
    def cleanup_expired(self) -> int:
        """
        Remove todas as entradas expiradas do cache.
        Deve ser chamado periodicamente para evitar memory leak.
        
        Returns:
            Número de entradas removidas
        """
        with self._lock:
            expired_keys = []
            now = datetime.utcnow()
            
            for key, timestamp in list(self._timestamps.items()):
                age = (now - timestamp).total_seconds()
                if age > self.ttl_seconds:
                    expired_keys.append(key)
            
            for key in expired_keys:
                self._cache.pop(key, None)
                self._timestamps.pop(key, None)
                if key in self._access_order:
                    self._access_order.remove(key)
            
            return len(expired_keys)
    
    def get_stats(self) -> Dict:
        """Retorna estatísticas do cache."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'ttl_seconds': self.ttl_seconds,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.1f}%"
            }
    
    def __len__(self) -> int:
        """Retorna número de itens no cache."""
        return len(self._cache)
    
    def __contains__(self, key: str) -> bool:
        """Verifica se key está no cache (sem verificar expiração)."""
        return key in self._cache


# ===================== SINGLETON PATTERN =====================

class SingletonCache:
    """
    Wrapper para criar caches singleton por nome.
    Útil para ter um cache global compartilhado entre módulos.
    """
    
    _instances: Dict[str, LRUCache] = {}
    _lock = Lock()
    
    @classmethod
    def get_instance(cls, name: str, ttl_seconds: int = 3600, max_size: int = 500) -> LRUCache:
        """
        Obtém ou cria uma instância singleton do cache.
        
        Args:
            name: Nome único do cache
            ttl_seconds: TTL para novos caches
            max_size: Tamanho máximo para novos caches
            
        Returns:
            Instância do LRUCache
        """
        with cls._lock:
            if name not in cls._instances:
                cls._instances[name] = LRUCache(ttl_seconds, max_size)
            return cls._instances[name]
    
    @classmethod
    def reset_instance(cls, name: str) -> bool:
        """
        Remove e reseta uma instância de cache.
        
        Returns:
            True se existia e foi removida
        """
        with cls._lock:
            if name in cls._instances:
                cls._instances[name].clear()
                del cls._instances[name]
                return True
            return False
    
    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict]:
        """Retorna estatísticas de todos os caches singleton."""
        with cls._lock:
            return {name: cache.get_stats() for name, cache in cls._instances.items()}


# ===================== CONVENIENCE FUNCTIONS =====================

def get_profile_cache() -> LRUCache:
    """
    Obtém instância singleton do cache de perfis.
    Usado em automation/ para cachear perfis de matches.
    """
    return SingletonCache.get_instance("profile_cache", ttl_seconds=3600, max_size=500)


def get_api_response_cache() -> LRUCache:
    """
    Obtém instância singleton do cache de respostas de API.
    Usado para cachear respostas da OpenAI e outras APIs.
    """
    return SingletonCache.get_instance("api_cache", ttl_seconds=1800, max_size=200)


def reset_all_caches() -> None:
    """Reseta todos os caches singleton (útil para testes)."""
    SingletonCache.reset_instance("profile_cache")
    SingletonCache.reset_instance("api_cache")
