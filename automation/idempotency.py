"""
Idempotency Module - Garantias de envio único de mensagens.

Este módulo fornece:
- Verificação de idempotência pré-envio
- Lock de envio para evitar concorrência
- Validação de estado antes do envio
- Registro de tentativas de envio duplicado

PRINCÍPIO: Uma mensagem só pode ser enviada UMA VEZ para cada match.
Se houver QUALQUER dúvida, NÃO enviar.
"""

import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


class IdempotencyCheckResult(Enum):
    """Resultado da verificação de idempotência."""
    ALLOWED = "allowed"                    # Pode enviar
    ALREADY_SENT = "already_sent"          # Já enviou para este match
    LOCK_HELD = "lock_held"                # Outro processo está enviando
    MATCH_BLOCKED = "match_blocked"        # Match bloqueado/unmatch
    RECENT_ATTEMPT = "recent_attempt"      # Tentativa recente (possível duplicata)


@dataclass
class SendAttempt:
    """Registro de tentativa de envio."""
    match_id: str
    timestamp: datetime
    success: bool
    message_hash: str
    reason: str = ""


class IdempotencyGuard:
    """
    Guarda de idempotência para envio de mensagens.
    
    Implementa múltiplas camadas de proteção:
    1. Lock em memória por match_id (evita concorrência)
    2. Verificação de estado no banco ANTES do envio
    3. Registro de tentativas para auditoria
    4. Prevenção de reenvio em janela de tempo
    """
    
    _instance: Optional['IdempotencyGuard'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern para garantir único guard."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._match_locks: Dict[str, threading.Lock] = {}
        self._match_locks_lock = threading.Lock()
        self._active_sends: Set[str] = set()
        self._send_attempts: Dict[str, SendAttempt] = {}
        self._duplicate_count = 0
        self._blocked_count = 0
        
        logger.info("🔒 IdempotencyGuard inicializado")
    
    def _get_match_lock(self, tinder_match_id: str) -> threading.Lock:
        """Obtém ou cria lock para um match específico."""
        with self._match_locks_lock:
            if tinder_match_id not in self._match_locks:
                self._match_locks[tinder_match_id] = threading.Lock()
            return self._match_locks[tinder_match_id]
    
    def _hash_message(self, message: str) -> str:
        """Gera hash da mensagem para comparação."""
        return hashlib.md5(message.encode()).hexdigest()[:16]
    
    def check_can_send(
        self,
        tinder_match_id: str,
        session,
        Match
    ) -> Tuple[IdempotencyCheckResult, str]:
        """
        Verifica se pode enviar mensagem para este match.
        
        DEVE ser chamado ANTES de qualquer tentativa de envio.
        
        Args:
            tinder_match_id: ID do match no Tinder
            session: Sessão do banco de dados
            Match: Classe do modelo Match
            
        Returns:
            Tuple[IdempotencyCheckResult, str]: (resultado, motivo)
        """
        # 1. Verificar se há envio ativo (lock em memória)
        if tinder_match_id in self._active_sends:
            self._blocked_count += 1
            logger.warning(f"⚠️ BLOQUEADO: Envio já em andamento para {tinder_match_id}")
            return (IdempotencyCheckResult.LOCK_HELD, "Envio já em andamento")
        
        # 2. Buscar match no banco - estado REAL
        match = session.query(Match).filter(
            Match.tinder_match_id == tinder_match_id
        ).first()
        
        if not match:
            logger.warning(f"⚠️ Match {tinder_match_id} não encontrado no banco")
            return (IdempotencyCheckResult.MATCH_BLOCKED, "Match não encontrado")
        
        # 3. Verificar flags de envio
        if match.first_message_sent:
            self._duplicate_count += 1
            logger.warning(
                f"🚫 DUPLICATA PREVENIDA: {match.name} ({tinder_match_id}) "
                f"já tem first_message_sent=True"
            )
            return (IdempotencyCheckResult.ALREADY_SENT, "first_message_sent=True")
        
        if match.has_messages:
            self._duplicate_count += 1
            logger.warning(
                f"🚫 DUPLICATA PREVENIDA: {match.name} ({tinder_match_id}) "
                f"já tem has_messages=True"
            )
            return (IdempotencyCheckResult.ALREADY_SENT, "has_messages=True")
        
        # 4. Verificar se match está ativo
        if match.is_blocked or match.is_unmatched:
            logger.info(f"Match {match.name} bloqueado/unmatched - ignorando")
            return (IdempotencyCheckResult.MATCH_BLOCKED, "Match inativo")
        
        # 5. Verificar tentativa recente (proteção extra)
        recent_attempt = self._send_attempts.get(tinder_match_id)
        if recent_attempt:
            time_since = (datetime.utcnow() - recent_attempt.timestamp).total_seconds()
            if time_since < 300 and recent_attempt.success:  # 5 minutos
                self._duplicate_count += 1
                logger.warning(
                    f"🚫 DUPLICATA PREVENIDA: Tentativa recente bem-sucedida "
                    f"há {time_since:.0f}s para {tinder_match_id}"
                )
                return (IdempotencyCheckResult.RECENT_ATTEMPT, 
                       f"Envio bem-sucedido há {time_since:.0f}s")
        
        return (IdempotencyCheckResult.ALLOWED, "OK")
    
    @contextmanager
    def send_lock(self, tinder_match_id: str):
        """
        Context manager que garante envio único.
        
        Uso:
            with guard.send_lock(match_id):
                # Código de envio aqui
        """
        match_lock = self._get_match_lock(tinder_match_id)
        
        acquired = match_lock.acquire(blocking=False)
        if not acquired:
            logger.warning(f"⚠️ Não conseguiu lock para {tinder_match_id}")
            raise IdempotencyError(f"Lock não disponível para {tinder_match_id}")
        
        try:
            self._active_sends.add(tinder_match_id)
            yield
        finally:
            self._active_sends.discard(tinder_match_id)
            match_lock.release()
    
    def record_send_attempt(
        self,
        tinder_match_id: str,
        message: str,
        success: bool,
        reason: str = ""
    ):
        """Registra tentativa de envio para auditoria."""
        attempt = SendAttempt(
            match_id=tinder_match_id,
            timestamp=datetime.utcnow(),
            success=success,
            message_hash=self._hash_message(message),
            reason=reason
        )
        self._send_attempts[tinder_match_id] = attempt
        
        status = "✅ Sucesso" if success else "❌ Falha"
        logger.info(f"📝 Tentativa registrada: {tinder_match_id} - {status}")
    
    def get_stats(self) -> Dict:
        """Retorna estatísticas de idempotência."""
        return {
            "duplicates_prevented": self._duplicate_count,
            "blocked_by_lock": self._blocked_count,
            "active_sends": len(self._active_sends),
            "recorded_attempts": len(self._send_attempts),
            "match_locks_count": len(self._match_locks)
        }
    
    def reset(self):
        """Reseta estado do guard (usar com cuidado)."""
        with self._match_locks_lock:
            self._active_sends.clear()
            self._send_attempts.clear()
            self._duplicate_count = 0
            self._blocked_count = 0
        logger.info("🔄 IdempotencyGuard resetado")


class IdempotencyError(Exception):
    """Erro de violação de idempotência."""
    pass


def get_idempotency_guard() -> IdempotencyGuard:
    """Obtém instância singleton do guard."""
    return IdempotencyGuard()


# ==================== FUNÇÕES DE VERIFICAÇÃO DIRETA ====================

def verify_first_message_allowed(
    tinder_match_id: str,
    session,
    Match,
    Message
) -> Tuple[bool, str]:
    """
    Verificação completa se pode enviar primeira mensagem.
    
    Verifica:
    1. Match existe e está ativo
    2. first_message_sent == False
    3. has_messages == False
    4. Não existe mensagem is_from_me no banco
    
    Returns:
        Tuple[bool, str]: (pode_enviar, motivo)
    """
    # Buscar match
    match = session.query(Match).filter(
        Match.tinder_match_id == tinder_match_id
    ).first()
    
    if not match:
        return (False, "Match não encontrado")
    
    if match.is_blocked or match.is_unmatched:
        return (False, "Match bloqueado/unmatched")
    
    if match.first_message_sent:
        return (False, f"first_message_sent=True (valor atual no banco)")
    
    if match.has_messages:
        return (False, f"has_messages=True (valor atual no banco)")
    
    # Verificação extra: checar se existe mensagem minha no banco
    existing_my_message = session.query(Message).filter(
        Message.match_id == match.id,
        Message.is_from_me == True
    ).first()
    
    if existing_my_message:
        return (False, f"Já existe mensagem enviada por mim no banco (ID: {existing_my_message.id})")
    
    return (True, "Verificação OK - pode enviar")


def mark_first_message_sent_atomic(
    match,
    session,
    message_content: str,
    Message
) -> bool:
    """
    Marca match como tendo primeira mensagem enviada de forma atômica.
    
    DEVE ser chamado ANTES do envio real (pessimistic locking).
    Se o envio falhar, fazer rollback.
    
    Args:
        match: Objeto Match
        session: Sessão do banco
        message_content: Conteúdo da mensagem
        Message: Classe do modelo Message
        
    Returns:
        bool: True se marcou com sucesso
    """
    try:
        # Verificar novamente (dentro da transação)
        if match.first_message_sent or match.has_messages:
            logger.warning(f"Estado mudou durante transação para {match.tinder_match_id}")
            return False
        
        # Criar mensagem com status pending
        message = Message(
            match_id=match.id,
            content=message_content,
            is_from_me=True,
            message_type="first_message",
            ai_generated=True,
            sent_at=datetime.utcnow()
        )
        session.add(message)
        
        # Atualizar flags do match
        match.first_message_sent = True
        match.has_messages = True
        match.last_message_at = datetime.utcnow()
        match.last_interaction_at = datetime.utcnow()
        
        # Flush para validar (não commit ainda)
        session.flush()
        
        logger.debug(f"✅ Match {match.name} marcado como first_message_sent=True")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao marcar first_message_sent: {e}")
        return False
