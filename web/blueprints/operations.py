"""
Blueprint de automação, bloqueios/status de matches, perfil, preview e notificações.
Reaproveita os globais de web/app.py; nomes patchados nos testes (db, repos)
são acessados via webapp.* para que patch("web.app.X") continue válido.
"""
from flask import Blueprint

import web.app as webapp  # noqa: E402
from web.app import *  # noqa: F401, F403, E402
from utils.input_sanitizer import sanitize_integer  # noqa: E402

bp_operations = Blueprint("operations", __name__)

@bp_operations.route('/api/automation/status')
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


@bp_operations.route('/api/automation/run', methods=['POST'])
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


@bp_operations.route('/api/automation/sync', methods=['POST'])
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


@bp_operations.route('/api/automation/stop', methods=['POST'])
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


@bp_operations.route('/api/automation/force-stop', methods=['POST'])
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


@bp_operations.route('/api/automation/full-status')
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


@bp_operations.route('/api/automation/logs')
def api_automation_logs():
    """Retorna logs da automação."""
    limit = int(request.args.get('limit', 50))
    return jsonify({
        'success': True,
        'data': automation_state['logs'][-limit:]
    })


# ===================== API - MATCHES BLOQUEADOS =====================

@bp_operations.route('/api/matches/blocked')
def api_blocked_matches():
    """Retorna lista de matches bloqueados, com WhatsApp obtido ou encontro confirmado."""
    try:
        from sqlalchemy import or_
        
        with webapp.db.get_session() as session:
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

@bp_operations.route('/api/matches/<int:match_id>/block', methods=['POST'])
def api_block_match(match_id):
    """Bloqueia ou desbloqueia um match (toggle)."""
    try:
        data = request.get_json() or {}
        blocked = data.get('blocked', True)  # Se não especificado, bloqueia
        reason = data.get('reason', 'Bloqueado via interface web')
        
        with webapp.db.get_session() as session:
            repo = webapp.MatchRepository(session)
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


@bp_operations.route('/api/matches/<int:match_id>/status', methods=['POST'])
def api_update_match_status(match_id):
    """Atualiza status específico do match (whatsapp, date, blocked)."""
    try:
        data = request.get_json() or {}
        status_type = data.get('status_type')
        value = data.get('value', False)
        
        if status_type not in ['whatsapp', 'date', 'blocked', 'resend']:
            return jsonify({'success': False, 'error': 'Tipo de status inválido'}), 400
        
        with webapp.db.get_session() as session:
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
                            import json

                            from ai import get_openai_client
                            
                            with webapp.db.get_session() as async_session:
                                from database.repositories import (
                                    MatchReportRepository,
                                    MatchRepository,
                                    MessageRepository,
                                )
                                match_repo = webapp.MatchRepository(async_session)
                                msg_repo = webapp.MessageRepository(async_session)
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


@bp_operations.route('/api/matches/<int:match_id>/generate-report', methods=['POST'])
def api_generate_match_report(match_id):
    """Gera um relatório de análise do match usando IA."""
    try:
        with webapp.db.get_session() as session:
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


@bp_operations.route('/api/matches/<int:match_id>/unblock', methods=['POST'])
def api_unblock_match(match_id):
    """Desbloqueia um match."""
    try:
        with webapp.db.get_session() as session:
            repo = webapp.MatchRepository(session)
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


@bp_operations.route('/api/matches/block-by-name', methods=['POST'])
def api_block_by_name():
    """Bloqueia match pelo nome."""
    try:
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        reason = data.get('reason', 'Bloqueado via interface web')
        
        if not name:
            return jsonify({'success': False, 'error': 'Nome é obrigatório'}), 400
        
        with webapp.db.get_session() as session:
            matches = session.query(Match).filter(
                Match.name.ilike(f'%{name}%'),
                Match.is_blocked != True
            ).all()
            
            if not matches:
                return jsonify({'success': False, 'error': f'Nenhum match encontrado com nome "{name}"'}), 404
            
            repo = webapp.MatchRepository(session)
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

@bp_operations.route('/api/reports/generate', methods=['POST'])
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

@bp_operations.route('/api/profile')
def api_my_profile():
    """Retorna meu perfil com fotos."""
    try:
        with webapp.db.get_session() as session:
            repo = webapp.MyProfileRepository(session)
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

@bp_operations.route('/api/preview/messages', methods=['POST'])
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
        
        with webapp.db.get_session() as session:
            match_repo = webapp.MatchRepository(session)
            msg_repo = webapp.MessageRepository(session)
            
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


@bp_operations.route('/api/stats/temperature')
def api_temperature_stats():
    """Retorna estatísticas de temperatura das conversas."""
    try:
        with webapp.db.get_session() as session:
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

@bp_operations.route('/api/notifications')
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


@bp_operations.route('/api/notifications/count')
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
