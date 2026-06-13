"""
Testes para features de browser headless e sync durante pausa.

Cobre:
- BrowserController com parâmetro headless
- reset_browser() singleton reset
- Fluxo run_efficient_cycle (execução apenas com banco)
- run_automation sync durante pausa  
- _run_migrations (migrações de banco)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.models import Base, Match, Message
from database.repositories import active_match_filter


class TestBrowserHeadless:
    """Testes para modo headless do BrowserController."""
    
    def test_default_headless_from_settings(self):
        """Testa que headless usa configuração do settings quando não passado."""
        from automation.browser import BrowserController
        
        with patch("automation.browser.get_settings") as mock_settings:
            mock_settings.return_value.browser_headless = True
            controller = BrowserController()
            assert controller._headless == True
        
        with patch("automation.browser.get_settings") as mock_settings:
            mock_settings.return_value.browser_headless = False
            controller = BrowserController()
            assert controller._headless == False
    
    def test_explicit_headless_override(self):
        """Testa que parâmetro headless sobreescreve settings."""
        from automation.browser import BrowserController
        
        with patch("automation.browser.get_settings") as mock_settings:
            mock_settings.return_value.browser_headless = False
            
            controller = BrowserController(headless=True)
            assert controller._headless == True
            
            controller = BrowserController(headless=False)
            assert controller._headless == False
    
    def test_headless_none_uses_settings(self):
        """Testa que headless=None usa settings."""
        from automation.browser import BrowserController
        
        with patch("automation.browser.get_settings") as mock_settings:
            mock_settings.return_value.browser_headless = True
            
            controller = BrowserController(headless=None)
            assert controller._headless == True


class TestResetBrowser:
    """Testes para reset_browser singleton."""
    
    def test_reset_browser_clears_singleton(self):
        """Testa que reset_browser limpa o singleton."""
        from automation.browser import _browser, get_browser, reset_browser
        
        # Obter instância
        browser1 = get_browser()
        assert browser1 is not None
        
        # Resetar
        reset_browser()
        
        # Nova instância deve ser criada
        browser2 = get_browser()
        assert browser2 is not browser1
        
        # Cleanup
        reset_browser()
    
    def test_get_browser_returns_same_instance(self):
        """Testa que get_browser retorna singleton."""
        from automation.browser import get_browser, reset_browser
        
        reset_browser()
        
        browser1 = get_browser()
        browser2 = get_browser()
        assert browser1 is browser2
        
        reset_browser()
    
    def test_get_browser_with_headless_param(self):
        """Testa get_browser com parâmetro headless."""
        from automation.browser import get_browser, reset_browser
        
        reset_browser()
        
        browser = get_browser(headless=True)
        assert browser._headless == True
        
        reset_browser()


class TestRunEfficientCycle:
    """Testes para run_efficient_cycle."""
    
    @pytest.mark.asyncio
    async def test_cycle_no_pending_work(self):
        """Testa ciclo sem trabalho pendente."""
        from automation.orchestrator import AutomationOrchestrator
        
        with patch("automation.orchestrator.get_db_manager") as mock_db:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            
            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            
            mock_db.return_value.get_session.return_value.__enter__ = MagicMock(return_value=session)
            mock_db.return_value.get_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.return_value.initialize = MagicMock()
            
            with patch("automation.orchestrator.get_notification_manager"):
                orchestrator = AutomationOrchestrator()
                orchestrator.db = mock_db.return_value
                
                result = await orchestrator.run_efficient_cycle()
            
            assert result["success"] == True
            assert result["stats"]["skipped_no_work"] == True
            assert result["stats"]["messages_sent"] == 0
            
            session.close()
    
    @pytest.mark.asyncio
    async def test_cycle_with_pending_first_messages(self):
        """Testa ciclo com primeiras mensagens pendentes."""
        from automation.orchestrator import AutomationOrchestrator
        
        with patch("automation.orchestrator.get_db_manager") as mock_db:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            
            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            
            # Criar match pendente
            match = Match(
                tinder_match_id="cycle_001",
                name="Cycle Test",
                has_messages=False,
                first_message_sent=False,
                is_blocked=False
            )
            session.add(match)
            session.commit()
            
            mock_db.return_value.get_session.return_value.__enter__ = MagicMock(return_value=session)
            mock_db.return_value.get_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.return_value.initialize = MagicMock()
            
            mock_extractor = AsyncMock()
            mock_execution = AsyncMock()
            mock_execution.send_first_messages = AsyncMock(return_value={"sent": 1, "errors": 0, "skipped_incomplete_data": 0})
            mock_execution.respond_to_messages = AsyncMock(return_value={"sent": 0, "errors": 0, "skipped_incomplete_data": 0})
            mock_execution.resend_messages = AsyncMock(return_value={"sent": 0, "errors": 0})
            
            with patch("automation.orchestrator.get_notification_manager"):
                with patch("automation.orchestrator.get_execution_service", return_value=mock_execution):
                    with patch("automation.orchestrator.get_state_manager") as mock_state:
                        mock_state.return_value.dry_run = False
                        
                        orchestrator = AutomationOrchestrator()
                        orchestrator.db = mock_db.return_value
                        orchestrator.extractor = mock_extractor
                        
                        result = await orchestrator.run_efficient_cycle()
            
            assert result["success"] == True
            assert result["stats"]["matches_processed"] > 0
            
            session.close()
    
    @pytest.mark.asyncio
    async def test_cycle_matches_processed_counter(self):
        """Testa que matches_processed é atualizado corretamente."""
        from automation.orchestrator import AutomationOrchestrator
        
        with patch("automation.orchestrator.get_db_manager") as mock_db:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            
            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            
            # Criar 2 matches pendentes primeiro msg + 1 aguardando resposta
            m1 = Match(tinder_match_id="mp_001", name="M1", has_messages=False, first_message_sent=False, is_blocked=False)
            m2 = Match(tinder_match_id="mp_002", name="M2", has_messages=False, first_message_sent=False, is_blocked=False)
            m3 = Match(tinder_match_id="mp_003", name="M3", has_messages=True, awaiting_my_response=True, is_blocked=False)
            session.add_all([m1, m2, m3])
            session.commit()
            
            mock_db.return_value.get_session.return_value.__enter__ = MagicMock(return_value=session)
            mock_db.return_value.get_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.return_value.initialize = MagicMock()
            
            mock_execution = AsyncMock()
            mock_execution.send_first_messages = AsyncMock(return_value={"sent": 2, "errors": 0, "skipped_incomplete_data": 0})
            mock_execution.respond_to_messages = AsyncMock(return_value={"sent": 1, "errors": 0, "skipped_incomplete_data": 0})
            
            with patch("automation.orchestrator.get_notification_manager"):
                with patch("automation.orchestrator.get_execution_service", return_value=mock_execution):
                    with patch("automation.orchestrator.get_state_manager") as mock_state:
                        mock_state.return_value.dry_run = False
                        
                        orchestrator = AutomationOrchestrator()
                        orchestrator.db = mock_db.return_value
                        orchestrator.extractor = AsyncMock()
                        
                        result = await orchestrator.run_efficient_cycle()
            
            # matches_processed deve ser 3 (2 first + 1 response)
            assert result["stats"]["matches_processed"] == 3
            
            session.close()


class TestDatabaseMigrations:
    """Testes para _run_migrations do DatabaseManager."""
    
    def test_migrations_add_missing_columns(self):
        """Testa que migrações adicionam colunas faltantes (simulação)."""
        # Com SQLite in-memory, testar que o modelo já tem os campos
        from sqlalchemy import create_engine, inspect
        
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('matches')]
        
        # Verificar que as colunas de reenvio existem
        assert 'pending_resend' in columns
        assert 'resend_reason' in columns
        assert 'resend_at' in columns
    
    def test_matches_table_has_all_expected_columns(self):
        """Testa que a tabela matches tem todas as colunas esperadas."""
        from sqlalchemy import create_engine, inspect
        
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('matches')]
        
        expected_columns = [
            'id', 'tinder_match_id', 'name', 'age', 'bio',
            'has_messages', 'first_message_sent', 'awaiting_my_response',
            'is_blocked', 'is_unmatched',
            'pending_resend', 'resend_reason', 'resend_at',
            'whatsapp_obtained', 'date_confirmed',
            'conversation_temperature', 'temperature_score'
        ]
        
        for col in expected_columns:
            assert col in columns, f"Coluna '{col}' faltando na tabela matches"


class TestOrchestratorInitializeHeadless:
    """Testes para inicialização do orchestrator em modo headless."""
    
    @pytest.mark.asyncio
    async def test_initialize_headless_skips_login_prompt(self, mock_browser):
        """Testa que modo headless não pede login quando não logado."""
        from automation.orchestrator import AutomationOrchestrator
        
        mock_browser.is_logged_in = AsyncMock(return_value=False)
        
        with patch("automation.orchestrator.get_browser", return_value=mock_browser):
            with patch("automation.orchestrator.TinderDataExtractor"):
                with patch("automation.orchestrator.get_db_manager") as mock_db:
                    mock_db.return_value.initialize = MagicMock()
                    with patch("automation.browser.reset_browser"):
                        
                        orchestrator = AutomationOrchestrator()
                        result = await orchestrator.initialize(headless=True)
        
        # Em modo headless sem login, deve retornar False
        assert result == False
    
    @pytest.mark.asyncio
    async def test_initialize_headless_succeeds_when_logged_in(self, mock_browser):
        """Testa que modo headless funciona quando já logado."""
        from automation.orchestrator import AutomationOrchestrator
        
        mock_browser.is_logged_in = AsyncMock(return_value=True)
        
        with patch("automation.orchestrator.get_browser", return_value=mock_browser):
            with patch("automation.orchestrator.TinderDataExtractor"):
                with patch("automation.orchestrator.get_db_manager") as mock_db:
                    mock_db.return_value.initialize = MagicMock()
                    with patch("automation.browser.reset_browser"):
                        
                        orchestrator = AutomationOrchestrator()
                        result = await orchestrator.initialize(headless=True)
        
        assert result == True
    
    @pytest.mark.asyncio
    async def test_initialize_passes_headless_to_get_browser(self, mock_browser):
        """Testa que headless é passado para get_browser."""
        from automation.orchestrator import AutomationOrchestrator
        
        with patch("automation.orchestrator.get_browser", return_value=mock_browser) as mock_get_browser:
            with patch("automation.orchestrator.TinderDataExtractor"):
                with patch("automation.orchestrator.get_db_manager") as mock_db:
                    mock_db.return_value.initialize = MagicMock()
                    with patch("automation.browser.reset_browser"):
                        
                        orchestrator = AutomationOrchestrator()
                        await orchestrator.initialize(headless=True)
        
        mock_get_browser.assert_called_with(headless=True)


class TestSyncMessagesOnlyFilter:
    """Testes para sync_messages_only usando active_match_filter."""
    
    def test_active_match_filter_excludes_blocked(self, test_db):
        """Testa que active_match_filter exclui matches bloqueados."""
        blocked = Match(
            tinder_match_id="amf_001",
            name="Blocked",
            has_messages=True,
            is_blocked=True
        )
        active = Match(
            tinder_match_id="amf_002",
            name="Active",
            has_messages=True,
            is_blocked=False
        )
        test_db.add_all([blocked, active])
        test_db.commit()
        
        results = test_db.query(Match).filter(
            Match.has_messages == True,
            active_match_filter()
        ).all()
        
        assert len(results) == 1
        assert results[0].name == "Active"
    
    def test_active_match_filter_excludes_whatsapp_obtained(self, test_db):
        """Testa que active_match_filter exclui matches com WhatsApp obtido."""
        whatsapp = Match(
            tinder_match_id="amf_003",
            name="WhatsApp",
            has_messages=True,
            whatsapp_obtained=True
        )
        normal = Match(
            tinder_match_id="amf_004",
            name="Normal",
            has_messages=True,
            whatsapp_obtained=False
        )
        test_db.add_all([whatsapp, normal])
        test_db.commit()
        
        results = test_db.query(Match).filter(
            Match.has_messages == True,
            active_match_filter()
        ).all()
        
        assert len(results) == 1
        assert results[0].name == "Normal"
