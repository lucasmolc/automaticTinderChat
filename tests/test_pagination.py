"""
Testes para o sistema de cursor-based pagination.

Testa funcionalidades de:
- Encoding e decoding de cursores
- Criação de cursor a partir de items
- Construção de resposta paginada
- Tratamento de cursores inválidos
"""

from datetime import datetime

import pytest


class TestCursorPaginationEncoding:
    """Testes para encoding/decoding de cursores."""
    
    def test_encode_cursor_returns_string(self):
        """Testa que encode_cursor retorna string."""
        from utils.pagination import CursorPagination
        
        data = {"id": 123, "timestamp": datetime(2024, 1, 15, 10, 30)}
        cursor = CursorPagination.encode_cursor(data)
        
        assert isinstance(cursor, str)
        assert len(cursor) > 0
    
    def test_decode_cursor_recovers_original_data(self):
        """Testa que decode recupera dados originais."""
        from utils.pagination import CursorPagination
        
        original_data = {"id": 123, "timestamp": datetime(2024, 1, 15, 10, 30)}
        
        cursor = CursorPagination.encode_cursor(original_data)
        decoded = CursorPagination.decode_cursor(cursor)
        
        assert decoded is not None
        assert decoded['id'] == original_data['id']
        # Timestamp pode ser string ou datetime após decode
        timestamp = decoded['timestamp']
        if isinstance(timestamp, str):
            from datetime import datetime as dt
            timestamp = dt.fromisoformat(timestamp)
        assert timestamp.year == 2024
        assert timestamp.month == 1
        assert timestamp.day == 15
    
    def test_decode_invalid_cursor_returns_none(self):
        """Testa que cursor inválido retorna None."""
        from utils.pagination import CursorPagination
        
        result = CursorPagination.decode_cursor("invalid_cursor_string")
        
        assert result is None
    
    def test_decode_none_cursor_handles_gracefully(self):
        """Testa que cursor None é tratado."""
        from utils.pagination import CursorPagination
        
        try:
            result = CursorPagination.decode_cursor(None)
            assert result is None
        except (TypeError, AttributeError):
            pass  # Comportamento aceitável


class TestCursorPaginationFromItem:
    """Testes para criação de cursor a partir de item."""
    
    def test_create_cursor_from_dict_item(self):
        """Testa criação de cursor a partir de dicionário."""
        from utils.pagination import CursorPagination
        
        item = {"id": 42, "created_at": datetime(2024, 1, 15)}
        cursor = CursorPagination.create_cursor_from_item(item)
        
        assert isinstance(cursor, str)
        
        decoded = CursorPagination.decode_cursor(cursor)
        assert decoded['id'] == 42


class TestCursorPaginateResponse:
    """Testes para função cursor_paginate_response."""
    
    def test_builds_response_with_pagination_info(self):
        """Testa construção de resposta com info de paginação."""
        from utils.pagination import cursor_paginate_response
        
        items = [
            {"id": 1, "created_at": "2024-01-15T10:00:00"},
            {"id": 2, "created_at": "2024-01-15T11:00:00"},
        ]
        
        response = cursor_paginate_response(
            items=items,
            next_cursor="test_cursor",
            has_more=True
        )
        
        assert 'data' in response
        assert 'pagination' in response
        assert response['pagination']['next_cursor'] == "test_cursor"
        assert response['pagination']['has_more'] is True
    
    def test_has_more_true_when_more_pages_exist(self):
        """Testa has_more=True quando há mais páginas."""
        from utils.pagination import cursor_paginate_response
        
        items = [{"id": i} for i in range(5)]
        
        response = cursor_paginate_response(
            items=items,
            next_cursor="next",
            has_more=True
        )
        
        assert response['pagination']['has_more'] is True
    
    def test_has_more_false_when_no_more_pages(self):
        """Testa has_more=False quando não há mais páginas."""
        from utils.pagination import cursor_paginate_response
        
        items = [{"id": i} for i in range(3)]
        
        response = cursor_paginate_response(
            items=items,
            next_cursor=None,
            has_more=False
        )
        
        assert response['pagination']['has_more'] is False
        assert response['pagination']['next_cursor'] is None
