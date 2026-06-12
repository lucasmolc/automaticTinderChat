"""
Interface Web para o Automatic Tinder Chat.
Interface completa com visualização E controle da automação.

Funcionalidades:
- WebSocket para notificações em tempo real
- Métricas Prometheus para observabilidade
- A/B Testing para otimização de mensagens
- Audit Logging para segurança
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from datetime import datetime, timedelta
from loguru import logger
import sys
import os
import asyncio
import threading

# Rate limiting
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    RATE_LIMITING_ENABLED = True
except ImportError:
    RATE_LIMITING_ENABLED = False
    logger.warning("flask-limiter não instalado. Rate limiting desabilitado.")

# WebSocket support
# Nota: O erro "write() before start_response" no Werkzeug pode ser ignorado
# É um problema do servidor de desenvolvimento, não afeta a funcionalidade
try:
    from web.websocket import create_socketio, get_websocket_notifier
    WEBSOCKET_ENABLED = True
except ImportError as e:
    WEBSOCKET_ENABLED = False
    logger.warning(f"WebSocket não disponível: {e}. Usando polling.")
except Exception as e:
    WEBSOCKET_ENABLED = False
    logger.warning(f"WebSocket erro: {type(e).__name__}: {e}. Usando polling.")

# Prometheus metrics
try:
    from utils.metrics import init_metrics, get_metrics_collector
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    logger.warning("Prometheus metrics não disponível.")

# A/B Testing
try:
    from utils.ab_testing import get_ab_manager, setup_default_experiments
    AB_TESTING_ENABLED = True
except ImportError:
    AB_TESTING_ENABLED = False
    logger.warning("A/B Testing não disponível.")

# Audit logging
try:
    from utils.audit_log import get_audit_logger, AuditAction, audit_automation_start, audit_automation_stop
    AUDIT_ENABLED = True
except ImportError:
    AUDIT_ENABLED = False
    logger.warning("Audit logging não disponível.")

# Background Tasks (alternativa leve ao Celery)
try:
    from utils.background_tasks import get_task_manager, submit_task, schedule_task
    BACKGROUND_TASKS_ENABLED = True
except ImportError:
    BACKGROUND_TASKS_ENABLED = False
    logger.warning("Background Tasks não disponível.")

# Adicionar diretório pai ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DatabaseManager, MatchRepository, MessageRepository, MyProfileRepository
from database.models import Match, Message, MyProfile
from sqlalchemy import func, desc
from utils.notifications import get_notification_manager
from utils.helpers import clean_message_preview
from automation.state_manager import get_state_manager

app = Flask(__name__)

# WebSocket initialization
socketio = None
if WEBSOCKET_ENABLED:
    socketio = create_socketio(app)
    logger.debug("✅ WebSocket habilitado")

# CORS restrito - apenas origens permitidas
CORS(app, origins=[
    'http://localhost:5000',
    'http://127.0.0.1:5000',
    'http://localhost:3000',  # Dev frontend se houver
])

# Configurações
app.config['JSON_AS_ASCII'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Prometheus metrics initialization
if METRICS_ENABLED:
    init_metrics(app)
    logger.debug("✅ Prometheus metrics habilitado")

# A/B Testing setup
if AB_TESTING_ENABLED:
    setup_default_experiments()
    logger.debug("✅ A/B Testing habilitado")

# Rate limiting configuração com suporte a Redis
if RATE_LIMITING_ENABLED:
    from utils.rate_limiter import RateLimitConfig
    
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=RateLimitConfig.get_default_limits(),
        storage_uri=RateLimitConfig.get_storage_uri()
    )
else:
    limiter = None


def rate_limit(limit_string):
    """Decorator condicional de rate limiting."""
    def decorator(f):
        if limiter:
            return limiter.limit(limit_string)(f)
        return f
    return decorator

# Database
db = DatabaseManager()
db.initialize()  # Inicializar banco na importação

# Estado em memória para dados NÃO-CRÍTICOS (logs, resultados)
# IMPORTANTE: O estado de is_running/is_syncing/should_stop é gerenciado
# pelo AutomationStateManager (persistido em arquivo) para sobreviver a refreshes
automation_state = {
    'is_running': False,      # DEPRECATED: usar state_manager.is_running
    'is_syncing': False,      # DEPRECATED: usar state_manager.is_syncing
    'last_result': None,      # Último resultado da automação (apenas em memória)
    'last_sync_result': None, # Último resultado do sync (apenas em memória)
    'logs': []                # Logs em memória (não persistidos)
}


def add_log(message: str, level: str = 'info'):
    """Adiciona log ao estado global e persiste os últimos logs."""
    log_entry = {
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'message': message,
        'level': level
    }
    automation_state['logs'].append(log_entry)
    # Manter apenas os últimos 100 logs
    if len(automation_state['logs']) > 100:
        automation_state['logs'] = automation_state['logs'][-100:]
    
    # Log também no logger para persistência
    if level == 'error':
        logger.error(f"[UI] {message}")
    elif level == 'warning':
        logger.warning(f"[UI] {message}")
    elif level == 'success':
        logger.success(f"[UI] {message}")
    else:
        logger.info(f"[UI] {message}")


# ===================== BACKGROUND TASKS SETUP =====================

def _sync_matches_task():
    """Task de sincronização de matches para execução em background."""
    from automation import sync_matches_only
    
    automation_state['is_syncing'] = True
    add_log('🔄 [Background] Sincronização iniciada...', 'info')
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(sync_matches_only())
        loop.close()
        
        automation_state['last_sync_result'] = result
        
        if result.get('success'):
            add_log(
                f'✅ [Background] Sync concluído! Matches: {result.get("total_matches", 0)}, '
                f'Novos: {result.get("new_matches", 0)}', 
                'success'
            )
            
            # Notificar via WebSocket se disponível
            if WEBSOCKET_ENABLED:
                try:
                    ws_notifier = get_websocket_notifier()
                    ws_notifier.emit_notification({
                        'type': 'sync_completed',
                        'title': 'Sincronização Concluída',
                        'message': f'Encontrados {result.get("new_matches", 0)} novos matches!',
                        'data': result
                    })
                except Exception:
                    pass
        else:
            add_log(f'❌ [Background] Erro no sync: {result.get("error", "Desconhecido")}', 'error')
            
        return result
        
    except Exception as e:
        error_result = {'success': False, 'error': str(e)}
        automation_state['last_sync_result'] = error_result
        add_log(f'❌ [Background] Erro: {str(e)}', 'error')
        return error_result
        
    finally:
        automation_state['is_syncing'] = False


# Inicializar Background Tasks (sem sync automático)
if BACKGROUND_TASKS_ENABLED:
    task_manager = get_task_manager()
    logger.debug("✅ Background Tasks habilitado")


# ===================== PÁGINAS =====================

@app.route('/')
def index():
    """Página principal - Dashboard."""
    return render_template('index.html')


@app.route('/matches')
def matches_page():
    """Página de matches."""
    return render_template('matches.html')


@app.route('/messages')
def messages_page():
    """Página de mensagens."""
    return render_template('messages.html')


@app.route('/analytics')
def analytics_page():
    """Página de analytics."""
    return render_template('analytics.html')


@app.route('/control')
def control_page():
    """Página de controle da automação."""
    return render_template('control.html')

# ===================== API - ESTATÍSTICAS =====================

@app.route('/api/stats')
def api_stats():
    """Retorna estatísticas gerais."""
    try:
        with db.get_session() as session:
            # Total de matches
            total_matches = session.query(func.count(Match.id)).scalar() or 0
            
            # Matches bloqueados
            blocked_matches = session.query(func.count(Match.id)).filter(
                Match.is_blocked == True
            ).scalar() or 0
            
            # Matches aguardando resposta
            awaiting_response = session.query(func.count(Match.id)).filter(
                Match.awaiting_my_response == True,
                Match.is_blocked != True
            ).scalar() or 0
            
            # Matches novos (sem mensagens)
            new_matches = session.query(func.count(Match.id)).filter(
                Match.has_messages == False,
                Match.is_blocked != True
            ).scalar() or 0
            
            # Total de mensagens enviadas
            messages_sent = session.query(func.count(Message.id)).filter(
                Message.is_from_me == True
            ).scalar() or 0
            
            # Total de mensagens recebidas
            messages_received = session.query(func.count(Message.id)).filter(
                Message.is_from_me == False
            ).scalar() or 0
            
            # WhatsApp obtidos
            whatsapp_obtained = session.query(func.count(Match.id)).filter(
                Match.whatsapp_obtained == True
            ).scalar() or 0
            
            # Matches ativos (com mensagens, não bloqueados)
            active_matches = session.query(func.count(Match.id)).filter(
                Match.has_messages == True,
                Match.is_blocked != True
            ).scalar() or 0
            
            # Matches pendentes de reenvio
            pending_resend = session.query(func.count(Match.id)).filter(
                Match.pending_resend == True,
                Match.is_blocked != True
            ).scalar() or 0
            
            return jsonify({
                'success': True,
                'data': {
                    'total_matches': total_matches,
                    'blocked_matches': blocked_matches,
                    'awaiting_response': awaiting_response,
                    'new_matches': new_matches,
                    'messages_sent': messages_sent,
                    'messages_received': messages_received,
                    'whatsapp_obtained': whatsapp_obtained,
                    'active_matches': active_matches,
                    'pending_resend': pending_resend
                }
            })
    except Exception as e:
        logger.error(f"Erro ao buscar stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Isentar endpoint de rate limiting (usado para polling no dashboard)
if limiter:
    api_stats = limiter.exempt(api_stats)


# Importar sanitizador de inputs
from utils.input_sanitizer import (
    sanitize_search_input, sanitize_integer, sanitize_boolean,
    sanitize_sort_field, sanitize_pagination
)


@app.route('/api/matches')
def api_matches():
    """Retorna lista de matches com inputs sanitizados."""
    try:
        # Parâmetros de filtro (sanitizados)
        show_blocked = sanitize_boolean(request.args.get('show_blocked'), default=False)
        status_filter = sanitize_sort_field(
            request.args.get('status', 'all'),
            allowed_fields=['all', 'new', 'awaiting', 'active', 'blocked'],
            default='all'
        )
        search = sanitize_search_input(request.args.get('search', ''), max_length=100)
        
        # Paginação sanitizada (máximo 100 por página)
        page = sanitize_integer(request.args.get('page', 1), default=1, min_value=1)
        limit = sanitize_integer(request.args.get('limit', 50), default=50, min_value=1, max_value=100)
        offset = sanitize_integer(request.args.get('offset', 0), default=0, min_value=0, max_value=100000)
        
        with db.get_session() as session:
            # Ordenar: primeiro por matched_at DESC (mais recente primeiro)
            # Perfis SEM data vão para o final (ordenados por created_at)
            from sqlalchemy import case, nullslast, or_, and_
            query = session.query(Match).order_by(
                # Primeiro ordena por ter ou não data (quem tem data vem primeiro)
                case((Match.matched_at != None, 0), else_=1),
                # Depois ordena por data do match DESC (mais recente primeiro)
                desc(Match.matched_at),
                # Quem não tem data, ordena por created_at DESC
                desc(Match.created_at)
            )
            
            # Filtrar por status primeiro
            if status_filter == 'new':
                # Novos: sem mensagens E não finalizados
                query = query.filter(
                    Match.has_messages == False,
                    or_(Match.is_blocked == False, Match.is_blocked == None),
                    or_(Match.whatsapp_obtained == False, Match.whatsapp_obtained == None),
                    or_(Match.date_confirmed == False, Match.date_confirmed == None)
                )
            elif status_filter == 'awaiting':
                # Aguardando: aguardando resposta E não finalizados
                query = query.filter(
                    Match.awaiting_my_response == True,
                    or_(Match.is_blocked == False, Match.is_blocked == None),
                    or_(Match.whatsapp_obtained == False, Match.whatsapp_obtained == None),
                    or_(Match.date_confirmed == False, Match.date_confirmed == None)
                )
            elif status_filter == 'active':
                # Ativos: com mensagens, sem aguardar resposta E não finalizados
                query = query.filter(
                    Match.has_messages == True,
                    Match.awaiting_my_response == False,
                    or_(Match.is_blocked == False, Match.is_blocked == None),
                    or_(Match.whatsapp_obtained == False, Match.whatsapp_obtained == None),
                    or_(Match.date_confirmed == False, Match.date_confirmed == None)
                )
            elif status_filter == 'blocked':
                # Bloqueados: incluir bloqueados, whatsapp obtido ou encontro confirmado
                query = query.filter(
                    or_(
                        Match.is_blocked == True,
                        Match.whatsapp_obtained == True,
                        Match.date_confirmed == True
                    )
                )
            else:
                # 'all' - mostrar apenas não finalizados
                if not show_blocked:
                    query = query.filter(
                        and_(
                            or_(Match.is_blocked == False, Match.is_blocked == None),
                            or_(Match.whatsapp_obtained == False, Match.whatsapp_obtained == None),
                            or_(Match.date_confirmed == False, Match.date_confirmed == None)
                        )
                    )
            
            # Busca por nome
            if search:
                query = query.filter(Match.name.ilike(f'%{search}%'))
            
            # Contar total antes de paginar
            total = query.count()
            
            # Criar subquery para contagem de mensagens (resolve N+1)
            msg_count_subquery = session.query(
                Message.match_id,
                func.count(Message.id).label('msg_count')
            ).group_by(Message.match_id).subquery()
            
            # Aplicar paginação com join para contagem
            matches_with_counts = session.query(
                Match,
                func.coalesce(msg_count_subquery.c.msg_count, 0).label('message_count')
            ).outerjoin(
                msg_count_subquery,
                Match.id == msg_count_subquery.c.match_id
            ).filter(Match.id.in_([m.id for m in query.offset(offset).limit(limit).all()])).all()
            
            # Serializar
            matches_data = []
            for row in matches_with_counts:
                # row é uma Row(Match, message_count)
                m = row[0]
                msg_count = row[1] or 0
                
                # Ignorar matches sem nome
                if not m.name or m.name.strip() == "":
                    continue
                    
                # Determinar status
                if m.is_blocked:
                    status = 'blocked'
                    status_label = 'Bloqueado'
                    status_color = 'danger'
                elif not m.has_messages:
                    status = 'new'
                    status_label = 'Novo'
                    status_color = 'success'
                elif m.awaiting_my_response:
                    status = 'awaiting'
                    status_label = 'Aguardando'
                    status_color = 'warning'
                else:
                    status = 'active'
                    status_label = 'Ativo'
                    status_color = 'primary'
                
                # Determinar badge de temperatura
                temp_badge = ''
                temp_color = ''
                if m.conversation_temperature:
                    if m.conversation_temperature == 'hot':
                        temp_badge = '🔥 Hot'
                        temp_color = 'danger'
                    elif m.conversation_temperature == 'warm':
                        temp_badge = '🌡️ Warm'
                        temp_color = 'warning'
                    elif m.conversation_temperature == 'cold':
                        temp_badge = '❄️ Cold'
                        temp_color = 'info'
                
                matches_data.append({
                    'id': m.id,
                    'tinder_id': m.tinder_match_id,
                    'name': m.name,
                    'age': m.age,
                    'bio': m.bio,
                    'photo_url': m.profile_photo_url,
                    'is_verified': m.is_verified or False,
                    'last_message': clean_message_preview(m.last_message_text, m.name) if m.last_message_text else None,
                    'last_message_from_me': m.last_message_from_me,
                    'has_messages': m.has_messages,
                    'message_count': msg_count,
                    'is_blocked': m.is_blocked or False,
                    'blocked_reason': m.blocked_reason,
                    'whatsapp_obtained': m.whatsapp_obtained or False,
                    'whatsapp_number': m.whatsapp_number,
                    'date_confirmed': m.date_confirmed or False,
                    'is_unmatched': m.is_unmatched or False,
                    'pending_resend': m.pending_resend or False,
                    'resend_reason': m.resend_reason,
                    'conversation_temperature': m.conversation_temperature,
                    'temperature_score': m.temperature_score,
                    'temp_badge': temp_badge,
                    'temp_color': temp_color,
                    'status': status,
                    'status_label': status_label,
                    'status_color': status_color,
                    'matched_at': m.matched_at.isoformat() if m.matched_at else None,
                    'created_at': m.created_at.isoformat() if m.created_at else None,
                    'last_interaction': m.last_interaction_at.isoformat() if m.last_interaction_at else None
                })
            
            return jsonify({
                'success': True,
                'data': matches_data,
                'total': total,
                'limit': limit,
                'offset': offset
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar matches: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>')
def api_match_detail(match_id):
    """Retorna detalhes de um match específico."""
    try:
        with db.get_session() as session:
            match = session.query(Match).filter(Match.id == match_id).first()
            
            if not match:
                return jsonify({'success': False, 'error': 'Match não encontrado'}), 404
            
            # Buscar mensagens
            messages = session.query(Message).filter(
                Message.match_id == match_id
            ).order_by(Message.id).all()
            
            # Contar mensagens
            message_count = len(messages)
            
            messages_data = [{
                'id': msg.id,
                'content': msg.content,
                'is_from_me': msg.is_from_me,
                'sent_at': msg.sent_at.isoformat() if msg.sent_at else None,
                'ai_generated': msg.ai_generated
            } for msg in messages]
            
            return jsonify({
                'success': True,
                'data': {
                    'id': match.id,
                    'tinder_id': match.tinder_match_id,
                    'name': match.name,
                    'age': match.age,
                    'bio': match.bio,
                    'photo_url': match.profile_photo_url,
                    'is_blocked': match.is_blocked or False,
                    'blocked_reason': match.blocked_reason,
                    'whatsapp_obtained': match.whatsapp_obtained or False,
                    'date_confirmed': match.date_confirmed or False,
                    'pending_resend': match.pending_resend or False,
                    'resend_reason': match.resend_reason,
                    'has_messages': match.has_messages,
                    'message_count': message_count,
                    'created_at': match.created_at.isoformat() if match.created_at else None,
                    'messages': messages_data
                }
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar match {match_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/profile')
def api_match_profile(match_id):
    """Retorna dados completos do perfil de um match."""
    try:
        with db.get_session() as session:
            match_repo = MatchRepository(session)
            match = match_repo.get_by_id(match_id)
            
            if not match:
                return jsonify({'success': False, 'error': 'Match não encontrado'}), 404
            
            # Buscar interesses
            interests = match_repo.get_interests(match)
            
            # Buscar fotos
            photos = [
                {'url': photo.photo_url, 'order': photo.photo_order}
                for photo in match.photos
            ] if match.photos else []
            
            logger.debug(f"Match {match_id} tem {len(photos)} fotos: {[p['url'][:100] for p in photos]}")
            
            return jsonify({
                'success': True,
                'profile': {
                    'name': match.name,
                    'age': match.age,
                    'bio': match.bio,
                    'distance_km': match.distance_km,
                    'job_title': match.job_title,
                    'company': match.company,
                    'school': match.school,
                    'gender': match.gender,
                    'city': match.city,
                    'relationship_intent': match.relationship_intent,
                    'sexual_orientations': match.sexual_orientations,
                    'matched_at': match.matched_at.isoformat() if match.matched_at else None,
                    'photos': photos,
                    'interests': interests,
                    'photos_count': len(photos)
                }
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar perfil do match {match_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/report')
@rate_limit("20 per hour")
def api_match_report(match_id):
    """Retorna o relatório mais recente de um match ou gera um novo se solicitado."""
    try:
        from database import MatchReportRepository
        from ai import get_ai_manager, BudgetExceededError, AIProviderError
        import json
        
        # Parâmetro para forçar geração de novo relatório
        force_generate = request.args.get('generate', 'false').lower() == 'true'
        
        with db.get_session() as session:
            match_repo = MatchRepository(session)
            report_repo = MatchReportRepository(session)
            msg_repo = MessageRepository(session)
            
            match = match_repo.get_by_id(match_id)
            if not match:
                return jsonify({'success': False, 'error': 'Match não encontrado'}), 404
            
            # Buscar relatório mais recente
            report = report_repo.get_latest_by_match(match_id)
            
            # Se existe relatório e não foi solicitado forçar geração, retornar existente
            if report and not force_generate:
                return jsonify({
                    'success': True,
                    'report': {
                        'id': report.id,
                        'conversation_summary': report.conversation_summary,
                        'topic_suggestions': json.loads(report.topic_suggestions) if report.topic_suggestions else [],
                        'next_message_suggestions': json.loads(report.next_message_suggestions) if report.next_message_suggestions else [],
                        'compatibility_analysis': report.compatibility_analysis,
                        'strengths': json.loads(report.strengths) if report.strengths else [],
                        'warnings': json.loads(report.warnings) if report.warnings else [],
                        'conversation_temperature': report.conversation_temperature,
                        'temperature_score': report.temperature_score,
                        'engagement_score': report.engagement_score,
                        'progression_score': report.progression_score,
                        'created_at': report.created_at.isoformat(),
                        'updated_at': report.updated_at.isoformat()
                    },
                    'from_cache': True
                })
            
            # Se não existe relatório e não foi solicitado gerar, retornar indicando que não há
            if not report and not force_generate:
                return jsonify({
                    'success': True,
                    'report': None,
                    'message': 'Nenhum relatório disponível. Clique em "Gerar Relatório" para criar.',
                    'from_cache': False
                })
            
            # Gerar novo relatório
            logger.debug(f"Gerando novo relatório para match {match_id}")
            
            # Buscar dados necessários
            messages = msg_repo.get_messages_for_match(match_id, limit=1000)
            conversation_history = [
                {
                    'content': msg.content,
                    'is_from_me': msg.is_from_me,
                    'sent_at': msg.sent_at.isoformat() if msg.sent_at else None
                }
                for msg in messages
            ]
            
            match_profile = {
                'name': match.name,
                'age': match.age,
                'bio': match.bio,
                'job_title': match.job_title,
                'school': match.school,
                'gender': match.gender,
                'city': match.city,
                'relationship_intent': match.relationship_intent,
                'interests': match_repo.get_interests(match)
            }
            
            # Usar o novo sistema de gerenciamento de IA
            try:
                ai_manager = get_ai_manager()
                provider = ai_manager.get_active_provider()
                
                if not provider or not provider.is_enabled:
                    # Fallback para cliente legado
                    from ai import get_openai_client
                    openai_client = get_openai_client()
                    ai_report = openai_client.generate_match_report(
                        match_profile=match_profile,
                        conversation_history=conversation_history
                    )
                else:
                    # Usar novo sistema
                    from ai import get_openai_client
                    openai_client = get_openai_client()
                    ai_report = openai_client.generate_match_report(
                        match_profile=match_profile,
                        conversation_history=conversation_history
                    )
                    
            except BudgetExceededError as e:
                notification_manager = get_notification_manager()
                notification_manager.add(
                    notification_type='ai_error',
                    message=f'⚠️ Budget excedido ao gerar relatório para {match.name}',
                    match_id=match_id,
                    match_name=match.name,
                    data={'error_type': 'budget_exceeded', 'details': e.details}
                )
                return jsonify({
                    'success': False,
                    'error': 'Budget da API de IA excedido',
                    'error_type': 'budget_exceeded',
                    'details': e.details
                }), 402
                
            except AIProviderError as e:
                return jsonify({
                    'success': False,
                    'error': f'Erro na API de IA: {str(e)}',
                    'error_type': 'ai_error'
                }), 500
            
            # Salvar no banco
            report = report_repo.create(
                match_id=match_id,
                report_type="conversation_analysis",
                conversation_summary=ai_report.get('conversation_summary'),
                topic_suggestions=json.dumps(ai_report.get('topic_suggestions', [])),
                next_message_suggestions=json.dumps(ai_report.get('next_message_suggestions', [])),
                compatibility_analysis=ai_report.get('compatibility_analysis'),
                strengths=json.dumps(ai_report.get('strengths', [])),
                warnings=json.dumps(ai_report.get('warnings', [])),
                conversation_temperature=ai_report.get('conversation_temperature'),
                temperature_score=ai_report.get('temperature_score'),
                engagement_score=ai_report.get('engagement_score'),
                progression_score=ai_report.get('progression_score')
            )
            
            # Limpar relatórios antigos (manter últimos 5)
            report_repo.delete_old_reports(match_id, keep_last=5)
            
            # Notificar geração do relatório
            notification_manager = get_notification_manager()
            notification_manager.add(
                notification_type='report_generated',
                message=f'Relatório de análise gerado para {match.name}',
                match_id=match_id,
                match_name=match.name,
                data={'report_id': report.id, 'temperature': ai_report.get('conversation_temperature')}
            )
            logger.debug(f"📊 Notificação de relatório gerado enviada para match {match_id}")
            
            # Retornar relatório
            return jsonify({
                'success': True,
                'report': {
                    'id': report.id,
                    'conversation_summary': report.conversation_summary,
                    'topic_suggestions': json.loads(report.topic_suggestions) if report.topic_suggestions else [],
                    'next_message_suggestions': json.loads(report.next_message_suggestions) if report.next_message_suggestions else [],
                    'compatibility_analysis': report.compatibility_analysis,
                    'strengths': json.loads(report.strengths) if report.strengths else [],
                    'warnings': json.loads(report.warnings) if report.warnings else [],
                    'conversation_temperature': report.conversation_temperature,
                    'temperature_score': report.temperature_score,
                    'engagement_score': report.engagement_score,
                    'progression_score': report.progression_score,
                    'created_at': report.created_at.isoformat(),
                    'updated_at': report.updated_at.isoformat()
                },
                'from_cache': False
            })
            
    except Exception as e:
        logger.error(f"Erro ao gerar/buscar relatório do match {match_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/messages/recent')
def api_recent_messages():
    """Retorna mensagens recentes."""
    try:
        limit = int(request.args.get('limit', 20))
        
        with db.get_session() as session:
            # Buscar mensagens recentes com join no match
            messages = session.query(Message, Match).join(
                Match, Message.match_id == Match.id
            ).order_by(desc(Message.sent_at)).limit(limit).all()
            
            messages_data = []
            for msg, match in messages:
                messages_data.append({
                    'id': msg.id,
                    'content': msg.content,
                    'is_from_me': msg.is_from_me,
                    'sent_at': msg.sent_at.isoformat() if msg.sent_at else None,
                    'ai_generated': msg.ai_generated,
                    'match': {
                        'id': match.id,
                        'name': match.name,
                        'photo_url': match.profile_photo_url
                    }
                })
            
            return jsonify({
                'success': True,
                'data': messages_data
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar mensagens: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/messages/ai')
def api_ai_messages():
    """Retorna apenas mensagens geradas por IA."""
    try:
        limit = int(request.args.get('limit', 30))
        offset = int(request.args.get('offset', 0))
        
        with db.get_session() as session:
            # Buscar apenas mensagens de IA
            messages = session.query(Message, Match).join(
                Match, Message.match_id == Match.id
            ).filter(
                Message.ai_generated == True,
                Message.is_from_me == True
            ).order_by(desc(Message.sent_at)).offset(offset).limit(limit).all()
            
            messages_data = []
            for msg, match in messages:
                messages_data.append({
                    'id': msg.id,
                    'content': msg.content,
                    'is_from_me': msg.is_from_me,
                    'sent_at': msg.sent_at.isoformat() if msg.sent_at else None,
                    'ai_generated': msg.ai_generated,
                    'message_type': msg.message_type,
                    'match': {
                        'id': match.id,
                        'name': match.name,
                        'photo_url': match.profile_photo_url
                    }
                })
            
            return jsonify({
                'success': True,
                'data': messages_data
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar mensagens de IA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/messages/ai-stats')
def api_ai_messages_stats():
    """Retorna estatísticas de mensagens de IA."""
    try:
        with db.get_session() as session:
            # Total de mensagens de IA
            total_ai = session.query(func.count(Message.id)).filter(
                Message.ai_generated == True,
                Message.is_from_me == True
            ).scalar() or 0
            
            # Matches únicos com mensagens de IA
            matches_with_ai = session.query(func.count(func.distinct(Message.match_id))).filter(
                Message.ai_generated == True,
                Message.is_from_me == True
            ).scalar() or 0
            
            return jsonify({
                'success': True,
                'data': {
                    'total_ai_messages': total_ai,
                    'matches_with_ai': matches_with_ai
                }
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar stats de IA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/analytics/timeline')
def api_analytics_timeline():
    """Retorna dados de timeline para gráficos."""
    try:
        days = int(request.args.get('days', 7))
        
        with db.get_session() as session:
            from sqlalchemy import text
            
            # Dados dos últimos N dias
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Matches por dia usando SQL nativo para compatibilidade
            matches_query = text("""
                SELECT CAST(created_at AS DATE) as date, COUNT(*) as count
                FROM matches
                WHERE created_at >= :start_date
                GROUP BY CAST(created_at AS DATE)
                ORDER BY date
            """)
            matches_result = session.execute(matches_query, {'start_date': start_date}).fetchall()
            
            # Mensagens enviadas por dia
            messages_query = text("""
                SELECT CAST(sent_at AS DATE) as date, COUNT(*) as count
                FROM messages
                WHERE sent_at >= :start_date AND is_from_me = 1
                GROUP BY CAST(sent_at AS DATE)
                ORDER BY date
            """)
            messages_result = session.execute(messages_query, {'start_date': start_date}).fetchall()
            
            return jsonify({
                'success': True,
                'data': {
                    'matches_by_day': [{'date': str(row[0]), 'count': row[1]} for row in matches_result],
                    'messages_by_day': [{'date': str(row[0]), 'count': row[1]} for row in messages_result]
                }
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar analytics: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== HEALTH CHECK =====================

@app.route('/health')
def health_check():
    """
    Endpoint de health check para monitoramento.
    Verifica saúde do banco de dados e componentes críticos.
    """
    checks = {
        'database': False,
        'openai_configured': False,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    # Verificar banco de dados
    try:
        checks['database'] = db.health_check()
    except Exception as e:
        logger.error(f"Health check - DB falhou: {e}")
        checks['database'] = False
        checks['database_error'] = str(e)
    
    # Verificar se OpenAI está configurada
    try:
        from config import get_settings
        settings = get_settings()
        checks['openai_configured'] = bool(settings.openai_api_key and len(settings.openai_api_key) > 10)
    except Exception:
        checks['openai_configured'] = False
    
    # Status geral: o banco é o componente crítico. A chave de IA é opcional
    # (pode ser configurada pela interface), então sua ausência não torna o
    # serviço indisponível — fica apenas registrada em checks para observabilidade.
    is_healthy = checks['database']
    status = 'healthy' if is_healthy else 'unhealthy'

    return jsonify({
        'status': status,
        'checks': checks
    }), 200 if is_healthy else 503


@app.route('/api/health')
def api_health():
    """Alias para /health com prefixo de API."""
    return health_check()


def run_web_server(host='0.0.0.0', port=5000, debug=False):
    """Inicia o servidor web com suporte a WebSocket."""
    logger.warning(f"🌐 Servidor web iniciado em http://{host}:{port}")
    
    # Usar SocketIO se disponível para WebSocket support
    if WEBSOCKET_ENABLED and socketio is not None:
        logger.debug("🔌 WebSocket ativado via SocketIO")
        socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
    else:
        logger.debug("📡 Modo polling (sem WebSocket)")
        app.run(host=host, port=port, debug=debug, threaded=True)


# ===================== API - CONTROLE DA AUTOMAÇÃO =====================

@app.route('/api/automation/status')
def api_automation_status():
    """Retorna status atual da automação (usa state_manager persistido)."""
    state_manager = get_state_manager()
    status = state_manager.get_status()
    
    return jsonify({
        'success': True,
        'data': {
            'is_running': status.get('is_running', False),
            'is_syncing': status.get('is_syncing', False),
            'should_stop': status.get('should_stop', False),
            'last_result': automation_state['last_result'],
            'last_sync_result': automation_state['last_sync_result'],
            'logs': automation_state['logs'][-20:]  # Últimos 20 logs
        }
    })


@app.route('/api/automation/run', methods=['POST'])
@rate_limit("5 per hour")  # Limitar execuções de automação
def api_run_automation():
    """Inicia a automação contínua (rate limited)."""
    state_manager = get_state_manager()
    
    # Usar check_and_cleanup para verificar estado E limpar estados órfãos
    # Isso verifica se o processo realmente existe e limpa se necessário
    if not state_manager.check_and_cleanup():
        return jsonify({'success': False, 'error': 'Automação já está em execução'}), 400
    
    if state_manager.is_syncing:
        return jsonify({'success': False, 'error': 'Sincronização em andamento'}), 400
    
    # Obter parâmetros do request
    data = request.get_json(silent=True) or {}
    interval_minutes = sanitize_integer(data.get('interval_minutes', 10), default=10, min_value=1, max_value=60)
    dry_run = data.get('dry_run', False) == True
    
    # IMPORTANTE: Marcar como running ANTES de iniciar a thread via state_manager
    # O state_manager persiste o estado em arquivo, sobrevivendo a refreshes
    state_manager.start(interval_minutes)
    automation_state['is_running'] = True  # Para compatibilidade
    
    def run_async():
        mode_str = " [DRY RUN]" if dry_run else ""
        add_log(f'🚀 Iniciando automação contínua{mode_str} (intervalo: {interval_minutes}min)...', 'info')
        
        try:
            from automation import run_automation
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(run_automation(
                interval_minutes=interval_minutes,
                dry_run=dry_run
            ))
            loop.close()
            
            automation_state['last_result'] = result
            stats = result.get('stats', {})
            
            if result.get('success'):
                add_log(f'✅ Automação encerrada! Ciclos: {stats.get("cycles_completed", 0)} | Msgs: {stats.get("total_messages_sent", 0)}', 'success')
            else:
                add_log(f'❌ Erro na automação: {result.get("error", "Desconhecido")}', 'error')
        except Exception as e:
            automation_state['last_result'] = {'success': False, 'error': str(e)}
            add_log(f'❌ Erro: {str(e)}', 'error')
        finally:
            # Garantir que state_manager seja finalizado
            state_manager = get_state_manager()
            state_manager.finish()
            automation_state['is_running'] = False
    
    thread = threading.Thread(target=run_async, daemon=True)
    thread.start()
    
    mode_msg = " (Dry Run - simulação)" if dry_run else ""
    return jsonify({'success': True, 'message': f'Automação contínua iniciada{mode_msg}'})


@app.route('/api/automation/sync', methods=['POST'])
def api_sync_matches():
    """Sincroniza matches e perfil."""
    state_manager = get_state_manager()
    
    # Usar state_manager para verificar estado (persistido)
    if state_manager.is_syncing:
        return jsonify({'success': False, 'error': 'Sincronização já está em andamento'}), 400
    
    # Verificar se automação está rodando (com limpeza de estados órfãos)
    if not state_manager.check_and_cleanup():
        return jsonify({'success': False, 'error': 'Automação em execução'}), 400
    
    # Obter parâmetros do request
    data = request.get_json(silent=True) or {}
    force_update = data.get('force_update', False) == True
    extract_profiles = data.get('extract_profiles', True) != False
    sync_messages = data.get('sync_messages', True) != False
    
    def run_sync():
        state_manager = get_state_manager()
        state_manager.is_syncing = True
        automation_state['is_syncing'] = True  # Para compatibilidade
        mode_str = " [FORCE UPDATE]" if force_update else ""
        add_log(f'🔄 Iniciando sincronização{mode_str}...', 'info')
        
        try:
            from automation import sync_matches_only
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(sync_matches_only(
                force_update=force_update,
                extract_profiles=extract_profiles,
                sync_messages=sync_messages
            ))
            loop.close()
            
            automation_state['last_sync_result'] = result
            
            if result.get('success'):
                add_log(f'✅ Sincronização concluída! Matches: {result.get("total_matches", 0)}, Novos: {result.get("new_matches", 0)}', 'success')
            else:
                add_log(f'❌ Erro na sincronização: {result.get("error", "Desconhecido")}', 'error')
        except Exception as e:
            automation_state['last_sync_result'] = {'success': False, 'error': str(e)}
            add_log(f'❌ Erro: {str(e)}', 'error')
        finally:
            state_manager = get_state_manager()
            state_manager.is_syncing = False
            automation_state['is_syncing'] = False
    
    thread = threading.Thread(target=run_sync, daemon=True)
    thread.start()
    
    mode_msg = " (Force Update)" if force_update else ""
    return jsonify({'success': True, 'message': f'Sincronização iniciada{mode_msg}'})


@app.route('/api/automation/stop', methods=['POST'])
def api_stop_automation():
    """Para a automação graciosamente através do state_manager."""
    state_manager = get_state_manager()
    
    if not state_manager.is_running and not state_manager.is_syncing:
        return jsonify({'success': False, 'error': 'Nenhuma automação em execução'}), 400
    
    state_manager.stop()
    
    # NÃO resetar automation_state aqui — o state_manager controla o estado real.
    # O should_stop=True será detectado pelo loop de automação, que fará finish().
    # A UI lê should_stop e mostra "Parando..." até is_running virar False.
    
    add_log('⏹️ Solicitação de parada enviada. Aguarde o ciclo atual terminar...', 'warning')
    return jsonify({'success': True, 'message': 'Solicitação de parada enviada'})


@app.route('/api/automation/force-stop', methods=['POST'])
def api_force_stop_automation():
    """Força parada imediata da automação (para emergências).
    
    Diferente do stop normal, este endpoint:
    - Reseta o estado imediatamente
    - Tenta terminar o processo de automação via PID
    - Deve ser usado apenas se o stop normal não funcionar
    """
    import os
    import signal
    
    state_manager = get_state_manager()
    
    # Capturar PID antes de resetar o estado
    status = state_manager.get_status()
    automation_pid = status.get('pid')
    
    # Forçar reset do estado
    state_manager.finish()
    
    # Resetar estado em memória
    automation_state['is_running'] = False
    automation_state['is_syncing'] = False
    
    # Tentar fechar o browser via singleton (se existir no mesmo processo)
    try:
        from automation import browser as browser_module
        if hasattr(browser_module, '_browser') and browser_module._browser is not None:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(browser_module._browser.close())
                loop.close()
                browser_module._browser = None
            except Exception:
                pass
    except Exception:
        pass
    
    add_log('🛑 FORCE STOP: Estado resetado e parada forçada executada.', 'error')
    logger.warning("[FORCE STOP] Estado de automação resetado forçadamente")
    
    return jsonify({
        'success': True, 
        'message': 'Estado resetado e parada forçada executada.',
        'warning': 'O processo de automação foi interrompido. Verifique se o navegador foi fechado.'
    })


@app.route('/api/automation/full-status')
def api_automation_full_status():
    """Retorna status completo da automação incluindo state_manager.
    
    IMPORTANTE: O estado de execução vem SEMPRE do state_manager (persistido em arquivo)
    para garantir que a UI reflita o estado real mesmo após refresh da página.
    
    Isento de rate limiting pois é usado para polling frequente (15s).
    """
    state_manager = get_state_manager()
    status = state_manager.get_status()
    stats = status.get('stats', {})
    
    return jsonify({
        'success': True,
        'data': {
            # Estado de execução vem APENAS do state_manager (fonte de verdade)
            'is_running': status.get('is_running', False),
            'is_syncing': status.get('is_syncing', False),
            'should_stop': status.get('should_stop', False),
            'current_cycle': status.get('current_cycle', 0),
            'total_messages_sent': stats.get('messages_sent', 0),
            'total_errors': stats.get('errors', 0),
            'started_at': status.get('started_at'),
            'interval_minutes': status.get('interval_minutes', 10),
            'pid': status.get('pid'),  # PID do processo de automação
            # Dados em memória (não-críticos)
            'last_result': automation_state['last_result'],
            'logs': automation_state['logs'][-20:]
        }
    })

# Isentar endpoint de rate limiting se disponível
if limiter:
    api_automation_full_status = limiter.exempt(api_automation_full_status)


@app.route('/api/automation/logs')
def api_automation_logs():
    """Retorna logs da automação."""
    limit = int(request.args.get('limit', 50))
    return jsonify({
        'success': True,
        'data': automation_state['logs'][-limit:]
    })


# ===================== API - MATCHES BLOQUEADOS =====================

@app.route('/api/matches/blocked')
def api_blocked_matches():
    """Retorna lista de matches bloqueados, com WhatsApp obtido ou encontro confirmado."""
    try:
        from sqlalchemy import or_
        
        with db.get_session() as session:
            # Incluir matches que estão bloqueados OU obtiveram WhatsApp OU confirmaram encontro
            matches = session.query(Match).filter(
                or_(
                    Match.is_blocked == True,
                    Match.whatsapp_obtained == True,
                    Match.date_confirmed == True
                )
            ).order_by(desc(Match.blocked_at), desc(Match.updated_at)).all()
            
            matches_data = []
            for m in matches:
                # Determinar o motivo/status
                status_reasons = []
                if m.is_blocked:
                    status_reasons.append('Bloqueado')
                if m.whatsapp_obtained:
                    status_reasons.append('WhatsApp obtido')
                if m.date_confirmed:
                    status_reasons.append('Encontro confirmado')
                
                matches_data.append({
                    'id': m.id,
                    'tinder_id': m.tinder_match_id,
                    'name': m.name,
                    'age': m.age,
                    'photo_url': m.profile_photo_url,
                    'blocked_reason': m.blocked_reason,
                    'status_reasons': status_reasons,
                    'is_blocked': m.is_blocked,
                    'whatsapp_obtained': m.whatsapp_obtained,
                    'date_confirmed': m.date_confirmed,
                    'blocked_at': m.blocked_at.isoformat() if m.blocked_at else None,
                    'has_messages': m.has_messages,
                    'created_at': m.created_at.isoformat() if m.created_at else None
                })
            
            return jsonify({
                'success': True,
                'data': matches_data,
                'total': len(matches_data)
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar matches bloqueados: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - AÇÕES EM MATCHES =====================

@app.route('/api/matches/<int:match_id>/block', methods=['POST'])
def api_block_match(match_id):
    """Bloqueia ou desbloqueia um match (toggle)."""
    try:
        data = request.get_json() or {}
        blocked = data.get('blocked', True)  # Se não especificado, bloqueia
        reason = data.get('reason', 'Bloqueado via interface web')
        
        with db.get_session() as session:
            repo = MatchRepository(session)
            match = repo.get_by_id(match_id)
            
            if not match:
                return jsonify({'success': False, 'error': 'Match não encontrado'}), 404
            
            if blocked:
                repo.block_match(match, reason)
                add_log(f'🚫 Match bloqueado: {match.name}', 'warning')
                message = f'Match {match.name} bloqueado'
            else:
                repo.unblock_match(match)
                add_log(f'✅ Match desbloqueado: {match.name}', 'info')
                message = f'Match {match.name} desbloqueado'
            
            session.commit()
            
            return jsonify({
                'success': True,
                'message': message
            })
            
    except Exception as e:
        logger.error(f"Erro ao bloquear/desbloquear match: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/status', methods=['POST'])
def api_update_match_status(match_id):
    """Atualiza status específico do match (whatsapp, date, blocked)."""
    try:
        data = request.get_json() or {}
        status_type = data.get('status_type')
        value = data.get('value', False)
        
        if status_type not in ['whatsapp', 'date', 'blocked', 'resend']:
            return jsonify({'success': False, 'error': 'Tipo de status inválido'}), 400
        
        with db.get_session() as session:
            match = session.query(Match).filter(Match.id == match_id).first()
            
            if not match:
                return jsonify({'success': False, 'error': 'Match não encontrado'}), 404
            
            if status_type == 'whatsapp':
                match.whatsapp_obtained = value
                status_name = 'WhatsApp obtido'
            elif status_type == 'date':
                match.date_confirmed = value
                status_name = 'Encontro confirmado'
            elif status_type == 'resend':
                if value:
                    match.pending_resend = True
                    match.resend_at = datetime.now()
                    match.resend_reason = data.get('reason', 'Mensagem incompleta')
                else:
                    match.pending_resend = False
                    match.resend_at = None
                    match.resend_reason = None
                status_name = 'Reenvio pendente'
            else:  # blocked
                if value:
                    match.is_blocked = True
                    match.blocked_at = datetime.now()
                    match.blocked_reason = 'Bloqueado manualmente'
                else:
                    match.is_blocked = False
                    match.blocked_at = None
                    match.blocked_reason = None
                status_name = 'Bloqueado'
            
            session.commit()
            
            action = 'marcado' if value else 'desmarcado'
            add_log(f'✅ Match {match.name}: {status_name} {action}', 'info')
            
            # Gerar relatório automaticamente ao marcar WhatsApp ou encontro
            if value and status_type in ['whatsapp', 'date']:
                try:
                    from threading import Thread
                    def generate_report_async():
                        # Usar nova sessão para thread separada
                        try:
                            from ai import get_openai_client
                            import json
                            
                            with db.get_session() as async_session:
                                from database.repositories import MatchRepository, MessageRepository, MatchReportRepository
                                match_repo = MatchRepository(async_session)
                                msg_repo = MessageRepository(async_session)
                                report_repo = MatchReportRepository(async_session)
                                
                                # Buscar match
                                async_match = async_session.query(Match).filter(Match.id == match_id).first()
                                if not async_match:
                                    return
                                
                                # Verificar se já existe relatório recente (menos de 1h)
                                existing_report = report_repo.get_latest_by_match(match_id)
                                if existing_report and (datetime.utcnow() - existing_report.created_at).total_seconds() < 3600:
                                    logger.debug(f"Relatório recente já existe para match {match_id}, não gerando novo")
                                    return
                                
                                # Buscar mensagens
                                messages = msg_repo.get_messages_for_match(match_id, limit=1000)
                                conversation_history = [
                                    {
                                        'content': msg.content,
                                        'is_from_me': msg.is_from_me,
                                        'sent_at': msg.sent_at.isoformat() if msg.sent_at else None
                                    }
                                    for msg in messages
                                ]
                                
                                # Perfil do match
                                match_profile = {
                                    'name': async_match.name,
                                    'age': async_match.age,
                                    'bio': async_match.bio,
                                    'job_title': async_match.job_title,
                                    'school': async_match.school,
                                    'gender': async_match.gender,
                                    'city': async_match.city,
                                    'relationship_intent': async_match.relationship_intent,
                                    'interests': match_repo.get_interests(async_match)
                                }
                                
                                # Gerar relatório com IA
                                openai_client = get_openai_client()
                                ai_report = openai_client.generate_match_report(
                                    match_profile=match_profile,
                                    conversation_history=conversation_history
                                )
                                
                                logger.debug(f"Relatório gerado pela IA: {list(ai_report.keys()) if ai_report else 'None'}")
                                logger.debug(f"Summary: {ai_report.get('conversation_summary', 'N/A')[:100] if ai_report else 'N/A'}")
                                logger.debug(f"Temperature: {ai_report.get('conversation_temperature', 'N/A')}")
                                logger.debug(f"Engagement: {ai_report.get('engagement_score', 'N/A')}")
                                
                                # Salvar no banco
                                report = report_repo.create(
                                    match_id=match_id,
                                    report_type="conversation_analysis",
                                    conversation_summary=ai_report.get('conversation_summary'),
                                    topic_suggestions=json.dumps(ai_report.get('topic_suggestions', [])),
                                    next_message_suggestions=json.dumps(ai_report.get('next_message_suggestions', [])),
                                    compatibility_analysis=ai_report.get('compatibility_analysis'),
                                    strengths=json.dumps(ai_report.get('strengths', [])),
                                    warnings=json.dumps(ai_report.get('warnings', [])),
                                    conversation_temperature=ai_report.get('conversation_temperature'),
                                    temperature_score=ai_report.get('temperature_score'),
                                    engagement_score=ai_report.get('engagement_score'),
                                    progression_score=ai_report.get('progression_score')
                                )
                                
                                async_session.commit()
                                
                                # Notificar geração automática do relatório
                                notification_manager = get_notification_manager()
                                notification_manager.add(
                                    notification_type='report_generated',
                                    message=f'Relatório automático gerado para {async_match.name}',
                                    match_id=match_id,
                                    match_name=async_match.name,
                                    data={
                                        'report_id': report.id, 
                                        'temperature': ai_report.get('conversation_temperature'),
                                        'auto_generated': True,
                                        'trigger': 'whatsapp/date marked'
                                    }
                                )
                                
                                logger.debug(f"✅ Relatório gerado automaticamente para match {match_id} ({async_match.name})")
                                add_log(f'📊 Relatório gerado automaticamente para {async_match.name}', 'success')
                                
                        except Exception as e:
                            logger.error(f"Erro ao gerar relatório em background para match {match_id}: {e}")
                    
                    thread = Thread(target=generate_report_async)
                    thread.daemon = True
                    thread.start()
                    logger.debug(f"Iniciando geração de relatório em background para match {match_id}")
                except Exception as e:
                    logger.error(f"Erro ao iniciar thread de geração de relatório: {e}")
            
            return jsonify({
                'success': True,
                'message': f'{status_name} {action} para {match.name}'
            })
            
    except Exception as e:
        logger.error(f"Erro ao atualizar status do match: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/generate-report', methods=['POST'])
def api_generate_match_report(match_id):
    """Gera um relatório de análise do match usando IA."""
    try:
        with db.get_session() as session:
            match = session.query(Match).filter(Match.id == match_id).first()
            
            if not match:
                return jsonify({'success': False, 'error': 'Match não encontrado'}), 404
            
            # Buscar mensagens do match
            messages = session.query(Message).filter(
                Message.match_id == match_id
            ).order_by(Message.id).all()
            
            # Montar contexto para a IA
            profile_info = f"Nome: {match.name}"
            if match.age:
                profile_info += f", Idade: {match.age}"
            if match.bio:
                profile_info += f", Bio: {match.bio}"
            
            conversation_text = ""
            if messages:
                for msg in messages:
                    sender = "Você" if msg.is_from_me else match.name
                    conversation_text += f"{sender}: {msg.content}\n"
            
            # Gerar análise com OpenAI
            try:
                from ai import get_openai_client
                openai_client = get_openai_client()
                
                # Buscar interesses do match
                match_interests = [i.interest_name for i in match.interests] if match.interests else []
                
                prompt = f"""Analise este perfil e conversa de um match do Tinder e forneça um relatório detalhado.
Seja informal e direto, como se estivesse dando conselhos pra um amigo.

PERFIL:
{profile_info}
Interesses: {', '.join(match_interests) if match_interests else 'Não informado'}
Trabalho: {match.job_title or 'Não informado'}
Faculdade: {match.school or 'Não informado'}

CONVERSA:
{conversation_text if conversation_text else "Nenhuma mensagem ainda"}

Forneça sua análise no seguinte formato JSON:
{{
    "profile_analysis": "O que dá pra perceber sobre essa pessoa baseado no perfil (seja informal)",
    "conversation_analysis": "Como tá o papo - ela tá interessada? tá fria? análise real",
    "suggestions": "Dicas práticas de como continuar - seja específico e informal",
    "compatibility_score": número de 0 a 100,
    "whatsapp_topics": [
        "Assunto 1 pra puxar papo no WhatsApp baseado no perfil/conversa",
        "Assunto 2 - algo que ela demonstrou interesse",
        "Assunto 3 - algo em comum ou que dá pra perguntar"
    ],
    "warning_signs": "Algum sinal de alerta ou coisa pra prestar atenção (ou null se tudo ok)",
    "vibe_check": "Resumo rápido da vibe dela em uma frase"
}}

Responda APENAS com o JSON, sem markdown."""

                response = openai_client.client.chat.completions.create(
                    model=openai_client.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7
                )
                
                import json
                report_text = response.choices[0].message.content.strip()
                # Limpar possíveis marcadores de código
                if report_text.startswith("```"):
                    report_text = report_text.split("```")[1]
                    if report_text.startswith("json"):
                        report_text = report_text[4:]
                report = json.loads(report_text)
                
            except Exception as ai_error:
                logger.warning(f"Erro ao gerar relatório com IA: {ai_error}")
                # Relatório básico sem IA
                report = {
                    "profile_analysis": f"Perfil: {profile_info}",
                    "conversation_analysis": f"Total de {len(messages)} mensagens trocadas" if messages else "Nenhuma conversa iniciada",
                    "suggestions": "Inicie uma conversa interessante baseada no perfil" if not messages else "Continue a conversa de forma natural",
                    "compatibility_score": 50
                }
            
            add_log(f'📊 Relatório gerado para: {match.name}', 'info')
            
            return jsonify({
                'success': True,
                'data': report
            })
            
    except Exception as e:
        logger.error(f"Erro ao gerar relatório: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/matches/<int:match_id>/unblock', methods=['POST'])
def api_unblock_match(match_id):
    """Desbloqueia um match."""
    try:
        with db.get_session() as session:
            repo = MatchRepository(session)
            match = repo.get_by_id(match_id)
            
            if not match:
                return jsonify({'success': False, 'error': 'Match não encontrado'}), 404
            
            repo.unblock_match(match)
            session.commit()
            
            add_log(f'✅ Match desbloqueado: {match.name}', 'info')
            
            return jsonify({
                'success': True,
                'message': f'Match {match.name} desbloqueado'
            })
            
    except Exception as e:
        logger.error(f"Erro ao desbloquear match: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/matches/block-by-name', methods=['POST'])
def api_block_by_name():
    """Bloqueia match pelo nome."""
    try:
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        reason = data.get('reason', 'Bloqueado via interface web')
        
        if not name:
            return jsonify({'success': False, 'error': 'Nome é obrigatório'}), 400
        
        with db.get_session() as session:
            matches = session.query(Match).filter(
                Match.name.ilike(f'%{name}%'),
                Match.is_blocked != True
            ).all()
            
            if not matches:
                return jsonify({'success': False, 'error': f'Nenhum match encontrado com nome "{name}"'}), 404
            
            repo = MatchRepository(session)
            blocked_count = 0
            
            for match in matches:
                repo.block_match(match, reason)
                blocked_count += 1
            
            session.commit()
            
            add_log(f'🚫 {blocked_count} match(es) bloqueado(s) com nome "{name}"', 'warning')
            
            return jsonify({
                'success': True,
                'message': f'{blocked_count} match(es) bloqueado(s)',
                'blocked_count': blocked_count
            })
            
    except Exception as e:
        logger.error(f"Erro ao bloquear por nome: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - RELATÓRIOS =====================

@app.route('/api/reports/generate', methods=['POST'])
def api_generate_report():
    """Gera relatório."""
    try:
        add_log('📊 Gerando relatório...', 'info')
        
        from reports import generate_report
        result = generate_report()
        
        if result.get('success'):
            add_log(f'✅ Relatório gerado: {result.get("report_path", "N/A")}', 'success')
        else:
            add_log(f'❌ Erro ao gerar relatório', 'error')
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Erro ao gerar relatório: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - PERFIL =====================

@app.route('/api/profile')
def api_my_profile():
    """Retorna meu perfil com fotos."""
    try:
        with db.get_session() as session:
            repo = MyProfileRepository(session)
            profile = repo.get_or_create()
            
            # Buscar fotos
            photos = [
                {
                    'id': photo.id,
                    'url': photo.photo_url,
                    'order': photo.photo_order,
                    'description': photo.description
                }
                for photo in sorted(profile.photos, key=lambda x: x.photo_order)
            ] if profile.photos else []
            
            # Buscar interesses
            interests = [i.interest_name for i in profile.interests] if profile.interests else []
            
            return jsonify({
                'success': True,
                'data': {
                    'id': profile.id,
                    'name': profile.name,
                    'age': profile.age,
                    'bio': profile.bio,
                    'location': profile.location,
                    'job_title': profile.job_title,
                    'company': profile.company,
                    'school': profile.school,
                    'photos': photos,
                    'interests': interests,
                    'photos_count': len(photos),
                    'overall_score': profile.overall_score,
                    'updated_at': profile.updated_at.isoformat() if profile.updated_at else None
                }
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar perfil: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - PREVIEW DE MENSAGENS =====================

@app.route('/api/preview/messages', methods=['POST'])
def api_preview_messages():
    """
    Preview de mensagens que seriam enviadas (modo simulação).
    Gera mensagens mas NÃO envia para o Tinder.
    """
    try:
        from ai import get_openai_client
        
        data = request.get_json() or {}
        message_type = data.get('type', 'first')  # 'first' ou 'response'
        limit = min(int(data.get('limit', 5)), 10)
        
        openai_client = get_openai_client()
        previews = []
        
        with db.get_session() as session:
            match_repo = MatchRepository(session)
            msg_repo = MessageRepository(session)
            
            if message_type == 'first':
                # Preview de primeiras mensagens
                matches = match_repo.get_matches_without_messages()[:limit]
                
                for match in matches:
                    match_profile = {
                        "name": match.name,
                        "age": match.age,
                        "bio": match.bio,
                        "job_title": match.job_title,
                        "interests": match_repo.get_interests(match)
                    }
                    
                    # Gerar mensagem
                    ai_result = openai_client.generate_first_message(
                        match_profile=match_profile
                    )
                    
                    previews.append({
                        'match_id': match.id,
                        'match_name': match.name,
                        'match_age': match.age,
                        'type': 'first_message',
                        'message': ai_result.get('message', ''),
                        'hook_used': ai_result.get('hook_used', ''),
                        'confidence': ai_result.get('confidence_score', 0)
                    })
            
            else:
                # Preview de respostas
                matches = match_repo.get_matches_awaiting_my_response()[:limit]
                
                for match in matches:
                    # Buscar mensagens do match
                    messages = msg_repo.get_messages_for_match(match.id, limit=10)
                    
                    if not messages:
                        continue
                    
                    # Formatar histórico
                    # NOTA: messages vem em ordem desc (mais recente primeiro)
                    # Reverter para ordem cronológica (mais antiga primeiro)
                    messages_chronological = list(reversed(messages))
                    conversation = []
                    for msg in messages_chronological:
                        conversation.append({
                            "content": msg.content,
                            "is_from_me": msg.is_from_me
                        })
                    
                    # Última mensagem é a mais recente (messages[0])
                    last_msg = messages[0] if messages else None
                    
                    match_profile = {
                        "name": match.name,
                        "age": match.age,
                        "bio": match.bio,
                        "interests": match_repo.get_interests(match)
                    }
                    
                    # Gerar resposta
                    ai_result = openai_client.analyze_conversation_and_respond(
                        match_profile=match_profile,
                        conversation_history=conversation[:-1],
                        last_message=last_msg.content if last_msg else ""
                    )
                    
                    previews.append({
                        'match_id': match.id,
                        'match_name': match.name,
                        'match_age': match.age,
                        'type': 'response',
                        'last_message_received': last_msg.content if last_msg else '',
                        'message': ai_result.get('suggested_response', ''),
                        'temperature': ai_result.get('temperature_label', ''),
                        'temperature_score': ai_result.get('temperature_score', 0),
                        'next_step': ai_result.get('next_step_recommendation', '')
                    })
        
        add_log(f'👁️ Preview gerado: {len(previews)} mensagens', 'info')
        
        return jsonify({
            'success': True,
            'data': previews,
            'count': len(previews),
            'type': message_type
        })
        
    except Exception as e:
        logger.error(f"Erro ao gerar preview: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/stats/temperature')
def api_temperature_stats():
    """Retorna estatísticas de temperatura das conversas."""
    try:
        with db.get_session() as session:
            hot_count = session.query(func.count(Match.id)).filter(
                Match.conversation_temperature == 'hot'
            ).scalar() or 0
            
            warm_count = session.query(func.count(Match.id)).filter(
                Match.conversation_temperature == 'warm'
            ).scalar() or 0
            
            cold_count = session.query(func.count(Match.id)).filter(
                Match.conversation_temperature == 'cold'
            ).scalar() or 0
            
            unmatched_count = session.query(func.count(Match.id)).filter(
                Match.is_unmatched == True
            ).scalar() or 0
            
            return jsonify({
                'success': True,
                'data': {
                    'hot': hot_count,
                    'warm': warm_count,
                    'cold': cold_count,
                    'unmatched': unmatched_count
                }
            })
            
    except Exception as e:
        logger.error(f"Erro ao buscar stats de temperatura: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - NOTIFICAÇÕES =====================

@app.route('/api/notifications')
def api_notifications():
    """Retorna lista de notificações."""
    try:
        limit = int(request.args.get('limit', 50))
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        
        manager = get_notification_manager()
        
        if unread_only:
            notifications = manager.get_unread()[:limit]
        else:
            notifications = manager.get_all(limit)
        
        return jsonify({
            'success': True,
            'data': notifications,
            'unread_count': manager.get_unread_count(),
            'total': len(notifications)
        })
        
    except Exception as e:
        logger.error(f"Erro ao buscar notificações: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/notifications/count')
def api_notifications_count():
    """Retorna apenas a contagem de notificações não lidas.
    
    Isento de rate limiting pois é usado para polling frequente.
    """
    try:
        manager = get_notification_manager()
        return jsonify({
            'success': True,
            'unread_count': manager.get_unread_count()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Isentar endpoint de rate limiting se disponível
if limiter:
    api_notifications_count = limiter.exempt(api_notifications_count)


# ===================== AI PROVIDERS MANAGEMENT =====================

@app.route('/api/ai/providers')
def api_ai_providers():
    """Retorna lista de todos os provedores de IA disponíveis."""
    try:
        from ai import get_ai_manager
        
        manager = get_ai_manager()
        providers = manager.get_all_providers_status()
        
        return jsonify({
            'success': True,
            'providers': providers,
            'active_provider': manager._active_provider_id
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter provedores de IA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/providers/<provider_id>/activate', methods=['POST'])
def api_activate_ai_provider(provider_id):
    """Ativa um provedor de IA."""
    try:
        from ai import get_ai_manager
        
        manager = get_ai_manager()
        success = manager.set_active_provider(provider_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Provedor {provider_id} ativado com sucesso'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Não foi possível ativar o provedor. Verifique se está configurado e habilitado.'
            }), 400
            
    except Exception as e:
        logger.error(f"Erro ao ativar provedor {provider_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/providers/<provider_id>/enable', methods=['POST'])
def api_enable_ai_provider(provider_id):
    """Habilita um provedor de IA."""
    try:
        from ai import get_ai_manager
        
        manager = get_ai_manager()
        success = manager.enable_provider(provider_id)
        
        return jsonify({
            'success': success,
            'message': f'Provedor {provider_id} habilitado' if success else 'Falha ao habilitar'
        })
        
    except Exception as e:
        logger.error(f"Erro ao habilitar provedor {provider_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/providers/<provider_id>/disable', methods=['POST'])
def api_disable_ai_provider(provider_id):
    """Desabilita um provedor de IA."""
    try:
        from ai import get_ai_manager
        
        manager = get_ai_manager()
        success = manager.disable_provider(provider_id)
        
        return jsonify({
            'success': success,
            'message': f'Provedor {provider_id} desabilitado' if success else 'Falha ao desabilitar'
        })
        
    except Exception as e:
        logger.error(f"Erro ao desabilitar provedor {provider_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/providers/<provider_id>/model', methods=['POST'])
def api_set_ai_model(provider_id):
    """Define o modelo de um provedor de IA."""
    try:
        from ai import get_ai_manager
        
        data = request.get_json() or {}
        model_id = data.get('model_id')
        
        if not model_id:
            return jsonify({'success': False, 'error': 'model_id é obrigatório'}), 400
        
        manager = get_ai_manager()
        success = manager.set_provider_model(provider_id, model_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Modelo alterado para {model_id}'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Falha ao definir modelo. Verifique se é válido.'
            }), 400
            
    except Exception as e:
        logger.error(f"Erro ao definir modelo do provedor {provider_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/providers/<provider_id>/configure', methods=['POST'])
def api_configure_ai_provider(provider_id):
    """Configura um provedor de IA com nova API key."""
    try:
        from ai import get_ai_manager
        import os
        
        data = request.get_json() or {}
        api_key = data.get('api_key')
        model = data.get('model')
        
        if not api_key:
            return jsonify({'success': False, 'error': 'api_key é obrigatória'}), 400
        
        manager = get_ai_manager()
        success = manager.initialize_provider(
            provider_id=provider_id,
            api_key=api_key,
            model=model,
            set_as_active=data.get('set_as_active', False)
        )
        
        if success:
            # Atualizar variável de ambiente em runtime
            env_key = f"{provider_id.upper()}_API_KEY"
            os.environ[env_key] = api_key
            if model:
                os.environ[f"{provider_id.upper()}_MODEL"] = model
            os.environ[f"{provider_id.upper()}_ENABLED"] = "true"
            
            return jsonify({
                'success': True,
                'message': f'Provedor {provider_id} configurado com sucesso'
            })
        else:
            provider = manager.get_provider(provider_id)
            error = provider.last_error if provider else "Provedor não encontrado"
            return jsonify({
                'success': False,
                'error': f'Falha ao configurar: {error}'
            }), 400
            
    except Exception as e:
        logger.error(f"Erro ao configurar provedor {provider_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/test', methods=['POST'])
def api_test_ai():
    """Testa a conexão com o provedor de IA ativo."""
    try:
        from ai import get_ai_manager, AIProviderError, BudgetExceededError
        
        manager = get_ai_manager()
        provider = manager.get_active_provider()
        
        if not provider:
            return jsonify({
                'success': False,
                'error': 'Nenhum provedor de IA ativo'
            }), 400
        
        # Fazer uma chamada simples de teste
        try:
            response = manager.chat_completion(
                messages=[
                    {"role": "user", "content": "Responda apenas com 'OK' para confirmar que está funcionando."}
                ],
                temperature=0,
                max_tokens=10,
                interaction_type='test'
            )
            
            return jsonify({
                'success': True,
                'message': 'Conexão com IA funcionando',
                'provider': provider.PROVIDER_ID,
                'model': provider.current_model,
                'response': response.content,
                'tokens_used': response.total_tokens
            })
            
        except BudgetExceededError as e:
            return jsonify({
                'success': False,
                'error': 'Budget excedido',
                'error_type': 'budget_exceeded',
                'details': e.details
            }), 402  # Payment Required
            
    except Exception as e:
        logger.error(f"Erro ao testar IA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/usage')
def api_ai_usage():
    """Retorna estatísticas de uso de tokens por provedor."""
    try:
        from ai import get_ai_manager
        
        manager = get_ai_manager()
        usage_data = manager.get_usage_stats()
        
        return jsonify({
            'success': True,
            'usage': usage_data
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas de uso de IA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/costs')
def api_ai_costs():
    """
    Retorna gastos detalhados com IA por provedor e tipo de interação.
    
    Query params:
        days: Número de dias a considerar (default: 30)
    """
    try:
        from database import AIInteractionRepository
        
        days = int(request.args.get('days', 30))
        
        with db.get_session() as session:
            repo = AIInteractionRepository(session)
            stats = repo.get_detailed_stats(days=days)
        
        return jsonify({
            'success': True,
            'data': stats
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter gastos de IA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/costs/by-provider')
def api_ai_costs_by_provider():
    """Retorna gastos agrupados por provedor."""
    try:
        from database import AIInteractionRepository
        
        days = int(request.args.get('days', 30))
        
        with db.get_session() as session:
            repo = AIInteractionRepository(session)
            by_provider = repo.get_cost_by_provider(days=days)
        
        return jsonify({
            'success': True,
            'data': by_provider,
            'period_days': days
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter gastos por provedor: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai/costs/by-type')
def api_ai_costs_by_type():
    """Retorna gastos agrupados por tipo de interação."""
    try:
        from database import AIInteractionRepository
        
        days = int(request.args.get('days', 30))
        provider = request.args.get('provider')  # Opcional
        
        with db.get_session() as session:
            repo = AIInteractionRepository(session)
            by_type = repo.get_cost_by_type(provider=provider, days=days)
        
        return jsonify({
            'success': True,
            'data': by_type,
            'provider': provider,
            'period_days': days
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter gastos por tipo: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/notifications/<notification_id>/read', methods=['POST'])
def api_mark_notification_read(notification_id):
    """Marca uma notificação como lida."""
    try:
        manager = get_notification_manager()
        success = manager.mark_as_read(notification_id)
        
        if success:
            return jsonify({'success': True, 'message': 'Notificação marcada como lida'})
        else:
            return jsonify({'success': False, 'error': 'Notificação não encontrada'}), 404
            
    except Exception as e:
        logger.error(f"Erro ao marcar notificação como lida: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/notifications/read-all', methods=['POST'])
def api_mark_all_notifications_read():
    """Marca todas as notificações como lidas."""
    try:
        manager = get_notification_manager()
        count = manager.mark_all_as_read()
        
        return jsonify({
            'success': True,
            'message': f'{count} notificações marcadas como lidas',
            'marked_count': count
        })
        
    except Exception as e:
        logger.error(f"Erro ao marcar notificações como lidas: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/notifications/<notification_id>', methods=['DELETE'])
def api_delete_notification(notification_id):
    """Remove uma notificação."""
    try:
        manager = get_notification_manager()
        success = manager.delete(notification_id)
        
        if success:
            return jsonify({'success': True, 'message': 'Notificação removida'})
        else:
            return jsonify({'success': False, 'error': 'Notificação não encontrada'}), 404
            
    except Exception as e:
        logger.error(f"Erro ao remover notificação: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/notifications/clear', methods=['POST'])
def api_clear_notifications():
    """Remove todas as notificações."""
    try:
        manager = get_notification_manager()
        count = manager.clear_all()
        
        return jsonify({
            'success': True,
            'message': f'{count} notificações removidas',
            'cleared_count': count
        })
        
    except Exception as e:
        logger.error(f"Erro ao limpar notificações: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# Endpoint de teste para adicionar notificação
@app.route('/api/notifications/test', methods=['POST'])
def api_test_notification():
    """Adiciona notificação de teste."""
    try:
        data = request.get_json() or {}
        notification_type = data.get('type', 'new_message')
        message = data.get('message', 'Notificação de teste')
        
        manager = get_notification_manager()
        notification = manager.add(notification_type, message)
        
        return jsonify({
            'success': True,
            'notification': notification
        })
        
    except Exception as e:
        logger.error(f"Erro ao criar notificação de teste: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - LOGS MANAGEMENT =====================

@app.route('/api/logs/status')
def api_logs_status():
    """Retorna status atual dos arquivos de log."""
    try:
        from utils.log_cleaner import get_logs_status
        status = get_logs_status()
        
        return jsonify({
            'success': True,
            'data': status
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter status dos logs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/logs/cleanup', methods=['POST'])
@rate_limit("2 per hour")
def api_cleanup_logs():
    """Executa limpeza manual dos logs."""
    try:
        from utils.log_cleaner import cleanup_logs_now
        stats = cleanup_logs_now()
        
        add_log(
            f'🧹 Limpeza de logs: {stats.files_deleted} deletados, '
            f'{stats.files_compressed} comprimidos, '
            f'{stats.space_saved_mb:.1f}MB liberados',
            'info'
        )
        
        return jsonify({
            'success': True,
            'message': 'Limpeza de logs concluída',
            'data': stats.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Erro na limpeza de logs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - A/B TESTING =====================

@app.route('/api/ab-testing/experiments')
def api_ab_experiments():
    """Lista todos os experimentos A/B."""
    if not AB_TESTING_ENABLED:
        return jsonify({'success': False, 'error': 'A/B Testing não disponível'}), 501
    
    try:
        manager = get_ab_manager()
        experiments = manager.get_all_experiments()
        
        return jsonify({
            'success': True,
            'data': experiments
        })
        
    except Exception as e:
        logger.error(f"Erro ao listar experimentos: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ab-testing/experiments/<experiment_name>')
def api_ab_experiment_detail(experiment_name: str):
    """Retorna detalhes de um experimento."""
    if not AB_TESTING_ENABLED:
        return jsonify({'success': False, 'error': 'A/B Testing não disponível'}), 501
    
    try:
        manager = get_ab_manager()
        results = manager.get_experiment_results(experiment_name)
        
        if not results:
            return jsonify({'success': False, 'error': 'Experimento não encontrado'}), 404
        
        return jsonify({
            'success': True,
            'data': results
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter experimento: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ab-testing/experiments', methods=['POST'])
@rate_limit("10 per hour")
def api_create_ab_experiment():
    """Cria novo experimento A/B."""
    if not AB_TESTING_ENABLED:
        return jsonify({'success': False, 'error': 'A/B Testing não disponível'}), 501
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Dados inválidos'}), 400
        
        name = data.get('name')
        variants = data.get('variants', [])
        weights = data.get('weights')
        description = data.get('description', '')
        
        if not name or not variants:
            return jsonify({'success': False, 'error': 'Nome e variantes são obrigatórios'}), 400
        
        manager = get_ab_manager()
        experiment = manager.create_experiment(name, variants, weights, description)
        
        return jsonify({
            'success': True,
            'data': experiment.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Erro ao criar experimento: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ab-testing/experiments/<experiment_name>/pause', methods=['POST'])
def api_pause_ab_experiment(experiment_name: str):
    """Pausa um experimento."""
    if not AB_TESTING_ENABLED:
        return jsonify({'success': False, 'error': 'A/B Testing não disponível'}), 501
    
    try:
        manager = get_ab_manager()
        success = manager.pause_experiment(experiment_name)
        
        return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"Erro ao pausar experimento: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ab-testing/experiments/<experiment_name>/resume', methods=['POST'])
def api_resume_ab_experiment(experiment_name: str):
    """Retoma um experimento."""
    if not AB_TESTING_ENABLED:
        return jsonify({'success': False, 'error': 'A/B Testing não disponível'}), 501
    
    try:
        manager = get_ab_manager()
        success = manager.resume_experiment(experiment_name)
        
        return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"Erro ao retomar experimento: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - ML INSIGHTS =====================

@app.route('/api/ml/insights')
def api_ml_insights():
    """Retorna insights gerais do ML Adaptive."""
    try:
        from services.ml_adaptive import get_ml_service
        
        ml = get_ml_service()
        stats = ml.get_stats()
        
        # Obter insights de todos os experimentos
        experiments_insights = []
        for exp_name in stats.get('experiments', []):
            insights = ml.get_experiment_insights(exp_name)
            experiments_insights.append(insights)
        
        return jsonify({
            'success': True,
            'stats': stats,
            'experiments': experiments_insights
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter ML insights: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ml/insights/<experiment_name>')
def api_ml_experiment_insights(experiment_name: str):
    """Retorna insights detalhados de um experimento específico."""
    try:
        from services.ml_adaptive import get_ml_service
        
        ml = get_ml_service()
        insights = ml.get_experiment_insights(experiment_name)
        suggestions = ml.get_prompt_suggestions(experiment_name)
        
        return jsonify({
            'success': True,
            'insights': insights,
            'suggestions': suggestions
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter insights do experimento {experiment_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ml/auto-adjust/<experiment_name>', methods=['POST'])
def api_ml_auto_adjust(experiment_name: str):
    """Executa ajuste automático de pesos para um experimento."""
    try:
        from services.ml_adaptive import get_ml_service
        
        ml = get_ml_service()
        data = request.get_json() or {}
        min_samples = data.get('min_samples', 50)
        
        success = ml.auto_adjust_weights(experiment_name, min_samples=min_samples)
        
        if success:
            # Obter novos insights após ajuste
            insights = ml.get_experiment_insights(experiment_name)
            return jsonify({
                'success': True,
                'message': f'Pesos ajustados para {experiment_name}',
                'insights': insights
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Não foi possível ajustar (amostras insuficientes ou sem diferença significativa)'
            }), 400
        
    except Exception as e:
        logger.error(f"Erro ao ajustar pesos do experimento {experiment_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ml/stats')
def api_ml_stats():
    """Retorna estatísticas gerais do sistema ML."""
    try:
        from services.ml_adaptive import get_ml_service
        
        ml = get_ml_service()
        return jsonify({
            'success': True,
            'stats': ml.get_stats()
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas ML: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - SCHEDULER =====================

@app.route('/api/scheduler/status')
def api_scheduler_status():
    """Retorna status do scheduler e tarefas agendadas."""
    try:
        from services.scheduler_service import get_scheduler
        
        scheduler = get_scheduler()
        return jsonify({
            'success': True,
            'status': scheduler.get_status()
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter status do scheduler: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/scheduler/task/<task_name>/run', methods=['POST'])
def api_run_scheduler_task(task_name: str):
    """Executa uma tarefa imediatamente."""
    try:
        from services.scheduler_service import get_scheduler
        
        scheduler = get_scheduler()
        success = scheduler.run_task_now(task_name)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Tarefa {task_name} executada'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Tarefa {task_name} não encontrada'
            }), 404
        
    except Exception as e:
        logger.error(f"Erro ao executar tarefa {task_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/scheduler/task/<task_name>/enable', methods=['POST'])
def api_enable_scheduler_task(task_name: str):
    """Habilita uma tarefa."""
    try:
        from services.scheduler_service import get_scheduler
        
        scheduler = get_scheduler()
        success = scheduler.enable_task(task_name)
        
        return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"Erro ao habilitar tarefa {task_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/scheduler/task/<task_name>/disable', methods=['POST'])
def api_disable_scheduler_task(task_name: str):
    """Desabilita uma tarefa."""
    try:
        from services.scheduler_service import get_scheduler
        
        scheduler = get_scheduler()
        success = scheduler.disable_task(task_name)
        
        return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"Erro ao desabilitar tarefa {task_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - EMBEDDINGS CACHE =====================

@app.route('/api/cache/embeddings/stats')
def api_embeddings_cache_stats():
    """Retorna estatísticas do cache de embeddings."""
    try:
        from services.embeddings_cache import get_embeddings_cache
        
        cache = get_embeddings_cache()
        return jsonify({
            'success': True,
            'stats': cache.get_stats()
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter stats do cache: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cache/embeddings/cleanup', methods=['POST'])
def api_embeddings_cache_cleanup():
    """Remove entradas expiradas do cache."""
    try:
        from services.embeddings_cache import get_embeddings_cache
        
        cache = get_embeddings_cache()
        deleted = cache.cleanup_expired()
        
        return jsonify({
            'success': True,
            'deleted': deleted
        })
        
    except Exception as e:
        logger.error(f"Erro ao limpar cache: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cache/embeddings/clear', methods=['POST'])
def api_embeddings_cache_clear():
    """Limpa todo o cache de embeddings."""
    try:
        from services.embeddings_cache import get_embeddings_cache
        
        model = request.json.get('model') if request.is_json else None
        
        cache = get_embeddings_cache()
        deleted = cache.clear(model=model)
        
        return jsonify({
            'success': True,
            'deleted': deleted,
            'model': model or 'all'
        })
        
    except Exception as e:
        logger.error(f"Erro ao limpar cache: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - AUDIT LOG =====================

@app.route('/api/audit/logs')
def api_audit_logs():
    """Lista logs de auditoria."""
    if not AUDIT_ENABLED:
        return jsonify({'success': False, 'error': 'Audit não disponível'}), 501
    
    try:
        audit = get_audit_logger()
        
        # Parâmetros de filtro
        action = request.args.get('action')
        resource_type = request.args.get('resource_type')
        limit = int(request.args.get('limit', 100))
        
        logs = audit.get_logs(
            action=action,
            resource_type=resource_type,
            limit=min(limit, 500)  # Máximo 500
        )
        
        return jsonify({
            'success': True,
            'data': logs
        })
        
    except Exception as e:
        logger.error(f"Erro ao listar audit logs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/audit/summary')
def api_audit_summary():
    """Resumo de atividades de auditoria."""
    if not AUDIT_ENABLED:
        return jsonify({'success': False, 'error': 'Audit não disponível'}), 501
    
    try:
        audit = get_audit_logger()
        days = int(request.args.get('days', 7))
        
        summary = audit.get_summary(days=min(days, 30))
        
        return jsonify({
            'success': True,
            'data': summary
        })
        
    except Exception as e:
        logger.error(f"Erro ao gerar resumo de audit: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - MAINTENANCE =====================

@app.route('/api/maintenance/clean-message-previews', methods=['POST'])
def api_clean_message_previews():
    """Limpa os textos de última mensagem removendo prefixos do Tinder."""
    try:
        cleaned_count = 0
        
        with db.get_session() as session:
            # Buscar matches com last_message_text que contém o padrão problemático
            matches = session.query(Match).filter(
                Match.last_message_text.isnot(None),
                Match.last_message_text != ''
            ).all()
            
            for match in matches:
                original = match.last_message_text
                cleaned = clean_message_preview(original, match.name)
                
                if cleaned != original:
                    match.last_message_text = cleaned
                    cleaned_count += 1
            
            session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Limpeza concluída: {cleaned_count} mensagens atualizadas',
            'cleaned_count': cleaned_count
        })
        
    except Exception as e:
        logger.error(f"Erro ao limpar previews: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - BACKGROUND TASKS =====================

@app.route('/api/tasks')
def api_list_tasks():
    """Lista todas as tasks executadas e em execução."""
    if not BACKGROUND_TASKS_ENABLED:
        return jsonify({'success': False, 'error': 'Background Tasks não disponível'}), 501
    
    try:
        task_manager = get_task_manager()
        
        tasks = task_manager.get_all_tasks(limit=50)
        running = task_manager.get_running_tasks()
        scheduled = task_manager.get_scheduled_tasks()
        
        return jsonify({
            'success': True,
            'data': {
                'tasks': [
                    {
                        'task_id': t.task_id,
                        'task_name': t.task_name,
                        'status': t.status.value,
                        'result': t.result if t.status.value == 'completed' else None,
                        'error': t.error,
                        'started_at': t.started_at.isoformat() if t.started_at else None,
                        'completed_at': t.completed_at.isoformat() if t.completed_at else None,
                        'duration_ms': t.duration_ms
                    }
                    for t in tasks
                ],
                'running_count': len(running),
                'scheduled': scheduled
            }
        })
        
    except Exception as e:
        logger.error(f"Erro ao listar tasks: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tasks/<task_id>')
def api_get_task(task_id):
    """Obtém status de uma task específica."""
    if not BACKGROUND_TASKS_ENABLED:
        return jsonify({'success': False, 'error': 'Background Tasks não disponível'}), 501
    
    try:
        task_manager = get_task_manager()
        task = task_manager.get_task_status(task_id)
        
        if not task:
            return jsonify({'success': False, 'error': 'Task não encontrada'}), 404
        
        return jsonify({
            'success': True,
            'data': {
                'task_id': task.task_id,
                'task_name': task.task_name,
                'status': task.status.value,
                'result': task.result,
                'error': task.error,
                'started_at': task.started_at.isoformat() if task.started_at else None,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                'duration_ms': task.duration_ms
            }
        })
        
    except Exception as e:
        logger.error(f"Erro ao obter task: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tasks/sync', methods=['POST'])
def api_task_sync_now():
    """Executa sync de matches sob demanda via Background Task."""
    if not BACKGROUND_TASKS_ENABLED:
        return jsonify({'success': False, 'error': 'Background Tasks não disponível'}), 501
    
    if automation_state['is_syncing']:
        return jsonify({'success': False, 'error': 'Sincronização já em andamento'}), 400
    
    if automation_state['is_running']:
        return jsonify({'success': False, 'error': 'Automação em execução'}), 400
    
    try:
        task_id = submit_task(_sync_matches_task, task_name='sync_matches_manual')
        
        return jsonify({
            'success': True,
            'message': 'Sincronização iniciada em background',
            'task_id': task_id
        })
        
    except Exception as e:
        logger.error(f"Erro ao iniciar sync: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tasks/scheduled')
def api_scheduled_tasks():
    """Lista tasks agendadas."""
    if not BACKGROUND_TASKS_ENABLED:
        return jsonify({'success': False, 'error': 'Background Tasks não disponível'}), 501
    
    try:
        task_manager = get_task_manager()
        scheduled = task_manager.get_scheduled_tasks()
        
        return jsonify({
            'success': True,
            'data': scheduled
        })
        
    except Exception as e:
        logger.error(f"Erro ao listar tasks agendadas: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tasks/scheduled/<name>/run', methods=['POST'])
def api_run_scheduled_task(name):
    """Executa uma task agendada imediatamente."""
    if not BACKGROUND_TASKS_ENABLED:
        return jsonify({'success': False, 'error': 'Background Tasks não disponível'}), 501
    
    try:
        task_manager = get_task_manager()
        task_id = task_manager.run_scheduled_now(name)
        
        if not task_id:
            return jsonify({'success': False, 'error': f'Task agendada não encontrada: {name}'}), 404
        
        return jsonify({
            'success': True,
            'message': f'Task {name} executada',
            'task_id': task_id
        })
        
    except Exception as e:
        logger.error(f"Erro ao executar task agendada: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tasks/scheduled/<name>/pause', methods=['POST'])
def api_pause_scheduled_task(name):
    """Pausa uma task agendada."""
    if not BACKGROUND_TASKS_ENABLED:
        return jsonify({'success': False, 'error': 'Background Tasks não disponível'}), 501
    
    try:
        task_manager = get_task_manager()
        success = task_manager.pause_scheduled(name)
        
        if not success:
            return jsonify({'success': False, 'error': f'Task não encontrada: {name}'}), 404
        
        return jsonify({
            'success': True,
            'message': f'Task {name} pausada'
        })
        
    except Exception as e:
        logger.error(f"Erro ao pausar task: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tasks/scheduled/<name>/resume', methods=['POST'])
def api_resume_scheduled_task(name):
    """Retoma uma task agendada pausada."""
    if not BACKGROUND_TASKS_ENABLED:
        return jsonify({'success': False, 'error': 'Background Tasks não disponível'}), 501
    
    try:
        task_manager = get_task_manager()
        success = task_manager.resume_scheduled(name)
        
        if not success:
            return jsonify({'success': False, 'error': f'Task não encontrada: {name}'}), 404
        
        return jsonify({
            'success': True,
            'message': f'Task {name} retomada'
        })
        
    except Exception as e:
        logger.error(f"Erro ao retomar task: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tasks/scheduled/add', methods=['POST'])
def api_add_scheduled_task():
    """Adiciona uma nova task agendada."""
    if not BACKGROUND_TASKS_ENABLED:
        return jsonify({'success': False, 'error': 'Background Tasks não disponível'}), 501
    
    try:
        data = request.json
        name = data.get('name')
        task_type = data.get('task_type')  # 'sync', 'cleanup', etc
        interval_minutes = data.get('interval_minutes', 30)
        
        if not name or not task_type:
            return jsonify({'success': False, 'error': 'Nome e tipo são obrigatórios'}), 400
        
        # Mapear tipos para funções
        task_functions = {
            'sync': _sync_matches_task,
            # Adicionar outras funções conforme necessário
        }
        
        func = task_functions.get(task_type)
        if not func:
            return jsonify({'success': False, 'error': f'Tipo de task inválido: {task_type}'}), 400
        
        schedule_task(
            name=name,
            func=func,
            interval_seconds=interval_minutes * 60,
            run_immediately=data.get('run_immediately', False)
        )
        
        return jsonify({
            'success': True,
            'message': f'Task {name} agendada para cada {interval_minutes} minutos'
        })
        
    except Exception as e:
        logger.error(f"Erro ao adicionar task agendada: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== API - ADVANCED METRICS =====================

@app.route('/api/metrics/conversion-funnel')
def api_conversion_funnel():
    """Retorna dados do funil de conversão."""
    try:
        with db.get_session() as session:
            # Total de matches
            total_matches = session.query(func.count(Match.id)).scalar() or 0
            
            # Matches com mensagem enviada (por mim)
            matches_with_message = session.query(func.count(func.distinct(Message.match_id)))\
                .filter(Message.is_from_me == True).scalar() or 0
            
            # Matches com resposta recebida (mensagens que não são minhas)
            matches_with_response = session.query(func.count(func.distinct(Message.match_id)))\
                .filter(Message.is_from_me == False).scalar() or 0
            
            # Matches hot (temperatura_score >= 4)
            hot_matches = session.query(func.count(Match.id))\
                .filter(Match.temperature_score >= 4).scalar() or 0
            
            # WhatsApp obtidos
            whatsapp_obtained = session.query(func.count(Match.id))\
                .filter(Match.whatsapp_obtained == True).scalar() or 0
            
            # Encontros confirmados
            dates_confirmed = session.query(func.count(Match.id))\
                .filter(Match.date_confirmed == True).scalar() or 0
        
        funnel = [
            {'stage': 'Matches', 'count': total_matches, 'percentage': 100},
            {'stage': 'Mensagem Enviada', 'count': matches_with_message, 
             'percentage': round(matches_with_message / total_matches * 100, 1) if total_matches else 0},
            {'stage': 'Resposta Recebida', 'count': matches_with_response,
             'percentage': round(matches_with_response / total_matches * 100, 1) if total_matches else 0},
            {'stage': 'Hot (Temp ≥4)', 'count': hot_matches,
             'percentage': round(hot_matches / total_matches * 100, 1) if total_matches else 0},
            {'stage': 'WhatsApp', 'count': whatsapp_obtained,
             'percentage': round(whatsapp_obtained / total_matches * 100, 1) if total_matches else 0},
            {'stage': 'Encontro', 'count': dates_confirmed,
             'percentage': round(dates_confirmed / total_matches * 100, 1) if total_matches else 0}
        ]
        
        return jsonify({
            'success': True,
            'data': funnel
        })
        
    except Exception as e:
        logger.error(f"Erro ao calcular funil: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/metrics/temperature-stats')
def api_metrics_temperature_stats():
    """Estatísticas por temperatura (métricas avançadas)."""
    try:
        with db.get_session() as session:
            # Distribuição por conversation_temperature (cold, warm, hot)
            temp_distribution = session.query(
                Match.conversation_temperature,
                func.count(Match.id).label('count')
            ).filter(Match.conversation_temperature.isnot(None))\
             .group_by(Match.conversation_temperature).all()
            
            distribution = {
                str(temp or 'unknown'): count for temp, count in temp_distribution
            }
            
            # Taxa de conversão por faixa de temperature_score (1-5)
            conversion_by_temp = []
            for temp in range(1, 6):
                # Score entre temp e temp+1 (ex: 1 a 2, 2 a 3, etc)
                total = session.query(func.count(Match.id))\
                    .filter(Match.temperature_score >= temp)\
                    .filter(Match.temperature_score < temp + 1).scalar() or 0
                
                converted = session.query(func.count(Match.id))\
                    .filter(Match.temperature_score >= temp)\
                    .filter(Match.temperature_score < temp + 1)\
                    .filter(Match.whatsapp_obtained == True).scalar() or 0
                
                conversion_by_temp.append({
                    'temperature': temp,
                    'total': total,
                    'converted': converted,
                    'conversion_rate': round(converted / total * 100, 1) if total else 0
                })
            
            # Tempo médio para atingir cada temperatura (se houver timestamps)
            # Simplificado por enquanto
        
        return jsonify({
            'success': True,
            'data': {
                'distribution': distribution,
                'conversion_by_temperature': conversion_by_temp
            }
        })
        
    except Exception as e:
        logger.error(f"Erro ao calcular stats de temperatura: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/metrics/ai-performance')
def api_ai_performance():
    """Métricas de performance da IA."""
    try:
        with db.get_session() as session:
            # Total de mensagens AI
            ai_messages = session.query(func.count(Message.id))\
                .filter(Message.ai_generated == True).scalar() or 0
            
            # Taxa de resposta para mensagens AI vs manuais
            ai_with_response = session.query(func.count(func.distinct(Message.match_id)))\
                .filter(Message.ai_generated == True)\
                .filter(Message.sender == 'user').scalar() or 0
            
            manual_messages = session.query(func.count(Message.id))\
                .filter(Message.ai_generated == False)\
                .filter(Message.sender == 'user').scalar() or 0
        
        return jsonify({
            'success': True,
            'data': {
                'ai_messages_total': ai_messages,
                'manual_messages_total': manual_messages,
                'ai_percentage': round(ai_messages / (ai_messages + manual_messages) * 100, 1) 
                                 if (ai_messages + manual_messages) else 0
            }
        })
        
    except Exception as e:
        logger.error(f"Erro ao calcular métricas de IA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/metrics/activity-heatmap')
def api_activity_heatmap():
    """Heatmap de atividade por hora e dia da semana."""
    try:
        with db.get_session() as session:
            # Mensagens por hora e dia da semana
            # Usar created_at das mensagens
            messages = session.query(
                func.datepart('weekday', Message.created_at).label('weekday'),
                func.datepart('hour', Message.created_at).label('hour'),
                func.count(Message.id).label('count')
            ).group_by(
                func.datepart('weekday', Message.created_at),
                func.datepart('hour', Message.created_at)
            ).all()
            
            # Formatar para heatmap
            heatmap_data = []
            for weekday, hour, count in messages:
                heatmap_data.append({
                    'weekday': int(weekday) if weekday else 0,
                    'hour': int(hour) if hour else 0,
                    'count': count
                })
        
        return jsonify({
            'success': True,
            'data': heatmap_data
        })
        
    except Exception as e:
        logger.error(f"Erro ao gerar heatmap: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ===================== WEBSOCKET EVENTS =====================

def emit_notification(notification_type: str, data: dict):
    """Emite notificação via WebSocket se disponível."""
    if WEBSOCKET_ENABLED and socketio:
        try:
            notifier = get_websocket_notifier()
            notifier.notify(notification_type, data)
        except Exception as e:
            logger.warning(f"Erro ao emitir WebSocket: {e}")


def emit_stats_update(stats: dict):
    """Emite atualização de estatísticas."""
    if WEBSOCKET_ENABLED and socketio:
        try:
            notifier = get_websocket_notifier()
            notifier.broadcast_stats(stats)
        except Exception as e:
            logger.warning(f"Erro ao emitir stats: {e}")


def emit_automation_status(status: dict):
    """Emite status da automação."""
    if WEBSOCKET_ENABLED and socketio:
        try:
            notifier = get_websocket_notifier()
            notifier.broadcast_automation_status(status)
        except Exception as e:
            logger.warning(f"Erro ao emitir automation status: {e}")


if __name__ == '__main__':
    run_web_server(debug=True)
