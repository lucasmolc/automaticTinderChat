"""
Módulo de IA do Automatic Tinder Chat.

Arquitetura Centralizada:
- AIService: Ponto único de entrada para todas as operações de IA
- Provedores: OpenAI, DeepSeek, Claude (drivers intercambiáveis)
- Manager: Gerencia múltiplos provedores e alternância

Uso Recomendado:
    from ai import get_ai_service, ai_chat
    
    # Serviço completo
    service = get_ai_service()
    result = service.generate_message(match_profile)
    
    # Helper direto
    response = ai_chat([{"role": "user", "content": "..."}])
"""

# Serviço centralizado (RECOMENDADO)
from .ai_service import (
    AIService,
    ai_chat,
    get_ai_service,
    get_openai_client,  # Alias para compatibilidade
)

# Sistema de provedores (baixo nível)
from .base_provider import (
    AIModel,
    AIProviderError,
    AIProviderStatus,
    AIResponse,
    AuthenticationError,
    BaseAIProvider,
    BudgetExceededError,
    ModelNotAvailableError,
    RateLimitError,
)
from .claude_provider import ClaudeProvider
from .deepseek_provider import DeepSeekProvider

# Provedores disponíveis
from .openai_provider import OpenAIProvider

# Manager de provedores
from .provider_manager import AIProviderManager, get_ai_manager, reset_ai_manager

__all__ = [
    # === Serviço Centralizado (USE ESTES) ===
    "AIService",
    "get_ai_service",
    "get_openai_client",  # DEPRECATED - use get_ai_service
    "ai_chat",
    
    # === Provedores (baixo nível) ===
    "BaseAIProvider",
    "OpenAIProvider",
    "DeepSeekProvider", 
    "ClaudeProvider",
    
    # === Manager ===
    "AIProviderManager",
    "get_ai_manager",
    "reset_ai_manager",
    
    # === Tipos e Exceções ===
    "AIProviderError",
    "BudgetExceededError",
    "RateLimitError",
    "AuthenticationError",
    "ModelNotAvailableError",
    "AIProviderStatus",
    "AIModel",
    "AIResponse",
]
