"""
Testes para os helpers de match (match_helpers.py).
Testa MatchValidator, MatchDataFetcher, ProfileCache e retry_with_backoff.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta


class TestMatchValidator:
    """Testes para o MatchValidator."""
    
    @pytest.fixture
    def settings(self):
        """Mock das configurações."""
        settings = MagicMock()
        settings.days_without_interaction = 365
        return settings
    
    @pytest.fixture
    def validator(self, settings):
        """Cria instância do validator."""
        from automation.match_helpers import MatchValidator
        return MatchValidator(settings)
    
    def test_should_skip_blocked_match(self, validator):
        """Testa que match bloqueado é pulado."""
        match = MagicMock()
        match.is_blocked = True
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = datetime.utcnow()
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip == True
        assert 'bloqueado' in reason.lower()
    
    def test_should_skip_unmatched(self, validator):
        """Testa que match desfeito é pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = True
        match.whatsapp_obtained = False
        match.date_confirmed = False
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip == True
        assert 'unmatch' in reason.lower()
    
    def test_should_skip_whatsapp_obtained(self, validator):
        """Testa que match com WhatsApp obtido é pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = True
        match.date_confirmed = False
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip == True
        assert 'whatsapp' in reason.lower()
    
    def test_should_skip_date_confirmed(self, validator):
        """Testa que match com encontro confirmado é pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = True
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip == True
        assert 'confirmado' in reason.lower()
    
    def test_should_not_skip_active_match(self, validator):
        """Testa que match ativo não é pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = datetime.utcnow()
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip == False
        assert reason is None
    
    def test_should_not_skip_match_without_interaction_date(self, validator):
        """Testa que match novo (sem data) não é pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = None  # Match novo
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip == False
        assert reason is None
    
    def test_should_skip_inactive_match(self, validator):
        """Testa que match inativo é processado (bloqueio é feito separadamente)."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        # Último contato há 400 dias
        match.last_interaction_at = datetime.utcnow() - timedelta(days=400)
        
        should_skip, reason = validator.should_skip_match(match)
        
        # Inatividade não é mais verificada em should_skip_match
        # O bloqueio por inatividade é feito separadamente via should_block_for_inactivity
        assert should_skip == False
        assert reason is None
    
    def test_should_block_for_inactivity_returns_true_for_old_match(self, validator):
        """Testa detecção de inatividade para bloqueio."""
        match = MagicMock()
        match.last_interaction_at = datetime.utcnow() - timedelta(days=400)
        
        should_block, days = validator.should_block_for_inactivity(match)
        
        assert should_block == True
        assert days >= 400
    
    def test_should_block_for_inactivity_returns_false_for_new_match(self, validator):
        """Testa que match novo não é bloqueado."""
        match = MagicMock()
        match.last_interaction_at = None
        
        should_block, days = validator.should_block_for_inactivity(match)
        
        assert should_block == False
        assert days == -1


class TestMatchDataFetcher:
    """Testes para o MatchDataFetcher."""
    
    @pytest.fixture
    def mock_match_repo(self):
        """Mock do repositório de matches."""
        repo = MagicMock()
        repo.get_interests.return_value = ['viagens', 'música']
        repo.update_from_profile.return_value = {'bio': 'Nova bio'}
        return repo
    
    @pytest.fixture
    def mock_extractor(self):
        """Mock do extractor."""
        extractor = AsyncMock()
        extractor.extract_match_profile = AsyncMock(return_value={
            'name': 'Maria',
            'age': 25,
            'bio': 'Amo viajar',
            'interests': ['viagens', 'música']
        })
        return extractor
    
    @pytest.fixture
    def my_profile_data(self):
        """Dados do meu perfil."""
        return {
            'name': 'João',
            'age': 28,
            'interests': ['viagens', 'cinema', 'esportes']
        }
    
    @pytest.fixture
    def fetcher(self, mock_match_repo, mock_extractor, my_profile_data):
        """Cria instância do fetcher."""
        from automation.match_helpers import MatchDataFetcher
        return MatchDataFetcher(mock_match_repo, mock_extractor, my_profile_data)
    
    def test_get_match_profile_from_db(self, fetcher):
        """Testa extração de dados do banco."""
        match = MagicMock()
        match.name = 'Ana'
        match.age = 24
        match.bio = 'Teste bio'
        match.distance_km = 5
        match.job_title = 'Desenvolvedora'
        match.school = None
        match.gender = 'F'
        match.city = 'São Paulo'
        match.relationship_intent = None
        match.sexual_orientations = None
        match.photos_count = 3
        match.is_verified = True
        
        profile = fetcher.get_match_profile_from_db(match)
        
        assert profile['name'] == 'Ana'
        assert profile['age'] == 24
        assert profile['bio'] == 'Teste bio'
        assert profile['interests'] == ['viagens', 'música']
    
    def test_needs_screen_fetch_without_name(self, fetcher):
        """Testa detecção de necessidade de busca quando falta nome."""
        match = MagicMock()
        match.name = None
        match.bio = 'Tenho bio'
        match.job_title = 'Dev'
        
        assert fetcher.needs_screen_fetch(match) == True
    
    def test_needs_screen_fetch_without_bio_and_job(self, fetcher):
        """Testa detecção quando falta bio e job."""
        match = MagicMock()
        match.name = 'Ana'
        match.bio = None
        match.job_title = None
        
        assert fetcher.needs_screen_fetch(match) == True
    
    def test_does_not_need_screen_fetch_with_complete_data(self, fetcher):
        """Testa que não precisa buscar quando dados estão completos."""
        match = MagicMock()
        match.name = 'Ana'
        match.bio = 'Minha bio'
        match.job_title = 'Dev'
        
        assert fetcher.needs_screen_fetch(match) == False
    
    def test_get_common_interests(self, fetcher):
        """Testa cálculo de interesses em comum."""
        match_interests = ['viagens', 'música', 'leitura']
        
        common = fetcher.get_common_interests(match_interests)
        
        assert 'viagens' in common
        assert 'música' not in common  # Não está em my_interests
        assert 'leitura' not in common
    
    @pytest.mark.asyncio
    async def test_fetch_from_screen_detects_unmatch(self, mock_match_repo, my_profile_data):
        """Testa detecção de unmatch na busca de tela."""
        from automation.match_helpers import MatchDataFetcher
        
        mock_extractor = AsyncMock()
        mock_extractor.extract_match_profile = AsyncMock(return_value={
            'not_found': True
        })
        
        fetcher = MatchDataFetcher(mock_match_repo, mock_extractor, my_profile_data)
        
        match = MagicMock()
        match.name = 'Test'
        match.tinder_match_id = 'test_123'
        
        result = await fetcher.fetch_from_screen(match)
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_match_data_for_ai_with_complete_db_data(self, fetcher):
        """Testa obtenção de dados quando banco está completo."""
        match = MagicMock()
        match.name = 'Ana'
        match.age = 24
        match.bio = 'Minha bio completa'
        match.job_title = 'Desenvolvedora'
        match.distance_km = 5
        match.school = None
        match.gender = 'F'
        match.city = 'São Paulo'
        match.relationship_intent = None
        match.sexual_orientations = None
        match.photos_count = 3
        match.is_verified = True
        
        profile, was_unmatched = await fetcher.get_match_data_for_ai(match)
        
        assert was_unmatched == False
        assert profile['name'] == 'Ana'
        assert profile['bio'] == 'Minha bio completa'


class TestProfileCache:
    """Testes para o ProfileCache."""
    
    @pytest.fixture
    def cache(self):
        """Cria instância do cache."""
        from automation.match_helpers import ProfileCache
        return ProfileCache(ttl_seconds=60)  # 1 minuto para testes
    
    def test_set_and_get(self, cache):
        """Testa set e get básicos."""
        cache.set('test_key', {'name': 'Test'})
        
        result = cache.get('test_key')
        
        assert result == {'name': 'Test'}
    
    def test_get_returns_none_for_missing_key(self, cache):
        """Testa get para chave inexistente."""
        result = cache.get('nonexistent_key')
        
        assert result is None
    
    def test_invalidate_removes_item(self, cache):
        """Testa invalidação de item."""
        cache.set('test_key', {'name': 'Test'})
        cache.invalidate('test_key')
        
        result = cache.get('test_key')
        
        assert result is None
    
    def test_clear_removes_all(self, cache):
        """Testa limpeza total do cache."""
        cache.set('key1', {'a': 1})
        cache.set('key2', {'b': 2})
        cache.clear()
        
        assert cache.get('key1') is None
        assert cache.get('key2') is None
    
    def test_expired_item_returns_none(self):
        """Testa que item expirado retorna None."""
        from automation.match_helpers import ProfileCache
        
        # Cache com TTL de 0 segundos (expira imediatamente)
        cache = ProfileCache(ttl_seconds=0)
        cache.set('test_key', {'name': 'Test'})
        
        # Pequeno delay para garantir expiração
        import time
        time.sleep(0.1)
        
        result = cache.get('test_key')
        
        assert result is None
    
    def test_get_stats(self, cache):
        """Testa estatísticas do cache."""
        cache.set('key1', {'a': 1})
        cache.set('key2', {'b': 2})
        
        stats = cache.get_stats()
        
        assert stats['size'] == 2
        assert stats['ttl_seconds'] == 60


class TestRetryWithBackoff:
    """Testes para o decorator retry_with_backoff."""
    
    @pytest.mark.asyncio
    async def test_successful_first_try(self):
        """Testa função que sucede na primeira tentativa."""
        from automation.match_helpers import retry_with_backoff
        
        call_count = 0
        
        @retry_with_backoff(max_retries=3)
        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await success_func()
        
        assert result == "success"
        assert call_count == 1
    
    @pytest.mark.asyncio
    async def test_retry_on_failure_then_success(self):
        """Testa retry quando falha e depois sucede."""
        from automation.match_helpers import retry_with_backoff
        
        call_count = 0
        
        @retry_with_backoff(max_retries=3, base_delay=0.01)
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Erro temporário")
            return "success"
        
        result = await fail_then_succeed()
        
        assert result == "success"
        assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_exhausts_retries_then_raises(self):
        """Testa que exceção é levantada após esgotar retries."""
        from automation.match_helpers import retry_with_backoff
        
        @retry_with_backoff(max_retries=2, base_delay=0.01)
        async def always_fails():
            raise ValueError("Erro permanente")
        
        with pytest.raises(ValueError, match="Erro permanente"):
            await always_fails()


class TestSingletonCache:
    """Testes para o singleton do cache."""
    
    def test_get_profile_cache_returns_same_instance(self):
        """Testa que sempre retorna a mesma instância."""
        from automation.match_helpers import get_profile_cache, reset_profile_cache
        
        # Resetar para garantir estado limpo
        reset_profile_cache()
        
        cache1 = get_profile_cache()
        cache2 = get_profile_cache()
        
        assert cache1 is cache2
    
    def test_reset_profile_cache(self):
        """Testa reset do singleton."""
        from automation.match_helpers import get_profile_cache, reset_profile_cache
        
        cache1 = get_profile_cache()
        cache1.set('test', {'a': 1})
        
        reset_profile_cache()
        
        cache2 = get_profile_cache()
        
        assert cache2.get('test') is None


class TestValidateAiMessage:
    """Testes para a função validate_ai_message centralizada."""
    
    def test_valid_message(self):
        """Testa mensagem válida."""
        from automation.match_helpers import validate_ai_message
        
        is_valid, reason = validate_ai_message("Oi! Tudo bem?")
        
        assert is_valid == True
        assert reason is None
    
    def test_empty_message(self):
        """Testa mensagem vazia."""
        from automation.match_helpers import validate_ai_message
        
        is_valid, reason = validate_ai_message("")
        
        assert is_valid == False
        assert "vazia" in reason.lower()
    
    def test_message_too_short(self):
        """Testa mensagem muito curta."""
        from automation.match_helpers import validate_ai_message
        
        is_valid, reason = validate_ai_message("Oi")
        
        assert is_valid == False
        assert "curta" in reason.lower()
    
    def test_message_too_long(self):
        """Testa mensagem muito longa."""
        from automation.match_helpers import validate_ai_message
        
        long_msg = "A" * 501
        is_valid, reason = validate_ai_message(long_msg)
        
        assert is_valid == False
        assert "longa" in reason.lower()
    
    def test_bad_pattern_assistant(self):
        """Testa mensagem com padrão de assistente."""
        from automation.match_helpers import validate_ai_message
        
        is_valid, reason = validate_ai_message("Como assistente, não posso fazer isso")
        
        assert is_valid == False
        assert "padrão problemático" in reason.lower()
    
    def test_bad_pattern_template(self):
        """Testa mensagem com padrões de template."""
        from automation.match_helpers import validate_ai_message
        
        is_valid, reason = validate_ai_message("Olá {{name}}, tudo bem?")
        
        assert is_valid == False
        assert "padrão problemático" in reason.lower()
    
    def test_valid_long_message(self):
        """Testa mensagem longa mas válida."""
        from automation.match_helpers import validate_ai_message
        
        msg = "Olá! Vi que você também gosta de música. " * 10  # ~400 chars
        is_valid, reason = validate_ai_message(msg)
        
        assert is_valid == True
        assert reason is None
