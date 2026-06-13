"""
Detector de WhatsApp e confirmações de encontro em mensagens.
"""

import re
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


# Padrões de números de telefone brasileiros
PHONE_PATTERNS = [
    # Formato com DDD: (11) 99999-9999 ou (11) 9999-9999
    r'\(?\d{2}\)?\s*9?\d{4}[-.\s]?\d{4}',
    # Formato: 11 99999-9999 ou 11999999999
    r'\b\d{2}\s*9?\d{4}[-.\s]?\d{4}\b',
    # Formato internacional: +55 11 99999-9999
    r'\+?55\s*\(?\d{2}\)?\s*9?\d{4}[-.\s]?\d{4}',
    # Só os 9 dígitos: 999999999 ou 99999-9999
    r'\b9\d{4}[-.\s]?\d{4}\b',
]

# Palavras-chave que indicam compartilhamento de WhatsApp
WHATSAPP_KEYWORDS = [
    r'\bwhats\b', r'\bwhatsapp\b', r'\bzap\b', r'\bwpp\b', r'\bwats\b',
    r'\bmeu n[úu]mero\b', r'\bmeu celular\b', r'\bmeu telefone\b',
    r'\bme chama\b', r'\bme add\b', r'\bme adiciona\b',
    r'\banota a[íi]\b', r'\banota\b', r'\bsalva\b',
    r'\bvamos pro\b', r'\bvamos para o\b', r'\bpassa pro\b',
]

# Padrões de confirmação de encontro
DATE_CONFIRMATION_PATTERNS = [
    r'\bvamos\s*(sim|claro|bora)\b',
    r'\bbora\s*(sim|l[áa]|marcar)\b',
    r'\bpode ser\b', r'\bt[ôo]pando\b', r'\btopo\b',
    r'\bcombinado\b', r'\bfechado\b', r'\bbeleza\b',
    r'\bque horas\b', r'\ba que horas\b', r'\bonde\b.*encontr',
    r'\bmarcar\b.*encontro\b', r'\bonde .*quer\b',
    r'\bsim\b.*\bvamos\b', r'\bclaro\b.*\bsair\b',
    r'\bquero\b.*\bsair\b', r'\bquero\b.*\bte conhecer\b',
    r'\bte encontro\b', r'\bte vejo\b',
]


def extract_phone_number(text: str) -> Optional[str]:
    """
    Extrai número de telefone de uma mensagem.
    
    Args:
        text: Texto da mensagem
        
    Returns:
        Número formatado ou None
    """
    if not text:
        return None
    
    for pattern in PHONE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Limpar e formatar o número
            number = re.sub(r'[^\d]', '', match.group())
            
            # Validar tamanho (8-11 dígitos para números brasileiros)
            if 8 <= len(number) <= 11:
                # Formatar: (XX) XXXXX-XXXX
                if len(number) == 11:
                    return f"({number[:2]}) {number[2:7]}-{number[7:]}"
                elif len(number) == 10:
                    return f"({number[:2]}) {number[2:6]}-{number[6:]}"
                elif len(number) == 9:
                    return f"{number[:5]}-{number[5:]}"
                elif len(number) == 8:
                    return f"{number[:4]}-{number[4:]}"
                return number
    
    return None


def detect_whatsapp_share(text: str) -> Tuple[bool, Optional[str]]:
    """
    Detecta se a mensagem contém compartilhamento de WhatsApp.
    
    Args:
        text: Texto da mensagem
        
    Returns:
        Tuple (tem_whatsapp, numero_extraido)
    """
    if not text:
        return False, None
    
    text_lower = text.lower()
    
    # Verificar palavras-chave de WhatsApp
    has_keyword = any(
        re.search(pattern, text_lower)
        for pattern in WHATSAPP_KEYWORDS
    )
    
    # Extrair número
    phone_number = extract_phone_number(text)
    
    # Se tem número E palavra-chave, é compartilhamento de WhatsApp
    if phone_number and has_keyword:
        logger.debug(f"WhatsApp detectado: {phone_number}")
        return True, phone_number
    
    # Se tem número e é uma mensagem curta (provavelmente só o número)
    if phone_number and len(text.split()) <= 5:
        logger.debug(f"Possível WhatsApp (número isolado): {phone_number}")
        return True, phone_number
    
    return False, phone_number


def detect_date_confirmation(text: str) -> bool:
    """
    Detecta se a mensagem indica confirmação de encontro.
    
    Args:
        text: Texto da mensagem
        
    Returns:
        True se parece confirmação de encontro
    """
    if not text:
        return False
    
    text_lower = text.lower()
    
    for pattern in DATE_CONFIRMATION_PATTERNS:
        if re.search(pattern, text_lower):
            logger.debug(f"Possível confirmação de encontro detectada")
            return True
    
    return False


def analyze_message_for_progression(text: str) -> Dict:
    """
    Analisa mensagem para detectar progressão no relacionamento.
    
    Args:
        text: Texto da mensagem
        
    Returns:
        Dict com análise: {
            'has_whatsapp': bool,
            'whatsapp_number': str or None,
            'date_confirmation': bool,
            'progression_type': str or None
        }
    """
    has_whatsapp, phone_number = detect_whatsapp_share(text)
    date_confirmed = detect_date_confirmation(text)
    
    progression_type = None
    if has_whatsapp:
        progression_type = 'whatsapp_shared'
    elif date_confirmed:
        progression_type = 'date_confirmed'
    
    return {
        'has_whatsapp': has_whatsapp,
        'whatsapp_number': phone_number,
        'date_confirmation': date_confirmed,
        'progression_type': progression_type
    }
