"""
Blueprint de rotas auxiliares da API.

Agrupa: provedores e custos de IA, notificações, logs, A/B testing, ML adaptive,
scheduler, cache de embeddings, auditoria, manutenção, tarefas e métricas.
Reaproveita os globais já definidos em web/app.py.
"""
from flask import Blueprint

# Reaproveita os globais configurados em web/app.py (db, repositórios, modelos,
# helpers, flags e emitters), evitando reescrever os corpos das rotas. Nenhuma
# destas rotas é alvo de patch nos testes, então o binding direto é seguro.
from web.app import *  # noqa: F401, F403
from web.extensions import _sync_matches_task  # nome com _ não vem no import *

bp_api_extra = Blueprint("api_extra", __name__)

# ===================== AI PROVIDERS MANAGEMENT =====================

@bp_api_extra.route('/api/ai/providers')
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


@bp_api_extra.route('/api/ai/providers/<provider_id>/activate', methods=['POST'])
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


@bp_api_extra.route('/api/ai/providers/<provider_id>/enable', methods=['POST'])
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


@bp_api_extra.route('/api/ai/providers/<provider_id>/disable', methods=['POST'])
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


@bp_api_extra.route('/api/ai/providers/<provider_id>/model', methods=['POST'])
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


@bp_api_extra.route('/api/ai/providers/<provider_id>/configure', methods=['POST'])
def api_configure_ai_provider(provider_id):
    """Configura um provedor de IA com nova API key."""
    try:
        import os

        from ai import get_ai_manager
        
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


@bp_api_extra.route('/api/ai/test', methods=['POST'])
def api_test_ai():
    """Testa a conexão com o provedor de IA ativo."""
    try:
        from ai import AIProviderError, BudgetExceededError, get_ai_manager
        
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


@bp_api_extra.route('/api/ai/usage')
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


@bp_api_extra.route('/api/ai/costs')
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


@bp_api_extra.route('/api/ai/costs/by-provider')
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


@bp_api_extra.route('/api/ai/costs/by-type')
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


@bp_api_extra.route('/api/notifications/<notification_id>/read', methods=['POST'])
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


@bp_api_extra.route('/api/notifications/read-all', methods=['POST'])
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


@bp_api_extra.route('/api/notifications/<notification_id>', methods=['DELETE'])
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


@bp_api_extra.route('/api/notifications/clear', methods=['POST'])
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
@bp_api_extra.route('/api/notifications/test', methods=['POST'])
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

@bp_api_extra.route('/api/logs/status')
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


@bp_api_extra.route('/api/logs/cleanup', methods=['POST'])
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

@bp_api_extra.route('/api/ab-testing/experiments')
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


@bp_api_extra.route('/api/ab-testing/experiments/<experiment_name>')
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


@bp_api_extra.route('/api/ab-testing/experiments', methods=['POST'])
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


@bp_api_extra.route('/api/ab-testing/experiments/<experiment_name>/pause', methods=['POST'])
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


@bp_api_extra.route('/api/ab-testing/experiments/<experiment_name>/resume', methods=['POST'])
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

@bp_api_extra.route('/api/ml/insights')
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


@bp_api_extra.route('/api/ml/insights/<experiment_name>')
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


@bp_api_extra.route('/api/ml/auto-adjust/<experiment_name>', methods=['POST'])
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


@bp_api_extra.route('/api/ml/stats')
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

@bp_api_extra.route('/api/scheduler/status')
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


@bp_api_extra.route('/api/scheduler/task/<task_name>/run', methods=['POST'])
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


@bp_api_extra.route('/api/scheduler/task/<task_name>/enable', methods=['POST'])
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


@bp_api_extra.route('/api/scheduler/task/<task_name>/disable', methods=['POST'])
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

@bp_api_extra.route('/api/cache/embeddings/stats')
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


@bp_api_extra.route('/api/cache/embeddings/cleanup', methods=['POST'])
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


@bp_api_extra.route('/api/cache/embeddings/clear', methods=['POST'])
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

@bp_api_extra.route('/api/audit/logs')
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


@bp_api_extra.route('/api/audit/summary')
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

@bp_api_extra.route('/api/maintenance/clean-message-previews', methods=['POST'])
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

@bp_api_extra.route('/api/tasks')
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


@bp_api_extra.route('/api/tasks/<task_id>')
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


@bp_api_extra.route('/api/tasks/sync', methods=['POST'])
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


@bp_api_extra.route('/api/tasks/scheduled')
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


@bp_api_extra.route('/api/tasks/scheduled/<name>/run', methods=['POST'])
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


@bp_api_extra.route('/api/tasks/scheduled/<name>/pause', methods=['POST'])
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


@bp_api_extra.route('/api/tasks/scheduled/<name>/resume', methods=['POST'])
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


@bp_api_extra.route('/api/tasks/scheduled/add', methods=['POST'])
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

@bp_api_extra.route('/api/metrics/conversion-funnel')
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


@bp_api_extra.route('/api/metrics/temperature-stats')
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


@bp_api_extra.route('/api/metrics/ai-performance')
def api_ai_performance():
    """Métricas de performance da IA."""
    try:
        with db.get_session() as session:
            # Total de mensagens AI
            ai_messages = session.query(func.count(Message.id))\
                .filter(Message.ai_generated == True).scalar() or 0
            
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


@bp_api_extra.route('/api/metrics/activity-heatmap')
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


