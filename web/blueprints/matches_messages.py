"""
Blueprint de stats, matches, mensagens e analytics.
Reaproveita os globais de web/app.py; nomes patchados nos testes (db, repos)
são acessados via webapp.* para que patch("web.app.X") continue válido.
"""
from flask import Blueprint

import web.app as webapp  # noqa: E402
from web.app import *  # noqa: F401, F403, E402

bp_matches_messages = Blueprint("matches_messages", __name__)

# ===================== API - ESTATÍSTICAS =====================

def compute_dashboard_stats(session) -> dict:
    """Calcula as métricas do dashboard a partir de uma sessão aberta.

    Compartilhado entre /api/stats (JSON) e /fragments/stats (HTML via HTMX).
    """
    def count(*filters):
        q = session.query(func.count(Match.id))
        return (q.filter(*filters).scalar() if filters else q.scalar()) or 0

    def count_msgs(condition):
        return session.query(func.count(Message.id)).filter(condition).scalar() or 0

    return {
        'total_matches': count(),
        'blocked_matches': count(Match.is_blocked == True),
        'awaiting_response': count(Match.awaiting_my_response == True, Match.is_blocked != True),
        'new_matches': count(Match.has_messages == False, Match.is_blocked != True),
        'messages_sent': count_msgs(Message.is_from_me == True),
        'messages_received': count_msgs(Message.is_from_me == False),
        'whatsapp_obtained': count(Match.whatsapp_obtained == True),
        'active_matches': count(Match.has_messages == True, Match.is_blocked != True),
        'pending_resend': count(Match.pending_resend == True, Match.is_blocked != True),
    }


@bp_matches_messages.route('/api/stats')
def api_stats():
    """Retorna estatísticas gerais (JSON)."""
    try:
        with webapp.db.get_session() as session:
            return jsonify({'success': True, 'data': compute_dashboard_stats(session)})
    except Exception as e:
        logger.error(f"Erro ao buscar stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Isentar endpoint de rate limiting (usado para polling no dashboard)
if limiter:
    api_stats = limiter.exempt(api_stats)


# Importar sanitizador de inputs
from utils.input_sanitizer import (
    sanitize_boolean,
    sanitize_integer,
    sanitize_pagination,
    sanitize_search_input,
    sanitize_sort_field,
)


@bp_matches_messages.route('/api/matches')
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
        limit = sanitize_integer(request.args.get('limit', 50), default=50, min_value=1, max_value=100)
        offset = sanitize_integer(request.args.get('offset', 0), default=0, min_value=0, max_value=100000)
        
        with webapp.db.get_session() as session:
            # Ordenar: primeiro por matched_at DESC (mais recente primeiro)
            # Perfis SEM data vão para o final (ordenados por created_at)
            from sqlalchemy import and_, case, nullslast, or_
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


@bp_matches_messages.route('/api/matches/<int:match_id>')
def api_match_detail(match_id):
    """Retorna detalhes de um match específico."""
    try:
        with webapp.db.get_session() as session:
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


@bp_matches_messages.route('/api/matches/<int:match_id>/profile')
def api_match_profile(match_id):
    """Retorna dados completos do perfil de um match."""
    try:
        with webapp.db.get_session() as session:
            match_repo = webapp.MatchRepository(session)
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


@bp_matches_messages.route('/api/matches/<int:match_id>/report')
@rate_limit("20 per hour")
def api_match_report(match_id):
    """Retorna o relatório mais recente de um match ou gera um novo se solicitado."""
    try:
        import json

        from ai import AIProviderError, BudgetExceededError, get_ai_manager
        from database import MatchReportRepository
        
        # Parâmetro para forçar geração de novo relatório
        force_generate = request.args.get('generate', 'false').lower() == 'true'
        
        with webapp.db.get_session() as session:
            match_repo = webapp.MatchRepository(session)
            report_repo = MatchReportRepository(session)
            msg_repo = webapp.MessageRepository(session)
            
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


@bp_matches_messages.route('/api/messages/recent')
def api_recent_messages():
    """Retorna mensagens recentes."""
    try:
        limit = int(request.args.get('limit', 20))
        
        with webapp.db.get_session() as session:
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


@bp_matches_messages.route('/api/messages/ai')
def api_ai_messages():
    """Retorna apenas mensagens geradas por IA."""
    try:
        limit = int(request.args.get('limit', 30))
        offset = int(request.args.get('offset', 0))
        
        with webapp.db.get_session() as session:
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


@bp_matches_messages.route('/api/messages/ai-stats')
def api_ai_messages_stats():
    """Retorna estatísticas de mensagens de IA."""
    try:
        with webapp.db.get_session() as session:
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


@bp_matches_messages.route('/api/analytics/timeline')
def api_analytics_timeline():
    """Retorna dados de timeline para gráficos."""
    try:
        days = int(request.args.get('days', 7))
        
        with webapp.db.get_session() as session:
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

