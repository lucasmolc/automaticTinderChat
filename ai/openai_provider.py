"""
Provedor de IA para OpenAI (GPT).
Implementa a interface BaseAIProvider para a API da OpenAI.
"""

import time
from typing import Dict, List, Optional

from openai import AuthenticationError as OpenAIAuthError
from openai import OpenAI, OpenAIError
from openai import RateLimitError as OpenAIRateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from utils.logger import get_logger

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

logger = get_logger(__name__)


class OpenAIProvider(BaseAIProvider):
    """Provedor de IA usando a API da OpenAI."""
    
    PROVIDER_ID = "openai"
    PROVIDER_NAME = "OpenAI (GPT)"
    
    # Modelos disponíveis com suas configurações
    AVAILABLE_MODELS = [
        AIModel(
            id="gpt-4o",
            name="GPT-4o",
            provider="openai",
            max_tokens=128000,
            supports_json=True,
            cost_per_1k_input=0.0025,
            cost_per_1k_output=0.01,
            description="Modelo mais avançado, melhor qualidade"
        ),
        AIModel(
            id="gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openai",
            max_tokens=128000,
            supports_json=True,
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
            description="Versão econômica do GPT-4o, ótimo custo-benefício"
        ),
        AIModel(
            id="gpt-4-turbo",
            name="GPT-4 Turbo",
            provider="openai",
            max_tokens=128000,
            supports_json=True,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
            description="GPT-4 otimizado para velocidade"
        ),
        AIModel(
            id="gpt-3.5-turbo",
            name="GPT-3.5 Turbo",
            provider="openai",
            max_tokens=16385,
            supports_json=True,
            cost_per_1k_input=0.0005,
            cost_per_1k_output=0.0015,
            description="Modelo rápido e econômico"
        ),
    ]
    
    def __init__(self):
        super().__init__()
        self._client: Optional[OpenAI] = None
        self._api_key: Optional[str] = None
        self._models = self.AVAILABLE_MODELS.copy()
    
    def initialize(self, api_key: str, model: str = None, **kwargs) -> bool:
        """
        Inicializa o provedor OpenAI.
        
        Args:
            api_key: Chave de API da OpenAI
            model: Modelo a ser usado (default: gpt-4o-mini)
        """
        try:
            self._api_key = api_key
            self._client = OpenAI(api_key=api_key)
            
            # Definir modelo
            target_model = model or "gpt-4o-mini"
            self.set_model(target_model)
            
            # Testar conexão
            if self.validate_api_key():
                self._status = AIProviderStatus.ENABLED
                logger.info(f"OpenAI Provider inicializado com modelo: {self._current_model}")
                return True
            else:
                self._status = AIProviderStatus.ERROR
                return False
                
        except Exception as e:
            self._last_error = str(e)
            self._status = AIProviderStatus.ERROR
            logger.error(f"Erro ao inicializar OpenAI Provider: {e}")
            return False
    
    def validate_api_key(self) -> bool:
        """Valida a API key fazendo uma chamada simples."""
        if not self._client:
            return False
        
        try:
            # Fazer uma chamada mínima para validar
            self._client.models.list()
            return True
        except OpenAIAuthError:
            self._last_error = "API key inválida"
            self._status = AIProviderStatus.ERROR
            return False
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
        Executa chat completion com tratamento de erros de budget.
        """
        if not self._client:
            raise AIProviderError("OpenAI client não inicializado")
        
        if self._status != AIProviderStatus.ENABLED:
            raise AIProviderError(f"OpenAI Provider não está habilitado. Status: {self._status.value}")
        
        start_time = time.time()
        
        try:
            response = self._client.chat.completions.create(
                model=self._current_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            # Calcular custo estimado
            model_info = self.get_model_info()
            cost = 0.0
            if model_info:
                cost = (
                    (response.usage.prompt_tokens / 1000) * model_info.cost_per_1k_input +
                    (response.usage.completion_tokens / 1000) * model_info.cost_per_1k_output
                )
            
            ai_response = AIResponse(
                content=response.choices[0].message.content,
                model=response.model,
                provider=self.PROVIDER_ID,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                response_time_ms=elapsed_ms,
                cost_estimate=cost,
                raw_response=response
            )
            
            # Rastrear uso de tokens
            self._track_usage(ai_response)
            
            return ai_response
            
        except OpenAIRateLimitError as e:
            error_message = str(e)
            
            # Verificar se é erro de budget/quota
            if "insufficient_quota" in error_message.lower() or "exceeded" in error_message.lower():
                self._status = AIProviderStatus.BUDGET_EXCEEDED
                self._last_error = "Budget excedido na OpenAI"
                logger.error(f"Budget excedido na OpenAI: {error_message}")
                raise BudgetExceededError(
                    message="Seu limite de gastos na OpenAI foi atingido",
                    details={
                        "provider": self.PROVIDER_ID,
                        "error": error_message,
                        "suggestion": "Verifique seu plano de pagamento em platform.openai.com"
                    }
                )
            
            # Rate limit normal
            self._status = AIProviderStatus.RATE_LIMITED
            self._last_error = "Rate limit atingido"
            logger.warning(f"Rate limit OpenAI: {error_message}")
            raise RateLimitError(
                message="Rate limit da OpenAI atingido",
                retry_after=60  # Default 60 segundos
            )
            
        except OpenAIAuthError as e:
            self._status = AIProviderStatus.ERROR
            self._last_error = "Erro de autenticação"
            logger.error(f"Erro de autenticação OpenAI: {e}")
            raise AuthenticationError(f"Erro de autenticação na OpenAI: {e}")
            
        except Exception as e:
            error_message = str(e).lower()
            
            # Detectar erros de budget em mensagens genéricas
            if any(word in error_message for word in ['quota', 'billing', 'insufficient', 'exceeded', 'limit']):
                self._status = AIProviderStatus.BUDGET_EXCEEDED
                self._last_error = "Possível problema de budget"
                logger.error(f"Possível erro de budget OpenAI: {e}")
                raise BudgetExceededError(
                    message="Possível limite de gastos atingido",
                    details={"error": str(e)}
                )
            
            self._last_error = str(e)
            logger.error(f"Erro na chamada OpenAI: {e}")
            raise AIProviderError(f"Erro na chamada OpenAI: {e}")
    
    def chat_completion_with_retry(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 500,
        max_retries: int = 3,
        **kwargs
    ) -> AIResponse:
        """
        Chat completion com retry automático (exceto para erros de budget).
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return self.chat_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
            except BudgetExceededError:
                # Não fazer retry em erros de budget
                raise
            except RateLimitError as e:
                last_error = e
                wait_time = max(15, min(2 ** attempt * 15, 60))
                logger.warning(f"Rate limit, aguardando {wait_time}s antes do retry {attempt + 1}/{max_retries}")
                time.sleep(wait_time)
            except AIProviderError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = max(15, 2 ** attempt * 15)
                    logger.warning(f"Erro, retry {attempt + 1}/{max_retries} em {wait_time}s: {e}")
                    time.sleep(wait_time)
        
        raise last_error or AIProviderError("Falha após múltiplas tentativas")
