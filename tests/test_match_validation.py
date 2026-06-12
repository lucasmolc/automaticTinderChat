"""
Testes para o módulo match_validation.py.
Testa MatchValidator e funções de validação de mensagens.
"""

import pytest
from unittest.mock import MagicMock
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
        from automation.match_validation import MatchValidator
        return MatchValidator(settings)
    
    def test_should_skip_blocked_match(self, validator):
        """Match bloqueado deve ser pulado."""
        match = MagicMock()
        match.is_blocked = True
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = datetime.utcnow()
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip is True
        assert 'bloqueado' in reason.lower()
    
    def test_should_skip_unmatched(self, validator):
        """Match desfeito deve ser pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = True
        match.whatsapp_obtained = False
        match.date_confirmed = False
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip is True
        assert 'unmatch' in reason.lower()
    
    def test_should_skip_whatsapp_obtained(self, validator):
        """Match com WhatsApp obtido deve ser pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = True
        match.date_confirmed = False
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip is True
        assert 'whatsapp' in reason.lower()
    
    def test_should_skip_date_confirmed(self, validator):
        """Match com encontro confirmado deve ser pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = True
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip is True
        assert 'confirmado' in reason.lower()
    
    def test_should_not_skip_active_match(self, validator):
        """Match ativo não deve ser pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = datetime.utcnow()
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip is False
        assert reason is None
    
    def test_should_not_skip_new_match(self, validator):
        """Match novo (sem data de interação) não deve ser pulado."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = None
        
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip is False
        assert reason is None
    
    def test_should_skip_inactive_match(self, validator):
        """Match inativo deve ser processado (bloqueio é feito separadamente)."""
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = datetime.utcnow() - timedelta(days=400)
        
        should_skip, reason = validator.should_skip_match(match)
        
        # Inatividade não é mais verificada em should_skip_match
        # O bloqueio por inatividade é feito separadamente via should_block_for_inactivity
        assert should_skip is False
        assert reason is None


class TestValidateAIMessage:
    """Testes para validação de mensagens da IA."""
    
    def test_valid_message(self):
        """Mensagem válida deve passar."""
        from automation.match_validation import validate_ai_message
        
        is_valid, reason = validate_ai_message("Olá, tudo bem?")
        
        assert is_valid is True
        assert reason is None
    
    def test_empty_message(self):
        """Mensagem vazia deve ser rejeitada."""
        from automation.match_validation import validate_ai_message
        
        is_valid, reason = validate_ai_message("")
        
        assert is_valid is False
        assert 'vazia' in reason.lower()
    
    def test_short_message(self):
        """Mensagem muito curta deve ser rejeitada."""
        from automation.match_validation import validate_ai_message
        
        is_valid, reason = validate_ai_message("Oi")
        
        assert is_valid is False
        assert 'curta' in reason.lower()
    
    def test_long_message(self):
        """Mensagem muito longa deve ser rejeitada."""
        from automation.match_validation import validate_ai_message
        
        is_valid, reason = validate_ai_message("x" * 600)
        
        assert is_valid is False
        assert 'longa' in reason.lower()
    
    def test_message_with_assistant_pattern(self):
        """Mensagem com padrão de assistente deve ser rejeitada."""
        from automation.match_validation import validate_ai_message
        
        is_valid, reason = validate_ai_message("Como assistente, não posso fazer isso")
        
        assert is_valid is False
        assert 'padrão' in reason.lower()
    
    def test_message_with_placeholder(self):
        """Mensagem com placeholder deve ser rejeitada."""
        from automation.match_validation import validate_ai_message
        
        is_valid, reason = validate_ai_message("Olá {{nome}}, tudo bem?")
        
        assert is_valid is False
        assert 'padrão' in reason.lower()


class TestConvenienceFunctions:
    """Testes para funções de conveniência."""
    
    @pytest.fixture
    def settings(self):
        """Mock das configurações."""
        settings = MagicMock()
        settings.days_without_interaction = 365
        return settings
    
    def test_is_match_processable(self, settings):
        """Testa função is_match_processable."""
        from automation.match_validation import is_match_processable
        
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = datetime.utcnow()
        
        assert is_match_processable(match, settings) is True
    
    def test_get_skip_reason_none(self, settings):
        """Testa que match ativo não tem motivo de pulo."""
        from automation.match_validation import get_skip_reason
        
        match = MagicMock()
        match.is_blocked = False
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = datetime.utcnow()
        
        assert get_skip_reason(match, settings) is None
    
    def test_get_skip_reason_blocked(self, settings):
        """Testa motivo de pulo para match bloqueado."""
        from automation.match_validation import get_skip_reason
        
        match = MagicMock()
        match.is_blocked = True
        match.is_unmatched = False
        match.whatsapp_obtained = False
        match.date_confirmed = False
        match.last_interaction_at = datetime.utcnow()
        
        reason = get_skip_reason(match, settings)
        assert reason is not None
        assert 'bloqueado' in reason.lower()
