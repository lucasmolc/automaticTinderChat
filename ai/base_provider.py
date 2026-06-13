"""
Base class para provedores de IA.
Define a interface comum para todas as integrações de IA.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class AIProviderError(Exception):
    """Exceção base para erros de provedores de IA."""
    pass


class BudgetExceededError(AIProviderError):
    """Erro quando o limite de gastos/tokens foi excedido."""
    def __init__(self, message: str = "Budget exceeded", details: dict = None):
        super().__init__(message)
        self.details = details or {}


class RateLimitError(AIProviderError):
    """Erro quando rate limit foi atingido."""
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after


class AuthenticationError(AIProviderError):
    """Erro de autenticação com a API."""
    pass


class ModelNotAvailableError(AIProviderError):
    """Erro quando o modelo não está disponível."""
    pass


class AIProviderStatus(Enum):
    """Status possíveis de um provedor de IA."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class AIModel:
    """Representa um modelo de IA disponível."""
    id: str
    name: str
    provider: str
    max_tokens: int
    supports_json: bool = True
    cost_per_1k_input: float = 0.0  # USD
    cost_per_1k_output: float = 0.0  # USD
    description: str = ""


@dataclass
class AIResponse:
    """Resposta padronizada de uma chamada de IA."""
    content: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    response_time_ms: int
    cost_estimate: float = 0.0
    raw_response: Any = None


class BaseAIProvider(ABC):
    """
    Classe base abstrata para provedores de IA.
    Todas as integrações de IA devem herdar desta classe.
    """
    
    # Identificador único do provedor
    PROVIDER_ID: str = "base"
    PROVIDER_NAME: str = "Base Provider"
    
    def __init__(self):
        self._status = AIProviderStatus.DISABLED
        self._last_error: Optional[str] = None
        self._models: List[AIModel] = []
        self._current_model: Optional[str] = None
        # Estatísticas de uso
        self._usage_stats = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "requests": 0,
            "estimated_cost": 0.0
        }
    
    @property
    def status(self) -> AIProviderStatus:
        return self._status
    
    @property
    def is_enabled(self) -> bool:
        return self._status == AIProviderStatus.ENABLED
    
    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
    
    @property
    def available_models(self) -> List[AIModel]:
        return self._models
    
    @property
    def current_model(self) -> Optional[str]:
        return self._current_model
    
    @property
    def usage_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de uso de tokens."""
        return self._usage_stats.copy()
    
    def _track_usage(self, response: 'AIResponse'):
        """Atualiza estatísticas de uso com base na resposta."""
        self._usage_stats["total_tokens"] += response.total_tokens
        self._usage_stats["prompt_tokens"] += response.prompt_tokens
        self._usage_stats["completion_tokens"] += response.completion_tokens
        self._usage_stats["requests"] += 1
        self._usage_stats["estimated_cost"] += response.cost_estimate
    
    @abstractmethod
    def initialize(self, api_key: str, model: str = None, **kwargs) -> bool:
        """
        Inicializa o provedor com as credenciais.
        
        Args:
            api_key: Chave de API
            model: Modelo a ser usado (opcional)
            **kwargs: Configurações adicionais específicas do provedor
            
        Returns:
            True se inicializado com sucesso
        """
        pass
    
    @abstractmethod
    def validate_api_key(self) -> bool:
        """
        Valida se a API key está funcionando.
        
        Returns:
            True se a chave é válida
        """
        pass
    
    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 500,
        **kwargs
    ) -> AIResponse:
        """
        Executa uma chamada de chat completion.
        
        Args:
            messages: Lista de mensagens no formato [{"role": "...", "content": "..."}]
            temperature: Criatividade (0-1)
            max_tokens: Máximo de tokens na resposta
            **kwargs: Parâmetros adicionais específicos do provedor
            
        Returns:
            AIResponse com a resposta
            
        Raises:
            BudgetExceededError: Se o budget foi excedido
            RateLimitError: Se rate limit foi atingido
            AuthenticationError: Se credenciais inválidas
            AIProviderError: Para outros erros
        """
        pass
    
    def set_model(self, model_id: str) -> bool:
        """
        Define o modelo a ser usado.
        
        Args:
            model_id: ID do modelo
            
        Returns:
            True se o modelo foi definido com sucesso
        """
        # Verificar se o modelo existe
        model_ids = [m.id for m in self._models]
        if model_id not in model_ids:
            raise ModelNotAvailableError(f"Modelo '{model_id}' não disponível. Opções: {model_ids}")
        
        self._current_model = model_id
        return True
    
    def get_model_info(self, model_id: str = None) -> Optional[AIModel]:
        """Retorna informações sobre um modelo específico ou o atual."""
        target_id = model_id or self._current_model
        for model in self._models:
            if model.id == target_id:
                return model
        return None
    
    def disable(self):
        """Desabilita o provedor."""
        self._status = AIProviderStatus.DISABLED
    
    def enable(self):
        """Habilita o provedor (se configurado corretamente)."""
        if self._current_model:
            self._status = AIProviderStatus.ENABLED
    
    def to_dict(self) -> Dict:
        """Retorna representação em dicionário do provedor."""
        return {
            "provider_id": self.PROVIDER_ID,
            "provider_name": self.PROVIDER_NAME,
            "status": self._status.value,
            "is_enabled": self.is_enabled,
            "current_model": self._current_model,
            "last_error": self._last_error,
            "available_models": [
                {
                    "id": m.id,
                    "name": m.name,
                    "max_tokens": m.max_tokens,
                    "cost_per_1k_input": m.cost_per_1k_input,
                    "cost_per_1k_output": m.cost_per_1k_output,
                    "description": m.description
                }
                for m in self._models
            ]
        }
