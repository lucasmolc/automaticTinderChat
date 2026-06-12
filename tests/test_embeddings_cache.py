# -*- coding: utf-8 -*-
"""
Testes para o Serviço de Cache de Embeddings.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestEmbeddingsCache(unittest.TestCase):
    """Testes para EmbeddingsCache."""
    
    def setUp(self):
        """Setup para cada teste."""
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Cleanup após cada teste."""
        import shutil
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass
    
    def _create_cache(self, **kwargs):
        """Cria cache com diretório temporário."""
        # Importa dentro do método para evitar problemas de import
        from services.embeddings_cache import EmbeddingsCache
        
        defaults = {
            'cache_dir': self.temp_dir,
            'max_memory_items': 1000,
            'default_ttl_hours': 168,
            'similarity_threshold': 0.85
        }
        defaults.update(kwargs)
        return EmbeddingsCache(**defaults)
    
    def test_cache_creation(self):
        """Testa criação do cache."""
        cache = self._create_cache()
        
        self.assertIsNotNone(cache)
        self.assertTrue(cache.db_path.exists())
    
    def test_set_and_get(self):
        """Testa armazenar e recuperar embedding."""
        cache = self._create_cache()
        
        # Dados de teste
        text = "teste de embedding"
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        model = "text-embedding-3-small"
        
        # Armazena
        success = cache.set(text, embedding, model)
        self.assertTrue(success)
        
        # Recupera
        result = cache.get(text, model)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), len(embedding))
        
        # Verifica valores (com tolerância para float)
        for i, val in enumerate(result):
            self.assertAlmostEqual(val, embedding[i], places=5)
    
    def test_cache_miss(self):
        """Testa cache miss para texto não existente."""
        cache = self._create_cache()
        
        result = cache.get("texto não existente", "model")
        self.assertIsNone(result)
    
    def test_stats(self):
        """Testa estatísticas do cache."""
        cache = self._create_cache()
        
        # Algumas operações
        cache.set("texto1", [0.1, 0.2], "model")
        cache.get("texto1", "model")  # Hit
        cache.get("texto2", "model")  # Miss
        
        stats = cache.get_stats()
        
        self.assertIn('hits', stats)
        self.assertIn('misses', stats)
        self.assertIn('writes', stats)
        self.assertEqual(stats['writes'], 1)
        self.assertEqual(stats['hits'], 1)
        self.assertEqual(stats['misses'], 1)
    
    def test_memory_cache_lru(self):
        """Testa eviction LRU do cache em memória."""
        # Cache pequeno para testar eviction
        cache = self._create_cache(max_memory_items=3)
        
        # Adiciona 4 itens (deve evictar o primeiro)
        for i in range(4):
            cache.set(f"texto{i}", [float(i)], "model")
        
        # Verifica que o primeiro foi evictado da memória
        # mas ainda está no banco
        self.assertEqual(len(cache._memory_cache), 3)
        
        # O item deve ainda estar acessível via banco
        result = cache.get("texto0", "model")
        self.assertIsNotNone(result)
    
    def test_clear_all(self):
        """Testa limpar todo o cache."""
        cache = self._create_cache()
        
        # Adiciona alguns itens
        cache.set("texto1", [0.1], "model")
        cache.set("texto2", [0.2], "model")
        
        # Limpa
        deleted = cache.clear()
        
        # Verifica
        self.assertEqual(deleted, 2)
        self.assertIsNone(cache.get("texto1", "model"))
        self.assertIsNone(cache.get("texto2", "model"))
    
    def test_clear_by_model(self):
        """Testa limpar cache por modelo."""
        cache = self._create_cache()
        
        # Adiciona itens de modelos diferentes
        cache.set("texto1", [0.1], "model-a")
        cache.set("texto2", [0.2], "model-b")
        
        # Limpa apenas model-a
        deleted = cache.clear(model="model-a")
        
        # Verifica
        self.assertEqual(deleted, 1)
        self.assertIsNone(cache.get("texto1", "model-a"))
        self.assertIsNotNone(cache.get("texto2", "model-b"))
    
    def test_different_models_different_hashes(self):
        """Testa que mesmo texto com modelos diferentes tem hashes diferentes."""
        cache = self._create_cache()
        
        text = "mesmo texto"
        cache.set(text, [0.1, 0.2], "model-a")
        cache.set(text, [0.3, 0.4], "model-b")
        
        result_a = cache.get(text, "model-a")
        result_b = cache.get(text, "model-b")
        
        self.assertIsNotNone(result_a)
        self.assertIsNotNone(result_b)
        self.assertNotEqual(result_a, result_b)


class TestEmbeddingsCacheHelpers(unittest.TestCase):
    """Testes para funções auxiliares de cache."""
    
    def setUp(self):
        """Setup para cada teste."""
        self.temp_dir = tempfile.mkdtemp()
        # Reset singleton
        import services.embeddings_cache as ec
        ec._embeddings_cache = None
    
    def tearDown(self):
        """Cleanup após cada teste."""
        import shutil
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass
        # Reset singleton
        import services.embeddings_cache as ec
        ec._embeddings_cache = None
    
    @patch('services.embeddings_cache.EmbeddingsCache')
    def test_singleton_pattern(self, MockCache):
        """Testa padrão singleton do cache."""
        mock_instance = MagicMock()
        MockCache.return_value = mock_instance
        
        from services.embeddings_cache import get_embeddings_cache
        import services.embeddings_cache as ec
        ec._embeddings_cache = None
        
        cache1 = get_embeddings_cache()
        cache2 = get_embeddings_cache()
        
        self.assertIs(cache1, cache2)


class TestSimilaritySearch(unittest.TestCase):
    """Testes para busca por similaridade."""
    
    def setUp(self):
        """Setup para cada teste."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Cleanup após cada teste."""
        import shutil
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass
    
    def test_find_similar(self):
        """Testa busca por similaridade."""
        from services.embeddings_cache import EmbeddingsCache
        
        cache = EmbeddingsCache(
            cache_dir=self.temp_dir,
            similarity_threshold=0.8
        )
        
        # Adiciona embeddings normalizados
        emb1 = [0.9, 0.1, 0.0]
        emb2 = [0.1, 0.9, 0.0]
        emb3 = [0.85, 0.15, 0.0]  # Similar ao emb1
        
        cache.set("texto similar 1", emb1, "model")
        cache.set("texto diferente", emb2, "model")
        cache.set("texto similar 2", emb3, "model")
        
        # Busca similares ao emb1
        results = cache.find_similar(emb1, "model", threshold=0.8)
        
        # Deve encontrar pelo menos texto similar 1 e 2
        self.assertGreaterEqual(len(results), 1)
        
        # O mais similar deve ser o próprio texto
        self.assertEqual(results[0]['text'], "texto similar 1")
        self.assertAlmostEqual(results[0]['similarity'], 1.0, places=2)


class TestHashComputation(unittest.TestCase):
    """Testes para computação de hash."""
    
    def setUp(self):
        """Setup para cada teste."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Cleanup após cada teste."""
        import shutil
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass
    
    def test_hash_computation(self):
        """Testa computação de hash."""
        from services.embeddings_cache import EmbeddingsCache
        
        cache = EmbeddingsCache(cache_dir=self.temp_dir)
        
        hash1 = cache._compute_hash("texto", "model-a")
        hash2 = cache._compute_hash("texto", "model-b")
        hash3 = cache._compute_hash("outro texto", "model-a")
        hash4 = cache._compute_hash("texto", "model-a")
        
        # Mesmo texto + modelo = mesmo hash
        self.assertEqual(hash1, hash4)
        
        # Diferente modelo = diferente hash
        self.assertNotEqual(hash1, hash2)
        
        # Diferente texto = diferente hash
        self.assertNotEqual(hash1, hash3)


if __name__ == '__main__':
    unittest.main()
