"""
Cursor-Based Pagination - Paginação eficiente para grandes datasets.
Substitui offset-based pagination que tem performance O(n) para O(1).
"""

import base64
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from utils.logger import get_logger

logger = get_logger(__name__)


class CursorPagination:
    """
    Implementação de cursor-based pagination.
    
    Benefícios sobre offset pagination:
    - Performance constante O(1) vs O(n) do offset
    - Não pula/repete itens quando dados mudam
    - Melhor para datasets grandes
    
    Uso:
        # Primeira página (sem cursor)
        items, next_cursor, has_more = paginator.paginate(query, limit=50)
        
        # Próxima página
        items, next_cursor, has_more = paginator.paginate(query, limit=50, cursor=next_cursor)
    """
    
    @staticmethod
    def encode_cursor(data: Dict[str, Any]) -> str:
        """
        Codifica dados do cursor em string base64.
        
        Args:
            data: Dict com id e timestamp do último item
            
        Returns:
            Cursor encoded como string
        """
        # Converter datetime para ISO string se presente
        if 'timestamp' in data and isinstance(data['timestamp'], datetime):
            data['timestamp'] = data['timestamp'].isoformat()
        
        json_str = json.dumps(data, sort_keys=True)
        return base64.urlsafe_b64encode(json_str.encode()).decode()
    
    @staticmethod
    def decode_cursor(cursor: str) -> Optional[Dict[str, Any]]:
        """
        Decodifica cursor de string base64.
        
        Args:
            cursor: String do cursor encoded
            
        Returns:
            Dict com dados do cursor ou None se inválido
        """
        try:
            json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
            data = json.loads(json_str)
            
            # Converter ISO string de volta para datetime se presente
            if 'timestamp' in data and isinstance(data['timestamp'], str):
                data['timestamp'] = datetime.fromisoformat(data['timestamp'])
            
            return data
        except Exception as e:
            logger.warning(f"Cursor inválido: {e}")
            return None
    
    @staticmethod
    def create_cursor_from_item(item, id_field: str = 'id', timestamp_field: str = 'created_at') -> str:
        """
        Cria cursor a partir de um item (Model ou Dict).
        
        Args:
            item: Objeto ou dict do último item
            id_field: Nome do campo de ID
            timestamp_field: Nome do campo de timestamp
            
        Returns:
            Cursor encoded
        """
        if hasattr(item, id_field):
            item_id = getattr(item, id_field)
            timestamp = getattr(item, timestamp_field, None)
        else:
            item_id = item.get(id_field)
            timestamp = item.get(timestamp_field)
        
        return CursorPagination.encode_cursor({
            'id': item_id,
            'timestamp': timestamp
        })


def apply_cursor_pagination(
    query,
    model,
    cursor: Optional[str] = None,
    limit: int = 50,
    order_by_field: str = 'created_at',
    order_desc: bool = True,
    id_field: str = 'id'
) -> Tuple[List, Optional[str], bool]:
    """
    Aplica cursor pagination a uma query SQLAlchemy.
    
    Args:
        query: Query SQLAlchemy base
        model: Classe do modelo (ex: Match)
        cursor: Cursor da página anterior (None para primeira página)
        limit: Número de itens por página
        order_by_field: Campo para ordenação
        order_desc: Se True, ordena DESC
        id_field: Campo de ID único
        
    Returns:
        Tuple (items, next_cursor, has_more)
    """
    from sqlalchemy import desc, asc, and_, or_
    
    order_field = getattr(model, order_by_field)
    id_attr = getattr(model, id_field)
    
    # Aplicar ordenação
    if order_desc:
        query = query.order_by(desc(order_field), desc(id_attr))
    else:
        query = query.order_by(asc(order_field), asc(id_attr))
    
    # Aplicar filtro do cursor se fornecido
    if cursor:
        cursor_data = CursorPagination.decode_cursor(cursor)
        if cursor_data:
            cursor_timestamp = cursor_data.get('timestamp')
            cursor_id = cursor_data.get('id')
            
            if cursor_timestamp and cursor_id:
                # Filtrar itens após o cursor
                # Para DESC: itens com timestamp menor OU (timestamp igual E id menor)
                if order_desc:
                    query = query.filter(
                        or_(
                            order_field < cursor_timestamp,
                            and_(order_field == cursor_timestamp, id_attr < cursor_id)
                        )
                    )
                else:
                    query = query.filter(
                        or_(
                            order_field > cursor_timestamp,
                            and_(order_field == cursor_timestamp, id_attr > cursor_id)
                        )
                    )
    
    # Buscar limite + 1 para verificar se há mais itens
    items = query.limit(limit + 1).all()
    
    # Verificar se há próxima página
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]  # Remover item extra
    
    # Gerar cursor para próxima página
    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = CursorPagination.create_cursor_from_item(
            last_item,
            id_field=id_field,
            timestamp_field=order_by_field
        )
    
    return items, next_cursor, has_more


def cursor_paginate_response(
    items: List,
    next_cursor: Optional[str],
    has_more: bool,
    total: Optional[int] = None
) -> Dict:
    """
    Formata resposta de paginação cursor-based.
    
    Args:
        items: Lista de itens
        next_cursor: Cursor para próxima página
        has_more: Se há mais itens
        total: Total de itens (opcional, pode ser caro de calcular)
        
    Returns:
        Dict formatado para resposta JSON
    """
    response = {
        'data': items,
        'pagination': {
            'next_cursor': next_cursor,
            'has_more': has_more,
            'count': len(items)
        }
    }
    
    if total is not None:
        response['pagination']['total'] = total
    
    return response


# ===================== EXEMPLO DE USO =====================
"""
Exemplo de uso no web/app.py:

from utils.pagination import apply_cursor_pagination, cursor_paginate_response

@app.route('/api/matches/cursor')
def api_matches_cursor():
    cursor = request.args.get('cursor')
    limit = min(int(request.args.get('limit', 50)), 100)
    
    with db.get_session() as session:
        query = session.query(Match).filter(Match.is_blocked == False)
        
        items, next_cursor, has_more = apply_cursor_pagination(
            query,
            Match,
            cursor=cursor,
            limit=limit,
            order_by_field='matched_at',
            order_desc=True
        )
        
        # Serializar items...
        
        return jsonify(cursor_paginate_response(
            items=serialized_items,
            next_cursor=next_cursor,
            has_more=has_more
        ))
"""
