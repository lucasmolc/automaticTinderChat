"""
Utilitários gerais do sistema.
"""

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Any

from config import get_settings


def random_delay(min_seconds: float = None, max_seconds: float = None) -> None:
    """Aguarda um tempo aleatório (BLOQUEANTE - usar apenas em contextos síncronos)."""
    settings = get_settings()
    min_s = min_seconds or settings.action_delay_min
    max_s = max_seconds or settings.action_delay_max
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)


async def async_random_delay(min_seconds: float = 0.5, max_seconds: float = 1.5) -> None:
    """Aguarda um tempo aleatório (NÃO-BLOQUEANTE - para contextos async)."""
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)


def safe_json_loads(text: str, default: Any = None) -> Any:
    """Parse JSON de forma segura, retornando default em caso de erro."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(obj: Any, default: str = "{}") -> str:
    """Serializa para JSON de forma segura."""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return default


def extract_json_from_text(text: str) -> dict:
    """Extrai JSON de uma string que pode conter texto adicional."""
    import re
    from loguru import logger
    
    if not text:
        logger.debug("[JSON_EXTRACT] Texto vazio recebido")
        return {}
    
    original_text = text
    
    # Remover markdown code blocks (```json ... ``` ou ``` ... ```)
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # Tentar encontrar JSON no texto
    start_idx = text.find("{")
    end_idx = text.rfind("}") + 1
    
    if start_idx != -1 and end_idx > start_idx:
        json_str = text[start_idx:end_idx]
        
        # Tentar corrigir JSON com aspas inteligentes
        json_str = json_str.replace('"', '"').replace('"', '"')
        json_str = json_str.replace(''', "'").replace(''', "'")
        
        # Corrigir aspas duplas escapadas incorretamente
        # Ex: '\"message\"' -> '"message"'
        json_str = re.sub(r'\\+"', '"', json_str)
        
        # Corrigir valores que são strings JSON escapadas
        # Ex: {"message": "\"texto\""} -> {"message": "texto"}
        json_str = re.sub(r':\s*"\\+"([^"\\]+)\\+"', r': "\1"', json_str)
        
        result = safe_json_loads(json_str, None)
        if result is not None:
            # Verificar se valores são strings que parecem JSON escapado
            result = _fix_escaped_string_values(result)
            logger.debug(f"[JSON_EXTRACT] Parse bem sucedido, campos: {list(result.keys())}")
            return result
        
        # Tentar remover trailing commas
        json_str_fixed = re.sub(r',\s*}', '}', json_str)
        json_str_fixed = re.sub(r',\s*]', ']', json_str_fixed)
        result = safe_json_loads(json_str_fixed, None)
        if result is not None:
            result = _fix_escaped_string_values(result)
            logger.debug(f"[JSON_EXTRACT] Parse bem sucedido após fixes, campos: {list(result.keys())}")
            return result
        
        # Última tentativa: extrair valores manualmente
        logger.warning(f"[JSON_EXTRACT] JSON parsing falhou, tentando extração manual. Texto ({len(json_str)} chars): {json_str[:200]}...")
        result = _manual_json_extract(json_str)
        if result:
            return result
        
        # Se ainda não temos nada, logar o problema
        logger.error(f"[JSON_EXTRACT] Falha total ao extrair JSON. Resposta original: {original_text[:500]}...")
    else:
        logger.warning(f"[JSON_EXTRACT] Nenhum JSON encontrado no texto: {text[:200]}...")
    
    return {}


def _fix_escaped_string_values(data: dict) -> dict:
    """Corrige valores que são strings JSON escapadas."""
    if not isinstance(data, dict):
        return data
    
    fixed = {}
    for key, value in data.items():
        if isinstance(value, str):
            # Remover aspas extras no início/fim
            cleaned = value.strip()
            if cleaned.startswith('"') and cleaned.endswith('"'):
                cleaned = cleaned[1:-1]
            # Remover escapes de aspas
            cleaned = cleaned.replace('\\"', '"').replace("\\'", "'")
            fixed[key] = cleaned
        elif isinstance(value, dict):
            fixed[key] = _fix_escaped_string_values(value)
        else:
            fixed[key] = value
    return fixed


def _manual_json_extract(json_str: str) -> dict:
    """Extração manual de campos comuns quando o parsing falha."""
    import re
    from loguru import logger
    
    result = {}
    
    # Padrões para campos comuns - melhorados para capturar conteúdo variado
    patterns = {
        # message/suggested_response: captura até a próxima aspas não escapada
        "message": [
            r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"\s*[,}]',
            r'"message"\s*:\s*"([^"]+)"',
        ],
        "suggested_response": [
            r'"suggested_response"\s*:\s*"((?:[^"\\]|\\.)*)"\s*[,}]',
            r'"suggested_response"\s*:\s*"([^"]+)"',
        ],
        "temperature_score": [
            r'"temperature_score"\s*:\s*(\d+(?:\.\d+)?)',
        ],
        "temperature_label": [
            r'"temperature_label"\s*:\s*"([^"]+)"',
        ],
        "hook_used": [
            r'"hook_used"\s*:\s*"([^"]+)"',
        ],
        "confidence_score": [
            r'"confidence_score"\s*:\s*(\d+(?:\.\d+)?)',
        ],
        "next_step_recommendation": [
            r'"next_step_recommendation"\s*:\s*"([^"]+)"',
        ],
    }
    
    for field, pattern_list in patterns.items():
        for pattern in pattern_list:
            match = re.search(pattern, json_str, re.IGNORECASE | re.DOTALL)
            if match:
                value = match.group(1)
                
                # Converter números
                if field in ["temperature_score", "confidence_score"]:
                    try:
                        value = float(value)
                        if value == int(value):
                            value = int(value)
                    except ValueError:
                        continue  # Tentar próximo padrão
                # Desescapar strings
                elif isinstance(value, str):
                    value = value.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                    # Remover aspas extras no início/fim
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                
                # Validar que o valor extraído não é o próprio nome do campo
                if isinstance(value, str):
                    # Se o valor é exatamente o nome do campo (com ou sem aspas), é inválido
                    clean_value = value.strip().strip('"').strip("'").lower()
                    if clean_value == field.lower() or clean_value == f'"{field}"'.lower():
                        logger.warning(f"[MANUAL_EXTRACT] Valor inválido para {field}: '{value}'")
                        continue
                    # Se o valor é muito curto (< 3 chars para mensagens), pular
                    if field in ["message", "suggested_response"] and len(clean_value) < 3:
                        logger.warning(f"[MANUAL_EXTRACT] Valor muito curto para {field}: '{value}'")
                        continue
                
                result[field] = value
                break  # Encontrou um valor válido, próximo campo
    
    if result:
        logger.debug(f"[MANUAL_EXTRACT] Campos extraídos manualmente: {list(result.keys())}")
    
    return result


def format_datetime(dt: datetime, format_str: str = "%d/%m/%Y %H:%M") -> str:
    """Formata datetime para string."""
    if dt is None:
        return "N/A"
    return dt.strftime(format_str)


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Trunca texto para o tamanho máximo."""
    if not text or len(text) <= max_length:
        return text or ""
    return text[:max_length - len(suffix)] + suffix


def calculate_days_since(dt: datetime) -> int:
    """
    Calcula dias desde uma data.
    
    Args:
        dt: Data para calcular diferença
        
    Returns:
        Número de dias desde a data, ou -1 se None (indicando "sem data")
    """
    if dt is None:
        return -1  # Indica que não há data (não deve ser considerado como inatividade)
    delta = datetime.utcnow() - dt
    return delta.days


def sanitize_text(text: str) -> str:
    """Remove caracteres problemáticos do texto."""
    if not text:
        return ""
    # Remove caracteres de controle e normaliza espaços
    return " ".join(text.split())


def clean_city(text: str) -> str:
    """
    Limpa e valida texto de cidade extraído do Tinder.
    
    Remove padrões inválidos como:
    - "/no Centro", "/no Bairro" (sufixos de localização)
    - Timestamps (14:30, etc)
    - Textos muito longos
    - Prefixos como "Mora em", "Lives in"
    
    Args:
        text: Texto da cidade a limpar
        
    Returns:
        Cidade limpa ou string vazia se inválida
    """
    import re
    
    if not text or not isinstance(text, str):
        return ""
    
    text = text.strip()
    
    # Padrão especial: "/no Cidade" ou "/na Cidade" - extrair a cidade
    # Isso ocorre quando o Tinder mostra "X km /no Belo Horizonte"
    match = re.match(r'^/\s*n[oa]\s+(.+)$', text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    
    # Remover prefixos comuns
    prefixes = [
        r'^Mora em\s+',
        r'^Lives in\s+',
        r'^Vive em\s+',
        r'^De\s+',
        r'^From\s+',
        r'^/\s*n[oa]\s+',  # /no ou /na
        r'^/\s*in\s+',     # /in
    ]
    for prefix in prefixes:
        text = re.sub(prefix, '', text, flags=re.IGNORECASE)
    
    # Remover sufixos como "/no Centro", "/no Bairro X", etc.
    # Padrão: "/" seguido de qualquer texto
    text = re.sub(r'\s*/\s*n[oa]\s+.+$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*/\s*in\s+.+$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*/.*$', '', text)  # Remove qualquer coisa após "/"
    
    # Remover textos entre parênteses no final
    text = re.sub(r'\s*\([^)]+\)\s*$', '', text)
    
    # Limpar espaços
    text = ' '.join(text.split()).strip()
    
    # Validações
    if len(text) < 2:
        return ""
    
    if len(text) > 100:
        return ""
    
    # Não pode ser timestamp (formato HH:MM)
    if re.match(r'^\d{1,2}:\d{2}', text):
        return ""
    
    # Não pode ser só números
    if re.match(r'^\d+$', text):
        return ""
    
    # Não pode começar com "/" ou outros caracteres especiais (após limpeza)
    if re.match(r'^[/\-•·]', text):
        return ""
    
    return text


def clean_message_preview(text: str, match_name: str = None) -> str:
    """
    Remove padrões duplicados de preview de mensagem do Tinder.
    
    Ex: "Te chamei lá A última mensagem de Luiza foi: Te chamei lá"
        -> "Te chamei lá"
    
    Args:
        text: Texto da mensagem a limpar
        match_name: Nome do match para identificar padrões
        
    Returns:
        Mensagem limpa
    """
    if not text:
        return ""
    
    import re
    
    # Padrão 1: "A última mensagem de NOME foi: mensagem" (com ou sem acento)
    # Captura apenas a parte após "foi:"
    pattern1 = r'^.*?A [uú]ltima mensagem de .+ foi:\s*(.+?)$'
    match = re.match(pattern1, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Padrão 2: "Sua última mensagem foi: mensagem" (com ou sem acento)
    pattern2 = r'^.*?Sua [uú]ltima mensagem foi:\s*(.+?)$'
    match = re.match(pattern2, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Padrão 3: Apenas "A última mensagem de NOME foi: mensagem" (sem prefixo)
    pattern3 = r'^A [uú]ltima mensagem de .+ foi:\s*(.+?)$'
    match = re.match(pattern3, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Padrão alternativo: "Você: mensagem" ou "Nome: mensagem"
    prefixes_to_remove = [
        r'^Você:\s*',
        r'^Voce:\s*',
        r'^You:\s*',
        r'^Enviado:\s*',
        r'^Sent:\s*',
    ]
    
    if match_name:
        prefixes_to_remove.append(rf'^{re.escape(match_name)}:\s*')
    
    result = text
    for prefix_pattern in prefixes_to_remove:
        result = re.sub(prefix_pattern, '', result, flags=re.IGNORECASE)
    
    return result.strip()


def normalize_message_content(text: str) -> str:
    """
    Normaliza conteúdo de mensagem para exibição e processamento.
    
    - Substitui "??" e sequências de "?" por indicação de emoji
    - Remove caracteres especiais problemáticos
    - Normaliza espaços
    
    Args:
        text: Texto da mensagem
        
    Returns:
        Mensagem normalizada
    """
    if not text:
        return ""
    
    import re
    
    # "??" ou múltiplos "?" são emojis não carregados APENAS se:
    # 1. Estão sozinhos na mensagem, OU
    # 2. Têm espaço antes deles (ex: "Tudo bem! ??")
    # NÃO considerar como emoji se colados numa palavra (ex: "Tudo bem??")
    
    # Primeiro, tratar ?? que estão separados (com espaço antes)
    text = re.sub(r'(?<=\s)\?\?+', '[emoji]', text)
    
    # Tratar ?? no início da mensagem (sozinhos)
    text = re.sub(r'^\?\?+', '[emoji]', text)
    
    # Tratar ?? que são a mensagem inteira
    if re.match(r'^\?\?+$', text.strip()):
        text = '[emoji]'
    
    # Sequências de caracteres de substituição Unicode (também indicam emojis falhos)
    text = re.sub(r'[\ufffd]+', '[emoji]', text)
    
    # Múltiplos [emoji] seguidos viram um só
    text = re.sub(r'(\[emoji\]\s*)+', '[emoji] ', text)
    
    # Remove espaços extras
    text = ' '.join(text.split())
    
    return text.strip()


def parse_name_and_age(text: str) -> tuple:
    """
    Extrai nome e idade de uma string do Tinder.
    
    Formatos suportados:
    - "Lucas, 22"
    - "Lucas 22"
    - "Lucas22"
    - "Maria Luiza, 25"
    - "Maria Luiza 25"
    - "MariaLuiza25"  (detecta apenas se termina com 2 dígitos)
    
    Args:
        text: Texto contendo nome e possivelmente idade
        
    Returns:
        Tuple (nome, idade) onde idade pode ser None
    """
    if not text:
        return (None, None)
    
    import re
    
    text = text.strip()
    
    # Padrão 1: "Nome, 22" ou "Nome , 22" (com vírgula)
    match = re.match(r'^(.+?)\s*,\s*(\d{2})\s*$', text)
    if match:
        return (match.group(1).strip(), int(match.group(2)))
    
    # Padrão 2: "Nome 22" (com espaço antes da idade)
    match = re.match(r'^(.+?)\s+(\d{2})\s*$', text)
    if match:
        name = match.group(1).strip()
        # Verificar se o nome não termina com número (evitar "Ana2" ser parseado como "Ana" + 2)
        if not re.search(r'\d$', name):
            return (name, int(match.group(2)))
    
    # Padrão 3: "Nome22" (sem separador - idade colada ao nome)
    # Só aplica se termina com exatamente 2 dígitos (idade típica: 18-99)
    match = re.match(r'^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]+?)(\d{2})$', text)
    if match:
        name = match.group(1).strip()
        age = int(match.group(2))
        # Validar que a idade faz sentido (18-99)
        if 18 <= age <= 99 and len(name) >= 2:
            return (name, age)
    
    # Não conseguiu extrair idade, retorna só o nome
    return (text, None)
