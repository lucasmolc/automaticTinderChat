"""
Testes para o sistema de limpeza automática de logs (LogCleaner).

Testa funcionalidades de:
- Criação de diretórios de logs
- Listagem e cálculo de tamanho de arquivos
- Remoção de arquivos antigos por retenção
- Compressão de arquivos antigos
- Limite de tamanho total
- Scheduler de limpeza automática
- Estatísticas de limpeza (CleanupStats)
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import threading


class TestLogCleanerFileOperations:
    """Testes para operações de arquivo do LogCleaner."""
    
    @pytest.fixture
    def temp_logs_dir(self):
        """Cria diretório temporário de logs."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def log_cleaner(self, temp_logs_dir):
        """Cria LogCleaner com diretório temporário."""
        from utils.log_cleaner import LogCleaner
        return LogCleaner(
            logs_dir=temp_logs_dir,
            retention_days=7,
            max_total_size_mb=10,
            compress_after_days=3
        )
    
    def create_log_file(self, logs_dir: Path, name: str, content: str = "test", 
                        days_old: int = 0) -> Path:
        """Helper para criar arquivo de log."""
        file_path = logs_dir / name
        file_path.write_text(content)
        
        if days_old > 0:
            old_time = datetime.now() - timedelta(days=days_old)
            import os
            os.utime(file_path, (old_time.timestamp(), old_time.timestamp()))
        
        return file_path
    
    def test_init_creates_directory(self):
        """Testa que LogCleaner cria diretório se não existir."""
        from utils.log_cleaner import LogCleaner
        
        temp_dir = Path(tempfile.mkdtemp()) / "new_logs"
        cleaner = LogCleaner(logs_dir=temp_dir)
        
        assert temp_dir.exists()
        shutil.rmtree(temp_dir.parent, ignore_errors=True)
    
    def test_get_log_files_returns_file_info_tuples(self, log_cleaner, temp_logs_dir):
        """Testa listagem de arquivos retorna tuplas com info."""
        self.create_log_file(temp_logs_dir, "app_2026-01-01.log")
        self.create_log_file(temp_logs_dir, "errors_2026-01-01.log")
        
        files = log_cleaner.get_log_files()
        
        assert len(files) == 2
        assert all(isinstance(f, tuple) and len(f) == 3 for f in files)
    
    def test_get_total_size_calculates_bytes(self, log_cleaner, temp_logs_dir):
        """Testa cálculo do tamanho total em bytes."""
        content = "A" * 1000  # 1KB
        self.create_log_file(temp_logs_dir, "test.log", content)
        
        size = log_cleaner.get_total_size()
        
        assert size >= 1000
    
    def test_get_status_returns_complete_info(self, log_cleaner, temp_logs_dir):
        """Testa retorno de status com todas informações."""
        self.create_log_file(temp_logs_dir, "app.log")
        
        status = log_cleaner.get_status()
        
        assert 'total_files' in status
        assert 'total_size_mb' in status
        assert 'retention_days' in status


class TestLogCleanerRetention:
    """Testes para políticas de retenção do LogCleaner."""
    
    @pytest.fixture
    def temp_logs_dir(self):
        """Cria diretório temporário de logs."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def log_cleaner(self, temp_logs_dir):
        """Cria LogCleaner com diretório temporário."""
        from utils.log_cleaner import LogCleaner
        return LogCleaner(
            logs_dir=temp_logs_dir,
            retention_days=7,
            max_total_size_mb=10,
            compress_after_days=3
        )
    
    def create_log_file(self, logs_dir: Path, name: str, content: str = "test", 
                        days_old: int = 0) -> Path:
        """Helper para criar arquivo de log."""
        file_path = logs_dir / name
        file_path.write_text(content)
        
        if days_old > 0:
            old_time = datetime.now() - timedelta(days=days_old)
            import os
            os.utime(file_path, (old_time.timestamp(), old_time.timestamp()))
        
        return file_path
    
    def test_delete_old_files_removes_expired(self, log_cleaner, temp_logs_dir):
        """Testa remoção de arquivos mais antigos que retention_days."""
        from utils.log_cleaner import CleanupStats
        
        old_file = self.create_log_file(temp_logs_dir, "old.log", "old", days_old=10)
        new_file = self.create_log_file(temp_logs_dir, "new.log", "new", days_old=1)
        
        stats = CleanupStats()
        log_cleaner.delete_old_files(stats)
        
        assert not old_file.exists()
        assert new_file.exists()
        assert stats.files_deleted == 1
    
    def test_compress_old_files_creates_gzip(self, log_cleaner, temp_logs_dir):
        """Testa compressão de arquivos antigos cria .gz."""
        from utils.log_cleaner import CleanupStats
        
        old_file = self.create_log_file(temp_logs_dir, "compress.log", "compress me", days_old=5)
        
        stats = CleanupStats()
        log_cleaner.compress_old_files(stats)
        
        assert not old_file.exists()
        assert (temp_logs_dir / "compress.log.gz").exists()
        assert stats.files_compressed == 1
    
    def test_enforce_size_limit_removes_when_exceeded(self, temp_logs_dir):
        """Testa que limite de tamanho remove arquivos mais antigos."""
        from utils.log_cleaner import LogCleaner, CleanupStats
        
        cleaner = LogCleaner(
            logs_dir=temp_logs_dir,
            max_total_size_mb=0.001  # 1KB limite
        )
        
        # Criar arquivo de 2KB
        file_path = temp_logs_dir / "big.log"
        file_path.write_text("A" * 2000)
        
        stats = CleanupStats()
        stats.bytes_before = cleaner.get_total_size()
        cleaner.enforce_size_limit(stats)
        
        assert stats.files_deleted >= 1


class TestLogCleanerCleanup:
    """Testes para o método principal cleanup."""
    
    @pytest.fixture
    def temp_logs_dir(self):
        """Cria diretório temporário de logs."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def log_cleaner(self, temp_logs_dir):
        """Cria LogCleaner com diretório temporário."""
        from utils.log_cleaner import LogCleaner
        return LogCleaner(
            logs_dir=temp_logs_dir,
            retention_days=7,
            max_total_size_mb=10,
            compress_after_days=3
        )
    
    def test_cleanup_returns_stats_object(self, log_cleaner, temp_logs_dir):
        """Testa que cleanup retorna CleanupStats."""
        (temp_logs_dir / "test.log").write_text("test")
        
        stats = log_cleaner.cleanup()
        
        assert hasattr(stats, 'files_deleted')
        assert hasattr(stats, 'files_compressed')
        assert hasattr(stats, 'bytes_freed')
        assert hasattr(stats, 'space_saved_mb')


class TestLogCleanerScheduler:
    """Testes para o scheduler do LogCleaner."""
    
    def test_start_scheduler_returns_event(self):
        """Testa que início do scheduler retorna threading.Event."""
        from utils.log_cleaner import start_log_cleaner, stop_log_cleaner
        
        stop_event = start_log_cleaner(interval_hours=24)
        
        assert isinstance(stop_event, threading.Event)
        assert not stop_event.is_set()
        
        stop_log_cleaner()
    
    def test_stop_scheduler_idempotent(self):
        """Testa que parar múltiplas vezes não causa erro."""
        from utils.log_cleaner import start_log_cleaner, stop_log_cleaner
        
        start_log_cleaner(interval_hours=24)
        stop_log_cleaner()
        stop_log_cleaner()  # Segunda chamada não deve falhar
    
    def test_cleanup_logs_now_returns_stats(self):
        """Testa limpeza imediata retorna estatísticas."""
        from utils.log_cleaner import cleanup_logs_now
        
        stats = cleanup_logs_now()
        
        assert stats is not None
        assert hasattr(stats, 'to_dict')


class TestCleanupStats:
    """Testes para a classe CleanupStats."""
    
    def test_space_saved_mb_calculation(self):
        """Testa cálculo de espaço economizado em MB."""
        from utils.log_cleaner import CleanupStats
        
        stats = CleanupStats(bytes_freed=1024 * 1024)  # 1MB
        
        assert stats.space_saved_mb == 1.0
    
    def test_to_dict_contains_all_fields(self):
        """Testa que to_dict contém todos os campos."""
        from utils.log_cleaner import CleanupStats
        
        stats = CleanupStats(
            files_deleted=5,
            files_compressed=2,
            bytes_freed=512 * 1024,
            bytes_after=1024 * 1024
        )
        
        result = stats.to_dict()
        
        assert result['files_deleted'] == 5
        assert result['files_compressed'] == 2
        assert 'space_saved_mb' in result
