"""
Gerenciador de conexão com o banco de dados.

Suporta múltiplos bancos via SQLAlchemy:
  - SQLite (padrão, zero configuração)
  - PostgreSQL
  - SQL Server (via pyodbc)

Cria banco e tabelas automaticamente quando possível.
"""

import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from config import get_settings
from config.settings import PROJECT_ROOT
from utils.logger import get_logger
from .models import Base

logger = get_logger(__name__)


class DatabaseManager:
    """Gerencia conexões e operações com o banco de dados (multi-dialeto)."""

    def __init__(self):
        self.settings = get_settings()
        self.engine: Optional[Engine] = None
        self.SessionLocal: Optional[sessionmaker] = None
        self.dialect: str = "sqlite"
        self._initialized = False

    # ------------------------------------------------------------------
    # Resolução da URL do banco
    # ------------------------------------------------------------------
    def _resolve_database_url(self) -> str:
        """
        Determina a URL SQLAlchemy a partir das configurações, na ordem:
          1. DATABASE_URL (forma preferida)
          2. SQL_SERVER_CONNECTION_STRING (legado, monta URL mssql+pyodbc)
          3. SQLite local em data/ (padrão, zero configuração)
        """
        # 1. DATABASE_URL explícita
        url = (self.settings.database_url or "").strip()
        if url:
            return url

        # 2. Connection string ODBC de SQL Server (legado)
        conn_str = (self.settings.sql_server_connection_string or "").strip()
        if conn_str:
            encoded = urllib.parse.quote_plus(conn_str)
            return f"mssql+pyodbc:///?odbc_connect={encoded}"

        # 3. SQLite padrão
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "automatic_tinder_chat.db"
        return f"sqlite:///{db_path.as_posix()}"

    @staticmethod
    def _detect_dialect(url: str) -> str:
        """Extrai o nome do dialeto (sqlite, postgresql, mssql, ...) da URL."""
        scheme = url.split("://", 1)[0]
        return scheme.split("+", 1)[0].lower()

    # ------------------------------------------------------------------
    # Bootstrap do banco (criação do database quando aplicável)
    # ------------------------------------------------------------------
    def _ensure_database_exists(self, url: str) -> None:
        """
        Garante que o banco exista. Comportamento por dialeto:
          - sqlite: nada a fazer (arquivo é criado on-demand)
          - mssql:  cria o database via pyodbc se não existir
          - outros: assume que o database já existe (apenas loga)
        """
        if self.dialect == "sqlite":
            return

        if self.dialect == "mssql":
            self._create_sqlserver_database_if_not_exists()
            return

        logger.debug(
            f"Dialeto '{self.dialect}': certifique-se de que o banco já exista "
            "(criação automática suportada apenas para SQLite e SQL Server)."
        )

    def _create_sqlserver_database_if_not_exists(self) -> None:
        """Cria o database no SQL Server caso não exista (requer pyodbc)."""
        try:
            import pyodbc
        except ImportError:
            logger.warning(
                "pyodbc não instalado — pulando criação automática do banco SQL Server. "
                "Instale com: pip install pyodbc"
            )
            return

        conn_str = (self.settings.sql_server_connection_string or "").strip()
        if not conn_str:
            # DATABASE_URL aponta para mssql, mas sem a connection string ODBC
            # não conseguimos montar a conexão ao master; pulamos o bootstrap.
            logger.debug("Sem SQL_SERVER_CONNECTION_STRING — pulando criação do database.")
            return

        params = {}
        for part in conn_str.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                params[key.strip().lower()] = value.strip()
        db_name = params.get("database", "AutomaticTinderChat")

        master_parts = []
        for part in conn_str.split(";"):
            if "=" in part and part.split("=", 1)[0].strip().lower() == "database":
                master_parts.append("Database=master")
            else:
                master_parts.append(part)
        master_conn_str = ";".join(master_parts)

        try:
            conn = pyodbc.connect(master_conn_str, autocommit=True)
            cursor = conn.cursor()
            cursor.execute("SELECT database_id FROM sys.databases WHERE name = ?", (db_name,))
            if cursor.fetchone() is None:
                logger.warning(f"Banco '{db_name}' não encontrado. Criando...")
                cursor.execute(f"CREATE DATABASE [{db_name}]")
                logger.warning(f"Banco '{db_name}' criado com sucesso!")
            else:
                logger.debug(f"Banco '{db_name}' já existe.")
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Erro ao verificar/criar banco SQL Server: {e}")
            raise

    # ------------------------------------------------------------------
    # Migrações de colunas em tabelas existentes
    # ------------------------------------------------------------------
    def _run_migrations(self) -> None:
        """
        Adiciona colunas novas a tabelas já existentes.

        Bancos novos não precisam disto: `create_all()` já cria todas as colunas
        do modelo. A rotina só roda no SQL Server, onde o T-SQL é específico e
        bancos pré-existentes (criados em versões anteriores) podem faltar colunas.
        Para SQLite/PostgreSQL, recrie via `create_all` ou use migrações Alembic.
        """
        if self.dialect != "mssql":
            return

        migrations = [
            ("matches", "pending_resend", "BIT DEFAULT 0"),
            ("matches", "resend_reason", "NVARCHAR(500) NULL"),
            ("matches", "resend_at", "DATETIME NULL"),
        ]

        try:
            conn = self.engine.raw_connection()
            cursor = conn.cursor()
            for table, column, sql_type in migrations:
                cursor.execute(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = ? AND COLUMN_NAME = ?",
                    (table, column),
                )
                if cursor.fetchone()[0] == 0:
                    logger.warning(f"Migrando: adicionando coluna {column} em {table}...")
                    cursor.execute(f"ALTER TABLE [{table}] ADD [{column}] {sql_type}")
                    conn.commit()
                    logger.warning(f"Coluna {column} adicionada com sucesso!")
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"Erro ao executar migrações: {e}")
            # App continua: se as colunas já existem, não há problema.

    # ------------------------------------------------------------------
    # Inicialização
    # ------------------------------------------------------------------
    def _build_engine(self, url: str) -> Engine:
        """Cria o engine com parâmetros adequados ao dialeto."""
        if self.dialect == "sqlite":
            # SQLite: permitir uso entre threads (Flask/automação) e pool simples.
            return create_engine(
                url,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
                echo=False,
            )

        return create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            echo=False,
        )

    def initialize(self) -> None:
        """Inicializa o banco de dados e cria as tabelas."""
        if self._initialized:
            return

        url = self._resolve_database_url()
        self.dialect = self._detect_dialect(url)
        logger.debug(f"Inicializando banco de dados (dialeto: {self.dialect})...")

        self._ensure_database_exists(url)

        self.engine = self._build_engine(url)

        logger.debug("Criando/verificando tabelas...")
        Base.metadata.create_all(bind=self.engine)
        logger.debug("Tabelas verificadas com sucesso!")

        self._run_migrations()

        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self._initialized = True
        logger.debug("Banco de dados inicializado com sucesso!")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Context manager para sessões do banco."""
        if not self._initialized:
            self.initialize()

        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Erro na sessão do banco: {e}")
            raise
        finally:
            session.close()

    def execute_raw(self, query: str, params: dict = None) -> list:
        """Executa query SQL raw."""
        if not self._initialized:
            self.initialize()

        with self.engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return result.fetchall()

    def health_check(self) -> bool:
        """Verifica se a conexão está funcionando."""
        try:
            if not self._initialized:
                self.initialize()
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Health check falhou: {e}")
            return False


# Singleton do gerenciador
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Retorna instância singleton do DatabaseManager."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_session() -> Generator[Session, None, None]:
    """Shortcut para obter sessão do banco."""
    return get_db_manager().get_session()
