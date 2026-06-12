"""
Testes de segurança para a aplicação.
Verifica sanitização de inputs e proteções contra ataques.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.input_sanitizer import (
    sanitize_search_input,
    sanitize_integer,
    sanitize_boolean,
    sanitize_sort_field,
    sanitize_pagination,
    validate_match_id
)


class TestSearchInputSanitization:
    """Testes para sanitização de busca."""
    
    def test_removes_sql_wildcards(self):
        """Testa remoção de wildcards SQL."""
        assert sanitize_search_input('%admin%') == 'admin'
        assert sanitize_search_input('test_user') == 'testuser'
        assert sanitize_search_input('%%_%_%%') == ''
    
    def test_limits_length(self):
        """Testa limite de tamanho."""
        long_input = 'a' * 500
        result = sanitize_search_input(long_input, max_length=100)
        assert len(result) == 100
    
    def test_removes_control_characters(self):
        """Testa remoção de caracteres de controle."""
        assert sanitize_search_input('test\x00null') == 'testnull'
        assert sanitize_search_input('hello\x1fworld') == 'helloworld'
    
    def test_strips_whitespace(self):
        """Testa remoção de espaços extras."""
        assert sanitize_search_input('  test  ') == 'test'
    
    def test_handles_empty_input(self):
        """Testa input vazio."""
        assert sanitize_search_input('') == ''
        assert sanitize_search_input(None) == ''
    
    def test_unicode_preserved(self):
        """Testa que unicode válido é preservado."""
        assert sanitize_search_input('José') == 'José'
        assert sanitize_search_input('名前') == '名前'


class TestIntegerSanitization:
    """Testes para sanitização de inteiros."""
    
    def test_valid_integer(self):
        """Testa inteiro válido."""
        assert sanitize_integer('42') == 42
        assert sanitize_integer(42) == 42
    
    def test_invalid_returns_default(self):
        """Testa retorno de default para inválido."""
        assert sanitize_integer('abc', default=10) == 10
        assert sanitize_integer(None, default=5) == 5
    
    def test_respects_min_value(self):
        """Testa valor mínimo."""
        assert sanitize_integer(-10, min_value=0) == 0
        assert sanitize_integer('5', min_value=10) == 10
    
    def test_respects_max_value(self):
        """Testa valor máximo."""
        assert sanitize_integer(1000, max_value=100) == 100
        assert sanitize_integer('500', max_value=50) == 50
    
    def test_min_max_combined(self):
        """Testa min e max juntos."""
        assert sanitize_integer(5, min_value=1, max_value=10) == 5
        assert sanitize_integer(-5, min_value=1, max_value=10) == 1
        assert sanitize_integer(50, min_value=1, max_value=10) == 10


class TestBooleanSanitization:
    """Testes para sanitização de booleanos."""
    
    def test_string_true_values(self):
        """Testa valores string que devem ser True."""
        assert sanitize_boolean('true') == True
        assert sanitize_boolean('True') == True
        assert sanitize_boolean('1') == True
        assert sanitize_boolean('yes') == True
        assert sanitize_boolean('sim') == True
    
    def test_string_false_values(self):
        """Testa valores string que devem ser False."""
        assert sanitize_boolean('false') == False
        assert sanitize_boolean('0') == False
        assert sanitize_boolean('no') == False
        assert sanitize_boolean('nao') == False
    
    def test_none_returns_default(self):
        """Testa None retorna default."""
        assert sanitize_boolean(None) == False
        assert sanitize_boolean(None, default=True) == True
    
    def test_actual_booleans(self):
        """Testa booleanos reais."""
        assert sanitize_boolean(True) == True
        assert sanitize_boolean(False) == False


class TestSortFieldValidation:
    """Testes para validação de campo de ordenação."""
    
    def test_allowed_field(self):
        """Testa campo permitido."""
        allowed = ['name', 'created_at', 'score']
        assert sanitize_sort_field('name', allowed) == 'name'
        assert sanitize_sort_field('CREATED_AT', allowed) == 'created_at'
    
    def test_disallowed_field(self):
        """Testa campo não permitido."""
        allowed = ['name', 'created_at']
        assert sanitize_sort_field('password', allowed, default='name') == 'name'
        assert sanitize_sort_field('; DROP TABLE users;', allowed) == None
    
    def test_empty_input(self):
        """Testa input vazio."""
        assert sanitize_sort_field('', ['name'], default='name') == 'name'
        assert sanitize_sort_field(None, ['name']) == None


class TestPaginationValidation:
    """Testes para validação de paginação."""
    
    def test_valid_pagination(self):
        """Testa paginação válida."""
        page, per_page, offset = sanitize_pagination(page=2, per_page=20)
        assert page == 2
        assert per_page == 20
        assert offset == 20
    
    def test_negative_page(self):
        """Testa página negativa."""
        page, per_page, offset = sanitize_pagination(page=-5)
        assert page == 1
    
    def test_exceeds_max_per_page(self):
        """Testa limite de itens por página."""
        page, per_page, offset = sanitize_pagination(per_page=1000, max_per_page=100)
        assert per_page == 100
    
    def test_string_inputs(self):
        """Testa inputs string."""
        page, per_page, offset = sanitize_pagination(page='3', per_page='25')
        assert page == 3
        assert per_page == 25
        assert offset == 50


class TestMatchIdValidation:
    """Testes para validação de Match ID."""
    
    def test_valid_match_id(self):
        """Testa ID válido."""
        assert validate_match_id('abc123') == 'abc123'
        assert validate_match_id('a1b2c3d4e5f6') == 'a1b2c3d4e5f6'
    
    def test_invalid_characters(self):
        """Testa caracteres inválidos."""
        assert validate_match_id('abc;DROP TABLE') == None
        assert validate_match_id('id<script>') == None
        assert validate_match_id("id' OR '1'='1") == None
    
    def test_too_long(self):
        """Testa ID muito longo."""
        assert validate_match_id('a' * 200) == None
    
    def test_empty(self):
        """Testa ID vazio."""
        assert validate_match_id('') == None
        assert validate_match_id(None) == None


class TestAPISecurityIntegration:
    """Testes de integração de segurança da API."""
    
    @pytest.fixture
    def client(self):
        """Fixture do cliente de teste Flask."""
        from web.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_search_with_wildcards_safe(self, client):
        """Testa que busca com wildcards não quebra."""
        response = client.get('/api/matches?search=%25%25%25%25%25')
        assert response.status_code == 200
    
    def test_pagination_with_huge_values(self, client):
        """Testa paginação com valores enormes."""
        response = client.get('/api/matches?limit=999999&offset=999999')
        assert response.status_code == 200
    
    def test_invalid_sort_field_rejected(self, client):
        """Testa que campo de ordenação inválido é ignorado."""
        response = client.get('/api/matches?sort=; DROP TABLE matches;')
        assert response.status_code == 200
    
    def test_special_characters_in_search(self, client):
        """Testa caracteres especiais na busca."""
        response = client.get('/api/matches?search=<script>alert(1)</script>')
        assert response.status_code == 200


class TestRateLimiting:
    """Testes para rate limiting."""
    
    @pytest.fixture
    def client(self):
        """Fixture do cliente de teste."""
        from web.app import app
        app.config['TESTING'] = True
        # Desabilitar rate limiting em testes
        with app.test_client() as client:
            yield client
    
    def test_automation_endpoint_exists(self, client):
        """Testa que endpoint de automação existe."""
        response = client.post('/api/automation/run')
        # Pode ser 200 ou 400 (automação já rodando), mas não 404
        assert response.status_code in [200, 400]
    
    def test_stop_endpoint_exists(self, client):
        """Testa que endpoint de parada existe."""
        response = client.post('/api/automation/stop')
        assert response.status_code == 200
