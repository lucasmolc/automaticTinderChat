"""
Testes para modelos e repositórios do banco de dados.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Match, Message, MyProfile
from database.repositories import MatchRepository, MessageRepository, MyProfileRepository


class TestMatchModel:
    """Testes para o modelo Match."""
    
    def test_create_match(self, test_db):
        """Testa criação de match."""
        match = Match(
            tinder_match_id="test_123",
            name="Maria",
            age=25
        )
        test_db.add(match)
        test_db.commit()
        
        assert match.id is not None
        assert match.name == "Maria"
        assert match.age == 25
        assert match.is_blocked == False
        assert match.has_messages == False
    
    def test_match_default_values(self, test_db):
        """Testa valores padrão do match."""
        match = Match(tinder_match_id="test_456")
        test_db.add(match)
        test_db.commit()
        
        assert match.is_blocked == False
        assert match.has_messages == False
        assert match.first_message_sent == False
        assert match.whatsapp_requested == False
        assert match.whatsapp_obtained == False
    
    def test_match_with_photo(self, test_db):
        """Testa match com foto de perfil."""
        match = Match(
            tinder_match_id="test_789",
            name="Ana",
            profile_photo_url="https://example.com/photo.jpg"
        )
        test_db.add(match)
        test_db.commit()
        
        assert match.profile_photo_url == "https://example.com/photo.jpg"


class TestMatchRepository:
    """Testes para o repositório de Matches."""
    
    def test_get_or_create_new(self, test_db):
        """Testa criação de novo match."""
        repo = MatchRepository(test_db)
        
        match, created = repo.get_or_create("new_match_123", name="Laura")
        
        assert created == True
        assert match.tinder_match_id == "new_match_123"
        assert match.name == "Laura"
    
    def test_get_or_create_existing(self, test_db, sample_match):
        """Testa recuperação de match existente."""
        repo = MatchRepository(test_db)
        
        match, created = repo.get_or_create(sample_match.tinder_match_id)
        
        assert created == False
        assert match.id == sample_match.id
    
    def test_get_by_id(self, test_db, sample_match):
        """Testa busca por ID."""
        repo = MatchRepository(test_db)
        
        match = repo.get_by_id(sample_match.id)
        
        assert match is not None
        assert match.name == "Maria"
    
    def test_get_by_id_not_found(self, test_db):
        """Testa busca por ID inexistente."""
        repo = MatchRepository(test_db)
        
        match = repo.get_by_id(99999)
        
        assert match is None
    
    def test_update_match(self, test_db, sample_match):
        """Testa atualização de match."""
        repo = MatchRepository(test_db)
        
        repo.update(sample_match, age=26, bio="Novo bio")
        test_db.commit()
        test_db.refresh(sample_match)
        
        assert sample_match.age == 26
        assert sample_match.bio == "Novo bio"
    
    def test_count_total(self, test_db, sample_match, sample_blocked_match):
        """Testa contagem total."""
        repo = MatchRepository(test_db)
        
        count = repo.count_total()
        
        assert count == 2
    
    def test_get_matches_awaiting_response(self, test_db, sample_match_with_messages):
        """Testa busca de matches aguardando resposta."""
        repo = MatchRepository(test_db)
        
        matches = repo.get_matches_awaiting_my_response()
        
        assert len(matches) >= 1
        assert any(m.id == sample_match_with_messages.id for m in matches)
    
    def test_get_matches_without_messages(self, test_db, sample_match, sample_blocked_match):
        """Testa filtro de matches sem mensagens (não bloqueados)."""
        repo = MatchRepository(test_db)
        
        matches = repo.get_matches_without_messages()
        
        # Deve retornar apenas matches não bloqueados
        blocked_ids = [m.id for m in matches if m.is_blocked]
        assert len(blocked_ids) == 0


class TestMessageModel:
    """Testes para o modelo Message."""
    
    def test_create_message(self, test_db, sample_match):
        """Testa criação de mensagem."""
        msg = Message(
            match_id=sample_match.id,
            content="Olá!",
            is_from_me=True,
            ai_generated=True
        )
        test_db.add(msg)
        test_db.commit()
        
        assert msg.id is not None
        assert msg.content == "Olá!"
        assert msg.is_from_me == True
        assert msg.ai_generated == True
    
    def test_message_relationship(self, test_db, sample_match):
        """Testa relacionamento com match."""
        msg = Message(
            match_id=sample_match.id,
            content="Teste",
            is_from_me=True
        )
        test_db.add(msg)
        test_db.commit()
        
        assert msg.match.id == sample_match.id


class TestMessageRepository:
    """Testes para o repositório de Messages."""
    
    def test_get_messages_for_match(self, test_db, sample_match_with_messages):
        """Testa busca de mensagens por match."""
        repo = MessageRepository(test_db)
        
        messages = repo.get_messages_for_match(sample_match_with_messages.id)
        
        assert len(messages) == 2
    
    def test_create_message(self, test_db, sample_match):
        """Testa criação via repositório."""
        repo = MessageRepository(test_db)
        
        msg = repo.create(
            match_id=sample_match.id,
            content="Nova mensagem",
            is_from_me=True
        )
        
        assert msg.id is not None
        assert msg.content == "Nova mensagem"
    
    def test_count_my_messages(self, test_db, sample_match_with_messages):
        """Testa contagem de mensagens enviadas."""
        repo = MessageRepository(test_db)
        
        count = repo.count_my_messages()
        
        assert count >= 1


class TestMyProfileModel:
    """Testes para o modelo MyProfile."""
    
    def test_create_profile(self, test_db):
        """Testa criação de perfil."""
        profile = MyProfile(
            name="Carlos",
            age=28,
            bio="Olá mundo"
        )
        test_db.add(profile)
        test_db.commit()
        
        assert profile.id is not None
        assert profile.name == "Carlos"
    
    def test_profile_scores(self, test_db, sample_profile):
        """Testa scores do perfil."""
        sample_profile.bio_quality_score = 8.5
        sample_profile.overall_score = 7.8
        test_db.commit()
        
        assert sample_profile.bio_quality_score == 8.5
        assert sample_profile.overall_score == 7.8


class TestMyProfileRepository:
    """Testes para o repositório de MyProfile."""
    
    def test_get_or_create(self, test_db):
        """Testa criação de perfil."""
        repo = MyProfileRepository(test_db)
        
        profile = repo.get_or_create()
        
        assert profile is not None
        assert profile.id is not None
    
    def test_update_profile(self, test_db, sample_profile):
        """Testa atualização de perfil."""
        repo = MyProfileRepository(test_db)
        
        repo.update(sample_profile, name="João Carlos", age=31)
        test_db.commit()
        test_db.refresh(sample_profile)
        
        assert sample_profile.name == "João Carlos"
        assert sample_profile.age == 31
