"""
Configurações centralizadas do Automatic Tinder Chat.
Carrega variáveis de ambiente e define valores padrão.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Configurações da aplicação carregadas do .env"""
    
    # ==========================================
    # OpenAI API
    # ==========================================
    # Opcional: a chave também pode ser configurada pela interface web.
    # Sem chave o app inicia normalmente; chamadas de IA só falham ao serem usadas.
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", env="OPENAI_MODEL")
    
    # ==========================================
    # Configurações de Tokens IA
    # ==========================================
    ai_max_tokens_default: int = Field(default=2000, env="AI_MAX_TOKENS_DEFAULT")
    ai_max_tokens_first_message: int = Field(default=1500, env="AI_MAX_TOKENS_FIRST_MESSAGE")
    ai_max_tokens_conversation: int = Field(default=2000, env="AI_MAX_TOKENS_CONVERSATION")
    ai_max_tokens_report: int = Field(default=2500, env="AI_MAX_TOKENS_REPORT")
    
    # ==========================================
    # Banco de Dados
    # ==========================================
    # DATABASE_URL é a forma preferida (SQLAlchemy). Exemplos:
    #   SQLite (padrão):  sqlite:///./data/automatic_tinder_chat.db
    #   PostgreSQL:       postgresql+psycopg2://user:senha@localhost:5432/tinderchat
    #   SQL Server:       mssql+pyodbc://user:senha@host/banco?driver=ODBC+Driver+17+for+SQL+Server
    # Se vazio, o app usa SQLite num arquivo local (zero configuração).
    database_url: Optional[str] = Field(default=None, env="DATABASE_URL")

    # Legado/atalho para SQL Server via connection string ODBC.
    # Usado apenas se DATABASE_URL não estiver definido.
    sql_server_connection_string: Optional[str] = Field(
        default=None,
        env="SQL_SERVER_CONNECTION_STRING"
    )
    
    # ==========================================
    # Browser
    # ==========================================
    chrome_user_data_dir: Optional[str] = Field(default=None, env="CHROME_USER_DATA_DIR")
    chrome_profile: str = Field(default="Default", env="CHROME_PROFILE")
    browser_headless: bool = Field(default=False, env="BROWSER_HEADLESS")
    
    # ==========================================
    # Automação
    # ==========================================
    action_delay_min: int = Field(default=2, env="ACTION_DELAY_MIN")
    action_delay_max: int = Field(default=9, env="ACTION_DELAY_MAX")
    max_messages_per_run: int = Field(default=20, env="MAX_MESSAGES_PER_RUN")
    days_without_interaction: int = Field(default=365, env="DAYS_WITHOUT_INTERACTION")
    
    # ==========================================
    # Filtros
    # ==========================================
    ignore_doubledate: bool = Field(default=True, env="IGNORE_DOUBLEDATE")
    
    # ==========================================
    # Logs
    # ==========================================
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_retention_days: int = Field(default=30, env="LOG_RETENTION_DAYS")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignorar variáveis extras no .env


# ==========================================
# Caminhos do Projeto
# ==========================================
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
LOGS_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"
BROWSER_DATA_DIR = PROJECT_ROOT / "browser_data"
PROMPTS_DIR = CONFIG_DIR / "prompts"

# Criar diretórios se não existirem
for dir_path in [LOGS_DIR, REPORTS_DIR, BROWSER_DATA_DIR, PROMPTS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Retorna instância das configurações."""
    return Settings()


# ==========================================
# Constantes do Tinder
# ==========================================
TINDER_URL = "https://tinder.com"
TINDER_APP_URL = "https://tinder.com/app/recs"
TINDER_MATCHES_URL = "https://tinder.com/app/matches"
TINDER_MESSAGES_URL = "https://tinder.com/app/messages"

# ==========================================
# Scores e Avaliações
# ==========================================
CONVERSATION_TEMPERATURE = {
    "cold": {"min": 0, "max": 3, "description": "Conversa fria - baixo engajamento"},
    "warm": {"min": 4, "max": 6, "description": "Conversa morna - engajamento moderado"},
    "hot": {"min": 7, "max": 10, "description": "Conversa quente - alto engajamento"}
}

PROFILE_SCORE_WEIGHTS = {
    "bio_quality": 0.25,
    "photos_quality": 0.35,
    "profile_completeness": 0.20,
    "match_potential": 0.20
}
