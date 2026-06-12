"""
Gerenciador central de provedores de IA.
Coordena múltiplos provedores e permite alternar entre eles.
"""

import os
import json
from typing import Dict, List, Optional, Type
from pathlib import Path
from threading import Lock

from .base_provider import (
    BaseAIProvider, 
    AIResponse, 
    AIProviderStatus,
    AIProviderError,
    BudgetExceededError,
    RateLimitError,
    AuthenticationError
)
from .openai_provider import OpenAIProvider
from .deepseek_provider import DeepSeekProvider
from .claude_provider import ClaudeProvider
from utils.logger import get_logger
from utils.notifications import get_notification_manager
from utils.ai_logger import log_ai_interaction

logger = get_logger(__name__)


class AIProviderManager:
    """
    Gerenciador central de provedores de IA.
    Permite configurar, alternar e usar múltiplos provedores.
    """
    
    # Mapeamento de IDs para classes de provedores
    PROVIDER_CLASSES: Dict[str, Type[BaseAIProvider]] = {
        "openai": OpenAIProvider,
        "deepseek": DeepSeekProvider,
        "claude": ClaudeProvider,
    }
    
    def __init__(self):
        self._providers: Dict[str, BaseAIProvider] = {}
        self._active_provider_id: Optional[str] = None
        self._lock = Lock()
        self._config_file = Path(__file__).parent.parent / "config" / "ai_providers.json"
        
        # Criar diretório de config se não existir
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
    
    def register_provider(self, provider_id: str) -> Optional[BaseAIProvider]:
        """
        Registra um provedor de IA.
        
        Args:
            provider_id: ID do provedor (ex: "openai", "deepseek")
            
        Returns:
            Instância do provedor ou None se não suportado
        """
        if provider_id not in self.PROVIDER_CLASSES:
            logger.warning(f"Provedor '{provider_id}' não suportado")
            return None
        
        with self._lock:
            if provider_id not in self._providers:
                provider_class = self.PROVIDER_CLASSES[provider_id]
                self._providers[provider_id] = provider_class()
                logger.info(f"Provedor '{provider_id}' registrado")
            
            return self._providers[provider_id]
    
    def initialize_provider(
        self, 
        provider_id: str, 
        api_key: str, 
        model: str = None,
        set_as_active: bool = False,
        **kwargs
    ) -> bool:
        """
        Inicializa um provedor com credenciais.
        
        Args:
            provider_id: ID do provedor
            api_key: Chave de API
            model: Modelo a usar
            set_as_active: Se deve definir como provedor ativo
            
        Returns:
            True se inicializado com sucesso
        """
        provider = self.register_provider(provider_id)
        if not provider:
            return False
        
        success = provider.initialize(api_key, model, **kwargs)
        
        if success and set_as_active:
            self._active_provider_id = provider_id
        
        return success
    
    def initialize_from_env(self) -> bool:
        """
        Inicializa provedores a partir das variáveis de ambiente.
        
        Returns:
            True se pelo menos um provedor foi inicializado
        """
        initialized_any = False
        
        # OpenAI
        openai_key = os.getenv("OPENAI_API_KEY")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        openai_enabled = os.getenv("OPENAI_ENABLED", "true").lower() == "true"
        
        if openai_key and openai_enabled:
            if self.initialize_provider("openai", openai_key, openai_model, set_as_active=True):
                initialized_any = True
                logger.info(f"OpenAI inicializado com modelo: {openai_model}")
        
        # DeepSeek
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        deepseek_enabled = os.getenv("DEEPSEEK_ENABLED", "false").lower() == "true"
        
        if deepseek_key and deepseek_enabled:
            if self.initialize_provider("deepseek", deepseek_key, deepseek_model, set_as_active=not initialized_any):
                initialized_any = True
                logger.info(f"DeepSeek inicializado com modelo: {deepseek_model}")
        
        # Claude (Anthropic)
        claude_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        claude_model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        claude_enabled = os.getenv("CLAUDE_ENABLED", "false").lower() == "true"
        
        if claude_key and claude_enabled:
            if self.initialize_provider("claude", claude_key, claude_model, set_as_active=not initialized_any):
                initialized_any = True
                logger.info(f"Claude inicializado com modelo: {claude_model}")
        
        # Carregar configurações salvas
        self._load_config()
        
        return initialized_any
    
    def get_provider(self, provider_id: str = None) -> Optional[BaseAIProvider]:
        """
        Retorna um provedor específico ou o ativo.
        
        Args:
            provider_id: ID do provedor ou None para o ativo
            
        Returns:
            Instância do provedor
        """
        target_id = provider_id or self._active_provider_id
        if not target_id:
            return None
        
        return self._providers.get(target_id)
    
    def get_active_provider(self) -> Optional[BaseAIProvider]:
        """Retorna o provedor ativo."""
        return self.get_provider()
    
    def set_active_provider(self, provider_id: str) -> bool:
        """
        Define o provedor ativo.
        
        Args:
            provider_id: ID do provedor
            
        Returns:
            True se definido com sucesso
        """
        if provider_id not in self._providers:
            logger.warning(f"Provedor '{provider_id}' não registrado")
            return False
        
        provider = self._providers[provider_id]
        if not provider.is_enabled:
            logger.warning(f"Provedor '{provider_id}' não está habilitado")
            return False
        
        with self._lock:
            self._active_provider_id = provider_id
            logger.info(f"Provedor ativo alterado para: {provider_id}")
            self._save_config()
        
        return True
    
    def set_provider_model(self, provider_id: str, model_id: str) -> bool:
        """
        Define o modelo de um provedor.
        
        Args:
            provider_id: ID do provedor
            model_id: ID do modelo
            
        Returns:
            True se definido com sucesso
        """
        provider = self._providers.get(provider_id)
        if not provider:
            return False
        
        try:
            provider.set_model(model_id)
            self._save_config()
            logger.info(f"Modelo do {provider_id} alterado para: {model_id}")
            return True
        except Exception as e:
            logger.error(f"Erro ao definir modelo: {e}")
            return False
    
    def enable_provider(self, provider_id: str) -> bool:
        """Habilita um provedor."""
        provider = self._providers.get(provider_id)
        if not provider:
            return False
        
        provider.enable()
        self._save_config()
        return provider.is_enabled
    
    def disable_provider(self, provider_id: str) -> bool:
        """Desabilita um provedor."""
        provider = self._providers.get(provider_id)
        if not provider:
            return False
        
        provider.disable()
        
        # Se era o ativo, mudar para outro
        if self._active_provider_id == provider_id:
            for pid, p in self._providers.items():
                if p.is_enabled:
                    self._active_provider_id = pid
                    break
            else:
                self._active_provider_id = None
        
        self._save_config()
        return True
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 500,
        provider_id: str = None,
        interaction_type: str = None,
        **kwargs
    ) -> AIResponse:
        """
        Executa chat completion com o provedor especificado ou ativo.
        
        Inclui tratamento de erros, notificações e logging de custos.
        
        Args:
            messages: Lista de mensagens do chat
            temperature: Criatividade (0-1)
            max_tokens: Máximo de tokens
            provider_id: ID do provider a usar (ou ativo se None)
            interaction_type: Tipo de interação para tracking de custos
        """
        provider = self.get_provider(provider_id)
        
        if not provider:
            raise AIProviderError("Nenhum provedor de IA configurado")
        
        if not provider.is_enabled:
            raise AIProviderError(f"Provedor '{provider.PROVIDER_ID}' não está habilitado")
        
        notification_manager = get_notification_manager()
        
        try:
            response = provider.chat_completion_with_retry(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            
            # Logar interação para tracking de custos (apenas se não for openai_client que já loga)
            if provider.PROVIDER_ID != 'openai' or interaction_type:
                try:
                    log_ai_interaction(
                        interaction_type=interaction_type or 'unknown',
                        prompt=messages[-1].get('content', '')[:500] if messages else '',
                        response=response.content[:500] if response.content else '',
                        model_used=response.model,
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        response_time_ms=response.response_time_ms,
                        success=True,
                        provider=provider.PROVIDER_ID
                    )
                except Exception as e:
                    logger.warning(f"Falha ao logar interação AI: {e}")
            
            return response
            
        except BudgetExceededError as e:
            # Notificar erro de budget
            notification_manager.add(
                notification_type='ai_error',
                message=f'⚠️ Budget excedido: {provider.PROVIDER_NAME}',
                data={
                    'provider': provider.PROVIDER_ID,
                    'error_type': 'budget_exceeded',
                    'details': e.details,
                    'suggestion': 'Verifique seu plano de pagamento ou troque de provedor'
                }
            )
            logger.error(f"Budget excedido no {provider.PROVIDER_ID}: {e}")
            raise
            
        except RateLimitError as e:
            # Notificar rate limit
            notification_manager.add(
                notification_type='ai_warning',
                message=f'⏳ Rate limit atingido: {provider.PROVIDER_NAME}',
                data={
                    'provider': provider.PROVIDER_ID,
                    'error_type': 'rate_limit',
                    'retry_after': e.retry_after
                }
            )
            logger.warning(f"Rate limit no {provider.PROVIDER_ID}: {e}")
            raise
            
        except AuthenticationError as e:
            # Notificar erro de autenticação
            notification_manager.add(
                notification_type='ai_error',
                message=f'🔑 Erro de autenticação: {provider.PROVIDER_NAME}',
                data={
                    'provider': provider.PROVIDER_ID,
                    'error_type': 'authentication',
                    'suggestion': 'Verifique sua API key nas configurações'
                }
            )
            logger.error(f"Erro de autenticação no {provider.PROVIDER_ID}: {e}")
            raise
    
    def get_all_providers_status(self) -> List[Dict]:
        """Retorna status de todos os provedores."""
        result = []
        
        for provider_id, provider_class in self.PROVIDER_CLASSES.items():
            if provider_id in self._providers:
                provider = self._providers[provider_id]
                info = provider.to_dict()
                info["is_active"] = provider_id == self._active_provider_id
            else:
                # Provedor não inicializado
                info = {
                    "provider_id": provider_id,
                    "provider_name": provider_class.PROVIDER_NAME,
                    "status": "not_configured",
                    "is_enabled": False,
                    "is_active": False,
                    "current_model": None,
                    "available_models": [
                        {
                            "id": m.id,
                            "name": m.name,
                            "description": m.description
                        }
                        for m in provider_class.AVAILABLE_MODELS
                    ]
                }
            
            result.append(info)
        
        return result
    
    def _save_config(self):
        """Salva configuração atual em arquivo."""
        try:
            config = {
                "active_provider": self._active_provider_id,
                "providers": {}
            }
            
            for pid, provider in self._providers.items():
                config["providers"][pid] = {
                    "enabled": provider.is_enabled,
                    "model": provider.current_model
                }
            
            with open(self._config_file, 'w') as f:
                json.dump(config, f, indent=2)
                
        except Exception as e:
            logger.error(f"Erro ao salvar config de AI providers: {e}")
    
    def _load_config(self):
        """Carrega configuração de arquivo."""
        if not self._config_file.exists():
            return
        
        try:
            with open(self._config_file, 'r') as f:
                config = json.load(f)
            
            # Aplicar configurações
            if config.get("active_provider") in self._providers:
                self._active_provider_id = config["active_provider"]
            
            for pid, pconfig in config.get("providers", {}).items():
                if pid in self._providers:
                    provider = self._providers[pid]
                    
                    if pconfig.get("model"):
                        try:
                            provider.set_model(pconfig["model"])
                        except:
                            pass
                    
                    if pconfig.get("enabled"):
                        provider.enable()
                    else:
                        provider.disable()
                        
        except Exception as e:
            logger.error(f"Erro ao carregar config de AI providers: {e}")
    
    def get_usage_stats(self) -> List[Dict]:
        """Retorna estatísticas de uso de tokens por provedor."""
        result = []
        
        for provider_id, provider in self._providers.items():
            if hasattr(provider, 'usage_stats'):
                stats = provider.usage_stats
                result.append({
                    "provider": provider_id,
                    "model": provider.current_model,
                    "total_tokens": stats.get("total_tokens", 0),
                    "prompt_tokens": stats.get("prompt_tokens", 0),
                    "completion_tokens": stats.get("completion_tokens", 0),
                    "requests": stats.get("requests", 0),
                    "estimated_cost": stats.get("estimated_cost", 0.0)
                })
        
        return result


# Singleton
_ai_manager: Optional[AIProviderManager] = None


def get_ai_manager() -> AIProviderManager:
    """Retorna instância singleton do gerenciador de IA."""
    global _ai_manager
    if _ai_manager is None:
        _ai_manager = AIProviderManager()
        _ai_manager.initialize_from_env()
    return _ai_manager


def reset_ai_manager():
    """Reseta o gerenciador (útil para testes e reconfiguração)."""
    global _ai_manager
    _ai_manager = None
