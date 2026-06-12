"""
Validação de matches e mensagens.
Módulo especializado com validators reutilizáveis.
"""

from typing import Optional, Tuple

from database import Match
from utils.logger import get_logger
from utils.helpers import calculate_days_since

logger = get_logger(__name__)


# ===================== CONSTANTES =====================

SKIP_REASONS = {
    'blocked': 'Match está bloqueado',
    'unmatched': 'Match foi desfeito (unmatch)',
    'whatsapp_obtained': 'WhatsApp já obtido',
    'date_confirmed': 'Encontro já confirmado',
    'inactive': 'Inativo há muito tempo',
    'no_profile': 'Perfil não encontrado (unmatch)',
}

# Padrões problemáticos que indicam que a IA "escapou do papel"
BAD_MESSAGE_PATTERNS = [
    "como assistente", "como um assistente", "como ia",
    "não posso", "não consigo ajudar",
    "{{", "}}", "<msg>", "<gancho>"
]

# Saudações que NÃO devem ser usadas se já houve conversa
GREETING_PATTERNS = [
    "oi!", "oie", "oii", "oiii", "ola", "olá",
    "boa tarde", "boa noite", "bom dia",
    "e aí", "e ai", "eai", "eaí",
    "tudo bem?", "td bem?", "tdb?", "tudo bom?",
    "oi, tudo", "oie, tudo", "olá, tudo",
    "fala aí", "fala ai", "salve"
]


# ===================== MATCH VALIDATION =====================

class MatchValidator:
    """
    Validador centralizado para decidir se um match deve ser processado.
    Substitui verificações duplicadas em send_first_messages() e respond_to_messages().
    """
    
    def __init__(self, settings):
        """
        Args:
            settings: Configurações do sistema (de config.get_settings())
        """
        self.settings = settings
        self.days_limit = getattr(settings, 'days_without_interaction', 365)
    
    def should_skip_match(self, match: Match) -> Tuple[bool, Optional[str]]:
        """
        Verifica se o match deve ser pulado.
        
        Args:
            match: Match a ser verificado
            
        Returns:
            Tuple (should_skip: bool, reason: Optional[str])
            - (True, "motivo") se deve pular
            - (False, None) se deve processar
        """
        # 1. Verificar bloqueio
        if match.is_blocked:
            return True, SKIP_REASONS['blocked']
        
        # 2. Verificar unmatch
        if match.is_unmatched:
            return True, SKIP_REASONS['unmatched']
        
        # 3. Verificar WhatsApp já obtido
        if match.whatsapp_obtained:
            return True, SKIP_REASONS['whatsapp_obtained']
        
        # 4. Verificar encontro já confirmado
        if match.date_confirmed:
            return True, SKIP_REASONS['date_confirmed']
        
        # NOTA: Removida verificação de inatividade - sempre responder independente do tempo
        
        return False, None
    
    def should_block_for_inactivity(self, match: Match) -> Tuple[bool, int]:
        """
        Verifica se o match deve ser bloqueado por inatividade.
        
        Returns:
            Tuple (should_block: bool, days_inactive: int)
        """
        days_inactive = calculate_days_since(match.last_interaction_at)
        
        # days_inactive == -1 significa sem data (match novo, não bloquear)
        if days_inactive <= 0:
            return False, days_inactive
        
        if days_inactive > self.days_limit:
            return True, days_inactive
        
        return False, days_inactive


# ===================== AI MESSAGE VALIDATION =====================

def validate_ai_message(message: str) -> Tuple[bool, Optional[str]]:
    """
    Valida se mensagem da IA é adequada para envio.
    
    Centraliza validação usada em orchestrator.py e message_handler.py.
    
    Args:
        message: Texto da mensagem a validar
        
    Returns:
        Tuple (is_valid: bool, reason: Optional[str])
        - (True, None) se válida
        - (False, "motivo") se inválida
    """
    if not message:
        return False, "Mensagem vazia"
    
    # Garantir que é string
    if not isinstance(message, str):
        logger.warning(f"validate_ai_message recebeu tipo inválido: {type(message)} = {message}")
        return False, f"Tipo inválido: {type(message).__name__}"
    
    if len(message) < 3:
        return False, f"Mensagem muito curta ({len(message)} chars)"
    
    if len(message) > 500:
        return False, f"Mensagem muito longa ({len(message)} chars)"
    
    # Verificar padrões problemáticos
    message_lower = message.lower()
    for pattern in BAD_MESSAGE_PATTERNS:
        if pattern in message_lower:
            return False, f"Padrão problemático detectado: {pattern}"
    
    return True, None


def validate_ai_message_with_context(
    message: str, 
    conversation_history: list = None,
    is_first_message: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Valida mensagem da IA considerando o contexto da conversa.
    
    Evita saudações repetidas se a conversa já tem mensagens.
    
    Args:
        message: Texto da mensagem a validar
        conversation_history: Lista de mensagens anteriores
        is_first_message: Se True, permite saudações
        
    Returns:
        Tuple (is_valid: bool, reason: Optional[str])
        - (True, None) se válida
        - (False, "motivo") se inválida
    """
    # Primeiro, validação básica
    is_valid, reason = validate_ai_message(message)
    if not is_valid:
        return False, reason
    
    # Se é primeira mensagem, permite saudações
    if is_first_message:
        return True, None
    
    # Verificar se já houve troca de mensagens
    has_conversation = conversation_history and len(conversation_history) > 0
    
    if has_conversation:
        message_lower = message.lower().strip()
        
        # Verificar se começa com saudação
        for greeting in GREETING_PATTERNS:
            if message_lower.startswith(greeting):
                logger.warning(f"Saudação repetida bloqueada: '{message[:50]}...'")
                return False, f"Saudação repetida em conversa iniciada: '{greeting}'"
        
        # Verificar se a mensagem é APENAS uma saudação simples
        simple_greetings = ["oi", "oie", "oii", "ola", "olá", "eai", "eaí", "e aí"]
        if message_lower.rstrip("!?.") in simple_greetings:
            logger.warning(f"Mensagem é apenas saudação: '{message}'")
            return False, f"Mensagem é apenas saudação simples em conversa iniciada"
    
    return True, None


# ===================== CONVENIENCE FUNCTIONS =====================

def is_match_processable(match: Match, settings) -> bool:
    """
    Shortcut: verifica rapidamente se match pode ser processado.
    
    Args:
        match: Match a verificar
        settings: Configurações do sistema
        
    Returns:
        True se pode processar, False se deve pular
    """
    validator = MatchValidator(settings)
    should_skip, _ = validator.should_skip_match(match)
    return not should_skip


def get_skip_reason(match: Match, settings) -> Optional[str]:
    """
    Shortcut: obtém o motivo de pular um match (ou None se não deve pular).
    
    Args:
        match: Match a verificar
        settings: Configurações do sistema
        
    Returns:
        Motivo de pular ou None
    """
    validator = MatchValidator(settings)
    _, reason = validator.should_skip_match(match)
    return reason
