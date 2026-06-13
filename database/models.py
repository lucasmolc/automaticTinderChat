"""
Modelos de dados para o banco SQL Server.
Define todas as tabelas e relacionamentos.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, relationship

Base = declarative_base()


class MyProfile(Base):
    """Perfil do usuário (meu perfil)"""
    __tablename__ = "my_profile"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tinder_id = Column(String(100), unique=True, nullable=True)
    name = Column(String(200), nullable=True)
    age = Column(Integer, nullable=True)
    bio = Column(Text, nullable=True)
    location = Column(String(500), nullable=True)
    job_title = Column(String(300), nullable=True)
    company = Column(String(300), nullable=True)
    school = Column(String(300), nullable=True)
    
    # Contadores
    photos_count = Column(Integer, default=0)
    interests_count = Column(Integer, default=0)
    
    # Scores de análise
    bio_quality_score = Column(Float, nullable=True)
    photos_quality_score = Column(Float, nullable=True)
    completeness_score = Column(Float, nullable=True)
    match_potential_score = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)
    
    # Análises textuais
    bio_analysis = Column(Text, nullable=True)
    photos_analysis = Column(Text, nullable=True)
    strengths = Column(Text, nullable=True)  # JSON serializado
    improvements = Column(Text, nullable=True)  # JSON serializado
    
    # Metadados
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_analyzed_at = Column(DateTime, nullable=True)
    
    # Relacionamentos
    photos = relationship("MyProfilePhoto", back_populates="profile", cascade="all, delete-orphan")
    interests = relationship("MyProfileInterest", back_populates="profile", cascade="all, delete-orphan")


class MyProfilePhoto(Base):
    """Fotos do meu perfil"""
    __tablename__ = "my_profile_photos"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("my_profile.id"), nullable=False)
    photo_url = Column(String(1000), nullable=True)
    photo_order = Column(Integer, default=0)
    description = Column(Text, nullable=True)  # Descrição gerada pela IA
    created_at = Column(DateTime, default=datetime.utcnow)
    
    profile = relationship("MyProfile", back_populates="photos")


class MyProfileInterest(Base):
    """Interesses do meu perfil"""
    __tablename__ = "my_profile_interests"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("my_profile.id"), nullable=False)
    interest_name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    profile = relationship("MyProfile", back_populates="interests")


class Match(Base):
    """Matches (perfis que deram match)"""
    __tablename__ = "matches"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tinder_match_id = Column(String(100), unique=True, nullable=False)
    tinder_person_id = Column(String(100), nullable=True)
    
    # Informações do perfil
    name = Column(String(200), nullable=True)
    age = Column(Integer, nullable=True)
    bio = Column(Text, nullable=True)
    distance_km = Column(Float, nullable=True)
    job_title = Column(String(300), nullable=True)
    company = Column(String(300), nullable=True)
    school = Column(String(300), nullable=True)
    
    # Informações adicionais do perfil
    relationship_intent = Column(String(100), nullable=True)  # "Algo sério", "Amizade", etc
    sexual_orientations = Column(String(200), nullable=True)  # Orientação sexual
    gender = Column(String(50), nullable=True)  # Gênero
    city = Column(String(200), nullable=True)  # Cidade
    relationship_type = Column(String(100), nullable=True)  # "Monogamia", "Poliamoroso", etc
    lifestyle_info = Column(Text, nullable=True)  # Bebida, Fuma, Exercício, etc
    is_verified = Column(Boolean, default=False)  # Foto verificada
    
    # Foto de perfil (primeira foto / principal)
    profile_photo_url = Column(String(1000), nullable=True)
    
    # Última mensagem na conversa (preview)
    last_message_text = Column(Text, nullable=True)
    last_message_from_me = Column(Boolean, nullable=True)
    
    # Contadores
    photos_count = Column(Integer, default=0)
    interests_count = Column(Integer, default=0)
    
    # Scores
    bio_quality_score = Column(Float, nullable=True)
    photos_quality_score = Column(Float, nullable=True)
    compatibility_score = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)
    
    # Análises
    profile_analysis = Column(Text, nullable=True)
    common_interests = Column(Text, nullable=True)  # JSON serializado
    
    # Status da conversa
    has_messages = Column(Boolean, default=False)
    first_message_sent = Column(Boolean, default=False)
    awaiting_my_response = Column(Boolean, default=False)
    conversation_temperature = Column(String(20), nullable=True)  # cold, warm, hot
    temperature_score = Column(Float, nullable=True)
    
    # Progressão
    whatsapp_requested = Column(Boolean, default=False)
    whatsapp_obtained = Column(Boolean, default=False)
    whatsapp_number = Column(String(20), nullable=True)  # Número extraído
    date_suggested = Column(Boolean, default=False)
    date_confirmed = Column(Boolean, default=False)
    
    # Unmatch tracking
    is_unmatched = Column(Boolean, default=False)  # Se deu unmatch
    unmatched_at = Column(DateTime, nullable=True)  # Quando deu unmatch
    
    # Histórico de temperatura (JSON: [{"temp": "warm", "score": 5, "at": "2026-01-28T12:00:00"}])
    temperature_history = Column(Text, nullable=True)
    
    # Reenvio de mensagem (mensagem incompleta/falha)
    pending_resend = Column(Boolean, default=False)  # Flag para reenviar mensagem completando a conversa
    resend_reason = Column(String(500), nullable=True)  # Motivo do reenvio
    resend_at = Column(DateTime, nullable=True)  # Quando foi marcado para reenvio
    
    # Controle manual
    is_blocked = Column(Boolean, default=False)  # Bloqueia envio automático de mensagens
    blocked_reason = Column(String(500), nullable=True)  # Motivo do bloqueio
    blocked_at = Column(DateTime, nullable=True)  # Data do bloqueio
    
    # Metadados
    matched_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, nullable=True)
    last_interaction_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    photos = relationship("MatchPhoto", back_populates="match", cascade="all, delete-orphan")
    interests = relationship("MatchInterest", back_populates="match", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="match", cascade="all, delete-orphan")
    
    # Índices otimizados para queries frequentes
    __table_args__ = (
        Index('idx_match_tinder_id', 'tinder_match_id'),
        Index('idx_match_awaiting_response', 'awaiting_my_response'),
        Index('idx_match_has_messages', 'has_messages'),
        # Índices compostos para queries de matches ativos/pendentes
        Index('idx_match_active_status', 'is_blocked', 'is_unmatched', 'whatsapp_obtained', 'date_confirmed'),
        Index('idx_match_pending_msgs', 'has_messages', 'first_message_sent', 'is_blocked'),
        Index('idx_match_awaiting_active', 'awaiting_my_response', 'is_blocked', 'whatsapp_obtained'),
    )


class MatchPhoto(Base):
    """Fotos dos matches"""
    __tablename__ = "match_photos"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    photo_url = Column(String(1000), nullable=True)
    photo_order = Column(Integer, default=0)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    match = relationship("Match", back_populates="photos")


class MatchInterest(Base):
    """Interesses dos matches"""
    __tablename__ = "match_interests"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    interest_name = Column(String(200), nullable=False)
    is_common = Column(Boolean, default=False)  # Se é interesse em comum comigo
    created_at = Column(DateTime, default=datetime.utcnow)
    
    match = relationship("Match", back_populates="interests")


class Message(Base):
    """Mensagens trocadas"""
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    tinder_message_id = Column(String(100), nullable=True)  # Removido unique=True para permitir NULL
    
    # Conteúdo
    content = Column(Text, nullable=False)
    is_from_me = Column(Boolean, nullable=False)
    
    # Análise
    message_type = Column(String(50), nullable=True)  # first_message, response, question, etc
    ai_generated = Column(Boolean, default=False)
    ai_analysis = Column(Text, nullable=True)
    
    # Metadados
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    match = relationship("Match", back_populates="messages")
    
    __table_args__ = (
        Index('idx_message_match', 'match_id'),
        Index('idx_message_sent_at', 'sent_at'),
    )


class ExecutionLog(Base):
    """Log de execuções do sistema"""
    __tablename__ = "execution_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_type = Column(String(50), nullable=False)  # automation, report, analysis
    
    # Estatísticas
    matches_processed = Column(Integer, default=0)
    messages_sent = Column(Integer, default=0)
    messages_analyzed = Column(Integer, default=0)
    errors_count = Column(Integer, default=0)
    
    # Status
    status = Column(String(20), default="started")  # started, completed, failed
    error_message = Column(Text, nullable=True)
    
    # Tempo
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Detalhes
    details = Column(Text, nullable=True)  # JSON com detalhes adicionais


class AIInteraction(Base):
    """Log de interações com a API de IA (OpenAI, DeepSeek, etc.)"""
    __tablename__ = "ai_interactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Contexto
    interaction_type = Column(String(50), nullable=False)  # profile_analysis, message_generation, etc
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    
    # Provedor e Modelo
    provider = Column(String(50), nullable=True, default="openai")  # openai, deepseek, etc
    model_used = Column(String(50), nullable=True)
    
    # Request - Usar Text para permitir prompts grandes
    prompt_template = Column(Text, nullable=True)
    
    # Response
    response_content = Column(Text, nullable=True)
    
    # Tokens e Custo
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)
    
    # Status
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    
    # Metadados
    created_at = Column(DateTime, default=datetime.utcnow)
    response_time_ms = Column(Integer, nullable=True)
    
    # Índices para queries de gastos
    __table_args__ = (
        Index('idx_ai_interaction_type', 'interaction_type'),
        Index('idx_ai_provider', 'provider'),
        Index('idx_ai_created_at', 'created_at'),
        Index('idx_ai_provider_type', 'provider', 'interaction_type'),
    )


class Analytics(Base):
    """Métricas agregadas para análise"""
    __tablename__ = "analytics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)
    
    # Matches
    total_matches = Column(Integer, default=0)
    new_matches = Column(Integer, default=0)
    
    # Mensagens
    first_messages_sent = Column(Integer, default=0)
    responses_received = Column(Integer, default=0)
    response_rate = Column(Float, nullable=True)
    
    # Conversões
    whatsapp_conversions = Column(Integer, default=0)
    date_suggestions = Column(Integer, default=0)
    dates_confirmed = Column(Integer, default=0)
    
    # Temperatura média
    avg_conversation_temperature = Column(Float, nullable=True)
    
    # Custos
    total_ai_cost = Column(Float, default=0.0)
    total_tokens_used = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_analytics_date', 'date'),
    )


class Notification(Base):
    """Notificações do sistema para a interface web"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_id = Column(String(20), unique=True, nullable=False)  # ID curto para frontend
    
    # Tipo e conteúdo
    notification_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    icon = Column(String(100), nullable=True)  # HTML de ícone Bootstrap Icons
    color = Column(String(20), nullable=True)
    
    # Relacionamento opcional com match
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    match_name = Column(String(200), nullable=True)
    
    # Dados adicionais (JSON)
    extra_data = Column(Text, nullable=True)
    
    # Status
    is_read = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)
    
    __table_args__ = (
        Index('idx_notification_read', 'is_read'),
        Index('idx_notification_created', 'created_at'),
    )

class MatchReport(Base):
    """Relatórios e sugestões atrelados a cada match"""
    __tablename__ = "match_reports"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    
    # Tipo de relatório
    report_type = Column(String(50), default="conversation_analysis")  # conversation_analysis, profile_analysis
    
    # Análise e sugestões (JSON)
    conversation_summary = Column(Text, nullable=True)  # Resumo da conversa
    topic_suggestions = Column(Text, nullable=True)  # JSON: lista de tópicos sugeridos
    next_message_suggestions = Column(Text, nullable=True)  # JSON: sugestões de próximas mensagens
    compatibility_analysis = Column(Text, nullable=True)  # Análise de compatibilidade
    strengths = Column(Text, nullable=True)  # JSON: pontos fortes da conversa
    warnings = Column(Text, nullable=True)  # JSON: alertas (ex: conversa fria, possível desinteresse)
    
    # Métricas
    conversation_temperature = Column(String(20), nullable=True)  # warm, hot, cold
    temperature_score = Column(Float, nullable=True)  # 1-10
    engagement_score = Column(Float, nullable=True)  # 1-10
    progression_score = Column(Float, nullable=True)  # Quão perto de marcar encontro
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_match_report_match', 'match_id'),
        Index('idx_match_report_created', 'created_at'),
    )