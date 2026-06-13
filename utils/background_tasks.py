"""
Sistema de tarefas em background que funciona sem dependências externas.
Usa ThreadPoolExecutor para processamento assíncrono.

Pode ser substituído por Celery quando Redis estiver disponível.
"""

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class TaskStatus(Enum):
    """Status possíveis de uma task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """Resultado de uma task executada."""
    task_id: str
    task_name: str
    status: TaskStatus
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


@dataclass 
class ScheduledTask:
    """Task agendada para execução periódica."""
    name: str
    func: Callable
    interval_seconds: int
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    enabled: bool = True
    run_count: int = 0
    error_count: int = 0


class BackgroundTaskManager:
    """
    Gerenciador de tarefas em background usando ThreadPoolExecutor.
    Alternativa leve ao Celery para desenvolvimento e ambientes sem Redis.
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
    
    def __init__(self, max_workers: int = 4):
        if self._initialized:
            return
            
        self._initialized = True
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bg_task")
        
        # Tracking de tasks
        self._tasks: Dict[str, TaskResult] = {}
        self._task_counter = 0
        self._tasks_lock = threading.Lock()
        
        # Tasks agendadas
        self._scheduled_tasks: Dict[str, ScheduledTask] = {}
        self._scheduler_running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        
        logger.debug(f"🔄 BackgroundTaskManager inicializado com {max_workers} workers")
    
    def _generate_task_id(self) -> str:
        """Gera ID único para task."""
        with self._tasks_lock:
            self._task_counter += 1
            return f"task_{self._task_counter}_{int(time.time() * 1000)}"
    
    def submit(
        self, 
        func: Callable, 
        *args, 
        task_name: str = None,
        **kwargs
    ) -> str:
        """
        Submete uma task para execução em background.
        
        Args:
            func: Função a executar
            *args: Argumentos posicionais
            task_name: Nome descritivo da task
            **kwargs: Argumentos nomeados
            
        Returns:
            task_id: ID da task para tracking
        """
        task_id = self._generate_task_id()
        task_name = task_name or func.__name__
        
        # Registrar task
        task_result = TaskResult(
            task_id=task_id,
            task_name=task_name,
            status=TaskStatus.PENDING
        )
        
        with self._tasks_lock:
            self._tasks[task_id] = task_result
        
        def wrapped_func():
            """Wrapper para capturar resultado/erro."""
            task_result.status = TaskStatus.RUNNING
            task_result.started_at = datetime.utcnow()
            
            try:
                logger.debug(f"▶️ Executando task: {task_name} ({task_id})")
                result = func(*args, **kwargs)
                
                task_result.status = TaskStatus.COMPLETED
                task_result.result = result
                logger.debug(f"✅ Task concluída: {task_name} ({task_id})")
                
            except Exception as e:
                task_result.status = TaskStatus.FAILED
                task_result.error = str(e)
                logger.error(f"❌ Task falhou: {task_name} ({task_id}): {e}")
                
            finally:
                task_result.completed_at = datetime.utcnow()
                if task_result.started_at:
                    delta = task_result.completed_at - task_result.started_at
                    task_result.duration_ms = int(delta.total_seconds() * 1000)
        
        # Submeter para executor
        self.executor.submit(wrapped_func)
        logger.debug(f"📋 Task submetida: {task_name} ({task_id})")
        
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[TaskResult]:
        """Obtém status de uma task."""
        with self._tasks_lock:
            return self._tasks.get(task_id)
    
    def get_all_tasks(self, limit: int = 50) -> List[TaskResult]:
        """Lista últimas tasks."""
        with self._tasks_lock:
            tasks = list(self._tasks.values())
            return sorted(tasks, key=lambda t: t.started_at or datetime.min, reverse=True)[:limit]
    
    def get_running_tasks(self) -> List[TaskResult]:
        """Lista tasks em execução."""
        with self._tasks_lock:
            return [t for t in self._tasks.values() if t.status == TaskStatus.RUNNING]
    
    # === Tasks Agendadas ===
    
    def schedule(
        self,
        name: str,
        func: Callable,
        interval_seconds: int,
        run_immediately: bool = False
    ) -> None:
        """
        Agenda uma task para execução periódica.
        
        Args:
            name: Nome único da task
            func: Função a executar
            interval_seconds: Intervalo entre execuções
            run_immediately: Se deve executar imediatamente
        """
        now = datetime.utcnow()
        
        scheduled_task = ScheduledTask(
            name=name,
            func=func,
            interval_seconds=interval_seconds,
            next_run=now if run_immediately else now + timedelta(seconds=interval_seconds)
        )
        
        self._scheduled_tasks[name] = scheduled_task
        logger.debug(f"⏰ Task agendada: {name} (a cada {interval_seconds}s)")
        
        # Iniciar scheduler se não estiver rodando
        self._start_scheduler()
    
    def unschedule(self, name: str) -> bool:
        """Remove task agendada."""
        if name in self._scheduled_tasks:
            del self._scheduled_tasks[name]
            logger.debug(f"🗑️ Task removida do agendamento: {name}")
            return True
        return False
    
    def pause_scheduled(self, name: str) -> bool:
        """Pausa task agendada."""
        if name in self._scheduled_tasks:
            self._scheduled_tasks[name].enabled = False
            logger.debug(f"⏸️ Task pausada: {name}")
            return True
        return False
    
    def resume_scheduled(self, name: str) -> bool:
        """Resume task agendada."""
        if name in self._scheduled_tasks:
            self._scheduled_tasks[name].enabled = True
            logger.info(f"▶️ Task retomada: {name}")
            return True
        return False
    
    def run_scheduled_now(self, name: str) -> Optional[str]:
        """Executa task agendada imediatamente."""
        if name in self._scheduled_tasks:
            task = self._scheduled_tasks[name]
            return self.submit(task.func, task_name=f"{name}_manual")
        return None
    
    def get_scheduled_tasks(self) -> List[Dict]:
        """Lista todas tasks agendadas."""
        return [
            {
                'name': task.name,
                'interval_seconds': task.interval_seconds,
                'enabled': task.enabled,
                'last_run': task.last_run.isoformat() if task.last_run else None,
                'next_run': task.next_run.isoformat() if task.next_run else None,
                'run_count': task.run_count,
                'error_count': task.error_count
            }
            for task in self._scheduled_tasks.values()
        ]
    
    def _start_scheduler(self):
        """Inicia thread do scheduler."""
        if self._scheduler_running:
            return
            
        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="bg_scheduler"
        )
        self._scheduler_thread.start()
        logger.info("⏰ Scheduler de tasks iniciado")
    
    def _scheduler_loop(self):
        """Loop do scheduler que executa tasks no horário."""
        while self._scheduler_running:
            try:
                now = datetime.utcnow()
                
                for name, task in list(self._scheduled_tasks.items()):
                    if not task.enabled:
                        continue
                        
                    if task.next_run and now >= task.next_run:
                        # Executar task
                        try:
                            self.submit(task.func, task_name=f"{name}_scheduled")
                            task.last_run = now
                            task.run_count += 1
                        except Exception as e:
                            task.error_count += 1
                            logger.error(f"Erro ao agendar {name}: {e}")
                        
                        # Próxima execução
                        task.next_run = now + timedelta(seconds=task.interval_seconds)
                
                # Dormir 1 segundo antes de verificar novamente
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Erro no scheduler: {e}")
                time.sleep(5)
    
    def stop_scheduler(self):
        """Para o scheduler."""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        logger.info("⏹️ Scheduler parado")
    
    def shutdown(self, wait: bool = True):
        """Encerra o executor."""
        self.stop_scheduler()
        self.executor.shutdown(wait=wait)
        logger.info("🛑 BackgroundTaskManager encerrado")
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Remove tasks antigas do tracking."""
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        with self._tasks_lock:
            old_tasks = [
                task_id for task_id, task in self._tasks.items()
                if task.completed_at and task.completed_at < cutoff
            ]
            
            for task_id in old_tasks:
                del self._tasks[task_id]
            
            if old_tasks:
                logger.debug(f"🧹 Removidas {len(old_tasks)} tasks antigas")


# Instância global
_task_manager: Optional[BackgroundTaskManager] = None


def get_task_manager() -> BackgroundTaskManager:
    """Obtém instância global do task manager."""
    global _task_manager
    if _task_manager is None:
        _task_manager = BackgroundTaskManager()
    return _task_manager


def submit_task(func: Callable, *args, task_name: str = None, **kwargs) -> str:
    """Atalho para submeter task."""
    return get_task_manager().submit(func, *args, task_name=task_name, **kwargs)


def schedule_task(name: str, func: Callable, interval_seconds: int, run_immediately: bool = False):
    """Atalho para agendar task."""
    get_task_manager().schedule(name, func, interval_seconds, run_immediately)
