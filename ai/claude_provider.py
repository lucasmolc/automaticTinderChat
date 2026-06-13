"""
Provedor de IA para Anthropic Claude.
Implementa a interface BaseAIProvider para a API da Anthropic.
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


class ClaudeProvider(BaseAIProvider):
    """Provedor de IA usando a API da Anthropic Claude."""
    
    PROVIDER_ID = "claude"
    PROVIDER_NAME = "Anthropic Claude"
    
    # URL base da API
    API_BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"
    
    # Modelos disponíveis com suas configurações
    AVAILABLE_MODELS = [
        AIModel(
            id="claude-sonnet-4-20250514",
            name="Claude Sonnet 4",
            provider="claude",
            max_tokens=200000,
            supports_json=True,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
            description="Modelo mais recente, excelente para conversas naturais"
        ),
        AIModel(
            id="claude-3-5-sonnet-20241022",
            name="Claude 3.5 Sonnet",
            provider="claude",
            max_tokens=200000,
            supports_json=True,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
            description="Modelo balanceado, ótimo custo-benefício para conversas"
        ),
        AIModel(
            id="claude-3-5-haiku-20241022",
            name="Claude 3.5 Haiku",
            provider="claude",
            max_tokens=200000,
            supports_json=True,
            cost_per_1k_input=0.0008,
            cost_per_1k_output=0.004,
            description="Modelo rápido e econômico"
        ),
        AIModel(
            id="claude-3-opus-20240229",
            name="Claude 3 Opus",
            provider="claude",
            max_tokens=200000,
            supports_json=True,
            cost_per_1k_input=0.015,
            cost_per_1k_output=0.075,
            description="Modelo mais poderoso, máxima qualidade"
        ),
    ]
    
    def __init__(self):
        super().__init__()
        self._api_key: Optional[str] = None
        self._models = self.AVAILABLE_MODELS.copy()
        self._session = requests.Session()
    
    def initialize(self, api_key: str, model: str = None, **kwargs) -> bool:
        """
        Inicializa o provedor Claude.
        
        Args:
            api_key: Chave de API da Anthropic
            model: Modelo a ser usado (default: claude-3-5-sonnet-20241022)
        """
        try:
            self._api_key = api_key
            
            # Configurar headers da sessão
            self._session.headers.update({
                "x-api-key": api_key,
                "anthropic-version": self.API_VERSION,
                "content-type": "application/json"
            })
            
            # Definir modelo
            target_model = model or "claude-3-5-sonnet-20241022"
            self.set_model(target_model)
            
            # Testar conexão
            if self.validate_api_key():
                self._status = AIProviderStatus.ENABLED
                logger.info(f"Claude Provider inicializado com modelo: {self._current_model}")
                return True
            else:
                self._status = AIProviderStatus.ERROR
                return False
                
        except Exception as e:
            self._last_error = str(e)
            self._status = AIProviderStatus.ERROR
            logger.error(f"Erro ao inicializar Claude Provider: {e}")
            return False
    
    def validate_api_key(self) -> bool:
        """Valida a API key fazendo uma chamada simples."""
        if not self._api_key:
            return False
        
        try:
            # Fazer uma chamada mínima para validar
            response = self._session.post(
                f"{self.API_BASE_URL}/messages",
                json={
                    "model": self._current_model,
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "Hi"}]
                },
                timeout=10
            )
            
            if response.status_code == 401:
                self._last_error = "API key inválida"
                self._status = AIProviderStatus.ERROR
                return False
            
            # 200 ou outros códigos (exceto 401) indicam key válida
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"Erro ao validar API key Claude: {e}")
            # Se houver erro de conexão, assumir key válida e testar depois
            return True
    
    def set_model(self, model_id: str) -> bool:
        """Define o modelo a ser usado."""
        valid_ids = [m.id for m in self._models]
        
        if model_id in valid_ids:
            self._current_model = model_id
            return True
        
        # Tentar match parcial
        for m in self._models:
            if model_id.lower() in m.id.lower() or m.id.lower() in model_id.lower():
                self._current_model = m.id
                logger.info(f"Modelo '{model_id}' mapeado para '{m.id}'")
                return True
        
        logger.warning(f"Modelo '{model_id}' não encontrado, usando default")
        self._current_model = "claude-3-5-sonnet-20241022"
        return False
    
    def get_model_info(self) -> Optional[AIModel]:
        """Retorna informações do modelo atual."""
        if not self._current_model:
            return None
        
        for model in self._models:
            if model.id == self._current_model:
                return model
        return None
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> AIResponse:
        """
        Executa chat completion com a API Claude.
        
        Args:
            messages: Lista de mensagens no formato [{"role": "user/assistant", "content": "..."}]
            temperature: Criatividade (0-1)
            max_tokens: Máximo de tokens na resposta
            
        Returns:
            AIResponse com a resposta
        """
        if not self._api_key:
            raise AIProviderError("Claude client não inicializado")
        
        if self._status != AIProviderStatus.ENABLED:
            raise AIProviderError(f"Claude Provider não está habilitado. Status: {self._status.value}")
        
        start_time = time.time()
        
        try:
            # Converter formato de mensagens (OpenAI -> Claude)
            claude_messages, system_prompt = self._convert_messages(messages)
            
            # Preparar payload
            payload = {
                "model": self._current_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": claude_messages
            }
            
            # Adicionar system prompt se existir
            if system_prompt:
                payload["system"] = system_prompt
            
            # Fazer request
            response = self._session.post(
                f"{self.API_BASE_URL}/messages",
                json=payload,
                timeout=60
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            # Tratar erros
            if response.status_code == 401:
                self._status = AIProviderStatus.ERROR
                self._last_error = "API key inválida"
                raise AuthenticationError("API key da Anthropic inválida")
            
            if response.status_code == 429:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", "Rate limit exceeded")
                
                # Verificar se é erro de budget
                if "credit" in error_message.lower() or "billing" in error_message.lower():
                    self._status = AIProviderStatus.BUDGET_EXCEEDED
                    self._last_error = "Budget excedido"
                    raise BudgetExceededError(
                        message="Limite de créditos da Anthropic atingido",
                        details={"error": error_message}
                    )
                
                self._status = AIProviderStatus.RATE_LIMITED
                self._last_error = "Rate limit atingido"
                raise RateLimitError(message=error_message, retry_after=60)
            
            if response.status_code >= 400:
                error_data = response.json().get("error", {})
                error_message = error_data.get("message", f"HTTP {response.status_code}")
                raise AIProviderError(f"Erro na API Claude: {error_message}")
            
            # Parsear resposta
            data = response.json()
            
            content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content += block.get("text", "")
            
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            
            # Calcular custo
            model_info = self.get_model_info()
            cost = 0.0
            if model_info:
                cost = (
                    (input_tokens / 1000) * model_info.cost_per_1k_input +
                    (output_tokens / 1000) * model_info.cost_per_1k_output
                )
            
            ai_response = AIResponse(
                content=content,
                model=data.get("model", self._current_model),
                provider=self.PROVIDER_ID,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                response_time_ms=elapsed_ms,
                cost_estimate=cost,
                raw_response=data
            )
            
            # Rastrear uso
            self._track_usage(ai_response)
            
            return ai_response
            
        except (BudgetExceededError, RateLimitError, AuthenticationError):
            raise
        except requests.exceptions.Timeout:
            self._last_error = "Timeout na requisição"
            raise AIProviderError("Timeout na chamada à API Claude")
        except requests.exceptions.ConnectionError as e:
            self._last_error = "Erro de conexão"
            raise AIProviderError(f"Erro de conexão com a API Claude: {e}")
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Erro na chamada Claude: {e}")
            raise AIProviderError(f"Erro na chamada Claude: {e}")
    
    def _convert_messages(self, messages: List[Dict[str, str]]) -> tuple:
        """
        Converte mensagens do formato OpenAI para formato Claude.
        
        OpenAI: [{"role": "system/user/assistant", "content": "..."}]
        Claude: system é separado, roles são apenas "user" e "assistant"
        
        Returns:
            Tuple (claude_messages, system_prompt)
        """
        system_prompt = None
        claude_messages = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                # System prompt é separado no Claude
                if system_prompt:
                    system_prompt += "\n\n" + content
                else:
                    system_prompt = content
            elif role in ("user", "assistant"):
                claude_messages.append({
                    "role": role,
                    "content": content
                })
            else:
                # Mapear outros roles para user
                claude_messages.append({
                    "role": "user",
                    "content": content
                })
        
        # Garantir que começa com user (requisito do Claude)
        if claude_messages and claude_messages[0]["role"] != "user":
            claude_messages.insert(0, {"role": "user", "content": "Continue a conversa."})
        
        return claude_messages, system_prompt
    
    def chat_completion_with_retry(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        max_retries: int = 3,
        **kwargs
    ) -> AIResponse:
        """Chat completion com retry automático."""
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
                raise  # Não fazer retry em erros de budget
            except RateLimitError as e:
                last_error = e
                wait_time = max(15, min(2 ** attempt * 15, 60))
                logger.warning(f"Rate limit Claude, aguardando {wait_time}s (tentativa {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except AIProviderError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = max(15, 2 ** attempt * 15)
                    logger.warning(f"Erro Claude, retry {attempt + 1}/{max_retries} em {wait_time}s: {e}")
                    time.sleep(wait_time)
        
        raise last_error or AIProviderError("Falha após múltiplas tentativas")
    
    def get_status(self) -> Dict:
        """Retorna status detalhado do provedor."""
        return {
            "provider_id": self.PROVIDER_ID,
            "provider_name": self.PROVIDER_NAME,
            "status": self._status.value,
            "current_model": self._current_model,
            "last_error": self._last_error,
            "usage_stats": self._usage_stats
        }
