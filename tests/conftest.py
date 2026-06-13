"""
Configurações e fixtures compartilhadas para testes.
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Adicionar diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Match, Message, MyProfile

# ============================================
# Rede de segurança: nenhum teste deve lançar um navegador real
# ============================================

@pytest.fixture(autouse=True)
def _no_real_browser():
    """
    Impede que testes iniciem um navegador Playwright de verdade.

    Testes devem mockar o browser/página. Um launch real depende de binários
    do Chromium e de display gráfico — frágil e indisponível no CI. Se algum
    teste tentar iniciar o Playwright, falha aqui com mensagem clara em vez de
    um erro obscuro no ambiente de CI.
    """
    # Importa o submódulo explicitamente: patch por string falha se
    # automation.browser ainda não tiver sido carregado (varia com a ordem
    # de coleta dos testes, como ocorreu no CI em Python 3.9).
    import automation.browser as browser_mod

    def _fail(*_args, **_kwargs):
        raise RuntimeError(
            "Tentativa de iniciar um navegador Playwright real em um teste. "
            "Mocke o browser/página (ou defina controller._is_initialized = True)."
        )

    with patch.object(browser_mod, "async_playwright", side_effect=_fail):
        yield


# ============================================
# Fixtures de Banco de Dados
# ============================================

@pytest.fixture(scope="function")
def test_db():
    """Cria banco de dados SQLite em memória para testes."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def sample_match(test_db):
    """Cria um match de exemplo."""
    match = Match(
        tinder_match_id="test_match_123",
        name="Maria",
        age=25,
        bio="Amo viajar e conhecer pessoas novas",
        has_messages=False,
        is_blocked=False,
        profile_photo_url="https://example.com/photo.jpg"
    )
    test_db.add(match)
    test_db.commit()
    test_db.refresh(match)
    return match


@pytest.fixture
def sample_match_with_messages(test_db, sample_match):
    """Cria um match com mensagens."""
    # Adicionar mensagens
    msg1 = Message(
        match_id=sample_match.id,
        content="Oi, tudo bem?",
        is_from_me=True,
        sent_at=datetime.utcnow(),
        ai_generated=True
    )
    msg2 = Message(
        match_id=sample_match.id,
        content="Oi! Tudo sim, e você?",
        is_from_me=False,
        sent_at=datetime.utcnow()
    )
    test_db.add_all([msg1, msg2])
    
    sample_match.has_messages = True
    sample_match.awaiting_my_response = True
    sample_match.last_message_text = "Oi! Tudo sim, e você?"
    sample_match.last_message_from_me = False
    
    test_db.commit()
    
    return sample_match


@pytest.fixture
def sample_blocked_match(test_db):
    """Cria um match bloqueado."""
    match = Match(
        tinder_match_id="blocked_match_456",
        name="Ana",
        age=28,
        is_blocked=True,
        blocked_reason="Bloqueado manualmente",
        blocked_at=datetime.utcnow()
    )
    test_db.add(match)
    test_db.commit()
    test_db.refresh(match)
    return match


@pytest.fixture
def sample_profile(test_db):
    """Cria um perfil de exemplo."""
    profile = MyProfile(
        name="João",
        age=30,
        bio="Desenvolvedor e amante de tecnologia"
    )
    test_db.add(profile)
    test_db.commit()
    test_db.refresh(profile)
    return profile


# ============================================
# Fixtures de Mocks
# ============================================

@pytest.fixture
def mock_openai():
    """Mock do cliente OpenAI."""
    with patch("ai.client.OpenAI") as mock:
        client = MagicMock()
        
        # Mock de resposta de chat
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '{"message": "Oi! Tudo bem?", "intent": "greeting"}'
        response.usage.prompt_tokens = 100
        response.usage.completion_tokens = 50
        
        client.chat.completions.create.return_value = response
        mock.return_value = client
        
        yield client


@pytest.fixture
def mock_browser():
    """Mock do controlador do navegador."""
    browser = AsyncMock()
    browser.initialize = AsyncMock(return_value=True)
    browser.close = AsyncMock()
    browser.is_logged_in = AsyncMock(return_value=True)
    browser.navigate_to = AsyncMock()
    browser.navigate_to_matches = AsyncMock()
    browser.page = AsyncMock()
    
    return browser


@pytest.fixture
def mock_extractor():
    """Mock do extrator de dados."""
    extractor = AsyncMock()
    extractor.extract_matches_list = AsyncMock(return_value=[
        {
            "tinder_match_id": "match_001",
            "name": "Carolina",
            "age": 26,
            "profile_photo_url": "https://example.com/carolina.jpg",
            "has_messages": False
        },
        {
            "tinder_match_id": "match_002",
            "name": "Fernanda",
            "age": 24,
            "profile_photo_url": "https://example.com/fernanda.jpg",
            "has_messages": True,
            "last_message_preview": "Oi, como vai?"
        }
    ])
    
    return extractor


# ============================================
# Fixtures Async
# ============================================

@pytest.fixture
def event_loop():
    """Cria event loop para testes assíncronos."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================
# Fixtures de API Web
# ============================================

@pytest.fixture
def web_client():
    """Cliente de teste para a API Flask."""
    from web.app import app
    app.config['TESTING'] = True
    
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_db_manager():
    """Mock do gerenciador de banco de dados."""
    with patch("database.get_db_manager") as mock:
        manager = MagicMock()
        
        # Mock de sessão
        session = MagicMock()
        manager.get_session.return_value.__enter__ = MagicMock(return_value=session)
        manager.get_session.return_value.__exit__ = MagicMock(return_value=False)
        
        mock.return_value = manager
        
        yield manager, session


# ============================================
# Fixtures de Match Helpers
# ============================================

@pytest.fixture
def mock_settings():
    """Mock das configurações do sistema."""
    settings = MagicMock()
    settings.days_without_interaction = 365
    settings.max_messages_per_run = 10
    settings.openai_model = "gpt-4"
    return settings


@pytest.fixture
def mock_match_validator(mock_settings):
    """Fixture do MatchValidator."""
    from automation.match_helpers import MatchValidator
    return MatchValidator(mock_settings)


@pytest.fixture
def mock_profile_cache():
    """Fixture do ProfileCache."""
    from automation.match_helpers import ProfileCache, reset_profile_cache
    reset_profile_cache()
    cache = ProfileCache(ttl_seconds=60)
    yield cache
    reset_profile_cache()


@pytest.fixture
def sample_match_data():
    """Dados de exemplo de um match."""
    return {
        "tinder_match_id": "sample_match_123",
        "name": "Carolina",
        "age": 26,
        "bio": "Amo viajar e conhecer pessoas novas",
        "job_title": "Designer",
        "school": "USP",
        "interests": ["viagens", "arte", "música"],
        "photos_count": 5,
        "profile_photo_url": "https://example.com/photo.jpg",
        "is_verified": True
    }


@pytest.fixture
def sample_my_profile():
    """Dados de exemplo do meu perfil."""
    return {
        "name": "João",
        "age": 28,
        "bio": "Desenvolvedor, amo tecnologia e viagens",
        "interests": ["viagens", "tecnologia", "música", "esportes"]
    }
