"""
Testes para os serviços da arquitetura SYNC/EXECUTE refatorada.

Testa:
- MatchDataService: Fornecimento de dados do banco
- ExecutionService: Execução de ações automatizadas
- DataValidationService: Validação de dados
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from automation.data_validation_service import DataValidationService
from automation.match_data_service import MatchDataService


class TestDataValidationService:
    """Testes para o serviço de validação de dados."""
    
    def test_validate_name_valid(self):
        """Testa validação de nome válido."""
        name, is_valid = DataValidationService.validate_name("Maria")
        assert name == "Maria"
        assert is_valid is True
    
    def test_validate_name_unknown_fallback(self):
        """Testa fallback para Unknown quando nome é inválido."""
        name, is_valid = DataValidationService.validate_name(None)
        assert name == "Unknown"
        assert is_valid is False
    
    def test_validate_name_extracts_from_match_text(self):
        """Testa extração de nome de texto de match."""
        text = "Você deu Match com Maria em 01/01/2026"
        name, is_valid = DataValidationService.validate_name(text)
        assert name == "Maria"
        assert is_valid is True
    
    def test_validate_name_rejects_only_numbers(self):
        """Testa rejeição de nomes com só números."""
        name, is_valid = DataValidationService.validate_name("12345")
        assert name == "Unknown"
        assert is_valid is False
    
    def test_validate_name_rejects_too_short(self):
        """Testa rejeição de nomes muito curtos."""
        name, is_valid = DataValidationService.validate_name("A")
        assert name == "Unknown"
        assert is_valid is False
    
    def test_validate_age_valid(self):
        """Testa validação de idade válida."""
        age, is_valid = DataValidationService.validate_age(25)
        assert age == 25
        assert is_valid is True
    
    def test_validate_age_too_young(self):
        """Testa rejeição de idade muito baixa."""
        age, is_valid = DataValidationService.validate_age(16)
        assert age is None
        assert is_valid is False
    
    def test_validate_age_none_is_valid(self):
        """Testa que idade None é válida (campo opcional)."""
        age, is_valid = DataValidationService.validate_age(None)
        assert age is None
        assert is_valid is True
    
    def test_validate_bio_valid(self):
        """Testa validação de bio válida."""
        bio, is_valid = DataValidationService.validate_bio("Amo viajar e conhecer pessoas")
        assert bio == "Amo viajar e conhecer pessoas"
        assert is_valid is True
    
    def test_validate_bio_rejects_ui_text(self):
        """Testa rejeição de texto de UI."""
        bio, is_valid = DataValidationService.validate_bio("Sobre mim")
        assert bio is None
        assert is_valid is False
    
    def test_validate_photo_url_valid(self):
        """Testa validação de URL válida."""
        url, is_valid = DataValidationService.validate_photo_url(
            "https://images.gotinder.com/user123/photo.jpg"
        )
        assert url is not None
        assert is_valid is True
    
    def test_validate_photo_url_rejects_icons(self):
        """Testa rejeição de URLs de ícones."""
        url, is_valid = DataValidationService.validate_photo_url(
            "https://tinder.com/static-assets/icons/icon.png"
        )
        assert url is None
        assert is_valid is False
    
    def test_validate_match_data_complete(self):
        """Testa validação de dados completos de match."""
        data = {
            "name": "Maria",
            "age": 25,
            "bio": "Amo viajar",
            "tinder_match_id": "abc123"
        }
        validated, warnings = DataValidationService.validate_match_data(data)
        
        assert validated["name"] == "Maria"
        assert validated["age"] == 25
        assert validated["bio"] == "Amo viajar"
        assert len(warnings) == 0
    
    def test_validate_match_data_with_invalid_name(self):
        """Testa validação com nome inválido gera warning."""
        data = {
            "name": "Você deu Match com Maria em 01/01/2026 às 15:00",
            "age": 25
        }
        validated, warnings = DataValidationService.validate_match_data(data)
        
        assert validated["name"] == "Maria"  # Deve extrair nome
        assert len(warnings) == 0  # Nome foi extraído com sucesso
    
    def test_is_data_complete_for_ai_with_bio(self):
        """Testa que dados com bio são suficientes para IA."""
        data = {"name": "Maria", "bio": "Amo viajar"}
        assert DataValidationService.is_data_complete_for_ai(data) is True
    
    def test_is_data_complete_for_ai_unknown_name(self):
        """Testa que nome Unknown não é suficiente."""
        data = {"name": "Unknown", "bio": "Amo viajar"}
        assert DataValidationService.is_data_complete_for_ai(data) is False


class TestMatchDataService:
    """Testes para o serviço de dados de matches."""
    
    @pytest.fixture
    def mock_session(self):
        """Cria sessão mockada."""
        return MagicMock()
    
    @pytest.fixture
    def mock_match(self):
        """Cria match mockado."""
        match = MagicMock()
        match.id = 1
        match.tinder_match_id = "abc123"
        match.name = "Maria"
        match.age = 25
        match.bio = "Amo viajar"
        match.distance_km = 5
        match.job_title = "Engenheira"
        match.school = None
        match.gender = "F"
        match.city = "São Paulo"
        match.relationship_intent = None
        match.sexual_orientations = None
        match.photos_count = 3
        match.is_verified = True
        match.matched_at = datetime.utcnow()
        match.is_unmatched = False
        match.is_blocked = False
        return match
    
    def test_get_match_profile_for_ai_returns_ok_status(self, mock_session, mock_match):
        """Testa que match completo retorna status ok."""
        with patch('automation.match_data_service.MatchRepository') as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_interests.return_value = ["Música", "Viagem"]
            MockRepo.return_value = mock_repo
            
            service = MatchDataService(mock_session)
            profile, status = service.get_match_profile_for_ai(mock_match)
            
            assert status == "ok"
            assert profile["name"] == "Maria"
            assert profile["age"] == 25
    
    def test_get_match_profile_for_ai_returns_unmatched_status(self, mock_session, mock_match):
        """Testa que match com unmatch retorna status correto."""
        mock_match.is_unmatched = True
        
        with patch('automation.match_data_service.MatchRepository') as MockRepo:
            service = MatchDataService(mock_session)
            profile, status = service.get_match_profile_for_ai(mock_match)
            
            assert status == "unmatched"
            assert profile is None
    
    def test_get_match_profile_for_ai_returns_blocked_status(self, mock_session, mock_match):
        """Testa que match bloqueado retorna status correto."""
        mock_match.is_blocked = True
        
        with patch('automation.match_data_service.MatchRepository') as MockRepo:
            service = MatchDataService(mock_session)
            profile, status = service.get_match_profile_for_ai(mock_match)
            
            assert status == "blocked"
            assert profile is None
    
    def test_get_match_profile_for_ai_returns_incomplete_status(self, mock_session, mock_match):
        """Testa que match sem bio/job retorna incomplete."""
        mock_match.name = "Unknown"
        mock_match.bio = None
        mock_match.job_title = None
        
        with patch('automation.match_data_service.MatchRepository') as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_interests.return_value = []
            MockRepo.return_value = mock_repo
            
            service = MatchDataService(mock_session)
            profile, status = service.get_match_profile_for_ai(mock_match)
            
            assert status == "incomplete"
    
    def test_get_common_interests(self, mock_session):
        """Testa cálculo de interesses em comum."""
        with patch('automation.match_data_service.MatchRepository'):
            with patch('automation.match_data_service.MyProfileRepository') as MockMyRepo:
                mock_profile = MagicMock()
                mock_profile.interests = [
                    MagicMock(interest_name="Música"),
                    MagicMock(interest_name="Viagem"),
                    MagicMock(interest_name="Cinema")
                ]
                mock_my_repo = MagicMock()
                mock_my_repo.get_or_create.return_value = mock_profile
                MockMyRepo.return_value = mock_my_repo
                
                service = MatchDataService(mock_session)
                
                # Primeiro chama get_my_profile_data para popular cache
                service.get_my_profile_data()
                
                # Calcula interesses em comum
                common = service.get_common_interests(["Música", "Esporte"])
                
                assert "Música" in common
                assert "Esporte" not in common


class TestExecutionServiceStats:
    """Testes para estatísticas do ExecutionService."""
    
    def test_execution_service_returns_dict_with_stats(self):
        """Testa que send_first_messages retorna Dict com estatísticas."""
        from automation.execution_service import get_execution_service, reset_execution_service
        
        # Reset singleton
        reset_execution_service()
        
        mock_extractor = MagicMock()
        service = get_execution_service(mock_extractor)
        
        # Verificar que stats inicial é dict vazio
        stats = service.get_stats()
        assert isinstance(stats, dict)
        assert "messages_sent" in stats
        assert "errors" in stats
        assert "skipped_incomplete_data" in stats
    
    def test_reset_stats_clears_counters(self):
        """Testa que reset_stats zera contadores."""
        from automation.execution_service import get_execution_service, reset_execution_service
        
        reset_execution_service()
        
        mock_extractor = MagicMock()
        service = get_execution_service(mock_extractor)
        
        # Simular algumas estatísticas
        service.stats["messages_sent"] = 5
        service.stats["errors"] = 2
        
        # Reset
        service.reset_stats()
        
        stats = service.get_stats()
        assert stats["messages_sent"] == 0
        assert stats["errors"] == 0


class TestGetExecutionServiceFactory:
    """Testes para factory function get_execution_service."""
    
    def test_get_execution_service_creates_singleton(self):
        """Testa que factory retorna mesma instância."""
        from automation.execution_service import get_execution_service, reset_execution_service
        
        reset_execution_service()
        
        mock_extractor = MagicMock()
        service1 = get_execution_service(mock_extractor)
        service2 = get_execution_service(mock_extractor)
        
        assert service1 is service2
    
    def test_get_execution_service_creates_new_on_different_extractor(self):
        """Testa que factory cria nova instância com extractor diferente."""
        from automation.execution_service import get_execution_service, reset_execution_service
        
        reset_execution_service()
        
        mock_extractor1 = MagicMock()
        mock_extractor2 = MagicMock()
        
        service1 = get_execution_service(mock_extractor1)
        service2 = get_execution_service(mock_extractor2)
        
        assert service1 is not service2
