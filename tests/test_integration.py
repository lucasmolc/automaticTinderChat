"""
Testes de integração para comunicação entre componentes.

Nota: Testes de ciclo de vida completo de match e fluxos E2E
estão em test_e2e.py. Este arquivo foca em integração de unidades.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDatabaseIntegration:
    """Testes de integração com banco de dados."""
    
    def test_full_match_workflow_create_update_messages(self, test_db):
        """Testa fluxo completo de criação, atualização e mensagens."""
        from database.models import Match, Message
        from database.repositories import MatchRepository, MessageRepository
        
        # 1. Criar match
        match_repo = MatchRepository(test_db)
        match, created = match_repo.get_or_create(
            "integration_test_match",
            name="Teste Integration"
        )
        test_db.commit()
        
        assert created == True
        
        # 2. Atualizar match
        match_repo.update(match, age=25, bio="Bio de teste")
        test_db.commit()
        test_db.refresh(match)
        
        assert match.age == 25
        
        # 3. Adicionar mensagens
        msg_repo = MessageRepository(test_db)
        msg1 = msg_repo.create(
            match_id=match.id,
            content="Olá!",
            is_from_me=True
        )
        msg2 = msg_repo.create(
            match_id=match.id,
            content="Oi, tudo bem?",
            is_from_me=False
        )
        test_db.commit()
        
        # 4. Atualizar status do match
        match_repo.update(
            match,
            has_messages=True,
            awaiting_my_response=True,
            last_message_text="Oi, tudo bem?"
        )
        test_db.commit()
        
        # 5. Verificar dados finais
        messages = msg_repo.get_messages_for_match(match.id)
        test_db.refresh(match)
        
        assert len(messages) == 2
        assert match.has_messages == True
        assert match.awaiting_my_response == True
    
    def test_block_unblock_workflow(self, test_db, sample_match):
        """Testa fluxo de bloqueio e desbloqueio."""
        from database.repositories import MatchRepository
        
        repo = MatchRepository(test_db)
        
        # Bloquear
        repo.block_match(sample_match, "Teste de bloqueio")
        test_db.commit()
        test_db.refresh(sample_match)
        
        assert sample_match.is_blocked == True
        assert sample_match.blocked_reason == "Teste de bloqueio"
        
        # Desbloquear
        repo.unblock_match(sample_match)
        test_db.commit()
        test_db.refresh(sample_match)
        
        assert sample_match.is_blocked == False


class TestWebAPIIntegration:
    """Testes de integração da API Web."""
    
    def test_all_main_pages_load(self, web_client):
        """Testa que todas páginas principais carregam."""
        pages = ["/", "/matches", "/messages", "/analytics", "/control"]
        
        for page in pages:
            response = web_client.get(page)
            assert response.status_code == 200, f"Falha na página {page}"


class TestMatchHelpersIntegration:
    """Testes de integração dos Match Helpers com o banco."""
    
    def test_match_validator_with_real_match(self, test_db):
        """Testa MatchValidator com match real do banco."""
        from unittest.mock import MagicMock

        from automation.match_helpers import MatchValidator
        from database.models import Match
        from database.repositories import MatchRepository
        
        match_repo = MatchRepository(test_db)
        
        match, _ = match_repo.get_or_create("validator_test", name="Maria")
        test_db.commit()
        
        settings = MagicMock()
        settings.days_without_interaction = 365
        validator = MatchValidator(settings)
        
        # Match novo não deve ser pulado
        should_skip, reason = validator.should_skip_match(match)
        assert should_skip == False
        
        # Bloquear match
        match_repo.block_match(match, "Teste")
        test_db.commit()
        test_db.refresh(match)
        
        # Match bloqueado deve ser pulado
        should_skip, reason = validator.should_skip_match(match)
        assert should_skip == True
        assert "bloqueado" in reason.lower()
    
    def test_profile_cache_integration_with_db(self, test_db):
        """Testa ProfileCache integrado com busca no banco."""
        from automation.match_helpers import ProfileCache
        from database.models import Match
        from database.repositories import MatchRepository
        
        match_repo = MatchRepository(test_db)
        cache = ProfileCache(ttl_seconds=60)
        
        match, _ = match_repo.get_or_create("cache_test", name="Julia")
        match_repo.update(match, age=25, bio="Teste bio")
        test_db.commit()
        
        def get_match_profile(tinder_id):
            cached = cache.get(tinder_id)
            if cached:
                return cached, True
            
            m = match_repo.get_by_tinder_id(tinder_id)
            if m:
                profile = {'name': m.name, 'age': m.age, 'bio': m.bio}
                cache.set(tinder_id, profile)
                return profile, False
            return None, False
        
        profile1, from_cache1 = get_match_profile("cache_test")
        assert from_cache1 == False
        assert profile1['name'] == "Julia"
        
        profile2, from_cache2 = get_match_profile("cache_test")
        assert from_cache2 == True
        assert profile2['name'] == "Julia"
    
    def test_update_from_profile_integration(self, test_db):
        """Testa update_from_profile com dados reais."""
        from database.repositories import MatchRepository
        
        match_repo = MatchRepository(test_db)
        
        match, _ = match_repo.get_or_create("update_test", name="Unknown")
        test_db.commit()
        
        profile_data = {
            'name': 'Carolina',
            'age': 26,
            'bio': 'Amo viajar e conhecer pessoas',
            'job_title': 'Designer',
            'interests': ['viagens', 'arte'],
            'photos': [
                {'url': 'https://photo1.jpg', 'order': 0},
                {'url': 'https://photo2.jpg', 'order': 1}
            ],
            'my_interests': ['viagens', 'música']
        }
        
        updated_fields = match_repo.update_from_profile(match, profile_data)
        test_db.commit()
        test_db.refresh(match)
        
        assert match.name == 'Carolina'
        assert match.age == 26
        assert match.bio == 'Amo viajar e conhecer pessoas'
        assert match.job_title == 'Designer'
        assert match.photos_count == 2
        
        interests = match_repo.get_interests(match)
        assert 'viagens' in interests
        assert 'arte' in interests
