"""
Serviço de Agendamento de Tarefas.
Gerencia tarefas agendadas como auto-ajuste de ML e limpeza de dados.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ScheduledTask:
    """Representa uma tarefa agendada."""
    name: str
    func: Callable
    interval_hours: float = 24  # Intervalo em horas
    last_run: datetime = None
    next_run: datetime = None
    enabled: bool = True
    run_count: int = 0
    last_error: str = None
    
    def should_run(self) -> bool:
        """Verifica se a tarefa deve executar."""
        if not self.enabled:
            return False
        if self.next_run is None:
            return True
        return datetime.utcnow() >= self.next_run
    
    def schedule_next(self):
        """Agenda próxima execução."""
        self.last_run = datetime.utcnow()
        self.next_run = self.last_run + timedelta(hours=self.interval_hours)


class SchedulerService:
    """
    Serviço de agendamento simples baseado em threading.
    
    Executa tarefas em intervalos configurados.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._check_interval = 60  # Verifica a cada 60 segundos
        
        # Registrar tarefas padrão
        self._register_default_tasks()
        
        self._initialized = True
        logger.info("SchedulerService inicializado")
    
    def _register_default_tasks(self):
        """Registra tarefas padrão do sistema."""
        # Auto-ajuste de ML (1x por dia)
        self.register_task(
            name="ml_auto_adjust",
            func=self._task_ml_auto_adjust,
            interval_hours=24,
            enabled=True
        )
        
        # Limpeza de logs antigos (1x por semana)
        self.register_task(
            name="cleanup_old_logs",
            func=self._task_cleanup_logs,
            interval_hours=168,  # 7 dias
            enabled=True
        )
        
        # Sincronização de dados ML com A/B Testing (4x por dia)
        self.register_task(
            name="ml_sync_ab",
            func=self._task_sync_ml_ab,
            interval_hours=6,
            enabled=True
        )
    
    def register_task(
        self,
        name: str,
        func: Callable,
        interval_hours: float = 24,
        enabled: bool = True
    ) -> bool:
        """
        Registra uma nova tarefa.
        
        Args:
            name: Nome único da tarefa
            func: Função a executar
            interval_hours: Intervalo em horas
            enabled: Se está habilitada
            
        Returns:
            True se registrada com sucesso
        """
        if name in self._tasks:
            logger.warning(f"Tarefa '{name}' já existe, atualizando...")
        
        self._tasks[name] = ScheduledTask(
            name=name,
            func=func,
            interval_hours=interval_hours,
            enabled=enabled,
            next_run=datetime.utcnow() + timedelta(hours=interval_hours)
        )
        
        logger.info(f"Tarefa '{name}' registrada (intervalo: {interval_hours}h)")
        return True
    
    def enable_task(self, name: str) -> bool:
        """Habilita uma tarefa."""
        if name not in self._tasks:
            return False
        self._tasks[name].enabled = True
        return True
    
    def disable_task(self, name: str) -> bool:
        """Desabilita uma tarefa."""
        if name not in self._tasks:
            return False
        self._tasks[name].enabled = False
        return True
    
    def run_task_now(self, name: str) -> bool:
        """Executa uma tarefa imediatamente."""
        if name not in self._tasks:
            return False
        
        task = self._tasks[name]
        self._execute_task(task)
        return True
    
    def start(self):
        """Inicia o scheduler em background."""
        if self._running:
            logger.warning("Scheduler já está rodando")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler iniciado")
    
    def stop(self):
        """Para o scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Scheduler parado")
    
    def _run_loop(self):
        """Loop principal do scheduler."""
        while self._running:
            try:
                for task in self._tasks.values():
                    if task.should_run():
                        self._execute_task(task)
            except Exception as e:
                logger.error(f"Erro no loop do scheduler: {e}")
            
            time.sleep(self._check_interval)
    
    def _execute_task(self, task: ScheduledTask):
        """Executa uma tarefa."""
        logger.info(f"Executando tarefa: {task.name}")
        
        try:
            task.func()
            task.run_count += 1
            task.last_error = None
            logger.info(f"Tarefa '{task.name}' concluída com sucesso")
        except Exception as e:
            task.last_error = str(e)
            logger.error(f"Erro na tarefa '{task.name}': {e}")
        finally:
            task.schedule_next()
    
    def get_status(self) -> Dict:
        """Retorna status do scheduler e tarefas."""
        return {
            "running": self._running,
            "check_interval_seconds": self._check_interval,
            "tasks": [
                {
                    "name": task.name,
                    "enabled": task.enabled,
                    "interval_hours": task.interval_hours,
                    "last_run": task.last_run.isoformat() if task.last_run else None,
                    "next_run": task.next_run.isoformat() if task.next_run else None,
                    "run_count": task.run_count,
                    "last_error": task.last_error
                }
                for task in self._tasks.values()
            ]
        }
    
    # ==================== TAREFAS PADRÃO ====================
    
    def _task_ml_auto_adjust(self):
        """Tarefa de auto-ajuste de ML."""
        try:
            from services.ml_adaptive import get_ml_service
            
            ml = get_ml_service()
            stats = ml.get_stats()
            
            adjusted = 0
            for exp_name in stats.get('experiments', []):
                if ml.auto_adjust_weights(exp_name, min_samples=50):
                    adjusted += 1
                    logger.info(f"Auto-ajuste aplicado em: {exp_name}")
            
            logger.info(f"ML Auto-Adjust: {adjusted} experimentos ajustados")
            
        except Exception as e:
            logger.error(f"Erro no ML auto-adjust: {e}")
            raise
    
    def _task_cleanup_logs(self):
        """Tarefa de limpeza de logs antigos."""
        try:
            import os
            from pathlib import Path

            from config.settings import PROJECT_ROOT
            
            logs_dir = PROJECT_ROOT / 'logs'
            if not logs_dir.exists():
                return
            
            cutoff = datetime.utcnow() - timedelta(days=30)
            deleted = 0
            
            for log_file in logs_dir.glob('*.log'):
                try:
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if mtime < cutoff:
                        log_file.unlink()
                        deleted += 1
                except Exception as e:
                    logger.warning(f"Erro ao deletar {log_file}: {e}")
            
            logger.info(f"Cleanup: {deleted} arquivos de log removidos")
            
        except Exception as e:
            logger.error(f"Erro na limpeza de logs: {e}")
            raise
    
    def _task_sync_ml_ab(self):
        """Tarefa de sincronização ML com A/B Testing."""
        try:
            from services.ml_adaptive import get_ml_service
            
            ml = get_ml_service()
            ml._sync_with_ab()
            
            logger.info("ML sincronizado com A/B Testing")
            
        except Exception as e:
            logger.error(f"Erro na sincronização ML/AB: {e}")
            raise


# Singleton
_scheduler: Optional[SchedulerService] = None


def get_scheduler() -> SchedulerService:
    """Retorna instância singleton do scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService()
    return _scheduler


def start_scheduler():
    """Inicia o scheduler global."""
    scheduler = get_scheduler()
    scheduler.start()
    return scheduler


def stop_scheduler():
    """Para o scheduler global."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
