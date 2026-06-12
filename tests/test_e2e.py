"""
Testes End-to-End (E2E) do Sistema
==================================

Testes que validam fluxos completos da aplicação:
- Fluxos via API Web
- Ciclo de vida de matches (sincronização, mensagens, WhatsApp)
- Filtros e validações
- Busca de dados (banco vs tela)
- Cache de perfis
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta


class TestE2EWebPages:
    """Testes E2E das páginas web."""
    
    @pytest.fixture
    def client(self):
        """Fixture do cliente Flask."""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_all_pages_load_successfully(self, client):
        """Testa que todas as páginas carregam sem erro."""
        pages = [
            ('/', 'Dashboard'),
            ('/matches', 'Matches'),
            ('/messages', 'Mensagens'),
            ('/analytics', 'Analytics'),
            ('/control', 'Controle'),
        ]
        
        for url, name in pages:
            response = client.get(url)
            assert response.status_code == 200, f"Página {name} ({url}) não carregou"


class TestE2EAPIFlow:
    """Testes E2E da integração da API."""
    
    @pytest.fixture
    def client(self):
        """Fixture do cliente Flask."""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_dashboard_data_flow(self, client):
        """Testa fluxo de dados do dashboard."""
        # Stats
        response = client.get('/api/stats')
        assert response.status_code == 200
        stats = response.get_json()
        # Stats pode estar em 'data' ou diretamente no response
        data = stats.get('data', stats)
        assert 'total_matches' in data
        
        # Timeline
        response = client.get('/api/analytics/timeline')
        assert response.status_code == 200
    
    def test_automation_control_flow(self, client):
        """Testa fluxo de controle da automação."""
        # Resetar estado para teste limpo
        from automation.state_manager import get_state_manager
        state_manager = get_state_manager()
        state_manager.finish()
        
        # Status
        response = client.get('/api/automation/status')
        assert response.status_code == 200
        
        # Logs
        response = client.get('/api/automation/logs')
        assert response.status_code == 200
        
        # Stop (agora retorna 400 se não estiver rodando)
        response = client.post('/api/automation/stop')
        # Aceita 200 (parou) ou 400 (não estava rodando)
        assert response.status_code in [200, 400]
    
    def test_notifications_flow(self, client):
        """Testa fluxo de notificações."""
        # Contagem
        response = client.get('/api/notifications/count')
        assert response.status_code == 200
        
        # Lista
        response = client.get('/api/notifications')
        assert response.status_code == 200
        
        # Marcar lidas
        response = client.post('/api/notifications/read-all')
        assert response.status_code == 200
    
    def test_health_checks(self, client):
        """Testa endpoints de health check."""
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data.get('status') == 'healthy'


class TestE2ESecurityFlow:
    """Testes E2E de segurança."""
    
    @pytest.fixture
    def client(self):
        """Fixture do cliente Flask."""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_malicious_inputs_handled(self, client):
        """Testa que inputs maliciosos são tratados."""
        payloads = [
            "'; DROP TABLE matches; --",
            "<script>alert('xss')</script>",
        ]
        
        for payload in payloads:
            response = client.get(f'/api/matches?search={payload}')
            # Não deve causar erro 500
            assert response.status_code != 500
    
    def test_invalid_match_id_handled(self, client):
        """Testa que ID inválido é tratado."""
        response = client.get('/api/matches/99999999')
        assert response.status_code in [404, 200]


class TestE2EMatchesAPI:
    """Testes E2E da API de matches."""
    
    @pytest.fixture
    def client(self):
        """Fixture do cliente Flask."""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_list_matches_with_filters(self, client):
        """Testa listagem com diferentes filtros."""
        filters = ['all', 'no_messages', 'awaiting_response', 'blocked']
        
        for f in filters:
            response = client.get(f'/api/matches?filter={f}')
            assert response.status_code == 200
    
    def test_list_matches_with_pagination(self, client):
        """Testa paginação."""
        response = client.get('/api/matches?limit=10&offset=0')
        assert response.status_code == 200
    
    def test_blocked_matches_endpoint(self, client):
        """Testa endpoint de matches bloqueados."""
        response = client.get('/api/matches/blocked')
        assert response.status_code == 200


class TestE2EAutomationFlow:
    """Testes E2E dos fluxos de automação."""
    
    @pytest.fixture
    def client(self):
        """Fixture do cliente Flask."""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_sync_matches_endpoint(self, client):
        """Testa endpoint de sincronização."""
        # Primeiro garantir que a automação não está rodando (resetar estado)
        from automation.state_manager import get_state_manager
        state_manager = get_state_manager()
        state_manager.finish()  # Resetar estado para teste limpo
        
        # O endpoint pode iniciar um processo assíncrono
        response = client.post('/api/automation/sync')
        # Aceita 200 (sucesso), 400 (já em execução/erro), ou 409 (conflito)
        assert response.status_code in [200, 400, 409]
    
    def test_automation_start_stop_flow(self, client):
        """Testa fluxo completo de start/stop."""
        # Resetar estado para teste limpo
        from automation.state_manager import get_state_manager
        state_manager = get_state_manager()
        state_manager.finish()
        
        # 1. Verificar status inicial
        response = client.get('/api/automation/status')
        assert response.status_code == 200
        
        # 2. Tentar parar (agora retorna 400 se não estiver rodando)
        response = client.post('/api/automation/stop')
        # Aceita 200 (parou) ou 400 (não estava rodando)
        assert response.status_code in [200, 400]
        
        # 3. Verificar status após parar
        response = client.get('/api/automation/status')
        assert response.status_code == 200


class TestE2EAnalyticsAPI:
    """Testes E2E da API de analytics."""
    
    @pytest.fixture
    def client(self):
        """Fixture do cliente Flask."""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_analytics_timeline(self, client):
        """Testa timeline de analytics."""
        response = client.get('/api/analytics/timeline')
        assert response.status_code == 200
        data = response.get_json()
        assert 'data' in data or 'success' in data
    
    def test_analytics_stats(self, client):
        """Testa estatísticas gerais."""
        response = client.get('/api/stats')
        assert response.status_code == 200
    
    def test_analytics_funnel(self, client):
        """Testa dados do funil."""
        response = client.get('/api/analytics/funnel')
        # Pode não existir, aceita 200 ou 404
        assert response.status_code in [200, 404]


# ===================== TESTES E2E DE CICLO DE VIDA =====================

class TestE2EMatchLifecycle:
    """Testes E2E do ciclo de vida completo de um match."""
    
    @pytest.fixture
    def test_db(self):
        """Cria banco de dados SQLite em memória para testes."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from database.models import Base
        
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        yield session
        
        session.close()
        Base.metadata.drop_all(engine)
    
    def test_full_match_lifecycle_from_sync_to_whatsapp(self, test_db):
        """
        Testa ciclo completo:
        1. Match é sincronizado
        2. Primeira mensagem é enviada
        3. Match responde
        4. Bot responde
        5. WhatsApp é detectado
        """
        from database.models import Match, Message
        from database.repositories import MatchRepository, MessageRepository
        
        match_repo = MatchRepository(test_db)
        msg_repo = MessageRepository(test_db)
        
        # 1. SYNC: Match é criado
        match, created = match_repo.get_or_create(
            "lifecycle_001",
            name="Ana"
        )
        match_repo.update(match, age=26, bio="Amo viajar e conhecer pessoas")
        test_db.commit()
        
        assert created == True
        assert match.has_messages == False
        
        # 2. PRIMEIRA MSG: Bot envia mensagem
        msg_repo.create(
            match_id=match.id,
            content="Oi Ana! Vi que você gosta de viajar, qual foi a última viagem?",
            is_from_me=True,
            ai_generated=True
        )
        match_repo.update(
            match,
            has_messages=True,
            first_message_sent=True,
            last_message_at=datetime.utcnow(),
            last_interaction_at=datetime.utcnow()
        )
        test_db.commit()
        
        test_db.refresh(match)
        assert match.has_messages == True
        assert match.first_message_sent == True
        
        # 3. RESPOSTA: Match responde
        msg_repo.create(
            match_id=match.id,
            content="Oii! Fui pra Portugal mês passado, foi incrível!",
            is_from_me=False
        )
        match_repo.update(
            match,
            awaiting_my_response=True,
            last_message_text="Oii! Fui pra Portugal mês passado, foi incrível!",
            last_interaction_at=datetime.utcnow()
        )
        test_db.commit()
        
        test_db.refresh(match)
        assert match.awaiting_my_response == True
        
        # 4. BOT RESPONDE: Conversa continua
        msg_repo.create(
            match_id=match.id,
            content="Que legal! Portugal é lindo. O que mais gostou por lá?",
            is_from_me=True,
            ai_generated=True
        )
        match_repo.update(
            match,
            awaiting_my_response=False,
            last_interaction_at=datetime.utcnow()
        )
        test_db.commit()
        
        # 5. WHATSAPP: Match envia número
        msg_repo.create(
            match_id=match.id,
            content="Amei Porto! Me adiciona no whats: 11999887766",
            is_from_me=False
        )
        match_repo.update_whatsapp(match, "11999887766")
        test_db.commit()
        
        test_db.refresh(match)
        assert match.whatsapp_obtained == True
        assert match.whatsapp_number == "11999887766"
        
        # Verificar que match não será mais processado
        from database.repositories import active_match_filter
        active_count = test_db.query(Match).filter(
            Match.id == match.id,
            active_match_filter()
        ).count()
        
        assert active_count == 0
    
    def test_match_blocked_for_inactivity(self, test_db):
        """Testa bloqueio automático por inatividade."""
        from database.models import Match
        from database.repositories import MatchRepository
        
        match_repo = MatchRepository(test_db)
        
        # Criar match antigo
        match, _ = match_repo.get_or_create("inactive_001", name="Maria")
        match_repo.update(
            match,
            has_messages=True,
            awaiting_my_response=True,
            last_interaction_at=datetime.utcnow() - timedelta(days=400)
        )
        test_db.commit()
        
        # Simular verificação de inatividade
        from automation.match_helpers import MatchValidator
        settings = MagicMock()
        settings.days_without_interaction = 365
        
        validator = MatchValidator(settings)
        should_block, days = validator.should_block_for_inactivity(match)
        
        assert should_block == True
        assert days >= 400
        
        # Bloquear match
        if should_block:
            match_repo.block_match(match, f"Inatividade prolongada ({days} dias)")
            test_db.commit()
        
        test_db.refresh(match)
        assert match.is_blocked == True
        assert "inatividade" in match.blocked_reason.lower()
    
    def test_new_match_not_blocked_without_date(self, test_db):
        """Testa que match novo (sem last_interaction_at) não é bloqueado."""
        from database.repositories import MatchRepository
        from automation.match_helpers import MatchValidator
        
        match_repo = MatchRepository(test_db)
        
        match, _ = match_repo.get_or_create("new_001", name="Julia")
        test_db.commit()
        
        settings = MagicMock()
        settings.days_without_interaction = 365
        
        validator = MatchValidator(settings)
        should_skip, reason = validator.should_skip_match(match)
        
        assert should_skip == False


class TestE2EConversationFlow:
    """Testes E2E de fluxo de conversação."""
    
    @pytest.fixture
    def test_db(self):
        """Cria banco de dados SQLite em memória."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from database.models import Base
        
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        yield session
        
        session.close()
        Base.metadata.drop_all(engine)
    
    def test_message_sync_replaces_old_messages(self, test_db):
        """Testa que sync de mensagens substitui mensagens antigas."""
        from database.models import Match, Message
        from database.repositories import MatchRepository, MessageRepository
        
        match_repo = MatchRepository(test_db)
        msg_repo = MessageRepository(test_db)
        
        match, _ = match_repo.get_or_create("sync_msg_001", name="Carla")
        msg_repo.create(match_id=match.id, content="Msg antiga 1", is_from_me=True)
        msg_repo.create(match_id=match.id, content="Msg antiga 2", is_from_me=False)
        test_db.commit()
        
        initial_count = msg_repo.count_messages_for_match(match.id)
        assert initial_count == 2
        
        # Simular sync
        test_db.query(Message).filter(Message.match_id == match.id).delete()
        
        new_messages = [
            {"content": "Nova msg 1", "is_from_me": True},
            {"content": "Nova msg 2", "is_from_me": False},
            {"content": "Nova msg 3", "is_from_me": True},
            {"content": "Nova msg 4", "is_from_me": False},
        ]
        
        for msg in new_messages:
            msg_repo.create(match_id=match.id, **msg)
        test_db.commit()
        
        final_count = msg_repo.count_messages_for_match(match.id)
        assert final_count == 4
        
        messages = msg_repo.get_messages_for_match(match.id, limit=10)
        contents = [m.content for m in messages]
        
        assert "Nova msg 1" in contents
        assert "Msg antiga 1" not in contents


class TestE2EMatchFilters:
    """Testes E2E dos filtros de match."""
    
    @pytest.fixture
    def test_db(self):
        """Cria banco de dados SQLite em memória."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from database.models import Base
        
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)
        
        Session = sessionmaker(bind=engine)
        session = Session()
        
        yield session
        
        session.close()
        Base.metadata.drop_all(engine)
    
    def test_filter_pending_first_message(self, test_db):
        """Testa filtro de matches aguardando primeira mensagem."""
        from database.repositories import MatchRepository
        
        match_repo = MatchRepository(test_db)
        
        m1, _ = match_repo.get_or_create("pending_001", name="Ana")
        match_repo.update(m1, has_messages=False, first_message_sent=False)
        
        m2, _ = match_repo.get_or_create("sent_001", name="Maria")
        match_repo.update(m2, has_messages=True, first_message_sent=True)
        
        m3, _ = match_repo.get_or_create("blocked_001", name="Julia")
        match_repo.update(m3, has_messages=False, first_message_sent=False, is_blocked=True)
        
        test_db.commit()
        
        pending = match_repo.get_matches_without_messages()
        
        assert len(pending) == 1
        assert pending[0].name == "Ana"
    
    def test_filter_awaiting_response(self, test_db):
        """Testa filtro de matches aguardando minha resposta."""
        from database.repositories import MatchRepository
        
        match_repo = MatchRepository(test_db)
        
        m1, _ = match_repo.get_or_create("awaiting_001", name="Ana")
        match_repo.update(m1, awaiting_my_response=True)
        
        m2, _ = match_repo.get_or_create("notwait_001", name="Maria")
        match_repo.update(m2, awaiting_my_response=False)
        
        m3, _ = match_repo.get_or_create("whats_001", name="Julia")
        match_repo.update(m3, awaiting_my_response=True, whatsapp_obtained=True)
        
        test_db.commit()
        
        awaiting = match_repo.get_matches_awaiting_my_response()
        
        assert len(awaiting) == 1
        assert awaiting[0].name == "Ana"


class TestE2EDataFetching:
    """Testes E2E de busca de dados (banco vs tela)."""
    
    @pytest.mark.asyncio
    async def test_data_fetcher_uses_db_when_complete(self):
        """Testa que dados completos do banco são usados sem buscar tela."""
        from automation.match_helpers import MatchDataFetcher
        
        match = MagicMock()
        match.name = "Ana"
        match.age = 25
        match.bio = "Amo viajar"
        match.job_title = "Desenvolvedora"
        match.distance_km = 5
        match.school = None
        match.gender = "F"
        match.city = "São Paulo"
        match.relationship_intent = None
        match.sexual_orientations = None
        match.photos_count = 3
        match.is_verified = True
        
        mock_repo = MagicMock()
        mock_repo.get_interests.return_value = ['viagens']
        
        mock_extractor = AsyncMock()
        mock_extractor.extract_match_profile = AsyncMock()
        
        my_profile = {'name': 'João', 'interests': ['viagens', 'música']}
        
        fetcher = MatchDataFetcher(mock_repo, mock_extractor, my_profile)
        
        profile, was_unmatched = await fetcher.get_match_data_for_ai(match)
        
        assert profile['name'] == 'Ana'
        assert profile['bio'] == 'Amo viajar'
        assert was_unmatched == False
        
        mock_extractor.extract_match_profile.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_data_fetcher_calls_screen_when_incomplete(self):
        """Testa que dados incompletos buscam na tela."""
        from automation.match_helpers import MatchDataFetcher
        
        match = MagicMock()
        match.name = "Ana"
        match.age = None
        match.bio = None
        match.job_title = None
        match.distance_km = None
        match.school = None
        match.gender = None
        match.city = None
        match.relationship_intent = None
        match.sexual_orientations = None
        match.photos_count = 0
        match.is_verified = False
        match.tinder_match_id = "test_123"
        
        mock_repo = MagicMock()
        mock_repo.get_interests.return_value = []
        mock_repo.update_from_profile.return_value = {'bio': 'Nova bio'}
        
        mock_extractor = AsyncMock()
        mock_extractor.extract_match_profile = AsyncMock(return_value={
            'name': 'Ana',
            'age': 25,
            'bio': 'Bio da tela',
            'job_title': 'Designer',
            'interests': ['arte']
        })
        
        my_profile = {'name': 'João', 'interests': ['arte', 'música']}
        
        fetcher = MatchDataFetcher(mock_repo, mock_extractor, my_profile)
        
        profile, was_unmatched = await fetcher.get_match_data_for_ai(match)
        
        assert profile['bio'] == 'Bio da tela'
        assert profile['job_title'] == 'Designer'
        assert was_unmatched == False
        
        mock_extractor.extract_match_profile.assert_called_once_with("test_123")


class TestE2EProfileCache:
    """Testes E2E do cache de perfis."""
    
    def test_cache_reduces_db_calls(self):
        """Testa que cache evita chamadas repetidas."""
        from automation.match_helpers import ProfileCache
        
        cache = ProfileCache(ttl_seconds=60)
        
        db_calls = 0
        
        def fetch_profile(profile_id):
            nonlocal db_calls
            
            cached = cache.get(profile_id)
            if cached:
                return cached
            
            db_calls += 1
            profile = {'id': profile_id, 'name': f'User {profile_id}'}
            
            cache.set(profile_id, profile)
            
            return profile
        
        result1 = fetch_profile('user_001')
        assert db_calls == 1
        
        result2 = fetch_profile('user_001')
        assert db_calls == 1
        
        result3 = fetch_profile('user_002')
        assert db_calls == 2
        
        result4 = fetch_profile('user_001')
        assert db_calls == 2