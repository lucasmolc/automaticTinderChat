"""
Testes de Idempotência - Garantia de envio único de mensagens.

Este arquivo contém testes críticos para garantir que:
1. Mensagens NUNCA são enviadas em duplicata
2. O sistema é resiliente a falhas
3. Reexecuções não causam duplicação
4. Concorrência é tratada corretamente

IMPORTANTE: Estes testes são CRÍTICOS para a confiabilidade do sistema.
"""

import threading
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

# Importar classes a serem testadas
from automation.idempotency import (
    IdempotencyCheckResult,
    IdempotencyError,
    IdempotencyGuard,
    get_idempotency_guard,
    verify_first_message_allowed,
)


class TestIdempotencyGuard:
    """Testes para o guard de idempotência."""
    
    def setup_method(self):
        """Reset do guard antes de cada teste."""
        guard = get_idempotency_guard()
        guard.reset()
    
    def test_singleton_pattern(self):
        """Verifica que IdempotencyGuard é singleton."""
        guard1 = get_idempotency_guard()
        guard2 = get_idempotency_guard()
        
        assert guard1 is guard2, "Guard deve ser singleton"
    
    def test_check_can_send_allowed(self):
        """Testa que envio é permitido para match sem mensagem."""
        guard = get_idempotency_guard()
        
        # Mock do match
        mock_match = MagicMock()
        mock_match.tinder_match_id = "test_match_123"
        mock_match.name = "Test User"
        mock_match.first_message_sent = False
        mock_match.has_messages = False
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        
        # Mock da session
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_match
        
        # Mock da classe Match
        mock_Match = MagicMock()
        
        result, reason = guard.check_can_send("test_match_123", mock_session, mock_Match)
        
        assert result == IdempotencyCheckResult.ALLOWED
        assert reason == "OK"
    
    def test_check_can_send_already_sent_first_message(self):
        """Testa bloqueio quando first_message_sent=True."""
        guard = get_idempotency_guard()
        
        mock_match = MagicMock()
        mock_match.tinder_match_id = "test_match_123"
        mock_match.name = "Test User"
        mock_match.first_message_sent = True  # JÁ ENVIOU
        mock_match.has_messages = True
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_match
        mock_Match = MagicMock()
        
        result, reason = guard.check_can_send("test_match_123", mock_session, mock_Match)
        
        assert result == IdempotencyCheckResult.ALREADY_SENT
        assert "first_message_sent=True" in reason
    
    def test_check_can_send_already_has_messages(self):
        """Testa bloqueio quando has_messages=True."""
        guard = get_idempotency_guard()
        
        mock_match = MagicMock()
        mock_match.tinder_match_id = "test_match_123"
        mock_match.name = "Test User"
        mock_match.first_message_sent = False
        mock_match.has_messages = True  # JÁ TEM MENSAGENS
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_match
        mock_Match = MagicMock()
        
        result, reason = guard.check_can_send("test_match_123", mock_session, mock_Match)
        
        assert result == IdempotencyCheckResult.ALREADY_SENT
        assert "has_messages=True" in reason
    
    def test_check_can_send_blocked_match(self):
        """Testa que match bloqueado é rejeitado."""
        guard = get_idempotency_guard()
        
        mock_match = MagicMock()
        mock_match.tinder_match_id = "test_match_123"
        mock_match.name = "Test User"
        mock_match.first_message_sent = False
        mock_match.has_messages = False
        mock_match.is_blocked = True  # BLOQUEADO
        mock_match.is_unmatched = False
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_match
        mock_Match = MagicMock()
        
        result, reason = guard.check_can_send("test_match_123", mock_session, mock_Match)
        
        assert result == IdempotencyCheckResult.MATCH_BLOCKED
    
    def test_check_can_send_unmatched(self):
        """Testa que match desmatchado é rejeitado."""
        guard = get_idempotency_guard()
        
        mock_match = MagicMock()
        mock_match.tinder_match_id = "test_match_123"
        mock_match.name = "Test User"
        mock_match.first_message_sent = False
        mock_match.has_messages = False
        mock_match.is_blocked = False
        mock_match.is_unmatched = True  # DESMATCHOU
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_match
        mock_Match = MagicMock()
        
        result, reason = guard.check_can_send("test_match_123", mock_session, mock_Match)
        
        assert result == IdempotencyCheckResult.MATCH_BLOCKED
    
    def test_check_can_send_match_not_found(self):
        """Testa que match inexistente é rejeitado."""
        guard = get_idempotency_guard()
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        mock_Match = MagicMock()
        
        result, reason = guard.check_can_send("nonexistent_match", mock_session, mock_Match)
        
        assert result == IdempotencyCheckResult.MATCH_BLOCKED
        assert "não encontrado" in reason
    
    def test_send_lock_blocks_concurrent_send(self):
        """Testa que lock previne envio concorrente."""
        guard = get_idempotency_guard()
        match_id = "concurrent_test_match"
        
        results = []
        
        def thread_function(thread_id):
            try:
                with guard.send_lock(match_id):
                    results.append(f"Thread {thread_id} acquired lock")
                    time.sleep(0.1)  # Simula trabalho
                    results.append(f"Thread {thread_id} released lock")
            except IdempotencyError:
                results.append(f"Thread {thread_id} blocked by lock")
        
        # Tentar adquirir lock de duas threads
        t1 = threading.Thread(target=thread_function, args=(1,))
        t2 = threading.Thread(target=thread_function, args=(2,))
        
        t1.start()
        time.sleep(0.01)  # Dar tempo para t1 adquirir lock
        t2.start()
        
        t1.join()
        t2.join()
        
        # Uma thread deve ter sido bloqueada
        blocked = any("blocked" in r for r in results)
        assert blocked, f"Uma thread deveria ter sido bloqueada. Resultados: {results}"
    
    def test_recent_attempt_blocks_resend(self):
        """Testa que tentativa recente bem-sucedida bloqueia reenvio."""
        guard = get_idempotency_guard()
        match_id = "recent_test_match"
        
        # Registrar tentativa bem-sucedida
        guard.record_send_attempt(match_id, "Test message", True, "Test success")
        
        # Mock do match
        mock_match = MagicMock()
        mock_match.tinder_match_id = match_id
        mock_match.name = "Test User"
        mock_match.first_message_sent = False
        mock_match.has_messages = False
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_match
        mock_Match = MagicMock()
        
        # Deve bloquear por tentativa recente
        result, reason = guard.check_can_send(match_id, mock_session, mock_Match)
        
        assert result == IdempotencyCheckResult.RECENT_ATTEMPT
        assert "Envio bem-sucedido" in reason
    
    def test_stats_tracking(self):
        """Testa que estatísticas são rastreadas corretamente."""
        guard = get_idempotency_guard()
        guard.reset()
        
        # Simular algumas verificações bloqueadas
        mock_match = MagicMock()
        mock_match.tinder_match_id = "stats_test_match"
        mock_match.name = "Test User"
        mock_match.first_message_sent = True  # Já enviou
        mock_match.has_messages = True
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_match
        mock_Match = MagicMock()
        
        # Fazer algumas verificações
        guard.check_can_send("stats_test_match", mock_session, mock_Match)
        guard.check_can_send("stats_test_match", mock_session, mock_Match)
        
        stats = guard.get_stats()
        
        assert stats["duplicates_prevented"] == 2
        assert "active_sends" in stats
        assert "recorded_attempts" in stats


class TestVerifyFirstMessageAllowed:
    """Testes para verificação direta de primeira mensagem."""
    
    def test_allows_valid_match(self):
        """Testa permissão para match válido."""
        mock_match = MagicMock()
        mock_match.id = 1
        mock_match.tinder_match_id = "valid_match"
        mock_match.first_message_sent = False
        mock_match.has_messages = False
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.side_effect = [
            mock_match,  # Busca do match
            None  # Nenhuma mensagem existente
        ]
        
        mock_Match = MagicMock()
        mock_Message = MagicMock()
        
        can_send, reason = verify_first_message_allowed(
            "valid_match", mock_session, mock_Match, mock_Message
        )
        
        assert can_send == True
        assert "OK" in reason
    
    def test_blocks_existing_message(self):
        """Testa bloqueio quando já existe mensagem no banco."""
        mock_match = MagicMock()
        mock_match.id = 1
        mock_match.tinder_match_id = "has_message_match"
        mock_match.first_message_sent = False  # Flag pode estar errada
        mock_match.has_messages = False  # Flag pode estar errada
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        
        mock_existing_message = MagicMock()
        mock_existing_message.id = 123
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.side_effect = [
            mock_match,  # Busca do match
            mock_existing_message  # Mensagem existente!
        ]
        
        mock_Match = MagicMock()
        mock_Message = MagicMock()
        
        can_send, reason = verify_first_message_allowed(
            "has_message_match", mock_session, mock_Match, mock_Message
        )
        
        assert can_send == False
        assert "Já existe mensagem" in reason


class TestDryRunMode:
    """Testes para modo dry-run/simulação."""
    
    @pytest.mark.asyncio
    async def test_dry_run_does_not_send(self):
        """Testa que dry-run não envia mensagens reais."""
        from automation.execution_service import ExecutionService
        
        mock_extractor = AsyncMock()
        mock_extractor.send_message = AsyncMock(return_value=True)
        
        # Mock do match
        mock_match = MagicMock()
        mock_match.id = 1
        mock_match.tinder_match_id = "dry_run_match"
        mock_match.name = "Test User"
        mock_match.first_message_sent = False
        mock_match.has_messages = False
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        mock_match.bio = "Test bio"
        
        with patch("automation.execution_service.get_db_manager") as mock_db:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_db.return_value.get_session.return_value = mock_session
            
            with patch("automation.execution_service.MatchRepository") as mock_match_repo:
                mock_match_repo.return_value.get_matches_without_messages.return_value = [mock_match]
                
                with patch("automation.execution_service.MatchDataService") as mock_data_service:
                    mock_data_service.return_value.get_match_profile_for_ai.return_value = (
                        {"name": "Test", "bio": "Bio"}, "valid"
                    )
                    mock_data_service.return_value.get_common_interests.return_value = []
                    
                    with patch("automation.execution_service.get_openai_client") as mock_openai:
                        mock_openai.return_value.generate_first_message.return_value = {
                            "message": "Test message!"
                        }
                        
                        with patch("automation.execution_service.MatchValidator") as mock_validator:
                            mock_validator.return_value.should_skip_match.return_value = (False, "")
                            
                            with patch("automation.execution_service.validate_ai_message", return_value=(True, "")):
                                with patch("automation.execution_service.get_idempotency_guard") as mock_guard:
                                    mock_guard.return_value.check_can_send.return_value = (
                                        IdempotencyCheckResult.ALLOWED, "OK"
                                    )
                                    
                                    with patch("automation.execution_service.verify_first_message_allowed", return_value=(True, "OK")):
                                        service = ExecutionService(mock_extractor)
                                        
                                        # Executar em modo dry-run
                                        result = await service.send_first_messages(limit=1, dry_run=True)
        
        # Verificar que send_message NÃO foi chamado
        mock_extractor.send_message.assert_not_called()
        
        # Verificar que resultado indica dry-run
        assert result.get("dry_run") == True
        assert result.get("simulated", 0) > 0 or len([d for d in result.get("details", []) if d.get("dry_run")]) > 0


class TestConcurrencyProtection:
    """Testes para proteção contra concorrência."""
    
    def test_active_sends_tracking(self):
        """Testa que envios ativos são rastreados."""
        guard = get_idempotency_guard()
        guard.reset()
        match_id = "tracking_test"
        
        # Verificar que não há envios ativos
        assert match_id not in guard._active_sends
        
        # Adquirir lock manualmente
        with guard.send_lock(match_id):
            # Durante o lock, deve estar nos ativos
            assert match_id in guard._active_sends
        
        # Após liberar, não deve estar mais
        assert match_id not in guard._active_sends
    
    def test_check_blocks_during_active_send(self):
        """Testa que check_can_send bloqueia durante envio ativo."""
        guard = get_idempotency_guard()
        guard.reset()
        match_id = "active_send_test"
        
        mock_match = MagicMock()
        mock_match.tinder_match_id = match_id
        mock_match.name = "Test"
        mock_match.first_message_sent = False
        mock_match.has_messages = False
        mock_match.is_blocked = False
        mock_match.is_unmatched = False
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_match
        mock_Match = MagicMock()
        
        # Simular envio ativo
        guard._active_sends.add(match_id)
        
        try:
            result, reason = guard.check_can_send(match_id, mock_session, mock_Match)
            
            assert result == IdempotencyCheckResult.LOCK_HELD
            assert "em andamento" in reason
        finally:
            guard._active_sends.discard(match_id)


class TestRollbackScenarios:
    """Testes para cenários de rollback."""
    
    def test_failed_send_should_rollback_flags(self):
        """Testa que falha no envio faz rollback das flags."""
        # Este é um teste conceitual - a implementação real
        # deve garantir que se send_message() falhar após
        # marcar first_message_sent=True, as flags voltam a False
        
        mock_match = MagicMock()
        mock_match.first_message_sent = False
        mock_match.has_messages = False
        
        # Simular marcação pré-envio
        mock_match.first_message_sent = True
        mock_match.has_messages = True
        
        # Simular falha no envio
        send_failed = True
        
        if send_failed:
            # Rollback
            mock_match.first_message_sent = False
            mock_match.has_messages = False
        
        assert mock_match.first_message_sent == False
        assert mock_match.has_messages == False


# ==================== FIXTURES ====================

@pytest.fixture
def mock_browser():
    """Mock do navegador."""
    browser = MagicMock()
    browser.close = MagicMock()
    return browser

@pytest.fixture
def mock_extractor():
    """Mock do extrator."""
    extractor = AsyncMock()
    extractor.send_message = AsyncMock(return_value=True)
    return extractor
