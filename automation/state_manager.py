"""
Gerenciador de estado global da automação.
Permite controlar início/parada da automação de qualquer lugar.

IMPORTANTE: O estado é persistido em arquivo JSON para sobreviver a:
- Refreshes da página web
- Reinicializações do servidor Flask
- Múltiplos processos/threads acessando o mesmo estado
"""

import json
import os
import signal
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

from loguru import logger

# Arquivo de controle de estado
STATE_FILE = Path(__file__).parent.parent / "data" / "automation_state.json"
# Arquivo de lock para evitar race conditions
LOCK_FILE = Path(__file__).parent.parent / "data" / "automation_state.lock"

# Tempo máximo (em segundos) que um estado "is_running" é considerado válido sem atualização
MAX_STALE_STATE_SECONDS = 300  # 5 minutos

# Tempo máximo (em segundos) que um sync pode ficar sem atualizar heartbeat
# Syncs longos atualizam heartbeat periodicamente; se exceder, é considerado travado
MAX_STALE_SYNC_SECONDS = 600  # 10 minutos


class AutomationStateManager:
    """
    Gerencia o estado da automação de forma persistente.
    
    CRÍTICO: O estado é SEMPRE lido do arquivo para garantir consistência
    entre múltiplos processos (ex: thread de automação vs requests HTTP).
    """
    
    _instance = None
    _lock = Lock()
    
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
        
        self._initialized = True
        self._default_state = {
            "is_running": False,
            "is_syncing": False,
            "should_stop": False,
            "dry_run": False,
            "current_cycle": 0,
            "started_at": None,
            "last_cycle_at": None,
            "sync_heartbeat_at": None,  # Heartbeat do sync para detecção de stale
            "interval_minutes": 10,
            "pid": None,  # PID do processo de automação
            "stats": {
                "cycles_completed": 0,
                "messages_sent": 0,
                "errors": 0
            }
        }
        
        # Criar diretório se não existir
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Verificar se há processo órfão (crash anterior)
        self._check_orphan_process()
    
    def _is_process_alive(self, pid: int) -> bool:
        """
        Verifica se um processo com o PID dado está rodando.
        Funciona em Windows e Unix sem dependência de psutil.
        """
        if pid is None:
            return False
        
        try:
            if os.name == 'nt':  # Windows
                # No Windows, usamos tasklist ou diretamente o kernel32
                import ctypes
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x00100000
                process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                if process:
                    kernel32.CloseHandle(process)
                    return True
                return False
            else:  # Unix/Linux/Mac
                # Enviar signal 0 não mata o processo, apenas verifica se existe
                os.kill(pid, 0)
                return True
        except (OSError, ProcessLookupError, PermissionError):
            return False
        except Exception:
            # Em caso de erro, assume que não está rodando
            return False
    
    def _is_state_stale(self, state: Dict) -> bool:
        """
        Verifica se o estado está "stale" (muito tempo sem atualização).
        Se o processo não atualizou o estado há mais de MAX_STALE_STATE_SECONDS,
        consideramos que crashou.
        """
        last_update = state.get("last_cycle_at") or state.get("started_at")
        if not last_update:
            return True
        
        try:
            if isinstance(last_update, str):
                last_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
            else:
                last_dt = last_update
            
            # Calcular tempo desde última atualização
            elapsed = (datetime.utcnow() - last_dt.replace(tzinfo=None)).total_seconds()
            return elapsed > MAX_STALE_STATE_SECONDS
        except Exception:
            return True
    
    def _is_sync_stale(self, state: Dict) -> bool:
        """
        Verifica se o sync está "stale" (travado sem atualizar heartbeat).
        Usa sync_heartbeat_at que é atualizado periodicamente durante o sync.
        """
        heartbeat = state.get("sync_heartbeat_at")
        if not heartbeat:
            # Sem heartbeat mas is_syncing=True → estado inconsistente, considerar stale
            return True
        
        try:
            if isinstance(heartbeat, str):
                heartbeat_dt = datetime.fromisoformat(heartbeat.replace('Z', '+00:00'))
            else:
                heartbeat_dt = heartbeat
            
            elapsed = (datetime.utcnow() - heartbeat_dt.replace(tzinfo=None)).total_seconds()
            return elapsed > MAX_STALE_SYNC_SECONDS
        except Exception:
            return True
    
    def update_sync_heartbeat(self):
        """
        Atualiza o heartbeat do sync para indicar que ainda está ativo.
        Deve ser chamado periodicamente durante operações longas de sync.
        """
        state = self._read_state()
        if state.get("is_syncing"):
            state["sync_heartbeat_at"] = datetime.utcnow().isoformat()
            self._write_state(state)
    
    def _check_orphan_process(self):
        """
        Verifica se há um processo de automação/sync que crashou.
        Se o PID salvo não existe mais OU o estado está stale, limpa o estado.
        """
        try:
            state = self._read_state()
            
            # Verificar is_running órfão
            if state.get("is_running"):
                pid = state.get("pid")
                
                # Caso 1: Não há PID salvo (estado inconsistente)
                if not pid:
                    logger.warning("Estado 'is_running' sem PID. Limpando estado órfão.")
                    self._reset_state()
                    return
                
                # Caso 2: Processo não existe mais
                if not self._is_process_alive(pid):
                    logger.warning(f"Processo de automação não existe mais (PID {pid}). Limpando estado órfão.")
                    self._reset_state()
                    return
                
                # Caso 3: Processo existe mas estado está stale (processo travou)
                if self._is_state_stale(state):
                    logger.warning(f"Estado stale detectado (PID {pid}). Processo pode ter travado. Limpando.")
                    self._reset_state()
                    return
            
            # Verificar is_syncing órfão (sem PID, processo morto, ou stale)
            if state.get("is_syncing"):
                pid = state.get("pid")
                
                # Se não tem PID ou processo não existe, limpar
                if not pid or not self._is_process_alive(pid):
                    logger.warning(f"Estado 'is_syncing' órfão detectado (PID: {pid}). Limpando.")
                    state["is_syncing"] = False
                    state["sync_heartbeat_at"] = None
                    self._write_state(state)
                    return
                
                # Verificar se sync está stale (sem heartbeat por muito tempo)
                if self._is_sync_stale(state):
                    logger.warning(f"Estado 'is_syncing' stale detectado (PID: {pid}). Sync travou. Limpando.")
                    state["is_syncing"] = False
                    state["sync_heartbeat_at"] = None
                    self._write_state(state)
                    return
                    
        except Exception as e:
            logger.debug(f"Erro ao verificar processo órfão: {e}")
    
    def _read_state(self) -> Dict:
        """Lê estado do arquivo (sempre lê do disco para consistência)."""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Erro ao ler estado: {e}")
        return self._default_state.copy()
    
    def _write_state(self, state: Dict):
        """Escreve estado no arquivo de forma atômica."""
        try:
            # Escrever em arquivo temporário primeiro
            temp_file = STATE_FILE.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, default=str)
            
            # Mover atomicamente
            temp_file.replace(STATE_FILE)
        except Exception as e:
            logger.error(f"Erro ao salvar estado: {e}")
    
    def _reset_state(self):
        """Reseta estado para valores padrão."""
        self._write_state(self._default_state.copy())
    
    def force_reset(self):
        """
        Força reset do estado (uso externo).
        Útil para limpar estados travados manualmente.
        """
        logger.warning("[StateManager] Forçando reset do estado")
        self._reset_state()
        return True
    
    def check_and_cleanup(self) -> bool:
        """
        Verifica estado atual e limpa se necessário.
        Retorna True se estava limpo ou foi limpo, False se está realmente rodando.
        """
        state = self._read_state()
        
        if not state.get("is_running"):
            return True  # Não está rodando
        
        pid = state.get("pid")
        
        # Se não tem PID, estado inválido
        if not pid:
            logger.info("Estado sem PID, limpando...")
            self._reset_state()
            return True
        
        # Se é o mesmo processo atual, está rodando
        if pid == os.getpid():
            return False  # Realmente rodando neste processo
        
        # Se processo não existe, limpar
        if not self._is_process_alive(pid):
            logger.info(f"Processo {pid} não existe mais, limpando estado...")
            self._reset_state()
            return True
        
        # Se estado está stale, limpar
        if self._is_state_stale(state):
            logger.info(f"Estado stale (PID {pid}), limpando...")
            self._reset_state()
            return True
        
        # Processo existe e estado é recente - realmente rodando
        return False
    
    @property
    def is_running(self) -> bool:
        """Lê is_running sempre do arquivo, verificando se é válido."""
        state = self._read_state()
        
        if not state.get("is_running"):
            return False
        
        # Verificar se o processo ainda existe
        pid = state.get("pid")
        if pid and not self._is_process_alive(pid):
            # Processo morreu, limpar estado automaticamente
            logger.debug(f"Processo {pid} não existe mais, auto-limpando estado")
            self._reset_state()
            return False
        
        return True
    
    @is_running.setter
    def is_running(self, value: bool):
        state = self._read_state()
        state["is_running"] = value
        if value:
            state["started_at"] = datetime.utcnow().isoformat()
            state["should_stop"] = False
            state["pid"] = os.getpid()  # Salvar PID do processo
        else:
            state["pid"] = None
        self._write_state(state)
    
    @property
    def is_syncing(self) -> bool:
        """Lê is_syncing sempre do arquivo, verificando se é válido."""
        state = self._read_state()
        
        if not state.get("is_syncing"):
            return False
        
        # Verificar se o processo ainda existe
        pid = state.get("pid")
        if pid and not self._is_process_alive(pid):
            # Processo morreu, limpar estado automaticamente
            logger.debug(f"Processo de sync {pid} não existe mais, auto-limpando estado")
            state["is_syncing"] = False
            state["sync_heartbeat_at"] = None
            state["pid"] = None
            self._write_state(state)
            return False
        
        # Se não tem PID mas está marcado como syncing, é estado órfão
        if not pid:
            logger.debug("Estado is_syncing sem PID, auto-limpando")
            state["is_syncing"] = False
            state["sync_heartbeat_at"] = None
            self._write_state(state)
            return False
        
        # Verificar se sync está stale (travou sem atualizar heartbeat)
        if self._is_sync_stale(state):
            logger.warning(f"Sync stale detectado (PID {pid} vivo mas sem heartbeat). Auto-limpando.")
            state["is_syncing"] = False
            state["sync_heartbeat_at"] = None
            self._write_state(state)
            return False
        
        return True
    
    @is_syncing.setter
    def is_syncing(self, value: bool):
        state = self._read_state()
        state["is_syncing"] = value
        if value:
            state["pid"] = os.getpid()  # Salvar PID do processo de sync
            state["sync_heartbeat_at"] = datetime.utcnow().isoformat()  # Heartbeat inicial
        else:
            state["sync_heartbeat_at"] = None
            if not state.get("is_running"):
                # Só limpa PID se não está rodando automação
                state["pid"] = None
        self._write_state(state)
    
    @property
    def should_stop(self) -> bool:
        """Lê should_stop sempre do arquivo (crítico para parada via web)."""
        return self._read_state().get("should_stop", False)
    
    @should_stop.setter
    def should_stop(self, value: bool):
        state = self._read_state()
        state["should_stop"] = value
        self._write_state(state)
    
    @property
    def current_cycle(self) -> int:
        return self._read_state().get("current_cycle", 0)
    
    @current_cycle.setter
    def current_cycle(self, value: int):
        state = self._read_state()
        state["current_cycle"] = value
        state["last_cycle_at"] = datetime.utcnow().isoformat()
        self._write_state(state)
    
    @property
    def interval_minutes(self) -> int:
        return self._read_state().get("interval_minutes", 10)
    
    @interval_minutes.setter
    def interval_minutes(self, value: int):
        state = self._read_state()
        state["interval_minutes"] = value
        self._write_state(state)
    
    @property
    def dry_run(self) -> bool:
        """Se True, simula execução sem enviar mensagens."""
        return self._read_state().get("dry_run", False)
    
    @dry_run.setter
    def dry_run(self, value: bool):
        state = self._read_state()
        state["dry_run"] = value
        self._write_state(state)
    
    def start(self, interval_minutes: int = 10, dry_run: bool = False):
        """Marca automação como iniciada."""
        state = {
            "is_running": True,
            "is_syncing": False,
            "should_stop": False,
            "dry_run": dry_run,
            "current_cycle": 0,
            "interval_minutes": interval_minutes,
            "started_at": datetime.utcnow().isoformat(),
            "last_cycle_at": None,
            "sync_heartbeat_at": None,
            "pid": os.getpid(),
            "stats": {
                "cycles_completed": 0,
                "messages_sent": 0,
                "errors": 0
            }
        }
        self._write_state(state)
        mode_str = " [DRY RUN]" if dry_run else ""
        logger.info(f"[StateManager] Automação iniciada{mode_str} (PID: {os.getpid()}, intervalo: {interval_minutes}min)")
    
    def stop(self):
        """Solicita parada da automação (e do sync, se estiver rodando)."""
        state = self._read_state()
        state["should_stop"] = True
        
        # Se apenas sync está rodando (sem automação), limpar is_syncing diretamente
        # já que sync não tem loop contínuo que verifica should_stop frequentemente
        if state.get("is_syncing") and not state.get("is_running"):
            state["is_syncing"] = False
            state["sync_heartbeat_at"] = None
            logger.info("[StateManager] Sync interrompido diretamente via stop")
        
        self._write_state(state)
        logger.info("[StateManager] Parada solicitada")
    
    def finish(self):
        """Marca automação como finalizada."""
        state = self._read_state()
        state["is_running"] = False
        state["is_syncing"] = False
        state["should_stop"] = False
        state["sync_heartbeat_at"] = None
        state["pid"] = None
        self._write_state(state)
        logger.info("[StateManager] Automação finalizada")
    
    def update_stats(self, messages_sent: int = 0, errors: int = 0):
        """Atualiza estatísticas."""
        state = self._read_state()
        stats = state.get("stats", {"cycles_completed": 0, "messages_sent": 0, "errors": 0})
        stats["cycles_completed"] = stats.get("cycles_completed", 0) + 1
        stats["messages_sent"] = stats.get("messages_sent", 0) + messages_sent
        stats["errors"] = stats.get("errors", 0) + errors
        state["stats"] = stats
        self._write_state(state)
    
    def get_status(self) -> Dict:
        """Retorna status completo (sempre lê do arquivo)."""
        state = self._read_state()
        return {
            "is_running": state.get("is_running", False),
            "is_syncing": state.get("is_syncing", False),
            "should_stop": state.get("should_stop", False),
            "dry_run": state.get("dry_run", False),
            "current_cycle": state.get("current_cycle", 0),
            "interval_minutes": state.get("interval_minutes", 10),
            "started_at": state.get("started_at"),
            "last_cycle_at": state.get("last_cycle_at"),
            "pid": state.get("pid"),
            "stats": state.get("stats", {})
        }


# Singleton
_state_manager: Optional[AutomationStateManager] = None


def get_state_manager() -> AutomationStateManager:
    """Retorna instância singleton do gerenciador de estado."""
    global _state_manager
    if _state_manager is None:
        _state_manager = AutomationStateManager()
    return _state_manager
