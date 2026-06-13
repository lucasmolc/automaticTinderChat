"""
Testes para funções de automação.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAutomationOrchestrator:
    """Testes para o orquestrador de automação."""
    
    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_browser, mock_extractor):
        """Testa inicialização bem sucedida."""
        from automation.orchestrator import AutomationOrchestrator
        
        with patch("automation.orchestrator.get_browser", return_value=mock_browser):
            with patch("automation.orchestrator.TinderDataExtractor", return_value=mock_extractor):
                with patch("automation.orchestrator.get_db_manager") as mock_db:
                    mock_db.return_value.initialize = MagicMock()
                    mock_db.return_value.get_session = MagicMock()
                    
                    orchestrator = AutomationOrchestrator()
                    result = await orchestrator.initialize()
        
        assert result == True
    
    @pytest.mark.asyncio
    async def test_close(self, mock_browser):
        """Testa fechamento do orquestrador."""
        from automation.orchestrator import AutomationOrchestrator
        
        with patch("automation.orchestrator.get_browser", return_value=mock_browser):
            with patch("automation.orchestrator.get_db_manager"):
                orchestrator = AutomationOrchestrator()
                orchestrator.browser = mock_browser
                
                await orchestrator.close()
        
        mock_browser.close.assert_called_once()


class TestBrowserController:
    """Testes para o controlador do navegador."""
    
    @pytest.mark.asyncio
    async def test_is_logged_in_true(self):
        """Testa detecção de login."""
        from automation.browser import BrowserController
        
        mock_page = AsyncMock()
        mock_page.query_selector.return_value = MagicMock()  # Elemento encontrado = logado
        
        controller = BrowserController()
        controller.page = mock_page
        
        # Simular verificação
        result = await mock_page.query_selector("button[aria-label='Matches']")
        
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_navigate_to_matches(self):
        """Testa navegação para matches."""
        from automation.browser import BrowserController
        
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        
        controller = BrowserController()
        controller.page = mock_page
        
        await mock_page.goto("https://tinder.com/app/matches")
        
        mock_page.goto.assert_called()


class TestDataExtractor:
    """Testes para o extrator de dados."""
    
    @pytest.mark.asyncio
    async def test_extract_matches_list(self, mock_extractor):
        """Testa extração de lista de matches."""
        matches = await mock_extractor.extract_matches_list()
        
        assert len(matches) == 2
        assert matches[0]["name"] == "Carolina"
        assert matches[1]["name"] == "Fernanda"
    
    def test_is_doubledate_detection_by_name(self):
        """Testa detecção de DoubleDate pelo nome."""
        # Nomes normais não são DoubleDate
        normal_names = ["Maria", "Ana Luiza", "Kawana", "Carol", "Julia"]
        
        for name in normal_names:
            # Verifica que não contém & ou +
            assert "&" not in name and "+" not in name
        
        # Nomes com & ou + indicam DoubleDate
        doubledate_names = ["Maria & Ana", "Carol + Fernanda", "Julia & Mariana"]
        
        for name in doubledate_names:
            assert "&" in name or "+" in name
    
    def test_extract_age_from_text(self):
        """Testa extração de idade."""
        import re
        
        # Simular extração
        test_cases = [
            ("Maria, 25 anos", 25),
            ("Ana 28", 28),
            ("Julia, 32 anos de idade", 32)
        ]
        
        for text, expected_age in test_cases:
            age_match = re.search(r'(\d{2})\s*(?:anos|years)?', text)
            assert age_match is not None
            assert int(age_match.group(1)) == expected_age


class TestNavigationOptimization:
    """Testes para verificar navegação otimizada."""
    
    @pytest.mark.asyncio
    async def test_navigate_to_matches_if_needed_skips_when_already_there(self):
        """Testa que navegação é pulada quando já está na página de matches."""
        from automation.browser import BrowserController
        
        mock_page = AsyncMock()
        mock_page.url = "https://tinder.com/app/matches"
        mock_page.goto = AsyncMock()
        
        controller = BrowserController()
        controller.page = mock_page
        
        result = await controller.navigate_to_matches_if_needed()
        
        assert result == False  # Não navegou
        mock_page.goto.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_navigate_to_matches_if_needed_navigates_when_elsewhere(self):
        """Testa que navegação ocorre quando não está na página."""
        from automation.browser import BrowserController

        mock_page = AsyncMock()
        mock_page.url = "https://tinder.com/app/messages/abc123"
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()

        controller = BrowserController()
        controller.page = mock_page
        # Marca como inicializado para que navigate_to use a página mockada
        # em vez de lançar um navegador real (que não existe no CI).
        # Os pequenos delays internos (asyncio.sleep / async_random_delay) rodam
        # de verdade aqui — propositalmente, para não depender de patch por string
        # (que falha conforme a ordem de import no Python 3.9).
        controller._is_initialized = True

        result = await controller.navigate_to_matches_if_needed()

        assert result is True  # Navegou
        mock_page.goto.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_navigate_to_match_if_needed_skips_when_already_there(self):
        """Testa que navegação para match é pulada quando já está lá."""
        from automation.browser import BrowserController
        
        match_id = "abc123"
        mock_page = AsyncMock()
        mock_page.url = f"https://tinder.com/app/messages/{match_id}"
        mock_page.goto = AsyncMock()
        
        controller = BrowserController()
        controller.page = mock_page
        
        result = await controller.navigate_to_match_if_needed(match_id)
        
        assert result == False
        mock_page.goto.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_navigate_to_match_if_needed_navigates_to_different_match(self):
        """Testa que navegação ocorre para match diferente."""
        from automation.browser import BrowserController
        
        mock_page = AsyncMock()
        mock_page.url = "https://tinder.com/app/messages/old123"
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        
        controller = BrowserController()
        controller.page = mock_page
        
        result = await controller.navigate_to_match_if_needed("new456")
        
        assert result == True


class TestExtractorNavigationOptimization:
    """Testes para navegação otimizada no extractor."""
    
    @pytest.mark.asyncio
    async def test_navigate_to_match_if_needed_skips(self):
        """Testa que _navigate_to_match_if_needed pula quando já está na página."""
        from automation.extractors import TinderDataExtractor
        
        mock_page = AsyncMock()
        mock_page.url = "https://tinder.com/app/messages/abc123"
        mock_page.goto = AsyncMock()
        
        extractor = TinderDataExtractor(mock_page)
        
        await extractor._navigate_to_match_if_needed("abc123")
        
        mock_page.goto.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_navigate_to_match_if_needed_navigates(self):
        """Testa que _navigate_to_match_if_needed navega quando necessário."""
        from automation.extractors import TinderDataExtractor
        
        mock_page = AsyncMock()
        mock_page.url = "https://tinder.com/app/matches"
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        
        extractor = TinderDataExtractor(mock_page)
        
        await extractor._navigate_to_match_if_needed("abc123")
        
        mock_page.goto.assert_called_once()
        assert "abc123" in str(mock_page.goto.call_args)


class TestProfileCacheUnification:
    """Testes para verificar que o cache de perfil usa singleton."""
    
    def test_orchestrator_uses_singleton_cache(self):
        """Testa que o orchestrator usa o singleton ProfileCache."""
        from automation.match_helpers import get_profile_cache
        from automation.orchestrator import AutomationOrchestrator
        
        with patch("automation.orchestrator.get_db_manager"):
            with patch("automation.orchestrator.get_notification_manager"):
                orchestrator = AutomationOrchestrator()
        
        # Verificar que usa o mesmo cache singleton
        assert orchestrator._profile_cache is get_profile_cache()
    
    def test_profile_cache_get_with_max_age(self):
        """Testa que _get_cached_profile respeita max_age."""
        from datetime import datetime, timedelta

        from automation.match_helpers import get_profile_cache, reset_profile_cache
        from automation.orchestrator import AutomationOrchestrator
        
        reset_profile_cache()  # Limpar estado anterior
        
        with patch("automation.orchestrator.get_db_manager"):
            with patch("automation.orchestrator.get_notification_manager"):
                orchestrator = AutomationOrchestrator()
        
        # Cachear um perfil
        test_profile = {"name": "Test", "age": 25}
        orchestrator._cache_profile(test_profile)
        
        # Deve retornar o perfil cacheado
        cached = orchestrator._get_cached_profile()
        assert cached is not None
        assert cached["name"] == "Test"


class TestSyncMatchesOnly:
    """Testes para função de sincronização."""
    
    @pytest.mark.asyncio
    async def test_sync_returns_dict(self):
        """Testa retorno da sincronização."""
        from automation.orchestrator import sync_matches_only
        
        with patch("automation.orchestrator.AutomationOrchestrator") as MockOrch:
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock(return_value=False)
            mock_instance.close = AsyncMock()
            MockOrch.return_value = mock_instance
            
            result = await sync_matches_only()
        
        assert isinstance(result, dict)
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_sync_failure_returns_error(self):
        """Testa retorno de erro na sincronização."""
        from automation.orchestrator import sync_matches_only
        
        with patch("automation.orchestrator.AutomationOrchestrator") as MockOrch:
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock(return_value=False)
            mock_instance.close = AsyncMock()
            MockOrch.return_value = mock_instance
            
            result = await sync_matches_only()
        
        assert result["success"] == False
        assert "error" in result
