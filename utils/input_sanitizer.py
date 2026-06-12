"""
Sanitização e validação de inputs.
Protege contra injeção e ataques de DoS.
"""

import re
from typing import Optional


def sanitize_search_input(
    value: str, 
    max_length: int = 100,
    remove_wildcards: bool = True
) -> str:
    """
    Sanitiza input de busca para prevenir DoS via wildcards.
    
    Args:
        value: Valor a ser sanitizado
        max_length: Tamanho máximo permitido
        remove_wildcards: Se deve remover % e _
        
    Returns:
        String sanitizada
    """
    if not value:
        return ""
    
    # Limitar tamanho
    value = str(value)[:max_length]
    
    # Remover wildcards SQL se solicitado
    if remove_wildcards:
        value = value.replace('%', '').replace('_', '')
    
    # Remover caracteres de controle
    value = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
    
    # Strip whitespace
    value = value.strip()
    
    return value


def sanitize_integer(
    value, 
    default: int = 0, 
    min_value: Optional[int] = None, 
    max_value: Optional[int] = None
) -> int:
    """
    Sanitiza e valida input numérico inteiro.
    
    Args:
        value: Valor a converter
        default: Valor padrão se conversão falhar
        min_value: Valor mínimo permitido
        max_value: Valor máximo permitido
        
    Returns:
        Inteiro validado
    """
    try:
        result = int(value)
    except (ValueError, TypeError):
        return default
    
    if min_value is not None and result < min_value:
        return min_value
    if max_value is not None and result > max_value:
        return max_value
    
    return result


def sanitize_boolean(value, default: bool = False) -> bool:
    """
    Sanitiza input booleano.
    
    Args:
        value: Valor a converter
        default: Valor padrão
        
    Returns:
        Booleano
    """
    if value is None:
        return default
    
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on', 'sim')
    
    return bool(value)


def sanitize_sort_field(value: str, allowed_fields: list, default: str = None) -> Optional[str]:
    """
    Valida campo de ordenação contra lista de permitidos.
    
    Args:
        value: Campo solicitado
        allowed_fields: Lista de campos permitidos
        default: Valor padrão se não permitido
        
    Returns:
        Campo validado ou default
    """
    if not value:
        return default
    
    value = str(value).lower().strip()
    
    if value in allowed_fields:
        return value
    
    return default


def sanitize_pagination(
    page: int = 1,
    per_page: int = 20,
    max_per_page: int = 100
) -> tuple[int, int, int]:
    """
    Valida parâmetros de paginação.
    
    Args:
        page: Número da página
        per_page: Itens por página
        max_per_page: Máximo de itens permitido por página
        
    Returns:
        Tupla (page, per_page, offset)
    """
    page = max(1, sanitize_integer(page, default=1))
    per_page = max(1, min(max_per_page, sanitize_integer(per_page, default=20)))
    offset = (page - 1) * per_page
    
    return page, per_page, offset


def validate_match_id(match_id: str) -> Optional[str]:
    """
    Valida formato de match ID do Tinder.
    
    Args:
        match_id: ID a validar
        
    Returns:
        ID validado ou None
    """
    if not match_id:
        return None
    
    # Match IDs do Tinder são alfanuméricos
    match_id = str(match_id).strip()
    
    if not re.match(r'^[a-zA-Z0-9_-]+$', match_id):
        return None
    
    # Tamanho razoável (IDs do Tinder têm ~25 chars)
    if len(match_id) > 100:
        return None
    
    return match_id
