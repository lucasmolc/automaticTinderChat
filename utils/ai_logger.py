"""
AI Interaction Logger - Helper centralizado para logging de interações com IA.
Evita duplicação de código ao registrar interações em diferentes partes do sistema.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from utils.helpers import safe_json_dumps
from utils.logger import get_logger

# Import lazy para evitar circular import
if TYPE_CHECKING:
    from database import AIInteractionRepository, DatabaseManager

logger = get_logger(__name__)


class AIInteractionLogger:
    """
    Logger centralizado para interações com IA.
    
    Uso:
        with AIInteractionLogger.log_interaction(
            interaction_type="first_message",
            model="gpt-4o-mini",
            match_id=123,
            provider="openai"
        ) as log:
            result = openai.generate_message(...)
            log.set_result(result)
    """
    
    def __init__(
        self,
        interaction_type: str,
        model_used: str,
        match_id: Optional[int] = None,
        prompt_template: Optional[str] = None,
        provider: Optional[str] = None,
        session=None
    ):
        self.interaction_type = interaction_type
        self.model_used = model_used
        self.match_id = match_id
        self.prompt_template = prompt_template
        self.provider = provider or self._detect_provider(model_used)
        self._session = session
        self._owns_session = session is None
        self._interaction = None
        self._result: Optional[Dict] = None
        self._error: Optional[str] = None
        self._start_time = None
    
    @staticmethod
    def _detect_provider(model: str) -> str:
        """Detecta o provider baseado no nome do modelo."""
        if model and 'deepseek' in model.lower():
            return 'deepseek'
        return 'openai'
    
    def __enter__(self):
        """Inicia o logging da interação."""
        # Import lazy para evitar circular import
        from database import AIInteractionRepository, get_db_manager
        
        self._start_time = datetime.utcnow()
        
        if self._owns_session:
            self._db = get_db_manager()
            self._session_ctx = self._db.get_session()
            self._session = self._session_ctx.__enter__()
        
        repo = AIInteractionRepository(self._session)
        self._interaction = repo.create(
            interaction_type=self.interaction_type,
            model_used=self.model_used,
            match_id=self.match_id,
            prompt_template=self.prompt_template,
            provider=self.provider
        )
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Finaliza o logging da interação."""
        # Import lazy para evitar circular import
        from database import AIInteractionRepository
        
        repo = AIInteractionRepository(self._session)
        
        if exc_type is not None:
            # Houve exceção
            repo.fail(self._interaction, str(exc_val))
            logger.error(f"AI interaction failed: {exc_val}")
        elif self._error:
            # Erro setado manualmente
            repo.fail(self._interaction, self._error)
        elif self._result:
            # Sucesso com resultado
            metadata = self._result.get("_metadata", {})
            
            # Calcular tempo de resposta se não fornecido
            response_time = metadata.get("response_time_ms")
            if response_time is None and self._start_time:
                response_time = int((datetime.utcnow() - self._start_time).total_seconds() * 1000)
            
            repo.complete(
                self._interaction,
                response_content=safe_json_dumps(self._result),
                prompt_tokens=metadata.get("prompt_tokens", 0),
                completion_tokens=metadata.get("completion_tokens", 0),
                response_time_ms=response_time or 0
            )
        else:
            # Sem resultado definido - marcar como falha
            repo.fail(self._interaction, "No result set")
        
        if self._owns_session:
            self._session_ctx.__exit__(exc_type, exc_val, exc_tb)
        
        # Não suprimir exceções
        return False
    
    def set_result(self, result: Dict) -> None:
        """Define o resultado da interação."""
        self._result = result
    
    def set_error(self, error: str) -> None:
        """Define erro na interação."""
        self._error = error
    
    @classmethod
    def log_interaction(
        cls,
        interaction_type: str,
        model_used: str,
        match_id: Optional[int] = None,
        prompt_template: Optional[str] = None,
        provider: Optional[str] = None,
        session=None
    ) -> "AIInteractionLogger":
        """
        Factory method para criar um context manager de logging.
        
        Args:
            interaction_type: Tipo da interação (first_message, response, profile_analysis)
            model_used: Modelo de IA usado
            match_id: ID do match relacionado (opcional)
            prompt_template: Template de prompt usado (opcional)
            provider: Provedor de IA (openai, deepseek) - auto-detectado se não fornecido
            session: Sessão do banco de dados (opcional, cria uma nova se não fornecida)
        
        Returns:
            AIInteractionLogger context manager
        """
        return cls(
            interaction_type=interaction_type,
            model_used=model_used,
            match_id=match_id,
            prompt_template=prompt_template,
            provider=provider,
            session=session
        )


def log_ai_interaction(
    interaction_type: str,
    prompt: str = None,
    response: str = None,
    model_used: str = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    response_time_ms: int = 0,
    success: bool = True,
    provider: str = None,
    match_id: int = None,
    session = None,
    ai_result: Dict = None
) -> None:
    """
    Função helper para registrar interação com IA.
    
    Suporta dois modos de uso:
    1. Parâmetros diretos (novo): log_ai_interaction(type, prompt=..., response=..., etc.)
    2. Legado com ai_result: passa ai_result como dict com _metadata
    
    Args:
        interaction_type: Tipo da interação
        prompt: Texto do prompt (opcional)
        response: Texto da resposta (opcional)
        model_used: Modelo de IA usado
        prompt_tokens: Tokens do prompt
        completion_tokens: Tokens da resposta
        response_time_ms: Tempo de resposta em ms
        success: Se a chamada foi bem sucedida
        provider: Provedor de IA (openai, deepseek) - auto-detectado se não fornecido
        match_id: ID do match (opcional)
        session: Sessão do banco (opcional, criada automaticamente)
        ai_result: Resultado da IA legado (opcional, para compatibilidade)
    """
    # Import lazy para evitar circular import
    from database import AIInteractionRepository
    
    # Detectar provider pelo modelo se não fornecido
    if not provider:
        if model_used and 'deepseek' in model_used.lower():
            provider = 'deepseek'
        else:
            provider = 'openai'
    
    # Modo legado: ai_result passado como dict
    if ai_result is not None and isinstance(ai_result, dict):
        metadata = ai_result.get("_metadata", {})
        prompt_tokens = metadata.get("prompt_tokens", prompt_tokens)
        completion_tokens = metadata.get("completion_tokens", completion_tokens)
        response_time_ms = metadata.get("response_time_ms", response_time_ms)
        model_used = metadata.get("model", model_used)
        response = safe_json_dumps(ai_result)
    
    # Se session não foi passada, criar uma nova
    if session is None:
        from database import get_db_manager
        db = get_db_manager()
        with db.get_session() as session:
            _log_ai_interaction_internal(
                session, interaction_type, model_used, prompt_tokens,
                completion_tokens, response_time_ms, success, provider,
                match_id, prompt, response
            )
    else:
        _log_ai_interaction_internal(
            session, interaction_type, model_used, prompt_tokens,
            completion_tokens, response_time_ms, success, provider,
            match_id, prompt, response
        )


def _log_ai_interaction_internal(
    session,
    interaction_type: str,
    model_used: str,
    prompt_tokens: int,
    completion_tokens: int,
    response_time_ms: int,
    success: bool,
    provider: str,
    match_id: int,
    prompt: str,
    response: str
) -> None:
    """Implementação interna do log de interação."""
    from database import AIInteractionRepository
    
    repo = AIInteractionRepository(session)
    
    # Calcular custo estimado
    cost = repo.calculate_cost(model_used, prompt_tokens, completion_tokens)
    
    interaction = repo.create(
        interaction_type=interaction_type,
        model_used=model_used,
        match_id=match_id,
        prompt_template=prompt[:500] if prompt else None,  # Truncar para caber na coluna VARCHAR(500)
        provider=provider
    )
    
    if success:
        repo.complete(
            interaction,
            response_content=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            response_time_ms=response_time_ms
        )
        # Atualizar custo calculado
        interaction.estimated_cost = cost
    else:
        repo.fail(interaction, response or "Unknown error")


def log_ai_error(
    interaction_type: str,
    error_message: str,
    model_used: str = None,
    match_id: Optional[int] = None,
    prompt_template: Optional[str] = None,
    provider: Optional[str] = None,
    session = None
) -> None:
    """
    Função helper para registrar erro em interação com IA.
    
    Args:
        interaction_type: Tipo da interação
        error_message: Mensagem de erro
        model_used: Modelo de IA usado
        match_id: ID do match (opcional)
        prompt_template: Template usado (opcional)
        provider: Provedor de IA (opcional, auto-detectado)
        session: Sessão do banco (opcional, criada automaticamente)
    """
    # Import lazy para evitar circular import
    from database import AIInteractionRepository, DatabaseManager
    
    # Detectar provider
    if not provider:
        if model_used and 'deepseek' in model_used.lower():
            provider = 'deepseek'
        else:
            provider = 'openai'
    
    def _log_error(session):
        repo = AIInteractionRepository(session)
        interaction = repo.create(
            interaction_type=interaction_type,
            model_used=model_used,
            match_id=match_id,
            prompt_template=prompt_template,
            provider=provider
        )
        repo.fail(interaction, error_message)
    
    if session is None:
        from database import get_db_manager
        db = get_db_manager()
        with db.get_session() as session:
            _log_error(session)
    else:
        _log_error(session)
