"""
Testes para a funcionalidade de reenvio de mensagens (resend).

Cobre:
- Campos do modelo Match (pending_resend, resend_reason, resend_at)
- Repositório: mark_for_resend, clear_resend, get_matches_pending_resend, count_pending_resend
- Filtro pending_resend_filter
- ExecutionService.resend_messages (dry run)
- API web: toggle resend status
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

from database.models import Match, Message
from database.repositories import (
    MatchRepository, MessageRepository,
    pending_resend_filter, active_match_filter
)


class TestResendModel:
    """Testes para os campos de reenvio no modelo Match."""
    
    def test_match_has_pending_resend_field(self, test_db):
        """Verifica que Match tem campo pending_resend."""
        match = Match(
            tinder_match_id="resend_model_001",
            name="Test Resend",
            pending_resend=False
        )
        test_db.add(match)
        test_db.commit()
        test_db.refresh(match)
        
        assert match.pending_resend == False
        assert match.resend_reason is None
        assert match.resend_at is None
    
    def test_match_pending_resend_defaults_to_false(self, test_db):
        """Verifica que pending_resend tem default False."""
        match = Match(tinder_match_id="resend_model_002", name="Test Default")
        test_db.add(match)
        test_db.commit()
        test_db.refresh(match)
        
        assert match.pending_resend == False
    
    def test_match_can_set_resend_fields(self, test_db):
        """Verifica que é possível setar todos os campos de reenvio."""
        now = datetime.utcnow()
        match = Match(
            tinder_match_id="resend_model_003",
            name="Test Set Fields",
            pending_resend=True,
            resend_reason="Mensagem cortada",
            resend_at=now
        )
        test_db.add(match)
        test_db.commit()
        test_db.refresh(match)
        
        assert match.pending_resend == True
        assert match.resend_reason == "Mensagem cortada"
        assert match.resend_at is not None


class TestResendRepository:
    """Testes para métodos de reenvio no MatchRepository."""
    
    def test_mark_for_resend(self, test_db, sample_match):
        """Testa marcação de match para reenvio."""
        repo = MatchRepository(test_db)
        
        repo.mark_for_resend(sample_match, reason="Mensagem incompleta")
        test_db.commit()
        test_db.refresh(sample_match)
        
        assert sample_match.pending_resend == True
        assert sample_match.resend_reason == "Mensagem incompleta"
        assert sample_match.resend_at is not None
    
    def test_mark_for_resend_default_reason(self, test_db, sample_match):
        """Testa marcação com motivo padrão."""
        repo = MatchRepository(test_db)
        
        repo.mark_for_resend(sample_match)
        test_db.commit()
        
        assert sample_match.resend_reason == "Mensagem incompleta"
    
    def test_clear_resend(self, test_db, sample_match):
        """Testa limpeza da flag de reenvio."""
        repo = MatchRepository(test_db)
        
        # Marcar e depois limpar
        repo.mark_for_resend(sample_match, reason="Teste")
        test_db.commit()
        
        repo.clear_resend(sample_match)
        test_db.commit()
        test_db.refresh(sample_match)
        
        assert sample_match.pending_resend == False
        assert sample_match.resend_reason is None
        assert sample_match.resend_at is None
    
    def test_get_matches_pending_resend(self, test_db):
        """Testa busca de matches com reenvio pendente."""
        repo = MatchRepository(test_db)
        
        # Criar matches: 1 com reenvio, 1 sem, 1 bloqueado com reenvio
        match_resend = Match(
            tinder_match_id="resend_001",
            name="Resend Match",
            pending_resend=True,
            resend_reason="Mensagem cortada"
        )
        match_normal = Match(
            tinder_match_id="normal_001",
            name="Normal Match",
            pending_resend=False
        )
        match_blocked_resend = Match(
            tinder_match_id="blocked_resend_001",
            name="Blocked Resend",
            pending_resend=True,
            is_blocked=True
        )
        test_db.add_all([match_resend, match_normal, match_blocked_resend])
        test_db.commit()
        
        results = repo.get_matches_pending_resend()
        
        # Apenas o match ativo com reenvio pendente
        assert len(results) == 1
        assert results[0].tinder_match_id == "resend_001"
    
    def test_count_pending_resend(self, test_db):
        """Testa contagem de matches pendentes de reenvio."""
        repo = MatchRepository(test_db)
        
        # Inicialmente zero
        assert repo.count_pending_resend() == 0
        
        # Adicionar 2 matches com reenvio pendente
        m1 = Match(tinder_match_id="count_001", name="M1", pending_resend=True)
        m2 = Match(tinder_match_id="count_002", name="M2", pending_resend=True)
        m3 = Match(tinder_match_id="count_003", name="M3", pending_resend=False)
        test_db.add_all([m1, m2, m3])
        test_db.commit()
        
        assert repo.count_pending_resend() == 2
    
    def test_pending_resend_filter_excludes_blocked(self, test_db):
        """Testa que filtro de reenvio exclui matches bloqueados."""
        match = Match(
            tinder_match_id="filter_001",
            name="Blocked",
            pending_resend=True,
            is_blocked=True
        )
        test_db.add(match)
        test_db.commit()
        
        results = test_db.query(Match).filter(pending_resend_filter()).all()
        assert len(results) == 0
    
    def test_pending_resend_filter_excludes_unmatched(self, test_db):
        """Testa que filtro de reenvio exclui matches com unmatch."""
        match = Match(
            tinder_match_id="filter_002",
            name="Unmatched",
            pending_resend=True,
            is_unmatched=True
        )
        test_db.add(match)
        test_db.commit()
        
        results = test_db.query(Match).filter(pending_resend_filter()).all()
        assert len(results) == 0
    
    def test_pending_resend_filter_includes_active(self, test_db):
        """Testa que filtro inclui matches ativos com reenvio."""
        match = Match(
            tinder_match_id="filter_003",
            name="Active Resend",
            pending_resend=True,
            is_blocked=False,
            is_unmatched=False
        )
        test_db.add(match)
        test_db.commit()
        
        results = test_db.query(Match).filter(pending_resend_filter()).all()
        assert len(results) == 1


class TestResendExecutionService:
    """Testes para resend_messages no ExecutionService."""
    
    @pytest.mark.asyncio
    async def test_resend_messages_no_pending(self):
        """Testa reenvio sem matches pendentes."""
        from automation.execution_service import ExecutionService
        
        mock_extractor = AsyncMock()
        
        with patch("automation.execution_service.get_db_manager") as mock_db:
            # Setup mock session
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from database.models import Base
            
            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            
            mock_db.return_value.get_session.return_value.__enter__ = MagicMock(return_value=session)
            mock_db.return_value.get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            service = ExecutionService(mock_extractor)
            service.db = mock_db.return_value
            
            result = await service.resend_messages(limit=5, dry_run=True)
            
            assert result["sent"] == 0
            assert result["errors"] == 0
            
            session.close()
    
    @pytest.mark.asyncio
    async def test_resend_messages_dry_run(self):
        """Testa reenvio em modo dry run."""
        from automation.execution_service import ExecutionService
        
        mock_extractor = AsyncMock()
        
        with patch("automation.execution_service.get_db_manager") as mock_db:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from database.models import Base
            
            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            
            # Criar match com reenvio pendente e mensagens
            match = Match(
                tinder_match_id="dry_resend_001",
                name="Dry Run Match",
                has_messages=True,
                first_message_sent=True,
                pending_resend=True,
                resend_reason="Mensagem cortada"
            )
            session.add(match)
            session.flush()
            
            msg = Message(
                match_id=match.id,
                content="Oi, tudo b",
                is_from_me=True,
                sent_at=datetime.utcnow()
            )
            session.add(msg)
            session.commit()
            
            mock_db.return_value.get_session.return_value.__enter__ = MagicMock(return_value=session)
            mock_db.return_value.get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            # Mock IA response
            mock_openai = MagicMock()
            mock_openai.analyze_conversation_and_respond.return_value = {
                "suggested_response": "bem? Sou o João, muito prazer!",
                "_metadata": {"model": "gpt-4o", "prompt_tokens": 100, "completion_tokens": 20, "response_time_ms": 500}
            }
            
            service = ExecutionService(mock_extractor)
            service.db = mock_db.return_value
            service.openai = mock_openai
            
            result = await service.resend_messages(limit=5, dry_run=True)
            
            assert result["sent"] == 1
            assert result["errors"] == 0
            assert result["details"][0]["dry_run"] == True
            assert result["details"][0]["resend"] == True
            
            # Verificar que mensagem foi registrada
            msgs = session.query(Message).filter(
                Message.match_id == match.id,
                Message.message_type == "resend_dry_run"
            ).all()
            assert len(msgs) == 1
            
            # Flag de reenvio deve ter sido limpa
            session.refresh(match)
            assert match.pending_resend == False
            
            session.close()


class TestResendWebAPI:
    """Testes para o endpoint de toggle de reenvio na API."""
    
    def test_toggle_resend_status(self, web_client):
        """Testa toggle de status de reenvio via API."""
        with patch("database.get_db_manager") as mock_db:
            mock_session = MagicMock()
            mock_match = MagicMock()
            mock_match.id = 1
            mock_match.name = "Test"
            mock_match.pending_resend = False
            mock_match.is_blocked = False
            mock_match.is_unmatched = False
            
            mock_repo = MagicMock()
            mock_repo.get_by_id.return_value = mock_match
            
            mock_session.query.return_value.filter.return_value.first.return_value = mock_match
            mock_db.return_value.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db.return_value.get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            with patch("web.app.MatchRepository", return_value=mock_repo):
                response = web_client.post(
                    "/api/matches/1/status",
                    json={"status_type": "resend", "reason": "Mensagem cortada"}
                )
            
            # Verificar que não deu erro 500
            assert response.status_code in [200, 404, 400]
