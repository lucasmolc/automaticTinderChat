"""
Provedor de IA para DeepSeek.
Implementa a interface BaseAIProvider para a API da DeepSeek.
"""

import time
from typing import Dict, List, Optional

import requests

from utils.logger import get_logger

from .base_provider import (
    AIModel,
    AIProviderError,
    AIProviderStatus,
    AIResponse,
    AuthenticationError,
    BaseAIProvider,
    BudgetExceededError,
    RateLimitError,
)

logger = get_logger(__name__)


class DeepSeekProvider(BaseAIProvider):
    """Provedor de IA usando a API da DeepSeek."""
    
    PROVIDER_ID = "deepseek"
    PROVIDER_NAME = "DeepSeek"
    
    # URL base da API
    API_BASE_URL = "https://api.deepseek.com/v1"
    
    # Modelos disponíveis
    AVAILABLE_MODELS = [
        AIModel(
            id="deepseek-chat",
            name="DeepSeek Chat",
            provider="deepseek",
            max_tokens=64000,
            supports_json=True,
            cost_per_1k_input=0.00014,
            cost_per_1k_output=0.00028,
            description="Modelo de chat geral, muito econômico"
        ),
        AIModel(
            id="deepseek-coder",
            name="DeepSeek Coder",
            provider="deepseek",
            max_tokens=64000,
            supports_json=True,
            cost_per_1k_input=0.00014,
            cost_per_1k_output=0.00028,
            description="Especializado em código"
        ),
        AIModel(
            id="deepseek-reasoner",
            name="DeepSeek Reasoner (R1)",
            provider="deepseek",
            max_tokens=64000,
            supports_json=True,
            cost_per_1k_input=0.00055,
            cost_per_1k_output=0.00219,
            description="Modelo com raciocínio avançado"
        ),
    ]
    
    def __init__(self):
        super().__init__()
        self._api_key: Optional[str] = None
        self._models = self.AVAILABLE_MODELS.copy()
    
    def initialize(self, api_key: str, model: str = None, **kwargs) -> bool:
        """
        Inicializa o provedor DeepSeek.
        
        Args:
            api_key: Chave de API da DeepSeek
            model: Modelo a ser usado (default: deepseek-chat)
        """
        try:
            self._api_key = api_key
            
            # Definir modelo
            target_model = model or "deepseek-chat"
            self.set_model(target_model)
            
            # Testar conexão
            if self.validate_api_key():
                self._status = AIProviderStatus.ENABLED
                logger.info(f"DeepSeek Provider inicializado com modelo: {self._current_model}")
                return True
            else:
                self._status = AIProviderStatus.ERROR
                return False
                
        except Exception as e:
            self._last_error = str(e)
            self._status = AIProviderStatus.ERROR
            logger.error(f"Erro ao inicializar DeepSeek Provider: {e}")
            return False
    
    def validate_api_key(self) -> bool:
        """Valida a API key fazendo uma chamada simples."""
        if not self._api_key:
            return False
        
        try:
            # Fazer uma chamada mínima para validar
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{self.API_BASE_URL}/models",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 401:
                self._last_error = "API key inválida"
                return False
            
            return response.status_code == 200
            
        except Exception as e:
            self._last_error = str(e)
            return False
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 500,
        **kwargs
    ) -> AIResponse:
        """
        Executa chat completion com a API DeepSeek.
        """
        if not self._api_key:
            raise AIProviderError("DeepSeek não configurado")
        
        if self._status != AIProviderStatus.ENABLED:
            raise AIProviderError(f"DeepSeek Provider não está habilitado. Status: {self._status.value}")
        
        start_time = time.time()
        
        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self._current_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs
            }
            
            response = requests.post(
                f"{self.API_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            if response.status_code == 401:
                self._status = AIProviderStatus.ERROR
                self._last_error = "Erro de autenticação"
                raise AuthenticationError("API key DeepSeek inválida")
            
            if response.status_code == 429:
                error_data = response.json() if response.text else {}
                error_message = error_data.get("error", {}).get("message", "Rate limit")
                
                if "quota" in error_message.lower() or "billing" in error_message.lower():
                    self._status = AIProviderStatus.BUDGET_EXCEEDED
                    raise BudgetExceededError(
                        message="Budget DeepSeek excedido",
                        details={"error": error_message}
                    )
                
                self._status = AIProviderStatus.RATE_LIMITED
                raise RateLimitError(message="Rate limit DeepSeek")
            
            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_message = error_data.get("error", {}).get("message", response.text)
                raise AIProviderError(f"Erro DeepSeek: {error_message}")
            
            data = response.json()
            
            # Calcular custo estimado
            model_info = self.get_model_info()
            usage = data.get("usage", {})
            cost = 0.0
            if model_info:
                cost = (
                    (usage.get("prompt_tokens", 0) / 1000) * model_info.cost_per_1k_input +
                    (usage.get("completion_tokens", 0) / 1000) * model_info.cost_per_1k_output
                )
            
            ai_response = AIResponse(
                content=data["choices"][0]["message"]["content"],
                model=data.get("model", self._current_model),
                provider=self.PROVIDER_ID,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                response_time_ms=elapsed_ms,
                cost_estimate=cost,
                raw_response=data
            )
            
            # Rastrear uso de tokens
            self._track_usage(ai_response)
            
            return ai_response
            
        except (BudgetExceededError, RateLimitError, AuthenticationError):
            raise
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Erro na chamada DeepSeek: {e}")
            raise AIProviderError(f"Erro na chamada DeepSeek: {e}")
