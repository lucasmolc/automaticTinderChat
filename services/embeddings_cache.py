# -*- coding: utf-8 -*-
"""
Serviço de Cache de Embeddings.

Cache inteligente para armazenar e reutilizar embeddings de mensagens,
melhorando performance e reduzindo custos de API.
"""

import hashlib
import json
import os
import pickle
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)


class EmbeddingsCache:
    """
    Cache de embeddings com armazenamento em SQLite.
    
    Features:
    - Cache em memória (LRU) + persistência em SQLite
    - TTL configurável
    - Compressão de embeddings
    - Busca por similaridade
    - Estatísticas de uso
    """
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        max_memory_items: int = 1000,
        default_ttl_hours: int = 168,  # 7 dias
        similarity_threshold: float = 0.85
    ):
        """
        Inicializa o cache de embeddings.
        
        Args:
            cache_dir: Diretório para armazenar o banco SQLite
            max_memory_items: Máximo de itens em memória
            default_ttl_hours: TTL padrão em horas
            similarity_threshold: Limiar de similaridade (0-1)
        """
        # Diretório do cache
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            settings = get_settings()
            base_dir = getattr(settings, 'DATA_DIR', 'data')
            self.cache_dir = Path(base_dir) / 'cache' / 'embeddings'
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / 'embeddings.db'
        
        # Configurações
        self.max_memory_items = max_memory_items
        self.default_ttl_hours = default_ttl_hours
        self.similarity_threshold = similarity_threshold
        
        # Cache em memória (LRU simples)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._access_order: List[str] = []
        self._lock = threading.RLock()
        
        # Estatísticas
        self._stats = {
            'hits': 0,
            'misses': 0,
            'memory_hits': 0,
            'db_hits': 0,
            'writes': 0,
            'evictions': 0
        }
        
        # Inicializa banco de dados
        self._init_db()
        
        logger.info(f"EmbeddingsCache inicializado: {self.db_path}")
    
    def _init_db(self) -> None:
        """Inicializa o banco de dados SQLite."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            
            # Tabela principal de embeddings
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS embeddings (
                    hash TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            ''')
            
            # Índices para busca eficiente
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_expires_at ON embeddings(expires_at)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_model ON embeddings(model)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_last_accessed ON embeddings(last_accessed)
            ''')
            
            # Tabela de estatísticas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cache_stats (
                    date TEXT PRIMARY KEY,
                    hits INTEGER DEFAULT 0,
                    misses INTEGER DEFAULT 0,
                    writes INTEGER DEFAULT 0,
                    evictions INTEGER DEFAULT 0,
                    avg_lookup_ms REAL DEFAULT 0,
                    total_entries INTEGER DEFAULT 0
                )
            ''')
            
            conn.commit()
    
    def _compute_hash(self, text: str, model: str) -> str:
        """
        Computa hash único para texto + modelo.
        
        Args:
            text: Texto para embedding
            model: Nome do modelo
            
        Returns:
            Hash SHA256
        """
        content = f"{model}:{text}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def _serialize_embedding(self, embedding: List[float]) -> bytes:
        """Serializa embedding para armazenamento."""
        return pickle.dumps(np.array(embedding, dtype=np.float32))
    
    def _deserialize_embedding(self, data: bytes) -> List[float]:
        """Deserializa embedding do armazenamento."""
        return pickle.loads(data).tolist()
    
    def _update_memory_cache(self, hash_key: str, entry: Dict[str, Any]) -> None:
        """Atualiza cache em memória com LRU."""
        with self._lock:
            # Remove da posição atual se existir
            if hash_key in self._access_order:
                self._access_order.remove(hash_key)
            
            # Adiciona ao final (mais recente)
            self._access_order.append(hash_key)
            self._memory_cache[hash_key] = entry
            
            # Evict itens antigos se necessário
            while len(self._memory_cache) > self.max_memory_items:
                oldest_key = self._access_order.pop(0)
                del self._memory_cache[oldest_key]
                self._stats['evictions'] += 1
    
    def get(
        self,
        text: str,
        model: str = 'text-embedding-3-small'
    ) -> Optional[List[float]]:
        """
        Busca embedding no cache.
        
        Args:
            text: Texto do embedding
            model: Modelo usado para gerar
            
        Returns:
            Lista de floats do embedding ou None
        """
        hash_key = self._compute_hash(text, model)
        
        # 1. Tenta cache em memória
        with self._lock:
            if hash_key in self._memory_cache:
                entry = self._memory_cache[hash_key]
                if datetime.fromisoformat(entry['expires_at']) > datetime.now():
                    self._stats['hits'] += 1
                    self._stats['memory_hits'] += 1
                    # Atualiza ordem de acesso
                    self._access_order.remove(hash_key)
                    self._access_order.append(hash_key)
                    return entry['embedding']
                else:
                    # Expirado, remove
                    del self._memory_cache[hash_key]
                    self._access_order.remove(hash_key)
        
        # 2. Tenta banco de dados
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT embedding, expires_at 
                    FROM embeddings 
                    WHERE hash = ? AND expires_at > datetime('now')
                ''', (hash_key,))
                
                row = cursor.fetchone()
                if row:
                    embedding = self._deserialize_embedding(row[0])
                    
                    # Atualiza estatísticas de acesso
                    cursor.execute('''
                        UPDATE embeddings 
                        SET access_count = access_count + 1,
                            last_accessed = datetime('now')
                        WHERE hash = ?
                    ''', (hash_key,))
                    conn.commit()
                    
                    # Adiciona ao cache em memória
                    self._update_memory_cache(hash_key, {
                        'embedding': embedding,
                        'expires_at': row[1]
                    })
                    
                    self._stats['hits'] += 1
                    self._stats['db_hits'] += 1
                    return embedding
        
        except Exception as e:
            logger.error(f"Erro ao buscar embedding no cache: {e}")
        
        self._stats['misses'] += 1
        return None
    
    def set(
        self,
        text: str,
        embedding: List[float],
        model: str = 'text-embedding-3-small',
        ttl_hours: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Armazena embedding no cache.
        
        Args:
            text: Texto original
            embedding: Vetor de embedding
            model: Modelo usado
            ttl_hours: TTL em horas (usa default se não especificado)
            metadata: Metadados opcionais
            
        Returns:
            True se armazenado com sucesso
        """
        hash_key = self._compute_hash(text, model)
        ttl = ttl_hours or self.default_ttl_hours
        expires_at = datetime.now() + timedelta(hours=ttl)
        
        try:
            # Armazena no banco
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO embeddings 
                    (hash, text, embedding, model, dimensions, expires_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    hash_key,
                    text,
                    self._serialize_embedding(embedding),
                    model,
                    len(embedding),
                    expires_at.isoformat(),
                    json.dumps(metadata) if metadata else None
                ))
                conn.commit()
            
            # Atualiza cache em memória
            self._update_memory_cache(hash_key, {
                'embedding': embedding,
                'expires_at': expires_at.isoformat()
            })
            
            self._stats['writes'] += 1
            return True
            
        except Exception as e:
            logger.error(f"Erro ao armazenar embedding: {e}")
            return False
    
    def get_or_create(
        self,
        text: str,
        model: str = 'text-embedding-3-small',
        generator_func: Optional[callable] = None,
        ttl_hours: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[List[float]]:
        """
        Busca embedding no cache ou gera se não existir.
        
        Args:
            text: Texto para embedding
            model: Modelo a usar
            generator_func: Função para gerar embedding se não existir
            ttl_hours: TTL em horas
            metadata: Metadados opcionais
            
        Returns:
            Embedding ou None se falhar
        """
        # Tenta buscar no cache
        embedding = self.get(text, model)
        if embedding is not None:
            return embedding
        
        # Se não tiver função geradora, retorna None
        if generator_func is None:
            return None
        
        # Gera novo embedding
        try:
            embedding = generator_func(text, model)
            if embedding:
                self.set(text, embedding, model, ttl_hours, metadata)
            return embedding
        except Exception as e:
            logger.error(f"Erro ao gerar embedding: {e}")
            return None
    
    def find_similar(
        self,
        embedding: List[float],
        model: str = 'text-embedding-3-small',
        threshold: Optional[float] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Busca embeddings similares no cache.
        
        Args:
            embedding: Embedding de referência
            model: Modelo para filtrar
            threshold: Limiar de similaridade (usa default se None)
            limit: Máximo de resultados
            
        Returns:
            Lista de dicts com text, similarity, metadata
        """
        threshold = threshold or self.similarity_threshold
        query_vec = np.array(embedding)
        results = []
        
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT hash, text, embedding, metadata 
                    FROM embeddings 
                    WHERE model = ? AND expires_at > datetime('now')
                ''', (model,))
                
                for row in cursor.fetchall():
                    stored_embedding = self._deserialize_embedding(row[2])
                    stored_vec = np.array(stored_embedding)
                    
                    # Similaridade cosseno
                    similarity = np.dot(query_vec, stored_vec) / (
                        np.linalg.norm(query_vec) * np.linalg.norm(stored_vec)
                    )
                    
                    if similarity >= threshold:
                        results.append({
                            'hash': row[0],
                            'text': row[1],
                            'similarity': float(similarity),
                            'metadata': json.loads(row[3]) if row[3] else None
                        })
                
                # Ordena por similaridade
                results.sort(key=lambda x: x['similarity'], reverse=True)
                return results[:limit]
                
        except Exception as e:
            logger.error(f"Erro ao buscar similares: {e}")
            return []
    
    def cleanup_expired(self) -> int:
        """
        Remove entradas expiradas.
        
        Returns:
            Número de entradas removidas
        """
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM embeddings 
                    WHERE expires_at < datetime('now')
                ''')
                deleted = cursor.rowcount
                conn.commit()
                
                # Limpa também da memória
                with self._lock:
                    now = datetime.now()
                    expired_keys = [
                        k for k, v in self._memory_cache.items()
                        if datetime.fromisoformat(v['expires_at']) < now
                    ]
                    for key in expired_keys:
                        del self._memory_cache[key]
                        if key in self._access_order:
                            self._access_order.remove(key)
                
                logger.info(f"Cache cleanup: {deleted} entradas removidas")
                return deleted
                
        except Exception as e:
            logger.error(f"Erro no cleanup do cache: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retorna estatísticas do cache.
        
        Returns:
            Dict com estatísticas
        """
        total_requests = self._stats['hits'] + self._stats['misses']
        hit_rate = (self._stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        # Conta entradas no banco
        db_count = 0
        db_size_mb = 0
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM embeddings WHERE expires_at > datetime("now")')
                db_count = cursor.fetchone()[0]
            
            db_size_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0
        except:
            pass
        
        return {
            'hits': self._stats['hits'],
            'misses': self._stats['misses'],
            'memory_hits': self._stats['memory_hits'],
            'db_hits': self._stats['db_hits'],
            'writes': self._stats['writes'],
            'evictions': self._stats['evictions'],
            'hit_rate_percent': round(hit_rate, 2),
            'memory_entries': len(self._memory_cache),
            'db_entries': db_count,
            'db_size_mb': round(db_size_mb, 2),
            'max_memory_items': self.max_memory_items,
            'ttl_hours': self.default_ttl_hours
        }
    
    def clear(self, model: Optional[str] = None) -> int:
        """
        Limpa o cache.
        
        Args:
            model: Se especificado, limpa apenas desse modelo
            
        Returns:
            Número de entradas removidas
        """
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.cursor()
                
                if model:
                    cursor.execute('DELETE FROM embeddings WHERE model = ?', (model,))
                else:
                    cursor.execute('DELETE FROM embeddings')
                
                deleted = cursor.rowcount
                conn.commit()
            
            # Limpa memória
            with self._lock:
                self._memory_cache.clear()
                self._access_order.clear()
            
            logger.info(f"Cache limpo: {deleted} entradas removidas")
            return deleted
            
        except Exception as e:
            logger.error(f"Erro ao limpar cache: {e}")
            return 0


# ===================== SINGLETON =====================

_embeddings_cache: Optional[EmbeddingsCache] = None
_cache_lock = threading.Lock()


def get_embeddings_cache() -> EmbeddingsCache:
    """
    Retorna instância singleton do cache de embeddings.
    
    Returns:
        EmbeddingsCache instance
    """
    global _embeddings_cache
    
    if _embeddings_cache is None:
        with _cache_lock:
            if _embeddings_cache is None:
                _embeddings_cache = EmbeddingsCache()
    
    return _embeddings_cache


def create_embedding_with_cache(
    text: str,
    model: str = 'text-embedding-3-small'
) -> Optional[List[float]]:
    """
    Cria embedding usando cache.
    
    Wrapper conveniente que usa o cache e gera via AIService se necessário.
    
    Args:
        text: Texto para embedding
        model: Modelo a usar
        
    Returns:
        Embedding ou None
    """
    cache = get_embeddings_cache()
    
    def generate(text: str, model: str) -> Optional[List[float]]:
        """Função geradora usando AIService."""
        try:
            from ai import get_ai_service
            service = get_ai_service()
            return service.create_embedding(text, model)
        except Exception as e:
            logger.error(f"Erro ao gerar embedding: {e}")
            return None
    
    return cache.get_or_create(text, model, generate)


def batch_create_embeddings_with_cache(
    texts: List[str],
    model: str = 'text-embedding-3-small'
) -> List[Optional[List[float]]]:
    """
    Cria embeddings em batch usando cache.
    
    Args:
        texts: Lista de textos
        model: Modelo a usar
        
    Returns:
        Lista de embeddings (None para falhas)
    """
    cache = get_embeddings_cache()
    results = []
    texts_to_generate = []
    indices_to_generate = []
    
    # Primeiro, verifica cache para todos
    for i, text in enumerate(texts):
        embedding = cache.get(text, model)
        if embedding is not None:
            results.append(embedding)
        else:
            results.append(None)  # Placeholder
            texts_to_generate.append(text)
            indices_to_generate.append(i)
    
    # Gera os que faltam
    if texts_to_generate:
        try:
            from ai import get_ai_service
            service = get_ai_service()
            
            # Gera em batch se suportado
            for text, idx in zip(texts_to_generate, indices_to_generate):
                try:
                    embedding = service.create_embedding(text, model)
                    if embedding:
                        cache.set(text, embedding, model)
                        results[idx] = embedding
                except Exception as e:
                    logger.error(f"Erro ao gerar embedding para texto {idx}: {e}")
                    
        except Exception as e:
            logger.error(f"Erro no batch de embeddings: {e}")
    
    return results


# ===================== EXPORTS =====================

__all__ = [
    'EmbeddingsCache',
    'get_embeddings_cache',
    'create_embedding_with_cache',
    'batch_create_embeddings_with_cache'
]
