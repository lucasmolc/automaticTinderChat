"""
Sistema de Audit Log para segurança e rastreabilidade.
Registra ações críticas do sistema para compliance e debugging.

Funcionalidades:
- Logging estruturado de ações
- Persistência em banco de dados
- Exportação de logs
- Filtros por tipo, data, usuário
"""

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Dict, List, Optional

from loguru import logger


class AuditAction(str, Enum):
    """Tipos de ações auditáveis."""
    # Automação
    AUTOMATION_START = "automation.start"
    AUTOMATION_STOP = "automation.stop"
    AUTOMATION_CONFIG_CHANGE = "automation.config_change"
    
    # Mensagens
    MESSAGE_SENT = "message.sent"
    MESSAGE_AI_GENERATED = "message.ai_generated"
    MESSAGE_MANUAL = "message.manual"
    
    # Matches
    MATCH_CREATED = "match.created"
    MATCH_TEMPERATURE_CHANGE = "match.temperature_change"
    MATCH_WHATSAPP_OBTAINED = "match.whatsapp_obtained"
    MATCH_DATE_CONFIRMED = "match.date_confirmed"
    MATCH_ARCHIVED = "match.archived"
    
    # Sistema
    LOGIN = "system.login"
    LOGOUT = "system.logout"
    CONFIG_CHANGE = "system.config_change"
    API_KEY_CHANGE = "system.api_key_change"
    
    # Dados
    DATA_EXPORT = "data.export"
    DATA_DELETE = "data.delete"
    DATA_BACKUP = "data.backup"
    
    # Erros
    ERROR_CRITICAL = "error.critical"
    ERROR_API = "error.api"
    ERROR_DATABASE = "error.database"


@dataclass
class AuditEntry:
    """Entrada de audit log."""
    action: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = field(default_factory=dict)
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'action': self.action,
            'timestamp': self.timestamp.isoformat(),
            'details': self.details,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'success': self.success,
            'error_message': self.error_message
        }


class AuditLogger:
    """
    Gerencia audit logs.
    Thread-safe com buffer para escrita em lote.
    """
    
    def __init__(self, db_manager=None, buffer_size: int = 100):
        self._buffer: List[AuditEntry] = []
        self._buffer_size = buffer_size
        self._lock = threading.Lock()
        self._db_manager = db_manager
        
        # Para persistência em arquivo (fallback)
        from config.settings import PROJECT_ROOT
        self._log_dir = PROJECT_ROOT / 'logs' / 'audit'
        self._log_dir.mkdir(parents=True, exist_ok=True)
    
    def log(
        self,
        action: AuditAction,
        details: Optional[Dict] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ):
        """
        Registra uma ação no audit log.
        
        Args:
            action: Tipo de ação (AuditAction)
            details: Detalhes adicionais da ação
            resource_type: Tipo de recurso afetado
            resource_id: ID do recurso afetado
            user_id: ID do usuário
            ip_address: IP de origem
            success: Se a ação foi bem sucedida
            error_message: Mensagem de erro se falhou
        """
        entry = AuditEntry(
            action=action.value if isinstance(action, AuditAction) else action,
            details=details or {},
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            ip_address=ip_address,
            success=success,
            error_message=error_message
        )
        
        with self._lock:
            self._buffer.append(entry)
            
            # Flush se buffer cheio
            if len(self._buffer) >= self._buffer_size:
                self._flush()
        
        # Log também no loguru para visibilidade imediata
        log_msg = f"📋 AUDIT: {entry.action}"
        if resource_type:
            log_msg += f" | {resource_type}"
        if resource_id:
            log_msg += f":{resource_id[:8]}..."
        
        if success:
            logger.info(log_msg)
        else:
            logger.warning(f"{log_msg} | FAILED: {error_message}")
    
    def _flush(self):
        """Persiste buffer no banco/arquivo."""
        if not self._buffer:
            return
        
        entries_to_save = self._buffer.copy()
        self._buffer.clear()
        
        # Tenta salvar no banco de dados
        if self._db_manager:
            try:
                self._save_to_db(entries_to_save)
                return
            except Exception as e:
                logger.warning(f"Falha ao salvar audit no DB: {e}, usando arquivo")
        
        # Fallback para arquivo
        self._save_to_file(entries_to_save)
    
    def _save_to_db(self, entries: List[AuditEntry]):
        """Salva entries no banco de dados."""
        # Implementação será feita quando integrar com DatabaseManager
        raise NotImplementedError("DB persistence not implemented")
    
    def _save_to_file(self, entries: List[AuditEntry]):
        """Salva entries em arquivo JSON."""
        today = datetime.utcnow().strftime('%Y-%m-%d')
        log_file = self._log_dir / f'audit_{today}.json'
        
        # Ler entries existentes
        existing = []
        if log_file.exists():
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except:
                existing = []
        
        # Adicionar novas entries
        existing.extend([e.to_dict() for e in entries])
        
        # Salvar
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
    
    def get_logs(
        self,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        success_only: bool = False,
        limit: int = 100
    ) -> List[Dict]:
        """
        Recupera logs filtrados.
        
        Args:
            action: Filtrar por tipo de ação
            resource_type: Filtrar por tipo de recurso
            start_date: Data início
            end_date: Data fim
            success_only: Apenas ações bem sucedidas
            limit: Limite de resultados
            
        Returns:
            Lista de entries
        """
        # Por enquanto, ler de arquivos
        all_entries = []
        
        # Determinar arquivos a ler
        if start_date is None:
            start_date = datetime.utcnow() - timedelta(days=7)
        if end_date is None:
            end_date = datetime.utcnow()
        
        current = start_date
        while current <= end_date:
            date_str = current.strftime('%Y-%m-%d')
            log_file = self._log_dir / f'audit_{date_str}.json'
            
            if log_file.exists():
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        entries = json.load(f)
                        all_entries.extend(entries)
                except Exception as e:
                    logger.warning(f"Erro ao ler {log_file}: {e}")
            
            current += timedelta(days=1)
        
        # Incluir buffer atual
        with self._lock:
            all_entries.extend([e.to_dict() for e in self._buffer])
        
        # Aplicar filtros
        filtered = []
        for entry in all_entries:
            # Filtro por ação
            if action and entry.get('action') != action:
                continue
            
            # Filtro por tipo de recurso
            if resource_type and entry.get('resource_type') != resource_type:
                continue
            
            # Filtro por sucesso
            if success_only and not entry.get('success', True):
                continue
            
            filtered.append(entry)
        
        # Ordenar por timestamp decrescente
        filtered.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return filtered[:limit]
    
    def flush(self):
        """Força flush do buffer."""
        with self._lock:
            self._flush()
    
    def get_summary(self, days: int = 7) -> Dict:
        """
        Retorna resumo de atividades.
        
        Args:
            days: Número de dias para análise
            
        Returns:
            Resumo estatístico
        """
        start_date = datetime.utcnow() - timedelta(days=days)
        logs = self.get_logs(start_date=start_date, limit=10000)
        
        # Contar por tipo de ação
        action_counts = {}
        success_count = 0
        failure_count = 0
        
        for log in logs:
            action = log.get('action', 'unknown')
            action_counts[action] = action_counts.get(action, 0) + 1
            
            if log.get('success', True):
                success_count += 1
            else:
                failure_count += 1
        
        return {
            'period_days': days,
            'total_events': len(logs),
            'success_count': success_count,
            'failure_count': failure_count,
            'success_rate': round(success_count / len(logs) * 100, 2) if logs else 0,
            'action_breakdown': action_counts
        }


# Instância global
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Retorna instância global do audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def audit(
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id_param: Optional[str] = None
):
    """
    Decorator para audit logging automático.
    
    Usage:
        @audit(AuditAction.MESSAGE_SENT, resource_type='match')
        def send_message(match_id: str, content: str):
            ...
    
    Args:
        action: Tipo de ação
        resource_type: Tipo de recurso
        resource_id_param: Nome do parâmetro que contém o ID do recurso
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            audit_logger = get_audit_logger()
            
            # Tentar extrair resource_id
            resource_id = None
            if resource_id_param:
                resource_id = kwargs.get(resource_id_param)
                if resource_id is None and args:
                    # Tentar primeiro argumento posicional
                    import inspect
                    sig = inspect.signature(func)
                    params = list(sig.parameters.keys())
                    if resource_id_param in params:
                        idx = params.index(resource_id_param)
                        if idx < len(args):
                            resource_id = args[idx]
            
            try:
                result = func(*args, **kwargs)
                
                audit_logger.log(
                    action=action,
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    details={'function': func.__name__}
                )
                
                return result
                
            except Exception as e:
                audit_logger.log(
                    action=action,
                    resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    success=False,
                    error_message=str(e),
                    details={'function': func.__name__}
                )
                raise
        
        return wrapper
    return decorator


# Funções de conveniência para ações comuns
def audit_automation_start(details: Dict = None):
    """Log início de automação."""
    get_audit_logger().log(
        AuditAction.AUTOMATION_START,
        details=details,
        resource_type='automation'
    )


def audit_automation_stop(details: Dict = None):
    """Log parada de automação."""
    get_audit_logger().log(
        AuditAction.AUTOMATION_STOP,
        details=details,
        resource_type='automation'
    )


def audit_message_sent(match_id: str, ai_generated: bool = False, details: Dict = None):
    """Log envio de mensagem."""
    action = AuditAction.MESSAGE_AI_GENERATED if ai_generated else AuditAction.MESSAGE_MANUAL
    get_audit_logger().log(
        action,
        details=details or {},
        resource_type='match',
        resource_id=match_id
    )


def audit_match_update(match_id: str, update_type: str, details: Dict = None):
    """Log atualização de match."""
    action_map = {
        'temperature': AuditAction.MATCH_TEMPERATURE_CHANGE,
        'whatsapp': AuditAction.MATCH_WHATSAPP_OBTAINED,
        'date': AuditAction.MATCH_DATE_CONFIRMED,
        'archive': AuditAction.MATCH_ARCHIVED
    }
    action = action_map.get(update_type, AuditAction.MATCH_CREATED)
    
    get_audit_logger().log(
        action,
        details=details or {},
        resource_type='match',
        resource_id=match_id
    )


def audit_config_change(config_key: str, old_value: Any, new_value: Any):
    """Log mudança de configuração."""
    # Mascarar valores sensíveis
    sensitive_keys = ['api_key', 'password', 'secret', 'token']
    is_sensitive = any(k in config_key.lower() for k in sensitive_keys)
    
    get_audit_logger().log(
        AuditAction.CONFIG_CHANGE,
        details={
            'key': config_key,
            'old_value': '***' if is_sensitive else str(old_value)[:100],
            'new_value': '***' if is_sensitive else str(new_value)[:100]
        },
        resource_type='config',
        resource_id=config_key
    )


def audit_error(error_type: str, error_message: str, details: Dict = None):
    """Log de erro."""
    action_map = {
        'api': AuditAction.ERROR_API,
        'database': AuditAction.ERROR_DATABASE,
        'critical': AuditAction.ERROR_CRITICAL
    }
    action = action_map.get(error_type, AuditAction.ERROR_CRITICAL)
    
    get_audit_logger().log(
        action,
        details=details or {},
        success=False,
        error_message=error_message
    )
