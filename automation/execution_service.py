"""
ExecutionService - Serviço de execução de ações automatizadas.

Este serviço é responsável por:
- Enviar primeiras mensagens
- Responder mensagens
- Registrar interações no banco
- Aplicar rate limiting

PRINCÍPIO FUNDAMENTAL:
- Usa EXCLUSIVAMENTE dados do banco de dados
- NÃO realiza scraping/navegação para obter dados
- Apenas navega para ENVIAR mensagens (ação final)
- Se dados insuficientes, sinaliza para fazer sync

GARANTIAS DE IDEMPOTÊNCIA:
- Verifica estado no banco ANTES de cada envio
- Usa locks para evitar envios concorrentes
- Persiste estado ANTES do envio real (pessimistic)
- Se envio falhar, faz rollback

Separação de responsabilidades:
- SYNC: ProfileSyncer (busca dados da UI e persiste no banco)
- EXECUÇÃO: ExecutionService (lê do banco e executa ações)
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from ai import get_openai_client
from config import get_settings
from database import (
    AIInteractionRepository,
    Match,
    MatchRepository,
    Message,
    MessageRepository,
    get_db_manager,
)
from utils.helpers import safe_json_dumps
from utils.logger import (
    console_error,
    console_matches_loaded,
    console_message_sent,
    console_message_skipped,
    console_processing_match,
    console_stats,
    console_waiting,
    console_warning,
    console_whatsapp_detected,
    get_logger,
    log_ai_decision,
    log_automation_step,
    log_file_only,
)
from utils.notifications import notify
from utils.whatsapp_detector import analyze_message_for_progression

from .idempotency import (
    IdempotencyCheckResult,
    IdempotencyError,
    get_idempotency_guard,
    verify_first_message_allowed,
)
from .match_data_service import MatchDataService
from .match_validation import MatchValidator, validate_ai_message, validate_ai_message_with_context
from .state_manager import get_state_manager

# A/B Testing - importar condicionalmente
try:
    from utils.ab_testing import get_ab_manager
    AB_TESTING_ENABLED = True
except ImportError:
    AB_TESTING_ENABLED = False
    get_ab_manager = None

# ML Adaptive - importar condicionalmente
try:
    from services.ml_adaptive import get_ml_service
    ML_ADAPTIVE_ENABLED = True
except ImportError:
    ML_ADAPTIVE_ENABLED = False
    get_ml_service = None

logger = get_logger(__name__)


# Rate limiting config - delays humanizados
RATE_LIMIT = {
    "messages_per_hour": 60,
    "messages_per_session": 200,
    "min_delay_between_messages": 2,   # segundos
    "max_delay_between_messages": 9,
}


class ExecutionService:
    """
    Serviço de execução de ações automatizadas.
    
    Características:
    - Lê dados SOMENTE do banco de dados
    - Usa TinderDataExtractor APENAS para enviar mensagens
    - Não faz scraping/extração de dados durante execução
    """
    
    def __init__(self, extractor):
        """
        Args:
            extractor: TinderDataExtractor (usado apenas para envio de mensagens)
        """
        self.settings = get_settings()
        self.extractor = extractor
        self.openai = get_openai_client()
        self.db = get_db_manager()
        
        # Rate limiting
        self._messages_this_hour = 0
        self._messages_this_session = 0
        self._last_message_time: Optional[datetime] = None
        self._hour_start: Optional[datetime] = None
        
        # Estatísticas
        self.stats = {
            "messages_sent": 0,
            "errors": 0,
            "whatsapp_detected": 0,
            "date_confirmations": 0,
            "skipped_incomplete_data": 0,
            "skipped_rate_limit": 0,
        }
    
    def reset_stats(self):
        """Reseta estatísticas da sessão."""
        self.stats = {k: 0 for k in self.stats}
    
    # ==================== RATE LIMITING ====================
    
    def _check_rate_limit(self) -> bool:
        """Verifica se pode enviar mais mensagens."""
        now = datetime.utcnow()
        
        if not self._hour_start or (now - self._hour_start).total_seconds() > 3600:
            self._hour_start = now
            self._messages_this_hour = 0
        
        if self._messages_this_hour >= RATE_LIMIT["messages_per_hour"]:
            self.stats["skipped_rate_limit"] += 1
            return False
        
        if self._messages_this_session >= RATE_LIMIT["messages_per_session"]:
            self.stats["skipped_rate_limit"] += 1
            return False
        
        if self._last_message_time:
            elapsed = (now - self._last_message_time).total_seconds()
            if elapsed < RATE_LIMIT["min_delay_between_messages"]:
                return False
        
        return True
    
    def _record_message_sent(self):
        """Registra envio de mensagem para rate limiting."""
        self._messages_this_hour += 1
        self._messages_this_session += 1
        self._last_message_time = datetime.utcnow()
    
    async def _apply_human_delay(self):
        """Aplica delay humanizado entre ações."""
        import asyncio
        delay = random.uniform(
            RATE_LIMIT["min_delay_between_messages"],
            RATE_LIMIT["max_delay_between_messages"]
        )
        console_waiting(int(delay), "delay humanizado")
        await asyncio.sleep(delay)
    
    # ==================== ENVIO DE PRIMEIRAS MENSAGENS ====================
    
    async def send_first_messages(self, limit: int = 5, dry_run: bool = False) -> List[Dict]:
        """
        Envia primeiras mensagens para matches sem interação.
        
        Usa EXCLUSIVAMENTE dados do banco. Se match não tem dados suficientes,
        é pulado e sinalizado para sincronização.
        
        GARANTIAS DE IDEMPOTÊNCIA:
        1. Verifica estado no banco ANTES de cada envio
        2. Usa lock por match para evitar concorrência
        3. Marca match como enviado ANTES do envio real
        4. Se envio falhar, faz rollback
        
        Args:
            limit: Número máximo de mensagens a enviar
            dry_run: Se True, simula envio sem executar (modo seguro para testes)
            
        Returns:
            Lista de resultados de cada tentativa
        """
        log_file_only(f"Enviando primeiras mensagens (limite: {limit})...")
        results = []
        matches_needing_sync = []
        
        if dry_run:
            logger.info("🧪 MODO DRY-RUN ATIVADO - Nenhuma mensagem será enviada")
        
        # Guard de idempotência
        idempotency_guard = get_idempotency_guard()
        
        with self.db.get_session() as session:
            # Serviço de dados (somente banco)
            data_service = MatchDataService(session)
            match_repo = MatchRepository(session)
            msg_repo = MessageRepository(session)
            ai_repo = AIInteractionRepository(session)
            
            # Validador de matches
            validator = MatchValidator(self.settings)
            
            # Buscar matches elegíveis DO BANCO
            matches = match_repo.get_matches_without_messages()[:limit * 2]  # Buscar mais para compensar pulados
            
            # Log de console: quantidade de matches
            console_matches_loaded(len(matches), "banco (sem mensagem)")
            
            sent_count = 0
            for match in matches:
                if sent_count >= limit:
                    break
                
                # Verificar se deve parar (sinal de stop via interface)
                if get_state_manager().should_stop:
                    log_file_only("Stop solicitado durante send_first_messages, interrompendo")
                    break
                
                # Rate limit check
                if not self._check_rate_limit():
                    console_warning("Rate limit atingido, parando envio")
                    break
                
                # ============================================================
                # VERIFICAÇÃO DE IDEMPOTÊNCIA (CRÍTICO)
                # ============================================================
                can_send_result, reason = idempotency_guard.check_can_send(
                    match.tinder_match_id, session, Match
                )
                
                if can_send_result != IdempotencyCheckResult.ALLOWED:
                    console_message_skipped(match.name, f"idempotência: {reason}")
                    log_file_only(f"Idempotência bloqueou {match.tinder_match_id}: {reason}")
                    results.append({
                        "match_id": match.tinder_match_id,
                        "name": match.name,
                        "success": False,
                        "error": f"Idempotência: {reason}",
                        "blocked_by_idempotency": True
                    })
                    continue
                
                # Verificação extra direta no banco
                can_send, verify_reason = verify_first_message_allowed(
                    match.tinder_match_id, session, Match, Message
                )
                if not can_send:
                    console_message_skipped(match.name, verify_reason)
                    log_file_only(f"Verificação banco bloqueou {match.tinder_match_id}: {verify_reason}")
                    results.append({
                        "match_id": match.tinder_match_id,
                        "name": match.name,
                        "success": False,
                        "error": f"Verificação banco: {verify_reason}",
                        "blocked_by_idempotency": True
                    })
                    continue
                # ============================================================
                
                # Log de processamento do match
                console_processing_match(match.name, "processando")
                
                # Validação do match
                should_skip, skip_reason = validator.should_skip_match(match)
                if should_skip:
                    console_message_skipped(match.name, skip_reason)
                    continue
                
                # Obter dados do match DO BANCO
                match_profile, status = data_service.get_match_profile_for_ai(match)
                
                if status == "unmatched":
                    console_message_skipped(match.name, "unmatch detectado")
                    match_repo.mark_as_unmatched(match)
                    continue
                
                if status == "blocked":
                    console_message_skipped(match.name, "bloqueado")
                    continue
                
                if status == "incomplete":
                    # Dados insuficientes - precisa sync
                    matches_needing_sync.append(match.tinder_match_id)
                    self.stats["skipped_incomplete_data"] += 1
                    console_message_skipped(match.name, "dados incompletos")
                    continue
                
                try:
                    # Interesses em comum
                    common_interests = data_service.get_common_interests(
                        match_profile.get("interests", [])
                    )
                    
                    # Adicionar interesses em comum ao perfil para a IA
                    if common_interests:
                        match_profile["common_interests"] = common_interests
                    
                    # A/B Testing + ML Adaptive - obter variantes otimizadas
                    ab_variants = {}
                    if AB_TESTING_ENABLED:
                        try:
                            # Usar ML Adaptive se disponível (Thompson Sampling)
                            if ML_ADAPTIVE_ENABLED:
                                ml_service = get_ml_service()
                                ab_variants = {
                                    'style': ml_service.get_optimized_variant('first_message_style', match.tinder_match_id),
                                    'intensity': ml_service.get_optimized_variant('flirt_intensity', match.tinder_match_id),
                                    'emoji': ml_service.get_optimized_variant('emoji_usage', match.tinder_match_id)
                                }
                                # Registrar impressões no ML
                                for exp_name, variant in ab_variants.items():
                                    if variant:
                                        ml_service.record_impression(f'{exp_name}', variant, match.tinder_match_id)
                            else:
                                # Fallback para A/B testing padrão
                                ab_manager = get_ab_manager()
                                ab_variants = {
                                    'style': ab_manager.get_variant('first_message_style', match.tinder_match_id),
                                    'intensity': ab_manager.get_variant('flirt_intensity', match.tinder_match_id),
                                    'emoji': ab_manager.get_variant('emoji_usage', match.tinder_match_id)
                                }
                            log_file_only(f"A/B Testing para {match.name}: {ab_variants}")
                        except Exception as e:
                            log_file_only(f"Erro ao obter variantes A/B: {e}")
                    
                    log_file_only(f"Gerando mensagem para {match.name}")
                    
                    # Gerar mensagem com IA (passando variantes A/B)
                    ai_result = self.openai.generate_first_message(
                        match_profile=match_profile,
                        ab_variants=ab_variants if ab_variants else None
                    )
                    
                    if not ai_result or not isinstance(ai_result, dict):
                        logger.error(f"IA retornou resultado inválido para {match.name}: {ai_result}")
                        raise ValueError("IA retornou resultado inválido")
                    
                    raw_message = ai_result.get("message")
                    message = (raw_message or "").strip() if isinstance(raw_message, str) else ""
                    
                    # Validar que a mensagem não é o nome do campo
                    invalid_values = ['"message"', "'message'", "message", "", "\"message\""]
                    message_lower = message.lower().strip('"').strip("'")
                    if not message or len(message) < 2 or message_lower in [v.lower().strip('"').strip("'") for v in invalid_values]:
                        logger.error(f"Mensagem inválida para {match.name}: '{raw_message}'")
                        raise ValueError(f"Mensagem inválida: '{message}'")
                    
                    # Validar mensagem
                    is_valid, reason = validate_ai_message(message)
                    if not is_valid:
                        logger.warning(f"Mensagem rejeitada: {reason}")
                        continue
                    
                    # ============================================================
                    # MODO DRY-RUN
                    # ============================================================
                    if dry_run:
                        log_file_only(
                            f"DRY-RUN: Simulando envio para {match.name}",
                            {"message": message[:50] + "...", "match_id": match.tinder_match_id}
                        )
                        console_message_skipped(match.name, "DRY-RUN (simulação)")
                        results.append({
                            "match_id": match.tinder_match_id,
                            "name": match.name,
                            "message": message,
                            "success": True,
                            "dry_run": True,
                            "ab_variants": ab_variants if ab_variants else None
                        })
                        sent_count += 1
                        continue
                    
                    # ============================================================
                    # ENVIO COM LOCK DE IDEMPOTÊNCIA (CRÍTICO)
                    # ============================================================
                    try:
                        with idempotency_guard.send_lock(match.tinder_match_id):
                            # PASSO 1: Marcar no banco ANTES de enviar (pessimistic locking)
                            # Isso previne que outro processo tente enviar para o mesmo match
                            match.first_message_sent = True
                            match.has_messages = True
                            match.awaiting_my_response = False
                            match.last_message_text = message[:200] if message else None
                            match.last_message_from_me = True
                            match.last_message_at = datetime.utcnow()
                            match.last_interaction_at = datetime.utcnow()
                            session.flush()  # Persiste mas não commita
                            
                            log_file_only(f"Lock adquirido e flags marcadas para {match.name}")
                            
                            # PASSO 2: ENVIAR mensagem (única interação com UI)
                            success = await self.extractor.send_message(
                                match.tinder_match_id,
                                message
                            )
                            
                            if success:
                                # PASSO 3: Criar registro da mensagem
                                msg_repo.create(
                                    match_id=match.id,
                                    content=message,
                                    is_from_me=True,
                                    message_type="first_message",
                                    ai_generated=True,
                                    sent_at=datetime.utcnow()
                                )
                                
                                # Registrar tentativa bem-sucedida
                                idempotency_guard.record_send_attempt(
                                    match.tinder_match_id, message, True, "Enviado com sucesso"
                                )
                                
                                self._record_message_sent()
                                self.stats["messages_sent"] += 1
                                sent_count += 1
                                
                                results.append({
                                    "match_id": match.tinder_match_id,
                                    "name": match.name,
                                    "message": message,
                                    "success": True,
                                    "ab_variants": ab_variants if ab_variants else None
                                })
                                
                                # Registrar uso da IA
                                self._log_ai_interaction(
                                    ai_repo, match, ai_result,
                                    "first_message_generation", "first_message"
                                )
                                
                                # Log de sucesso no console
                                console_message_sent(match.name, message)
                                
                                # Delay humanizado
                                await self._apply_human_delay()
                            else:
                                # PASSO FALLBACK: Envio falhou, fazer rollback das flags
                                console_warning(f"Envio falhou para {match.name}, fazendo rollback")
                                match.first_message_sent = False
                                match.has_messages = False
                                match.awaiting_my_response = False
                                match.last_message_text = None
                                match.last_message_from_me = None
                                match.last_message_at = None
                                session.flush()
                                
                                idempotency_guard.record_send_attempt(
                                    match.tinder_match_id, message, False, "Falha no envio"
                                )
                                
                                raise Exception("Falha ao enviar mensagem")
                    
                    except IdempotencyError as ie:
                        console_message_skipped(match.name, f"erro idempotência: {ie}")
                        results.append({
                            "match_id": match.tinder_match_id,
                            "name": match.name,
                            "success": False,
                            "error": f"Idempotência: {str(ie)}",
                            "blocked_by_idempotency": True
                        })
                        continue
                        
                except Exception as e:
                    console_error(f"Erro ao processar {match.name}", e)
                    self.stats["errors"] += 1
                    results.append({
                        "match_id": match.tinder_match_id,
                        "name": match.name,
                        "success": False,
                        "error": str(e)
                    })
        
        # Estatísticas de idempotência
        idempotency_stats = idempotency_guard.get_stats()
        blocked_by_idempotency = sum(1 for r in results if r.get("blocked_by_idempotency"))
        dry_run_count = sum(1 for r in results if r.get("dry_run"))
        
        # Log detalhado apenas em arquivo
        log_file_only(f"Primeiras mensagens: {sum(1 for r in results if r.get('success'))} enviadas, "
                     f"{blocked_by_idempotency} bloqueadas, {len(matches_needing_sync)} precisam sync")
        
        # Retornar Dict com estatísticas para o orchestrator
        return {
            "sent": sum(1 for r in results if r.get("success") and not r.get("dry_run")),
            "simulated": dry_run_count,
            "errors": self.stats["errors"],
            "skipped_incomplete_data": self.stats["skipped_incomplete_data"],
            "skipped_rate_limit": self.stats["skipped_rate_limit"],
            "blocked_by_idempotency": blocked_by_idempotency,
            "matches_needing_sync": matches_needing_sync,
            "idempotency_stats": idempotency_stats,
            "dry_run": dry_run,
            "details": results
        }
    
    # ==================== RESPONDER MENSAGENS ====================
    
    async def respond_to_messages(self, limit: int = 5, dry_run: bool = False) -> List[Dict]:
        """
        Responde mensagens aguardando resposta.
        
        Usa dados do banco para contexto. A conversa deve estar sincronizada
        previamente pelo sync.
        
        Args:
            limit: Número máximo de conversas a responder
            dry_run: Se True, simula envio sem executar (modo seguro para testes)
            
        Returns:
            Lista de resultados
        """
        log_file_only(f"Respondendo mensagens (limite: {limit}){'[DRY RUN]' if dry_run else ''}...")
        results = []
        
        with self.db.get_session() as session:
            data_service = MatchDataService(session)
            match_repo = MatchRepository(session)
            msg_repo = MessageRepository(session)
            ai_repo = AIInteractionRepository(session)
            
            validator = MatchValidator(self.settings)
            
            # Buscar matches aguardando resposta DO BANCO
            matches = data_service.get_matches_awaiting_response(limit=limit * 2)
            
            sent_count = 0
            for match in matches:
                if sent_count >= limit:
                    break
                
                # Verificar se deve parar (sinal de stop via interface)
                if get_state_manager().should_stop:
                    log_file_only("Stop solicitado durante respond_to_messages, interrompendo")
                    break
                
                if not self._check_rate_limit():
                    console_warning("Rate limit atingido")
                    break
                
                should_skip, skip_reason = validator.should_skip_match(match)
                if should_skip:
                    console_message_skipped(match.name, skip_reason)
                    continue
                
                match_profile, status = data_service.get_match_profile_for_ai(match)
                
                if status in ("unmatched", "blocked"):
                    if status == "unmatched":
                        match_repo.mark_as_unmatched(match)
                    continue
                
                if status == "incomplete":
                    self.stats["skipped_incomplete_data"] += 1
                    continue
                
                try:
                    # Obter histórico de mensagens DO BANCO
                    messages_raw = data_service.get_match_messages(match, limit=10)
                    
                    if not messages_raw:
                        logger.debug(f"Sem mensagens no banco para {match.name}")
                        continue
                    
                    # NOTA: get_match_messages retorna ordenado por ID desc (mais recente primeiro)
                    # Precisamos reverter para ordem cronológica (mais antiga primeiro)
                    # para que conversation_history[:-1] funcione corretamente
                    messages = list(reversed(messages_raw))
                    
                    # Filtrar mensagens de dry run para encontrar a última mensagem REAL
                    # Isso permite que após um dry run, as mensagens reais sejam enviadas
                    real_messages = [m for m in messages if not (m.get("message_type") or "").endswith("_dry_run")]
                    
                    # Verificar se última mensagem REAL é minha (a última na ordem cronológica)
                    last_real_msg = real_messages[-1] if real_messages else None
                    if last_real_msg and last_real_msg.get("is_from_me"):
                        match_repo.update(match, awaiting_my_response=False)
                        continue
                    
                    # Log de processamento APENAS quando realmente vai processar
                    console_processing_match(match.name, "respondendo")
                    
                    # Para o contexto da IA, usar a última mensagem (incluindo dry run se necessário)
                    last_msg = messages[-1] if messages else None
                    last_msg_content = last_msg.get("content", "") if last_msg else ""
                    
                    # Se última mensagem é dry run minha, usar a anterior como contexto
                    if last_msg and last_msg.get("is_from_me") and (last_msg.get("message_type") or "").endswith("_dry_run"):
                        # Encontrar última mensagem não-dry-run para contexto
                        for msg in reversed(messages[:-1]):
                            if not (msg.get("message_type") or "").endswith("_dry_run"):
                                last_msg_content = msg.get("content", "")
                                break
                    
                    # Detectar WhatsApp/encontro na mensagem
                    progression = analyze_message_for_progression(last_msg_content)
                    
                    if progression['has_whatsapp'] and progression['whatsapp_number']:
                        match_repo.update_whatsapp(match, progression['whatsapp_number'])
                        self.stats["whatsapp_detected"] += 1
                        await notify('whatsapp_received', {
                            'name': match.name,
                            'phone': progression['whatsapp_number']
                        })
                        console_whatsapp_detected(match.name, progression['whatsapp_number'])
                        
                        # A/B Testing + ML Adaptive - registrar conversão WhatsApp
                        if AB_TESTING_ENABLED:
                            try:
                                ab_manager = get_ab_manager()
                                ab_manager.record_conversion('first_message_style', match.tinder_match_id, 'whatsapp')
                                ab_manager.record_conversion('message_length', match.tinder_match_id, 'whatsapp')
                                ab_manager.record_conversion('emoji_usage', match.tinder_match_id, 'whatsapp')
                                
                                # ML Adaptive - registrar outcome
                                if ML_ADAPTIVE_ENABLED:
                                    ml_service = get_ml_service()
                                    for exp in ['first_message_style', 'flirt_intensity', 'emoji_usage']:
                                        variant = ab_manager.get_variant(exp, match.tinder_match_id)
                                        if variant:
                                            ml_service.record_outcome(exp, variant, 'whatsapp')
                                
                                logger.debug(f"🧪 Conversão WhatsApp registrada para {match.name}")
                            except Exception as e:
                                logger.warning(f"Erro ao registrar conversão A/B: {e}")
                    
                    if progression['date_confirmation']:
                        match_repo.confirm_date(match)
                        self.stats["date_confirmations"] += 1
                        await notify('date_confirmed', {'name': match.name})
                        
                        # A/B Testing + ML Adaptive - registrar conversão Encontro
                        if AB_TESTING_ENABLED:
                            try:
                                ab_manager = get_ab_manager()
                                ab_manager.record_conversion('first_message_style', match.tinder_match_id, 'date')
                                ab_manager.record_conversion('message_length', match.tinder_match_id, 'date')
                                ab_manager.record_conversion('emoji_usage', match.tinder_match_id, 'date')
                                
                                # ML Adaptive - registrar outcome
                                if ML_ADAPTIVE_ENABLED:
                                    ml_service = get_ml_service()
                                    for exp in ['first_message_style', 'flirt_intensity', 'emoji_usage']:
                                        variant = ab_manager.get_variant(exp, match.tinder_match_id)
                                        if variant:
                                            ml_service.record_outcome(exp, variant, 'date')
                                
                                logger.debug(f"🧪 Conversão Encontro registrada para {match.name}")
                            except Exception as e:
                                logger.warning(f"Erro ao registrar conversão A/B: {e}")
                    
                    # A/B Testing + ML Adaptive - registrar que recebeu resposta
                    ab_variants = {}
                    if AB_TESTING_ENABLED and last_msg and not last_msg.get("is_from_me"):
                        try:
                            ab_manager = get_ab_manager()
                            ab_manager.record_conversion('first_message_style', match.tinder_match_id, 'response')
                            ab_manager.record_conversion('flirt_intensity', match.tinder_match_id, 'response')
                            ab_manager.record_conversion('emoji_usage', match.tinder_match_id, 'response')
                            
                            # ML Adaptive - registrar outcome com metadados
                            if ML_ADAPTIVE_ENABLED:
                                ml_service = get_ml_service()
                                response_length = len(last_msg.get('content', ''))
                                for exp in ['first_message_style', 'flirt_intensity', 'emoji_usage']:
                                    variant = ab_manager.get_variant(exp, match.tinder_match_id)
                                    if variant:
                                        ml_service.record_outcome(
                                            exp, variant, 'response',
                                            metadata={'response_length': response_length}
                                        )
                            
                            # Obter variantes A/B para a resposta
                            ab_variants = {
                                'style': ab_manager.get_variant('first_message_style', match.tinder_match_id),
                                'intensity': ab_manager.get_variant('flirt_intensity', match.tinder_match_id),
                                'emoji': ab_manager.get_variant('emoji_usage', match.tinder_match_id)
                            }
                            log_file_only(f"A/B Testing para resposta de {match.name}: {ab_variants}")
                        except Exception as e:
                            logger.warning(f"Erro ao processar A/B: {e}")
                    
                    logger.debug(f"Analisando conversa com {match.name}")
                    
                    # Filtrar mensagens de dry run do histórico para a IA
                    # A IA não deve ver mensagens simuladas
                    # Excluir a última mensagem (que vai em last_message)
                    history_for_ai = real_messages[:-1] if len(real_messages) > 1 else []
                    
                    # Gerar resposta com IA (passando histórico completo e variantes A/B)
                    ai_result = self.openai.analyze_conversation_and_respond(
                        match_profile=match_profile,
                        conversation_history=history_for_ai,  # Histórico sem dry runs
                        last_message=last_msg_content,
                        ab_variants=ab_variants if ab_variants else None
                    )
                    
                    if not ai_result or not isinstance(ai_result, dict):
                        logger.error(f"IA retornou resultado inválido para {match.name}: {ai_result}")
                        raise ValueError("IA retornou resultado inválida")
                    
                    # Extrair dados da análise com validação robusta
                    raw_temperature = ai_result.get("temperature_label")
                    temperature = raw_temperature if isinstance(raw_temperature, str) else "warm"
                    
                    # Validar temperature_label
                    invalid_labels = ['"temperature_label"', "'temperature_label'", "temperature_label"]
                    if not temperature or temperature.lower().strip('"').strip("'") in [v.lower().strip('"').strip("'") for v in invalid_labels]:
                        temperature = "warm"
                    
                    # Validar temperature_score - deve ser número
                    raw_temp_score = ai_result.get("temperature_score")
                    temp_score = raw_temp_score if raw_temp_score is not None else 5
                    
                    invalid_scores = ['"temperature_score"', "'temperature_score'", "temperature_score"]
                    if isinstance(temp_score, str):
                        if temp_score.lower().strip('"').strip("'") in [v.lower().strip('"').strip("'") for v in invalid_scores]:
                            logger.warning(f"temperature_score inválido para {match.name}, usando default: 5")
                            temp_score = 5
                        else:
                            try:
                                temp_score = float(temp_score)
                            except ValueError:
                                temp_score = 5
                    if not isinstance(temp_score, (int, float)):
                        temp_score = 5
                    
                    next_step = ai_result.get("next_step_recommendation", "continuar")
                    # Garantir que é string
                    if not isinstance(next_step, str):
                        logger.warning(f"next_step_recommendation não é string: {type(next_step)} = {next_step}")
                        next_step = "continuar"
                    # Validar next_step
                    invalid_steps = ['"next_step_recommendation"', "'next_step_recommendation'"]
                    if not next_step or next_step.lower() in invalid_steps:
                        next_step = "continuar"
                    
                    # Atualizar temperatura no banco
                    match_repo.update_temperature_history(match, temperature, temp_score)
                    
                    # Notificar se conversa quente
                    if temp_score >= 7:
                        await notify('hot_conversation', {
                            'name': match.name,
                            'temperature': temp_score
                        })
                    
                    # Determinar mensagem a enviar
                    if next_step == "whatsapp" and ai_result.get("whatsapp_transition_message"):
                        message = ai_result.get("whatsapp_transition_message")
                        match_repo.update(match, whatsapp_requested=True)
                    elif next_step == "encontro" and ai_result.get("date_suggestion_message"):
                        message = ai_result.get("date_suggestion_message")
                        match_repo.update(match, date_suggested=True)
                    else:
                        message = ai_result.get("suggested_response", "")
                    
                    # Garantir que message é string
                    if not isinstance(message, str):
                        logger.warning(f"Mensagem não é string para {match.name}: {type(message)} = {message}")
                        message = str(message) if message else ""
                    
                    # Validar que a mensagem não é o nome do campo
                    invalid_msg_values = [
                        '"suggested_response"', "'suggested_response'", "suggested_response",
                        '"whatsapp_transition_message"', '"date_suggestion_message"', ""
                    ]
                    if not message or message.lower() in invalid_msg_values or len(message.strip()) < 3:
                        logger.warning(f"Resposta inválida recebida: '{message}'. AI result: {ai_result}")
                        continue
                    
                    # Validar com contexto (evita saudações repetidas em conversas já iniciadas)
                    is_valid, reason = validate_ai_message_with_context(
                        message, 
                        conversation_history=messages[:-1],
                        is_first_message=False
                    )
                    if not is_valid:
                        logger.warning(f"Mensagem rejeitada (contexto): {reason}")
                        continue
                    
                    # DRY RUN: simular envio sem executar
                    if dry_run:
                        logger.info(f"[DRY RUN] Simulando resposta para {match.name}: {message[:50]}...")
                        console_message_sent(match.name, "[DRY RUN] Simulado")
                        
                        # Registrar no banco como se tivesse enviado (para teste)
                        msg_repo.create(
                            match_id=match.id,
                            content=f"[DRY RUN] {message}",
                            is_from_me=True,
                            message_type="response_dry_run",
                            ai_generated=True,
                            ai_analysis=safe_json_dumps({
                                "temperature": temperature,
                                "next_step": next_step,
                                "dry_run": True
                            }),
                            sent_at=datetime.utcnow()
                        )
                        
                        sent_count += 1
                        results.append({
                            "match_id": match.tinder_match_id,
                            "name": match.name,
                            "message": message,
                            "temperature": temperature,
                            "success": True,
                            "dry_run": True
                        })
                        
                        await self._apply_human_delay()
                        continue
                    
                    # ENVIAR mensagem (modo real)
                    success = await self.extractor.send_message(
                        match.tinder_match_id,
                        message
                    )
                    
                    if success:
                        self._record_message_sent()
                        
                        msg_repo.create(
                            match_id=match.id,
                            content=message,
                            is_from_me=True,
                            message_type="response",
                            ai_generated=True,
                            ai_analysis=safe_json_dumps({
                                "temperature": temperature,
                                "next_step": next_step
                            }),
                            sent_at=datetime.utcnow()
                        )
                        
                        match_repo.update(
                            match,
                            awaiting_my_response=False,
                            last_message_text=message[:200] if message else None,
                            last_message_from_me=True,
                            last_message_at=datetime.utcnow(),
                            last_interaction_at=datetime.utcnow()
                        )
                        
                        self.stats["messages_sent"] += 1
                        sent_count += 1
                        
                        results.append({
                            "match_id": match.tinder_match_id,
                            "name": match.name,
                            "message": message,
                            "temperature": temperature,
                            "success": True
                        })
                        
                        self._log_ai_interaction(
                            ai_repo, match, ai_result,
                            "conversation_response", "conversation_response"
                        )
                        
                        await self._apply_human_delay()
                    else:
                        raise Exception("Falha ao enviar mensagem")
                        
                except Exception as e:
                    logger.error(f"Erro ao responder {match.tinder_match_id}: {e}")
                    self.stats["errors"] += 1
                    results.append({
                        "match_id": match.tinder_match_id,
                        "name": match.name,
                        "success": False,
                        "error": str(e)
                    })
        
        log_file_only(
            "Respostas enviadas",
            {"total": len(results), "success": sum(1 for r in results if r.get("success"))}
        )
        
        console_stats({
            "enviadas": sum(1 for r in results if r.get("success")),
            "erros": self.stats["errors"],
            "whatsapp": self.stats["whatsapp_detected"]
        })
        
        # Retornar Dict com estatísticas para o orchestrator
        return {
            "sent": sum(1 for r in results if r.get("success")),
            "errors": self.stats["errors"],
            "skipped_incomplete_data": self.stats["skipped_incomplete_data"],
            "whatsapp_detected": self.stats["whatsapp_detected"],
            "date_confirmations": self.stats["date_confirmations"],
            "details": results
        }
    
    # ==================== REENVIAR MENSAGENS (COMPLEMENTO) ====================
    
    async def resend_messages(self, limit: int = 5, dry_run: bool = False) -> Dict:
        """
        Reenvia mensagens para matches marcados com pending_resend.
        
        Usado quando uma mensagem foi enviada de forma incompleta/cortada.
        Gera uma nova mensagem complementar baseada no contexto da conversa,
        enviando como continuação natural (não repete a mensagem anterior).
        
        Args:
            limit: Número máximo de reenvios
            dry_run: Se True, simula envio sem executar
            
        Returns:
            Dict com estatísticas de reenvio
        """
        log_file_only(f"Reenviando mensagens complementares (limite: {limit}){'[DRY RUN]' if dry_run else ''}...")
        results = []
        
        with self.db.get_session() as session:
            data_service = MatchDataService(session)
            match_repo = MatchRepository(session)
            msg_repo = MessageRepository(session)
            ai_repo = AIInteractionRepository(session)
            
            # Buscar matches marcados para reenvio
            matches = match_repo.get_matches_pending_resend()[:limit]
            
            console_matches_loaded(len(matches), "banco (reenvio pendente)")
            
            sent_count = 0
            for match in matches:
                if sent_count >= limit:
                    break
                
                # Verificar se deve parar (sinal de stop via interface)
                if get_state_manager().should_stop:
                    log_file_only("Stop solicitado durante resend_messages, interrompendo")
                    break
                
                if not self._check_rate_limit():
                    console_warning("Rate limit atingido")
                    break
                
                console_processing_match(match.name, "reenvio complementar")
                
                match_profile, status = data_service.get_match_profile_for_ai(match)
                
                if status in ("unmatched", "blocked"):
                    if status == "unmatched":
                        match_repo.mark_as_unmatched(match)
                    # Limpar flag de reenvio
                    match_repo.clear_resend(match)
                    continue
                
                try:
                    # Obter histórico de mensagens DO BANCO
                    messages_raw = data_service.get_match_messages(match, limit=10)
                    
                    if not messages_raw:
                        logger.debug(f"Sem mensagens no banco para {match.name}, não há o que complementar")
                        match_repo.clear_resend(match)
                        continue
                    
                    # Reverter para ordem cronológica
                    messages = list(reversed(messages_raw))
                    
                    # Encontrar a última mensagem minha (que foi cortada/incompleta)
                    last_my_msg = None
                    for msg in reversed(messages):
                        if msg.get("is_from_me"):
                            last_my_msg = msg
                            break
                    
                    if not last_my_msg:
                        logger.debug(f"Sem mensagem minha para complementar para {match.name}")
                        match_repo.clear_resend(match)
                        continue
                    
                    incomplete_message = last_my_msg.get("content", "")
                    
                    # Gerar mensagem complementar com a IA
                    # Usando analyze_conversation_and_respond com contexto especial
                    # A IA receberá instrução de que a última mensagem foi cortada
                    resend_context = (
                        f"ATENÇÃO: A última mensagem que enviei foi cortada/incompleta. "
                        f"A mensagem incompleta foi: \"{incomplete_message}\"\n"
                        f"Motivo do reenvio: {match.resend_reason or 'Mensagem incompleta'}\n"
                        f"Gere uma mensagem curta e natural que COMPLETE o que eu estava dizendo, "
                        f"como se fosse uma continuação natural da conversa. "
                        f"NÃO repita o que já foi dito. NÃO comece com saudação. "
                        f"Apenas complete o pensamento de forma fluida."
                    )
                    
                    # Histórico sem a última mensagem (que será passada como last_message)
                    history_for_ai = [m for m in messages[:-1] if not (m.get("message_type") or "").endswith("_dry_run")]
                    
                    ai_result = self.openai.analyze_conversation_and_respond(
                        match_profile=match_profile,
                        conversation_history=history_for_ai,
                        last_message=resend_context
                    )
                    
                    if not ai_result or not isinstance(ai_result, dict):
                        logger.error(f"IA retornou resultado inválido para reenvio de {match.name}")
                        raise ValueError("IA retornou resultado inválido")
                    
                    message = ai_result.get("suggested_response", "")
                    
                    if not isinstance(message, str):
                        message = str(message) if message else ""
                    
                    # Validar mensagem
                    invalid_msg_values = [
                        '"suggested_response"', "'suggested_response'", "suggested_response", ""
                    ]
                    if not message or message.lower() in invalid_msg_values or len(message.strip()) < 3:
                        logger.warning(f"Mensagem de reenvio inválida para {match.name}: '{message}'")
                        continue
                    
                    is_valid, reason = validate_ai_message(message)
                    if not is_valid:
                        logger.warning(f"Mensagem de reenvio rejeitada: {reason}")
                        continue
                    
                    # DRY RUN
                    if dry_run:
                        logger.info(f"[DRY RUN] Simulando reenvio para {match.name}: {message[:50]}...")
                        console_message_sent(match.name, f"[DRY RUN] Reenvio: {message[:50]}...")
                        
                        msg_repo.create(
                            match_id=match.id,
                            content=f"[DRY RUN] [REENVIO] {message}",
                            is_from_me=True,
                            message_type="resend_dry_run",
                            ai_generated=True,
                            sent_at=datetime.utcnow()
                        )
                        
                        sent_count += 1
                        results.append({
                            "match_id": match.tinder_match_id,
                            "name": match.name,
                            "message": message,
                            "success": True,
                            "dry_run": True,
                            "resend": True
                        })
                        
                        # Limpar flag de reenvio mesmo em dry run
                        match_repo.clear_resend(match)
                        await self._apply_human_delay()
                        continue
                    
                    # ENVIAR mensagem real
                    success = await self.extractor.send_message(
                        match.tinder_match_id,
                        message
                    )
                    
                    if success:
                        self._record_message_sent()
                        
                        msg_repo.create(
                            match_id=match.id,
                            content=message,
                            is_from_me=True,
                            message_type="resend_completion",
                            ai_generated=True,
                            ai_analysis=safe_json_dumps({
                                "resend": True,
                                "incomplete_message": incomplete_message[:200],
                                "resend_reason": match.resend_reason
                            }),
                            sent_at=datetime.utcnow()
                        )
                        
                        # Atualizar match
                        match_repo.update(
                            match,
                            last_message_text=message[:200] if message else None,
                            last_message_from_me=True,
                            last_message_at=datetime.utcnow(),
                            last_interaction_at=datetime.utcnow()
                        )
                        
                        # Limpar flag de reenvio
                        match_repo.clear_resend(match)
                        
                        self.stats["messages_sent"] += 1
                        sent_count += 1
                        
                        results.append({
                            "match_id": match.tinder_match_id,
                            "name": match.name,
                            "message": message,
                            "success": True,
                            "resend": True
                        })
                        
                        self._log_ai_interaction(
                            ai_repo, match, ai_result,
                            "resend_completion", "resend_completion"
                        )
                        
                        console_message_sent(match.name, f"[REENVIO] {message}")
                        
                        await self._apply_human_delay()
                    else:
                        raise Exception("Falha ao enviar mensagem de reenvio")
                        
                except Exception as e:
                    console_error(f"Erro ao reenviar para {match.name}", e)
                    self.stats["errors"] += 1
                    results.append({
                        "match_id": match.tinder_match_id,
                        "name": match.name,
                        "success": False,
                        "error": str(e),
                        "resend": True
                    })
        
        log_file_only(
            "Reenvios processados",
            {"total": len(results), "success": sum(1 for r in results if r.get("success"))}
        )
        
        return {
            "sent": sum(1 for r in results if r.get("success")),
            "errors": sum(1 for r in results if not r.get("success")),
            "details": results
        }
    
    def _log_ai_interaction(
        self, ai_repo, match: Match, ai_result: Dict,
        interaction_type: str, prompt_template: str
    ):
        """Registra interação com IA no banco."""
        metadata = ai_result.get("_metadata", {})
        interaction = ai_repo.create(
            interaction_type=interaction_type,
            model_used=metadata.get("model", self.settings.openai_model),
            match_id=match.id,
            prompt_template=prompt_template
        )
        ai_repo.complete(
            interaction,
            response_content=safe_json_dumps(ai_result),
            prompt_tokens=metadata.get("prompt_tokens", 0),
            completion_tokens=metadata.get("completion_tokens", 0),
            response_time_ms=metadata.get("response_time_ms", 0)
        )
    
    def get_stats(self) -> Dict:
        """Retorna estatísticas da execução."""
        return self.stats.copy()


# Singleton instance
_execution_service: Optional[ExecutionService] = None


def get_execution_service(extractor, openai_client=None) -> ExecutionService:
    """
    Factory function para criar/obter ExecutionService.
    
    Args:
        extractor: TinderDataExtractor para envio de mensagens
        openai_client: Cliente OpenAI (opcional, usa padrão se não fornecido)
        
    Returns:
        Instância de ExecutionService
    """
    global _execution_service
    
    # Criar nova instância se não existir ou se extractor mudou
    if _execution_service is None or _execution_service.extractor != extractor:
        _execution_service = ExecutionService(extractor)
        if openai_client:
            _execution_service.openai = openai_client
    
    return _execution_service


def reset_execution_service():
    """Reseta o singleton (útil para testes)."""
    global _execution_service
    _execution_service = None
