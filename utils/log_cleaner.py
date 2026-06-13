"""
Sistema de limpeza automática de logs.

Responsável por:
- Remover arquivos de log antigos baseado em retention_days
- Comprimir logs antigos para economizar espaço
- Limitar tamanho total da pasta de logs
- Executar limpeza periódica em background

Exemplo de uso:
    from utils.log_cleaner import LogCleaner, start_log_cleaner
    
    # Limpeza manual
    cleaner = LogCleaner(retention_days=30, max_total_size_mb=500)
    stats = cleaner.cleanup()
    
    # Limpeza em background (a cada 24h)
    stop_event = start_log_cleaner(interval_hours=24)
"""

import gzip
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

from config import LOGS_DIR, get_settings


@dataclass
class CleanupStats:
    """Estatísticas da limpeza de logs."""
    files_deleted: int = 0
    files_compressed: int = 0
    bytes_freed: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
    
    @property
    def space_saved_mb(self) -> float:
        return self.bytes_freed / (1024 * 1024)
    
    @property
    def total_size_mb(self) -> float:
        return self.bytes_after / (1024 * 1024)
    
    def to_dict(self) -> Dict:
        return {
            "files_deleted": self.files_deleted,
            "files_compressed": self.files_compressed,
            "space_saved_mb": round(self.space_saved_mb, 2),
            "total_size_mb": round(self.total_size_mb, 2),
            "errors": self.errors
        }


class LogCleaner:
    """
    Gerenciador de limpeza de arquivos de log.
    
    Implementa:
    - Remoção por idade (retention_days)
    - Compressão de logs antigos
    - Limite de tamanho total
    
    Args:
        logs_dir: Diretório de logs (padrão: config.LOGS_DIR)
        retention_days: Dias para manter logs (padrão: settings.log_retention_days)
        max_total_size_mb: Tamanho máximo total em MB (padrão: 500MB)
        compress_after_days: Comprimir logs após N dias (padrão: 7)
    """
    
    # Padrões de arquivos de log
    LOG_PATTERNS = ["*.log", "*.log.*"]
    COMPRESSED_EXTENSIONS = [".gz", ".zip"]
    
    def __init__(
        self,
        logs_dir: Optional[Path] = None,
        retention_days: Optional[int] = None,
        max_total_size_mb: int = 500,
        compress_after_days: int = 7
    ):
        settings = get_settings()
        
        self.logs_dir = Path(logs_dir) if logs_dir else LOGS_DIR
        self.retention_days = retention_days or settings.log_retention_days
        self.max_total_size_mb = max_total_size_mb
        self.compress_after_days = compress_after_days
        
        # Garantir que o diretório existe
        self.logs_dir.mkdir(parents=True, exist_ok=True)
    
    def get_log_files(self) -> List[Tuple[Path, datetime, int]]:
        """
        Retorna lista de arquivos de log com data de modificação e tamanho.
        
        Returns:
            Lista de tuplas (path, modified_date, size_bytes)
        """
        files = []
        
        for pattern in self.LOG_PATTERNS:
            for file_path in self.logs_dir.glob(pattern):
                if file_path.is_file():
                    stat = file_path.stat()
                    modified = datetime.fromtimestamp(stat.st_mtime)
                    files.append((file_path, modified, stat.st_size))
        
        # Ordenar por data (mais antigo primeiro)
        files.sort(key=lambda x: x[1])
        
        return files
    
    def get_total_size(self) -> int:
        """Retorna tamanho total da pasta de logs em bytes."""
        total = 0
        for file_path in self.logs_dir.rglob("*"):
            if file_path.is_file():
                total += file_path.stat().st_size
        return total
    
    def delete_old_files(self, stats: CleanupStats) -> None:
        """Remove arquivos mais antigos que retention_days."""
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        
        for file_path, modified, size in self.get_log_files():
            if modified < cutoff_date:
                try:
                    file_path.unlink()
                    stats.files_deleted += 1
                    stats.bytes_freed += size
                    logger.debug(f"Arquivo de log deletado: {file_path.name}")
                except Exception as e:
                    stats.errors.append(f"Erro ao deletar {file_path.name}: {e}")
    
    def compress_old_files(self, stats: CleanupStats) -> None:
        """Comprime arquivos mais antigos que compress_after_days."""
        cutoff_date = datetime.now() - timedelta(days=self.compress_after_days)
        
        for file_path, modified, size in self.get_log_files():
            # Pular arquivos já comprimidos
            if any(file_path.suffix == ext for ext in self.COMPRESSED_EXTENSIONS):
                continue
            
            # Pular arquivos muito recentes
            if modified >= cutoff_date:
                continue
            
            # Pular arquivos muito antigos (serão deletados)
            delete_cutoff = datetime.now() - timedelta(days=self.retention_days)
            if modified < delete_cutoff:
                continue
            
            try:
                compressed_path = file_path.with_suffix(file_path.suffix + ".gz")
                
                with open(file_path, "rb") as f_in:
                    with gzip.open(compressed_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # Remover arquivo original
                original_size = size
                compressed_size = compressed_path.stat().st_size
                file_path.unlink()
                
                stats.files_compressed += 1
                stats.bytes_freed += original_size - compressed_size
                
                logger.debug(
                    f"Arquivo comprimido: {file_path.name} "
                    f"({original_size} -> {compressed_size} bytes)"
                )
                
            except Exception as e:
                stats.errors.append(f"Erro ao comprimir {file_path.name}: {e}")
    
    def enforce_size_limit(self, stats: CleanupStats) -> None:
        """Remove arquivos mais antigos se exceder limite de tamanho."""
        max_bytes = self.max_total_size_mb * 1024 * 1024
        current_size = self.get_total_size()
        
        if current_size <= max_bytes:
            return
        
        logger.debug(
            f"Pasta de logs excede limite: {current_size / (1024*1024):.1f}MB "
            f"> {self.max_total_size_mb}MB"
        )
        
        # Ordenar por data (mais antigo primeiro) e remover até caber
        files = self.get_log_files()
        
        for file_path, modified, size in files:
            if current_size <= max_bytes:
                break
            
            try:
                file_path.unlink()
                stats.files_deleted += 1
                stats.bytes_freed += size
                current_size -= size
                
                logger.debug(f"Arquivo removido por limite de tamanho: {file_path.name}")
                
            except Exception as e:
                stats.errors.append(f"Erro ao deletar {file_path.name}: {e}")
    
    def cleanup(self) -> CleanupStats:
        """
        Executa limpeza completa dos logs.
        
        Returns:
            CleanupStats com estatísticas da limpeza
        """
        stats = CleanupStats()
        stats.bytes_before = self.get_total_size()
        
        logger.debug(
            f"Iniciando limpeza de logs. "
            f"Tamanho atual: {stats.bytes_before / (1024*1024):.1f}MB, "
            f"Retention: {self.retention_days} dias"
        )
        
        # 1. Deletar arquivos muito antigos
        self.delete_old_files(stats)
        
        # 2. Comprimir arquivos antigos
        self.compress_old_files(stats)
        
        # 3. Aplicar limite de tamanho
        self.enforce_size_limit(stats)
        
        stats.bytes_after = self.get_total_size()
        
        logger.debug(
            f"Limpeza concluída. "
            f"Arquivos deletados: {stats.files_deleted}, "
            f"Comprimidos: {stats.files_compressed}, "
            f"Espaço liberado: {stats.space_saved_mb:.1f}MB"
        )
        
        return stats
    
    def get_status(self) -> Dict:
        """Retorna status atual da pasta de logs."""
        files = self.get_log_files()
        total_size = self.get_total_size()
        
        # Contar por tipo
        log_count = sum(1 for f, _, _ in files if not f.suffix.endswith(".gz"))
        compressed_count = sum(1 for f, _, _ in files if f.suffix.endswith(".gz"))
        
        oldest_file = files[0] if files else None
        newest_file = files[-1] if files else None
        
        return {
            "total_files": len(files),
            "log_files": log_count,
            "compressed_files": compressed_count,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "max_size_mb": self.max_total_size_mb,
            "retention_days": self.retention_days,
            "oldest_file": oldest_file[0].name if oldest_file else None,
            "oldest_date": oldest_file[1].isoformat() if oldest_file else None,
            "newest_file": newest_file[0].name if newest_file else None,
            "newest_date": newest_file[1].isoformat() if newest_file else None
        }


class LogCleanerScheduler:
    """
    Scheduler para executar limpeza de logs periodicamente em background.
    
    Usa threading para não bloquear a aplicação principal.
    """
    
    def __init__(
        self,
        cleaner: LogCleaner,
        interval_hours: int = 24
    ):
        self.cleaner = cleaner
        self.interval_seconds = interval_hours * 3600
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
    
    def _run_cleanup_loop(self):
        """Loop de limpeza em background."""
        logger.debug(
            f"Log cleaner scheduler iniciado. "
            f"Intervalo: {self.interval_seconds // 3600}h"
        )
        
        while not self._stop_event.is_set():
            try:
                self.cleaner.cleanup()
            except Exception as e:
                logger.error(f"Erro na limpeza automática de logs: {e}")
            
            # Aguardar próximo ciclo ou stop
            self._stop_event.wait(self.interval_seconds)
        
        logger.debug("Log cleaner scheduler finalizado")
    
    def start(self) -> threading.Event:
        """
        Inicia o scheduler em background.
        
        Returns:
            Event para parar o scheduler (chamar .set())
        """
        if self._thread and self._thread.is_alive():
            logger.warning("Log cleaner scheduler já está rodando")
            return self._stop_event
        
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_cleanup_loop,
            name="LogCleanerScheduler",
            daemon=True
        )
        self._thread.start()
        
        return self._stop_event
    
    def stop(self):
        """Para o scheduler."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)


# Instância global do scheduler
_scheduler: Optional[LogCleanerScheduler] = None


def start_log_cleaner(
    interval_hours: int = 24,
    retention_days: Optional[int] = None,
    max_total_size_mb: int = 500
) -> threading.Event:
    """
    Inicia o log cleaner em background.
    
    Args:
        interval_hours: Intervalo entre limpezas (padrão: 24h)
        retention_days: Dias para manter logs (padrão: settings)
        max_total_size_mb: Tamanho máximo total (padrão: 500MB)
    
    Returns:
        Event para parar o scheduler
    
    Exemplo:
        stop_event = start_log_cleaner(interval_hours=12)
        # ... aplicação rodando ...
        stop_event.set()  # Para o scheduler
    """
    global _scheduler
    
    cleaner = LogCleaner(
        retention_days=retention_days,
        max_total_size_mb=max_total_size_mb
    )
    
    _scheduler = LogCleanerScheduler(cleaner, interval_hours)
    return _scheduler.start()


def stop_log_cleaner():
    """Para o log cleaner se estiver rodando."""
    global _scheduler
    
    if _scheduler:
        _scheduler.stop()
        _scheduler = None


def cleanup_logs_now() -> CleanupStats:
    """
    Executa limpeza de logs imediatamente.
    
    Returns:
        CleanupStats com estatísticas
    """
    cleaner = LogCleaner()
    return cleaner.cleanup()


def get_logs_status() -> Dict:
    """
    Retorna status atual dos logs.
    
    Returns:
        Dict com informações sobre os logs
    """
    cleaner = LogCleaner()
    return cleaner.get_status()
