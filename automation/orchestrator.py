"""
Orquestrador principal da automação.
Coordena todas as operações de automação.
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ai import get_openai_client
from config import TINDER_MATCHES_URL, get_settings
from database import (
    AIInteractionRepository,
    AnalyticsRepository,
    ExecutionLogRepository,
    Match,
    MatchRepository,
    Message,
    MessageRepository,
    MyProfileRepository,
    get_db_manager,
)
from utils.ab_testing import get_ab_manager
from utils.helpers import async_random_delay, clean_message_preview, safe_json_dumps
from utils.logger import (
    console_complete,
    console_cycle,
    console_error,
    console_matches_loaded,
    console_message_sent,
    console_message_skipped,
    console_processing_match,
    console_start,
    console_stats,
    console_stop,
    console_sync_complete,
    console_sync_start,
    console_waiting,
    console_warning,
    console_whatsapp_detected,
    get_logger,
    log_ai_decision,
    log_automation_step,
    log_file_only,
)
from utils.notifications import get_notification_manager, notify
from utils.whatsapp_detector import analyze_message_for_progression

from .browser import BrowserController, get_browser
from .execution_service import get_execution_service
from .extractors import TinderDataExtractor

# Importar novos serviços da arquitetura refatorada
from .match_data_service import get_match_data_service
from .match_helpers import (
    MatchDataFetcher,
    MatchValidator,
    extract_complete_profile,
    get_profile_cache,
    retry_with_backoff,
    validate_ai_message,
    validate_ai_message_with_context,
)
from .state_manager import get_state_manager

logger = get_logger(__name__)


# Rate limiting config
RATE_LIMIT = {
    "messages_per_hour": 30,
    "messages_per_session": 50,
    "min_delay_between_messages": 2,  # segundos
    "max_delay_between_messages": 9,
}


class AutomationOrchestrator:
    """Orquestrador principal de todas as operações de automação."""
    
    def __init__(self):
        self.settings = get_settings()
        self.browser: Optional[BrowserController] = None
        self.extractor: Optional[TinderDataExtractor] = None
        self.openai = get_openai_client()
        self.db = get_db_manager()
        self.notification_manager = get_notification_manager()
        
        # Usar singleton ProfileCache ao invés de cache local
        self._profile_cache = get_profile_cache()
        
        # Rate limiting
        self._messages_this_hour = 0
        self._messages_this_session = 0
        self._last_message_time: Optional[datetime] = None
        self._hour_start: Optional[datetime] = None
        
        # Contadores da execução
        self.stats = {
            "matches_processed": 0,
            "messages_sent": 0,
            "profiles_analyzed": 0,
            "errors": 0,
            "whatsapp_detected": 0,
            "date_confirmations": 0,
            "unmatches_detected": 0
        }
    
    def _check_rate_limit(self) -> bool:
        """Verifica se pode enviar mais mensagens (rate limiting)."""
        now = datetime.utcnow()
        
        # Reset contador por hora
        if not self._hour_start or (now - self._hour_start).total_seconds() > 3600:
            self._hour_start = now
            self._messages_this_hour = 0
        
        # Verificar limites
        if self._messages_this_hour >= RATE_LIMIT["messages_per_hour"]:
            logger.warning(f"Rate limit: máximo de {RATE_LIMIT['messages_per_hour']} mensagens/hora atingido")
            return False
        
        if self._messages_this_session >= RATE_LIMIT["messages_per_session"]:
            logger.warning(f"Rate limit: máximo de {RATE_LIMIT['messages_per_session']} mensagens/sessão atingido")
            return False
        
        # Verificar delay mínimo
        if self._last_message_time:
            elapsed = (now - self._last_message_time).total_seconds()
            if elapsed < RATE_LIMIT["min_delay_between_messages"]:
                wait_time = RATE_LIMIT["min_delay_between_messages"] - elapsed
                logger.debug(f"Rate limit: aguardando {wait_time:.0f}s antes da próxima mensagem")
                return False
        
        return True
    
    def _record_message_sent(self):
        """Registra envio de mensagem para rate limiting."""
        self._messages_this_hour += 1
        self._messages_this_session += 1
        self._last_message_time = datetime.utcnow()
    
    async def _apply_human_delay(self):
        """Aplica delay humanizado entre ações (async-safe)."""
        delay = random.uniform(
            RATE_LIMIT["min_delay_between_messages"],
            RATE_LIMIT["max_delay_between_messages"]
        )
        console_waiting(int(delay), "delay humanizado")
        await asyncio.sleep(delay)
    
    def _get_cached_profile(self) -> Optional[Dict]:
        """Retorna perfil do cache singleton se válido (cache de 1 hora)."""
        return self._profile_cache.get("my_profile", max_age_seconds=3600)
    
    def _cache_profile(self, profile_data: Dict):
        """Armazena perfil no cache singleton."""
        self._profile_cache.set("my_profile", profile_data)
    
    def _validate_ai_message(self, message: str) -> bool:
        """Valida se mensagem da IA é adequada para envio."""
        is_valid, reason = validate_ai_message(message)
        if not is_valid:
            logger.warning(f"Mensagem rejeitada: {reason}")
        return is_valid
    
    def _validate_ai_message_with_context(
        self, 
        message: str, 
        conversation_history: list = None,
        is_first_message: bool = False
    ) -> bool:
        """
        Valida mensagem considerando o contexto da conversa.
        Evita saudações repetidas se já houve troca de mensagens.
        """
        is_valid, reason = validate_ai_message_with_context(
            message, 
            conversation_history, 
            is_first_message
        )
        if not is_valid:
            logger.warning(f"Mensagem rejeitada (contexto): {reason}")
        return is_valid
    
    async def initialize(self, headless: bool = None) -> bool:
        """Inicializa todos os componentes necessários.
        
        Args:
            headless: Se passado, força modo headless (True) ou visível (False).
                      Se None, usa configuração do settings.
        """
        log_file_only("Iniciando orquestrador de automação...")
        
        try:
            # Inicializar banco de dados
            self.db.initialize()
            
            # Resetar singleton do browser para permitir mudar modo headless/visível
            from .browser import reset_browser
            reset_browser()
            
            # Inicializar navegador
            self.browser = get_browser(headless=headless)
            await self.browser.initialize()
            
            # Criar extrator
            self.extractor = TinderDataExtractor(self.browser.page)
            
            # Navegar para o Tinder uma única vez
            log_file_only("Navegando para o Tinder...")
            await self.browser.navigate_to(TINDER_MATCHES_URL)
            
            # Verificar se já está logado
            if not await self.browser.is_logged_in():
                if headless:
                    # Em modo headless, não pode pedir login manual
                    console_warning("Modo headless: sessão não encontrada, pulando sync")
                    return False
                    
                console_warning("Usuário não está logado no Tinder")
                logger.debug("👆 Por favor, faça login manualmente no navegador que abriu...")
                logger.debug("⏳ O script irá detectar automaticamente quando você fizer login.")
                
                # Aguardar login (5 minutos)
                if not await self.browser.wait_for_login(timeout=300):
                    console_error("Timeout aguardando login (5 minutos)")
                    return False
            
            log_file_only("Orquestrador inicializado com sucesso")
            return True
            
        except Exception as e:
            console_error(f"Erro ao inicializar orquestrador: {e}")
            return False
    
    async def close(self) -> None:
        """Fecha todos os recursos."""
        if self.browser:
            await self.browser.close()
        log_file_only("Orquestrador fechado")
    
    async def analyze_my_profile(self) -> Dict:
        """
        Analisa e persiste meu perfil.
        Execução inicial obrigatória.
        """
        log_file_only("Analisando meu perfil...")
        
        # Extrair dados do perfil
        profile_data = await self.extractor.extract_my_profile()
        
        # Analisar com IA
        analysis = self.openai.analyze_profile(profile_data)
        
        # Persistir no banco
        with self.db.get_session() as session:
            repo = MyProfileRepository(session)
            profile = repo.get_or_create()
            
            # Atualizar dados básicos
            repo.update(
                profile,
                name=profile_data.get("name"),
                age=profile_data.get("age"),
                bio=profile_data.get("bio"),
                location=profile_data.get("location"),
                job_title=profile_data.get("job_title"),
                company=profile_data.get("company"),
                school=profile_data.get("school"),
                photos_count=len(profile_data.get("photos", [])),
                interests_count=len(profile_data.get("interests", []))
            )
            
            # Atualizar scores
            repo.update(
                profile,
                bio_quality_score=analysis.get("bio_quality_score"),
                photos_quality_score=analysis.get("photos_quality_score"),
                completeness_score=analysis.get("completeness_score"),
                match_potential_score=analysis.get("match_potential_score"),
                overall_score=analysis.get("overall_score"),
                bio_analysis=analysis.get("bio_analysis"),
                photos_analysis=analysis.get("photos_analysis"),
                strengths=safe_json_dumps(analysis.get("strengths", [])),
                improvements=safe_json_dumps(analysis.get("improvements", [])),
                last_analyzed_at=datetime.utcnow()
            )
            
            # Atualizar fotos
            repo.clear_photos(profile)
            for photo in profile_data.get("photos", []):
                repo.add_photo(
                    profile,
                    photo_url=photo.get("url"),
                    order=photo.get("order", 0)
                )
            
            # Atualizar interesses
            repo.clear_interests(profile)
            for interest in profile_data.get("interests", []):
                repo.add_interest(profile, interest)
            
            # Registrar interação com IA
            ai_repo = AIInteractionRepository(session)
            metadata = analysis.get("_metadata", {})
            interaction = ai_repo.create(
                interaction_type="profile_analysis",
                model_used=metadata.get("model", self.settings.openai_model),
                prompt_template="profile_analysis"
            )
            ai_repo.complete(
                interaction,
                response_content=safe_json_dumps(analysis),
                prompt_tokens=metadata.get("prompt_tokens", 0),
                completion_tokens=metadata.get("completion_tokens", 0),
                response_time_ms=metadata.get("response_time_ms", 0)
            )
        
        log_file_only(
            "Análise do meu perfil concluída",
            {"overall_score": analysis.get("overall_score")}
        )
        
        self.stats["profiles_analyzed"] += 1
        return analysis
    
    async def process_matches(self) -> Dict:
        """
        Processa todos os matches.
        Separa em: sem mensagem e aguardando resposta.
        """
        log_file_only("Processando matches...")
        logger.debug("[PROCESS_MATCHES] Iniciando...")
        
        # Navegar para matches
        logger.debug("[PROCESS_MATCHES] Navegando para matches...")
        await self.browser.navigate_to_matches()
        
        # Extrair lista de matches
        logger.debug("[PROCESS_MATCHES] Extraindo lista de matches...")
        matches_data = await self.extractor.extract_matches_list()
        logger.debug(f"[PROCESS_MATCHES] Extraídos {len(matches_data)} matches")
        
        results = {
            "new_matches": [],
            "awaiting_response": [],
            "processed": 0
        }
        
        with self.db.get_session() as session:
            match_repo = MatchRepository(session)
            msg_repo = MessageRepository(session)
            
            for i, match_data in enumerate(matches_data[:self.settings.max_messages_per_run]):
                # Verificar stop durante processamento de matches
                if get_state_manager().should_stop:
                    log_file_only("Stop solicitado durante process_matches, interrompendo")
                    break
                
                logger.debug(f"[PROCESS_MATCHES] Processando match {i+1}: {match_data}")
                match_id = match_data.get("tinder_match_id")
                if not match_id:
                    logger.debug(f"[PROCESS_MATCHES] Match sem ID, pulando")
                    continue
                
                # Buscar ou criar match no banco
                match, created = match_repo.get_or_create(
                    match_id,
                    name=match_data.get("name")
                )
                
                if created:
                    results["new_matches"].append(match_id)
                    # Novo match - marcar como sem mensagens
                    match_repo.update(match, has_messages=False)
                else:
                    # Match já existe - NÃO resetar status awaiting_my_response
                    # O status só deve ser alterado quando há sync de mensagens
                    # Verificar mensagens apenas para atualizar o status se necessário
                    messages = msg_repo.get_messages_for_match(match.id, limit=1)
                    
                    if messages:
                        last_msg = messages[0]
                        # Só atualizar awaiting se tiver mensagens no banco
                        new_awaiting = not last_msg.is_from_me
                        if match.awaiting_my_response != new_awaiting:
                            match_repo.update(match, awaiting_my_response=new_awaiting)
                            if new_awaiting:
                                results["awaiting_response"].append(match_id)
                        elif new_awaiting:
                            results["awaiting_response"].append(match_id)
                    # Se não tem mensagens no banco, manter o status atual
                    # (pode ter sido setado por sync anterior ou atualização manual)
                
                results["processed"] += 1
                self.stats["matches_processed"] += 1
        
        logger.debug(f"[PROCESS_MATCHES] Concluído: {results}")
        log_file_only(
            f"Matches processados: total={results['processed']}, new={len(results['new_matches'])}, awaiting={len(results['awaiting_response'])}"
        )
        
        return results
    
    async def send_first_messages(self, limit: int = 5) -> List[Dict]:
        """
        Envia primeiras mensagens para matches sem interação.
        
        Args:
            limit: Número máximo de mensagens a enviar
        """
        log_file_only(f"Enviando primeiras mensagens (limite: {limit})...")
        console_matches_loaded(limit, "limite de envio")
        
        results = []
        
        with self.db.get_session() as session:
            match_repo = MatchRepository(session)
            msg_repo = MessageRepository(session)
            ai_repo = AIInteractionRepository(session)
            my_profile_repo = MyProfileRepository(session)
            
            # Usar cache do perfil se disponível, senão buscar do banco
            my_profile_data = self._get_cached_profile()
            if not my_profile_data:
                my_profile = my_profile_repo.get_or_create()
                my_profile_data = {
                    "name": my_profile.name,
                    "age": my_profile.age,
                    "bio": my_profile.bio,
                    "interests": [i.interest_name for i in my_profile.interests]
                }
                self._cache_profile(my_profile_data)
            
            # Inicializar helpers centralizados
            validator = MatchValidator(self.settings)
            data_fetcher = MatchDataFetcher(match_repo, self.extractor, my_profile_data)
            
            # Buscar matches sem mensagem
            matches = match_repo.get_matches_without_messages()[:limit]
            
            for match in matches:
                # Verificar rate limit
                if not self._check_rate_limit():
                    console_warning("Rate limit atingido, parando envio")
                    break
                
                # Usar validador centralizado
                should_skip, skip_reason = validator.should_skip_match(match)
                if should_skip:
                    console_message_skipped(match.name, skip_reason)
                    continue
                
                try:
                    # Usar data fetcher centralizado (banco + tela se necessário)
                    match_profile, was_unmatched = await data_fetcher.get_match_data_for_ai(match)
                    
                    if was_unmatched:
                        match_repo.mark_as_unmatched(match)
                        self.stats["unmatches_detected"] += 1
                        continue
                    
                    # Gerar mensagem com IA
                    ai_result = self.openai.generate_first_message(
                        match_profile=match_profile
                    )
                    
                    # Validar resultado da IA
                    if not ai_result or not isinstance(ai_result, dict):
                        logger.error(f"IA retornou resultado inválido: {ai_result}")
                        raise ValueError("Resultado da IA inválido")
                    
                    message = ai_result.get("message") or ""
                    
                    # Validar mensagem - não pode ser nome do campo
                    invalid_values = ['"message"', "'message'", "message"]
                    if not message or not isinstance(message, str) or len(message.strip()) < 2 or message.lower() in invalid_values:
                        logger.error(f"IA não retornou mensagem válida: {ai_result}")
                        raise ValueError(f"Mensagem inválida da IA: '{message}'")
                    
                    if message and self._validate_ai_message(message):
                        # Enviar mensagem
                        success = await self.extractor.send_message(
                            match.tinder_match_id,
                            message
                        )
                        
                        if success:
                            # Registrar envio para rate limiting
                            self._record_message_sent()
                            
                            # Registrar mensagem no banco
                            msg_repo.create(
                                match_id=match.id,
                                content=message,
                                is_from_me=True,
                                message_type="first_message",
                                ai_generated=True,
                                sent_at=datetime.utcnow()
                            )
                            
                            match_repo.update(
                                match,
                                has_messages=True,
                                first_message_sent=True,
                                awaiting_my_response=False,
                                last_message_text=message[:200] if message else None,
                                last_message_from_me=True,
                                last_message_at=datetime.utcnow(),
                                last_interaction_at=datetime.utcnow()
                            )
                            
                            self.stats["messages_sent"] += 1
                            
                            results.append({
                                "match_id": match.tinder_match_id,
                                "name": match.name,
                                "message": message,
                                "success": True
                            })
                            
                            # Delay humanizado
                            await self._apply_human_delay()
                    
                    # Registrar uso da IA
                    metadata = ai_result.get("_metadata", {})
                    interaction = ai_repo.create(
                        interaction_type="first_message_generation",
                        model_used=metadata.get("model", self.settings.openai_model),
                        match_id=match.id,
                        prompt_template="first_message"
                    )
                    ai_repo.complete(
                        interaction,
                        response_content=safe_json_dumps(ai_result),
                        prompt_tokens=metadata.get("prompt_tokens", 0),
                        completion_tokens=metadata.get("completion_tokens", 0),
                        response_time_ms=metadata.get("response_time_ms", 0)
                    )
                    
                except Exception as e:
                    logger.error(f"Erro ao processar match {match.tinder_match_id}: {e}")
                    self.stats["errors"] += 1
                    results.append({
                        "match_id": match.tinder_match_id,
                        "name": match.name,
                        "success": False,
                        "error": str(e)
                    })
        
        log_file_only(
            "Primeiras mensagens enviadas",
            {"total": len(results), "success": sum(1 for r in results if r.get("success"))}
        )
        
        return results
    
    async def respond_to_messages(self, limit: int = 5) -> List[Dict]:
        """
        Responde mensagens aguardando resposta.
        
        Args:
            limit: Número máximo de conversas a responder
        """
        log_file_only(f"Respondendo mensagens (limite: {limit})...")
        
        results = []
        
        with self.db.get_session() as session:
            match_repo = MatchRepository(session)
            msg_repo = MessageRepository(session)
            ai_repo = AIInteractionRepository(session)
            my_profile_repo = MyProfileRepository(session)
            
            # Usar cache do perfil se disponível
            my_profile_data = self._get_cached_profile()
            if not my_profile_data:
                my_profile = my_profile_repo.get_or_create()
                my_profile_data = {
                    "name": my_profile.name,
                    "age": my_profile.age,
                    "bio": my_profile.bio,
                    "interests": [i.interest_name for i in my_profile.interests]
                }
                self._cache_profile(my_profile_data)
            
            # Inicializar helpers centralizados
            validator = MatchValidator(self.settings)
            data_fetcher = MatchDataFetcher(match_repo, self.extractor, my_profile_data)
            
            # Buscar matches aguardando resposta
            matches = match_repo.get_matches_awaiting_my_response()[:limit]
            
            for match in matches:
                # Verificar rate limit
                if not self._check_rate_limit():
                    console_warning("Rate limit atingido, parando envio")
                    break
                
                # Usar validador centralizado
                should_skip, skip_reason = validator.should_skip_match(match)
                if should_skip:
                    console_message_skipped(match.name, skip_reason)
                    continue
                
                try:
                    
                    # Extrair conversa
                    conversation = await self.extractor.extract_conversation(
                        match.tinder_match_id,
                        max_messages=10
                    )
                    
                    # Detectar unmatch (conversa não encontrada)
                    if conversation is None:
                        match_repo.mark_as_unmatched(match)
                        self.stats["unmatches_detected"] += 1
                        continue
                    
                    if not conversation:
                        continue
                    
                    # Verificar se última mensagem é minha
                    last_msg = conversation[-1] if conversation else None
                    if last_msg and last_msg.get("is_from_me"):
                        match_repo.update(match, awaiting_my_response=False)
                        continue
                    
                    # Analisar mensagem recebida para detectar WhatsApp/encontro
                    last_msg_content = last_msg.get("content", "") if last_msg else ""
                    progression = analyze_message_for_progression(last_msg_content)
                    
                    if progression['has_whatsapp'] and progression['whatsapp_number']:
                        match_repo.update_whatsapp(match, progression['whatsapp_number'])
                        self.stats["whatsapp_detected"] += 1
                        # Notificar
                        await notify('whatsapp_received', {
                            'name': match.name,
                            'phone': progression['whatsapp_number']
                        })
                        console_whatsapp_detected(match.name, progression['whatsapp_number'])
                    
                    if progression['date_confirmation']:
                        match_repo.confirm_date(match)
                        self.stats["date_confirmations"] += 1
                        # Notificar
                        await notify('date_confirmed', {
                            'name': match.name,
                            'message': last_msg_content[:100]
                        })
                        log_file_only(f"Encontro confirmado com {match.name}!")
                    
                    # Usar data fetcher centralizado (banco + tela se necessário)
                    match_profile_data, was_unmatched = await data_fetcher.get_match_data_for_ai(match)
                    
                    if was_unmatched:
                        match_repo.mark_as_unmatched(match)
                        self.stats["unmatches_detected"] += 1
                        continue
                    
                    # Obter variantes A/B para esta resposta
                    ab_manager = get_ab_manager()
                    ab_variants = {
                        'style': ab_manager.get_variant('first_message_style', match.tinder_match_id),
                        'intensity': ab_manager.get_variant('flirt_intensity', match.tinder_match_id),
                        'emoji': ab_manager.get_variant('emoji_usage', match.tinder_match_id)
                    }
                    logger.debug(f"🧪 Variantes A/B para {match.name}: {ab_variants}")
                    
                    # Analisar e gerar resposta
                    ai_result = self.openai.analyze_conversation_and_respond(
                        match_profile=match_profile_data,
                        conversation_history=conversation[:-1],
                        last_message=last_msg_content,
                        ab_variants=ab_variants
                    )
                    
                    # Validar resultado da IA
                    if not ai_result or not isinstance(ai_result, dict):
                        logger.error(f"IA retornou resultado inválido para resposta: {ai_result}")
                        raise ValueError("Resultado da IA inválido")
                    
                    # Determinar qual mensagem usar (com validação robusta)
                    temperature = ai_result.get("temperature_label") or "warm"
                    # Garantir que é string
                    if not isinstance(temperature, str):
                        logger.warning(f"temperature_label não é string: {type(temperature)} = {temperature}")
                        temperature = "warm"
                    # Validar que não é o nome do campo
                    invalid_labels = ['"temperature_label"', "'temperature_label'", "temperature_label"]
                    if temperature.lower() in invalid_labels:
                        temperature = "warm"
                    
                    temp_score = ai_result.get("temperature_score")
                    # Validar temp_score - deve ser número
                    invalid_scores = ['"temperature_score"', "'temperature_score'", "temperature_score"]
                    if isinstance(temp_score, str) and temp_score.lower() in invalid_scores:
                        logger.warning(f"temperature_score inválido: '{temp_score}'. AI result: {ai_result}")
                        temp_score = 5
                    elif isinstance(temp_score, str):
                        try:
                            temp_score = float(temp_score)
                        except ValueError:
                            temp_score = 5
                    if not isinstance(temp_score, (int, float)):
                        temp_score = 5
                    
                    next_step = ai_result.get("next_step_recommendation") or "continuar"
                    # Garantir que é string
                    if not isinstance(next_step, str):
                        logger.warning(f"next_step_recommendation não é string: {type(next_step)} = {next_step}")
                        next_step = "continuar"
                    invalid_steps = ['"next_step_recommendation"', "'next_step_recommendation'"]
                    if next_step.lower() in invalid_steps:
                        next_step = "continuar"
                    
                    # Atualizar histórico de temperatura
                    match_repo.update_temperature_history(match, temperature, temp_score)
                    
                    # Notificar se conversa quente
                    if temp_score >= 7:
                        await notify('hot_conversation', {
                            'name': match.name,
                            'temperature': temp_score,
                            'last_message': last_msg_content[:80]
                        })
                    
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
                        logger.warning(f"Mensagem não é string: {type(message)} = {message}")
                        message = str(message) if message else ""
                    
                    # Validar que mensagem não é nome do campo
                    invalid_msg = ['"suggested_response"', "'suggested_response'", "suggested_response"]
                    if message and message.lower() in invalid_msg:
                        logger.warning(f"Resposta inválida: '{message}'. AI result: {ai_result}")
                        message = ""
                    
                    # Validar mensagem com contexto (evita saudações repetidas)
                    if message and self._validate_ai_message_with_context(
                        message, 
                        conversation_history=conversation[:-1],
                        is_first_message=False
                    ):
                        # Enviar mensagem
                        success = await self.extractor.send_message(
                            match.tinder_match_id,
                            message
                        )
                        
                        if success:
                            # Registrar envio para rate limiting
                            self._record_message_sent()
                            
                            # Registrar mensagem
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
                            
                            results.append({
                                "match_id": match.tinder_match_id,
                                "name": match.name,
                                "message": message,
                                "temperature": temperature,
                                "next_step": next_step,
                                "success": True
                            })
                            
                            # Delay humanizado
                            await self._apply_human_delay()
                    
                    # Registrar uso da IA
                    metadata = ai_result.get("_metadata", {})
                    interaction = ai_repo.create(
                        interaction_type="conversation_response",
                        model_used=metadata.get("model", self.settings.openai_model),
                        match_id=match.id,
                        prompt_template="conversation_response"
                    )
                    ai_repo.complete(
                        interaction,
                        response_content=safe_json_dumps(ai_result),
                        prompt_tokens=metadata.get("prompt_tokens", 0),
                        completion_tokens=metadata.get("completion_tokens", 0),
                        response_time_ms=metadata.get("response_time_ms", 0)
                    )
                    
                    await async_random_delay(2, 4)
                    
                except Exception as e:
                    logger.error(f"Erro ao responder match {match.tinder_match_id}: {e}")
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
        
        return results
    
    async def run_full_automation(self) -> Dict:
        """
        Executa ciclo completo de automação.
        """
        console_start()
        
        execution_log = None
        
        with self.db.get_session() as session:
            exec_repo = ExecutionLogRepository(session)
            execution_log = exec_repo.create("automation")
        
        try:
            # 1. Analisar meu perfil (se primeira execução)
            with self.db.get_session() as session:
                my_profile = MyProfileRepository(session).get_or_create()
                if not my_profile.last_analyzed_at:
                    await self.analyze_my_profile()
            
            # 2. Processar matches
            await self.process_matches()
            
            # 3. Enviar primeiras mensagens
            first_msg_results = await self.send_first_messages(
                limit=self.settings.max_messages_per_run // 2
            )
            
            # 4. Responder mensagens
            response_results = await self.respond_to_messages(
                limit=self.settings.max_messages_per_run // 2
            )
            
            # Atualizar log de execução
            with self.db.get_session() as session:
                exec_repo = ExecutionLogRepository(session)
                exec_repo.complete(
                    execution_log,
                    matches_processed=self.stats["matches_processed"],
                    messages_sent=self.stats["messages_sent"],
                    errors_count=self.stats["errors"],
                    details=safe_json_dumps({
                        "first_messages": len(first_msg_results),
                        "responses": len(response_results)
                    })
                )
                
                # Atualizar analytics do dia
                analytics_repo = AnalyticsRepository(session)
                analytics = analytics_repo.get_or_create_for_date()
                analytics_repo.update(
                    analytics,
                    first_messages_sent=analytics.first_messages_sent + len(first_msg_results),
                    total_matches=MatchRepository(session).count_total()
                )
            
            log_file_only("Automação completa finalizada", self.stats)
            console_complete()
            
            return {
                "success": True,
                "stats": self.stats,
                "first_messages": first_msg_results,
                "responses": response_results
            }
            
        except Exception as e:
            logger.error(f"Erro na automação: {e}")
            
            with self.db.get_session() as session:
                exec_repo = ExecutionLogRepository(session)
                exec_repo.fail(execution_log, str(e))
            
            return {
                "success": False,
                "error": str(e),
                "stats": self.stats
            }
    
    async def sync_messages_only(self) -> Dict:
        """
        Sincroniza APENAS mensagens dos chats ativos.
        Versão leve do sync para usar durante a automação.
        
        Não extrai perfis completos, apenas atualiza mensagens
        para detectar novas respostas.
        """
        from database.models import Message
        
        messages_synced = 0
        chats_processed = 0
        
        try:
            log_file_only("Sync de mensagens iniciado...")
            
            # Buscar matches com mensagens que não estão bloqueados/finalizados
            with self.db.get_session() as session:
                from database.repositories import active_match_filter
                match_repo = MatchRepository(session)
                
                db_matches = session.query(Match).filter(
                    Match.has_messages == True,
                    active_match_filter()
                ).all()
                
                chats_to_sync = [
                    {"tinder_match_id": m.tinder_match_id, "name": m.name, "id": m.id}
                    for m in db_matches if m.tinder_match_id
                ]
            
            log_file_only(f"Sincronizando mensagens de {len(chats_to_sync)} chats...")
            
            for chat in chats_to_sync:
                # Verificar stop durante sync de mensagens
                if get_state_manager().should_stop:
                    log_file_only("Stop solicitado durante sync_messages_only, interrompendo")
                    break
                
                try:
                    tinder_id = chat.get("tinder_match_id")
                    if not tinder_id:
                        continue
                    
                    # Extrair mensagens do chat
                    conversation = await self.extractor.extract_conversation(tinder_id, max_messages=100)
                    
                    if conversation:
                        with self.db.get_session() as session:
                            match_repo = MatchRepository(session)
                            msg_repo = MessageRepository(session)
                            
                            match = session.query(Match).filter(
                                Match.tinder_match_id == tinder_id
                            ).first()
                            
                            if match:
                                # Deletar mensagens antigas e inserir novas
                                session.query(Message).filter(Message.match_id == match.id).delete()
                                session.flush()
                                
                                for msg in conversation:
                                    msg_repo.create(
                                        match_id=match.id,
                                        content=msg["content"],
                                        is_from_me=msg["is_from_me"]
                                    )
                                    messages_synced += 1
                                
                                # Atualizar status do match
                                last_msg = conversation[-1]
                                cleaned_text = clean_message_preview(last_msg["content"], match.name)
                                match_repo.update(
                                    match,
                                    has_messages=True,
                                    awaiting_my_response=not last_msg["is_from_me"],
                                    last_message_text=cleaned_text,
                                    last_message_from_me=last_msg["is_from_me"],
                                    last_message_at=datetime.utcnow()
                                )
                        
                        chats_processed += 1
                    
                    await asyncio.sleep(0.5)  # Delay curto entre chats
                    
                except Exception as e:
                    logger.warning(f"Erro ao sincronizar mensagens de {chat.get('name')}: {e}")
                    continue
            
            log_file_only(f"Sync de mensagens concluído: {chats_processed} chats, {messages_synced} msgs")
            
            return {
                "success": True,
                "chats_processed": chats_processed,
                "messages_synced": messages_synced
            }
            
        except Exception as e:
            logger.error(f"Erro no sync de mensagens: {e}")
            return {"success": False, "error": str(e)}
    
    async def run_efficient_cycle(self) -> Dict:
        """
        Executa um ciclo puramente de EXECUÇÃO.
        
        IMPORTANTE: O sync (process_matches + sync_messages_only) já foi
        realizado ANTES deste método ser chamado, pelo loop principal.
        Este método usa EXCLUSIVAMENTE dados do banco.
        
        Princípios:
        - Execução NUNCA busca dados da tela
        - Se dados estão incompletos, são pulados
        - Sync já foi feito previamente pelo run_automation
        """
        cycle_stats = {
            "messages_sent": 0,
            "matches_processed": 0,
            "errors": 0,
            "whatsapp_detected": 0,
            "unmatches_detected": 0,
            "skipped_incomplete_data": 0,
            "skipped_no_work": False
        }
        
        try:
            # =====================================================
            # FASE 1: VERIFICAR TRABALHO PENDENTE (banco apenas)
            # =====================================================
            logger.debug("[CYCLE] Verificando trabalho pendente...")
            with self.db.get_session() as session:
                match_repo = MatchRepository(session)
                pending_first_msg = match_repo.count_without_messages()
                pending_responses = match_repo.count_awaiting_response()
                pending_resend = match_repo.count_pending_resend()
            
            logger.debug(f"[CYCLE] Pendentes: first_msg={pending_first_msg}, responses={pending_responses}, resend={pending_resend}")
            total_pending = pending_first_msg + pending_responses + pending_resend
            cycle_stats["matches_processed"] = total_pending
            
            if total_pending == 0:
                cycle_stats["skipped_no_work"] = True
                log_file_only("Nenhum trabalho pendente, pulando execução")
                return {"success": True, "stats": cycle_stats}
            
            # =====================================================
            # FASE 2: EXECUTE (usa APENAS dados do banco)
            # =====================================================
            logger.debug("[CYCLE] Executando...")
            execution_service = get_execution_service(self.extractor, self.openai)
            
            state_manager = get_state_manager()
            is_dry_run = state_manager.dry_run
            logger.debug(f"[CYCLE] dry_run={is_dry_run}")
            
            # 2.1 Enviar primeiras mensagens
            if pending_first_msg > 0:
                logger.debug(f"[CYCLE] Enviando primeiras mensagens (pendentes: {pending_first_msg})...")
                first_results = await execution_service.send_first_messages(limit=999, dry_run=is_dry_run)
                logger.debug(f"[CYCLE] Resultado first_messages: {first_results}")
                cycle_stats["messages_sent"] += first_results.get("sent", 0)
                cycle_stats["skipped_incomplete_data"] += first_results.get("skipped_incomplete_data", 0)
                cycle_stats["errors"] += first_results.get("errors", 0)
            
            # Verificar stop entre fases de execução
            if state_manager.should_stop:
                log_file_only("Stop solicitado entre fases de execução (após first_messages)")
                return {"success": True, "stats": cycle_stats}
            
            # 2.2 Responder mensagens
            if pending_responses > 0:
                logger.debug(f"[CYCLE] Respondendo mensagens (pendentes: {pending_responses})...")
                response_results = await execution_service.respond_to_messages(limit=999, dry_run=is_dry_run)
                logger.debug(f"[CYCLE] Resultado responses: {response_results}")
                cycle_stats["messages_sent"] += response_results.get("sent", 0)
                cycle_stats["skipped_incomplete_data"] += response_results.get("skipped_incomplete_data", 0)
                cycle_stats["errors"] += response_results.get("errors", 0)
            
            # Verificar stop entre fases de execução
            if state_manager.should_stop:
                log_file_only("Stop solicitado entre fases de execução (após responses)")
                return {"success": True, "stats": cycle_stats}
            
            # 2.3 Reenviar mensagens complementares
            if pending_resend > 0:
                logger.debug(f"[CYCLE] Reenviando mensagens complementares (pendentes: {pending_resend})...")
                resend_results = await execution_service.resend_messages(limit=999, dry_run=is_dry_run)
                logger.debug(f"[CYCLE] Resultado resend: {resend_results}")
                cycle_stats["messages_sent"] += resend_results.get("sent", 0)
                cycle_stats["errors"] += resend_results.get("errors", 0)
            
            # =====================================================
            # FASE 3: FINALIZAÇÃO
            # =====================================================
            if cycle_stats["skipped_incomplete_data"] > 0:
                log_file_only(f"{cycle_stats['skipped_incomplete_data']} matches com dados incompletos (serão sincronizados no próximo sync)")
            
            cycle_stats["whatsapp_detected"] = self.stats.get("whatsapp_detected", 0)
            cycle_stats["unmatches_detected"] = self.stats.get("unmatches_detected", 0)
            
            # Registrar execução
            with self.db.get_session() as session:
                exec_repo = ExecutionLogRepository(session)
                exec_log = exec_repo.create("efficient_cycle")
                exec_repo.complete(
                    exec_log,
                    matches_processed=cycle_stats["matches_processed"],
                    messages_sent=cycle_stats["messages_sent"],
                    errors_count=cycle_stats["errors"]
                )
            
            logger.debug("[CYCLE] Execução concluída com sucesso")
            return {"success": True, "stats": cycle_stats}
            
        except Exception as e:
            import traceback
            logger.error(f"Erro no ciclo de execução: {e}")
            logger.error(f"[CYCLE] TRACEBACK COMPLETO:\n{traceback.format_exc()}")
            cycle_stats["errors"] += 1
            return {"success": False, "error": str(e), "stats": cycle_stats}


async def run_automation(interval_minutes: int = 10, dry_run: bool = False) -> Dict:
    """
    Executa automação em modo contínuo (única forma de execução).
    
    Fluxo otimizado por ciclo:
    1. EXECUTE: run_efficient_cycle() com browser visível (ações usando dados do banco)
    2. PAUSA: fecha browser visível → abre browser headless → SYNC completo → fecha headless → aguarda tempo restante
    3. Reinicializa browser visível → volta para EXECUTE
    
    O sync é feito DURANTE a pausa com browser escondido (headless),
    aproveitando o tempo ocioso sem desperdiçar tempo de execução.
    Se o sync headless falhar, o sync é feito como fallback com browser visível.
    
    Args:
        interval_minutes: Intervalo entre ciclos (padrão: 10 min)
        dry_run: Se True, simula execução sem enviar mensagens
        
    Returns:
        Dict com estatísticas da execução
    """
    from datetime import datetime, timedelta
    
    orchestrator = AutomationOrchestrator()
    notification_manager = get_notification_manager()
    state_manager = get_state_manager()
    
    # Garantir que o estado está marcado como running
    if not state_manager.is_running:
        state_manager.start(interval_minutes, dry_run)
    
    start_time = datetime.utcnow()
    
    total_stats = {
        "cycles_completed": 0,
        "total_messages_sent": 0,
        "total_matches_processed": 0,
        "total_errors": 0,
        "total_whatsapp_detected": 0,
        "total_unmatches": 0,
        "start_time": start_time.isoformat(),
        "stopped_reason": None,
        "dry_run": dry_run
    }
    
    # Log de início no console
    dry_run_str = " [DRY RUN]" if dry_run else ""
    console_start(f"AUTOMAÇÃO{dry_run_str} | Intervalo: {interval_minutes}min")
    
    notification_manager.notify_info(f"Automação{dry_run_str} iniciada - Ciclos de {interval_minutes}min")
    
    try:
        # Inicializar uma vez
        console_log_msg = "Inicializando navegador e conexões..."
        logger.info(f"⚙️ {console_log_msg}")
        
        if not await orchestrator.initialize():
            console_error("Falha na inicialização do orquestrador")
            state_manager.finish()
            return {"success": False, "error": "Falha na inicialização"}
        
        logger.info("✅ Inicialização concluída")
        
        # =====================================================
        # SYNC INICIAL (antes do primeiro ciclo, com browser já aberto)
        # =====================================================
        console_cycle(0, "sync inicial")
        try:
            if not state_manager.should_stop:
                await orchestrator.process_matches()
            if not state_manager.should_stop:
                await orchestrator.sync_messages_only()
            log_file_only("Sync inicial concluído")
        except Exception as sync_error:
            logger.warning(f"Erro no sync inicial: {sync_error}")
        
        cycle_number = 0
        
        while not state_manager.should_stop:
            cycle_number += 1
            state_manager.current_cycle = cycle_number
            cycle_start = datetime.utcnow()
            
            # Log detalhado apenas em arquivo
            log_file_only(f"{'='*50}")
            log_file_only(f"CICLO #{cycle_number} - {cycle_start.strftime('%H:%M:%S')}")
            
            # =====================================================
            # EXECUÇÃO (usa APENAS dados do banco, já sincronizados)
            # =====================================================
            console_cycle(cycle_number, "executando")
            
            try:
                result = await orchestrator.run_efficient_cycle()
                
                # Acumular estatísticas
                if result.get("success"):
                    stats = result.get("stats", {})
                    total_stats["cycles_completed"] += 1
                    total_stats["total_messages_sent"] += stats.get("messages_sent", 0)
                    total_stats["total_matches_processed"] += stats.get("matches_processed", 0)
                    total_stats["total_errors"] += stats.get("errors", 0)
                    total_stats["total_whatsapp_detected"] += stats.get("whatsapp_detected", 0)
                    total_stats["total_unmatches"] += stats.get("unmatches_detected", 0)
                    
                    state_manager.update_stats(
                        messages_sent=stats.get("messages_sent", 0),
                        errors=stats.get("errors", 0)
                    )
                    
                    # Resumo do ciclo no console
                    if stats.get("messages_sent", 0) > 0 or stats.get("whatsapp_detected", 0) > 0:
                        console_stats(stats)
                    else:
                        console_cycle(cycle_number, "concluído (sem ações)")
                    
                    # WhatsApp detectado - destaque especial
                    if stats.get("whatsapp_detected", 0) > 0:
                        console_whatsapp_detected(f"Ciclo #{cycle_number}")
                    
                    # Log detalhado apenas em arquivo
                    log_file_only(f"Ciclo #{cycle_number} stats: {stats}")
                else:
                    total_stats["total_errors"] += 1
                    console_warning(f"Ciclo #{cycle_number} com erro: {result.get('error')}")
                
            except Exception as cycle_error:
                total_stats["total_errors"] += 1
                console_error(f"Erro no ciclo #{cycle_number}", cycle_error)
                notification_manager.notify_error(f"Erro: {str(cycle_error)[:80]}")
            
            # Verificar se deve parar
            if state_manager.should_stop:
                console_stop("Automação", "solicitado via interface")
                total_stats["stopped_reason"] = "parada_interface_web"
                break
            
            # =====================================================
            # PAUSA: fechar browser visível → sync headless → aguardar
            # =====================================================
            logger.info("🔒 Fechando browser visível...")
            await orchestrator.close()
            orchestrator.browser = None
            orchestrator.extractor = None
            
            # Sync em background com browser escondido durante a pausa
            console_waiting(interval_minutes * 60, "próximo ciclo (sync em background)")
            pause_start = datetime.utcnow()
            
            sync_done = False
            
            # Só faz sync se não foi solicitado stop
            if not state_manager.should_stop:
                try:
                    log_file_only("Iniciando sync em background (headless)...")
                    sync_orchestrator = AutomationOrchestrator()
                    
                    if await sync_orchestrator.initialize(headless=True):
                        console_cycle(cycle_number, "sync headless durante pausa")
                        
                        try:
                            if not state_manager.should_stop:
                                await sync_orchestrator.process_matches()
                            if not state_manager.should_stop:
                                await sync_orchestrator.sync_messages_only()
                            sync_done = not state_manager.should_stop
                            log_file_only("Sync headless concluído com sucesso")
                        except Exception as sync_error:
                            logger.warning(f"Erro no sync headless: {sync_error}")
                        
                        await sync_orchestrator.close()
                    else:
                        logger.warning("Falha ao inicializar browser headless para sync")
                    
                    sync_orchestrator.browser = None
                    sync_orchestrator.extractor = None
                except Exception as e:
                    logger.warning(f"Erro no sync headless: {e}")
            
            # Aguardar tempo restante da pausa
            elapsed = (datetime.utcnow() - pause_start).total_seconds()
            remaining = max(0, (interval_minutes * 60) - elapsed)
            
            if remaining > 0:
                log_file_only(f"Sync levou {elapsed:.0f}s, aguardando mais {remaining:.0f}s")
                waited = 0
                while waited < remaining and not state_manager.should_stop:
                    await asyncio.sleep(5)
                    waited += 5
            
            # Reinicializar browser visível para execução (se não parou)
            if not state_manager.should_stop:
                logger.info("🚀 Reinicializando browser visível para execução...")
                if not await orchestrator.initialize(headless=False):
                    console_error("Falha ao reinicializar browser")
                    total_stats["stopped_reason"] = "falha_reinicializacao"
                    break
                
                # Se sync headless falhou, fazer sync rápido com browser visível
                if not sync_done:
                    log_file_only("Sync headless falhou, fazendo sync com browser visível...")
                    try:
                        await orchestrator.process_matches()
                        await orchestrator.sync_messages_only()
                    except Exception as sync_error:
                        logger.warning(f"Erro no sync fallback: {sync_error}")
        
        total_stats["stopped_reason"] = total_stats.get("stopped_reason") or "encerramento_normal"
        total_stats["end_time"] = datetime.utcnow().isoformat()
        
        duration = datetime.utcnow() - start_time
        total_stats["total_duration_minutes"] = duration.total_seconds() / 60
        
        # Resumo final no console
        console_complete(
            "AUTOMAÇÃO",
            f"Ciclos: {total_stats['cycles_completed']} | Msgs: {total_stats['total_messages_sent']} | "
            f"WhatsApp: {total_stats['total_whatsapp_detected']} | Duração: {duration.total_seconds()/60:.1f}min"
        )
        
        notification_manager.notify_automation_complete(
            total_stats['total_messages_sent'],
            total_stats['total_matches_processed'],
            total_stats['total_errors']
        )
        
        return {"success": True, "stats": total_stats}
        
    except Exception as e:
        console_error("Erro fatal na automação", e)
        return {"success": False, "error": str(e), "stats": total_stats}
    
    finally:
        state_manager.finish()
        await orchestrator.close()


async def sync_matches_only(
    force_update: bool = False,
    extract_profiles: bool = True,
    sync_messages: bool = True
) -> Dict:
    """
    Sincroniza TODAS as informações possíveis:
    - Perfil do usuário
    - Lista de matches
    - Mensagens de cada chat
    - Fotos, idades, bios
    
    Args:
        force_update: Se True, re-extrai dados mesmo se já existirem (sobrescreve bio, city, gender, etc)
        extract_profiles: Se True, extrai perfis completos (fotos, bio, interesses)
        sync_messages: Se True, sincroniza mensagens das conversas
    
    Returns:
        Dict com resultado da sincronização completa
    """
    orchestrator = AutomationOrchestrator()
    state_manager = get_state_manager()
    
    # NOTA: A verificação de "já está rodando" é feita ANTES de chamar esta função
    # (pela API web ou pelo CLI). Aqui apenas garantimos que is_syncing está marcado.
    if not state_manager.is_syncing:
        state_manager.is_syncing = True
    
    try:
        console_start("SINCRONIZAÇÃO COMPLETA")
        
        if not await orchestrator.initialize():
            console_error("Falha na inicialização")
            return {"success": False, "error": "Falha na inicialização"}
        
        console_sync_start("matches e conversas")
        state_manager.update_sync_heartbeat()  # Heartbeat após inicialização
        
        # ============================================
        # 1. Sincronizar meu perfil (usando método do extractor)
        # ============================================
        my_profile_data = None
        try:
            console_sync_start("Meu perfil")
            
            # Usar método centralizado do extractor
            profile_data = await orchestrator.extractor.extract_my_profile()
            
            # Salvar no banco
            with orchestrator.db.get_session() as session:
                from database import MyProfileRepository
                repo = MyProfileRepository(session)
                profile = repo.get_or_create()
                
                update_data = {}
                if profile_data.get("name"):
                    update_data["name"] = profile_data["name"]
                if profile_data.get("age"):
                    update_data["age"] = profile_data["age"]
                if profile_data.get("bio"):
                    update_data["bio"] = profile_data["bio"]
                if profile_data.get("job_title"):
                    update_data["job_title"] = profile_data["job_title"]
                if profile_data.get("school"):
                    update_data["school"] = profile_data["school"]
                if profile_data.get("photos"):
                    update_data["photos_count"] = len(profile_data["photos"])
                if profile_data.get("interests"):
                    update_data["interests_count"] = len(profile_data["interests"])
                
                if update_data:
                    repo.update(profile, **update_data)
                
                # Atualizar fotos
                if profile_data.get("photos"):
                    repo.clear_photos(profile)
                    for photo in profile_data["photos"]:
                        repo.add_photo(profile, photo.get("url"), photo.get("order", 0))
                
                # Atualizar interesses
                if profile_data.get("interests"):
                    repo.clear_interests(profile)
                    for interest in profile_data["interests"]:
                        repo.add_interest(profile, interest)
                
                my_profile_data = {
                    "id": profile.id,
                    "name": profile.name,
                    "age": profile.age,
                    "bio": profile.bio,
                    "photos_count": len(profile_data.get("photos", [])),
                    "interests": [i.interest_name for i in profile.interests] if profile.interests else []
                }
            
            console_sync_complete("Meu perfil")
            log_file_only(f"Perfil sincronizado: {my_profile_data}")
            
        except Exception as e:
            console_warning(f"Não foi possível sincronizar perfil: {e}")
        
        
        # ============================================
        # 2. Sincronizar matches (aba Matches + aba Mensagens)
        # ============================================
        console_sync_start("Matches e conversas")
        
        # Primeiro, excluir matches com mais de 1 ano
        old_matches_deleted = 0
        with orchestrator.db.get_session() as session:
            match_repo = MatchRepository(session)
            # DESABILITADO: Não excluir mais matches antigos
            # old_matches_deleted = match_repo.delete_old_matches(days=365)
            old_matches_deleted = 0
            logger.debug("Exclusão de matches antigos desabilitada")
            if old_matches_deleted > 0:
                logger.info(f"🗑️ Excluídos {old_matches_deleted} matches antigos")
        
        # Navegar para matches (otimizado - pula se já estiver lá)
        await orchestrator.browser.navigate_to_matches_if_needed()
        
        # =====================================================
        # 2.1 Extrair da aba Matches (matches novos sem mensagem)
        # =====================================================
        matches_data = await orchestrator.extractor.extract_matches_list()
        
        # =====================================================
        # 2.2 Extrair da aba Mensagens (conversas existentes)
        # =====================================================
        conversations_data = await orchestrator.extractor.extract_messages_list()
        
        # Combinar os dois, evitando duplicatas
        all_matches_data = []
        seen_tinder_ids = set()
        
        # Primeiro adicionar matches novos
        for m in matches_data:
            tid = m.get("tinder_match_id")
            if tid and tid not in seen_tinder_ids:
                all_matches_data.append(m)
                seen_tinder_ids.add(tid)
        
        # Depois adicionar conversas (se não estiverem já)
        for c in conversations_data:
            tid = c.get("tinder_match_id")
            if tid and tid not in seen_tinder_ids:
                all_matches_data.append(c)
                seen_tinder_ids.add(tid)
            elif tid in seen_tinder_ids:
                # Atualizar has_messages se já existe
                for m in all_matches_data:
                    if m.get("tinder_match_id") == tid:
                        m["has_messages"] = True
                        if c.get("last_message_preview"):
                            m["last_message_preview"] = c.get("last_message_preview")
                        break
        
        console_matches_loaded(len(all_matches_data), "matches/conversas")
        state_manager.update_sync_heartbeat()  # Heartbeat após extração de listas
        
        synced_matches = []
        new_count = 0
        updated_count = 0
        doubledate_count = 0
        messages_synced = 0
        
        with orchestrator.db.get_session() as session:
            match_repo = MatchRepository(session)
            msg_repo = MessageRepository(session)
            
            ignored_no_name = 0
            
            for match_data in all_matches_data:
                match_id = match_data.get("tinder_match_id")
                if not match_id:
                    continue
                
                # Matches sem nome serão cadastrados com nome 'Unknown' (serão atualizados depois)
                match_name = match_data.get("name")
                if not match_name or match_name.strip() == "":
                    match_name = "Unknown"
                    ignored_no_name += 1
                
                # Contar DoubleDates ignorados
                if match_data.get("is_doubledate"):
                    doubledate_count += 1
                
                # Buscar ou criar match no banco
                match, created = match_repo.get_or_create(
                    match_id,
                    name=match_name
                )
                
                if created:
                    new_count += 1
                else:
                    updated_count += 1
                
                # Atualizar dados do match
                update_data = {}
                
                # Só atualizar nome se o atual estiver vazio ou for "Unknown"
                if match_name and match_name != "Unknown":
                    current_name = match.name
                    if not current_name or current_name == "Unknown":
                        update_data["name"] = match_name
                
                if match_data.get("age"):
                    update_data["age"] = match_data.get("age")
                
                # Verificar foto de perfil - evitar duplicação
                photo_url = match_data.get("profile_photo_url")
                if photo_url:
                    # Verificar se esta foto já é usada por outro match
                    duplicate = match_repo.find_by_profile_photo(photo_url, exclude_match_id=match.id)
                    if duplicate:
                        log_file_only(f"Foto de perfil duplicada ignorada para {match_name} (já usada por {duplicate.name})")
                    elif not match.profile_photo_url:
                        # Só adiciona foto se o match não tem foto ainda
                        update_data["profile_photo_url"] = photo_url
                
                if match_data.get("last_message_preview"):
                    update_data["last_message_text"] = match_data.get("last_message_preview")
                    update_data["has_messages"] = True
                
                if match_data.get("has_messages"):
                    update_data["has_messages"] = True
                
                # Salvar data do match se disponível
                if match_data.get("matched_at"):
                    update_data["matched_at"] = match_data.get("matched_at")
                
                if update_data:
                    match_repo.update(match, **update_data)
                
                synced_matches.append({
                    "id": match.id,
                    "tinder_match_id": match_id,
                    "name": match.name,
                    "age": match.age,
                    "profile_photo_url": match.profile_photo_url,
                    "last_message_text": match.last_message_text,
                    "is_blocked": match.is_blocked,
                    "blocked_reason": match.blocked_reason,
                    "has_messages": match_data.get("has_messages", False)
                })
        
        # ============================================
        # 3. Extrair dados completos dos matches NOVOS (sem mensagem)
        # ============================================
        if extract_profiles:
            log_file_only("Extraindo dados completos dos matches novos (sem mensagem)...")
            
            # Filtrar matches que NÃO têm mensagens para clicar em cada um
            new_matches_to_process = [
                m for m in synced_matches 
                if not m.get("has_messages") and m.get("tinder_match_id")
            ]
            
            console_matches_loaded(len(new_matches_to_process), "matches novos para dados")
            
            for match_info in new_matches_to_process:
                # Verificar stop durante extração de perfis
                if state_manager.should_stop:
                    log_file_only("Stop solicitado durante extração de perfis, interrompendo")
                    break
                
                state_manager.update_sync_heartbeat()  # Heartbeat por perfil extraído
                
                try:
                    tinder_id = match_info.get("tinder_match_id")
                    match_name = match_info.get("name", "Unknown")
                    
                    console_processing_match(match_name, "extraindo dados")
                    
                    # Navegar para o chat/perfil do match (otimizado - pula se já estiver lá)
                    await orchestrator.browser.navigate_to_match_if_needed(tinder_id)
                    
                    # Aguardar página carregar - esperar pelo header com nome do match
                    try:
                        await orchestrator.browser.page.wait_for_selector('h1', timeout=10000)
                    except:
                        pass
                    
                    # Delay adicional para garantir que elementos carregaram
                    await asyncio.sleep(3)
                    
                    # =====================================================
                    # EXTRAÇÃO COMPLETA DO PERFIL (usando helper centralizado)
                    # =====================================================
                    fetched_profile = await extract_complete_profile(orchestrator.extractor, tinder_id)
                    
                    # Atualizar match no banco usando método centralizado
                    with orchestrator.db.get_session() as session:
                        match_repo = MatchRepository(session)
                        
                        match = session.query(Match).filter(
                            Match.tinder_match_id == tinder_id
                        ).first()
                        
                        if match:
                            # Usar método centralizado que trata duplicação de fotos,
                            # atualização de campos, salvamento de fotos e interesses
                            # force_update=True sobrescreve dados mesmo que já existam
                            updated_fields = match_repo.update_from_profile(match, fetched_profile, overwrite=force_update)
                            
                            if updated_fields:
                                log_file_only(f"Dados atualizados para {match_name}: {list(updated_fields.keys())}")
                            else:
                                log_file_only(f"Nenhum dado novo extraído para {match_name}")
                    
                    await asyncio.sleep(2)  # Delay entre profiles
                    
                except Exception as e:
                    logger.warning(f"Erro ao extrair dados de {match_info.get('name', 'unknown')}: {e}")
                    continue
        else:
            log_file_only("Extração de perfis desabilitada")
        
        # Voltar para a aba de matches apenas se necessário
        await orchestrator.browser.navigate_to_matches_if_needed()
        await asyncio.sleep(1)
        
        # ============================================
        # 4. Sincronizar mensagens de cada chat
        # ============================================
        if sync_messages:
            log_file_only("Sincronizando mensagens dos chats...")
            
            # Pegar matches que têm mensagens:
            # 1. Matches já no banco com has_messages == True
            # 2. Matches recém-sincronizados que indicaram ter mensagens
            chats_with_messages = []
            
            with orchestrator.db.get_session() as session:
                # Matches do banco com mensagens (excluindo bloqueados/finalizados)
                from sqlalchemy import or_
                db_matches = session.query(Match).filter(
                    Match.has_messages == True,
                    or_(Match.is_blocked == False, Match.is_blocked == None),
                    or_(Match.whatsapp_obtained == False, Match.whatsapp_obtained == None),
                    or_(Match.date_confirmed == False, Match.date_confirmed == None)
                ).all()
                
                for m in db_matches:
                    if m.tinder_match_id:
                        chats_with_messages.append({
                            "id": m.id,
                            "tinder_match_id": m.tinder_match_id,
                            "name": m.name
                        })
            
            # Adicionar matches recém-sincronizados que têm mensagens mas podem não estar no banco ainda
            seen_ids = {c["tinder_match_id"] for c in chats_with_messages}
            for synced in synced_matches:
                if synced.get("has_messages") and synced.get("tinder_match_id") not in seen_ids:
                    chats_with_messages.append({
                        "id": synced.get("id"),
                        "tinder_match_id": synced.get("tinder_match_id"),
                        "name": synced.get("name")
                    })
                    seen_ids.add(synced.get("tinder_match_id"))
            
            # Sem limite de chats
            console_matches_loaded(len(chats_with_messages), "chats para sincronizar")
            
            for chat in chats_with_messages:
                # Verificar stop durante sync de mensagens
                if state_manager.should_stop:
                    log_file_only("Stop solicitado durante sync de mensagens, interrompendo")
                    break
                
                state_manager.update_sync_heartbeat()  # Heartbeat por chat sincronizado
                
                try:
                    tinder_id = chat.get("tinder_match_id")
                    if not tinder_id:
                        continue
                    
                    console_processing_match(chat.get('name', tinder_id), "sincronizando msgs")
                    
                    # Extrair mensagens do chat (a função já navega para a conversa)
                    conversation = await orchestrator.extractor.extract_conversation(tinder_id, max_messages=500)
                    
                    # =====================================================
                    # EXTRAÇÃO COMPLETA DO PERFIL (usando helper centralizado)
                    # =====================================================
                    fetched_profile = await extract_complete_profile(orchestrator.extractor, tinder_id)
                    
                    with orchestrator.db.get_session() as session:
                        match_repo = MatchRepository(session)
                        msg_repo = MessageRepository(session)
                        
                        # Buscar match no banco OU criar se não existir
                        match = session.query(Match).filter(
                            Match.tinder_match_id == tinder_id
                        ).first()
                        
                        # Se não existe, criar o match
                        if not match:
                            # Usar nome do profile extraído ou nome do chat
                            final_name = fetched_profile.get('name') or chat.get('name') or 'Unknown'
                            
                            match, _ = match_repo.get_or_create(
                                tinder_id,
                                name=final_name
                            )
                            log_file_only(f"Match criado durante sync de mensagens: {final_name}")
                            new_count += 1
                        
                        if match:
                            # =====================================================
                            # ATUALIZAR DADOS DO PERFIL usando método centralizado
                            # force_update=True sobrescreve dados mesmo que já existam
                            # =====================================================
                            updated_fields = match_repo.update_from_profile(match, fetched_profile, overwrite=force_update)
                            
                            if updated_fields:
                                log_file_only(f"Dados do perfil atualizados para {chat.get('name')}: {list(updated_fields.keys())}")
                            
                            if conversation:
                                # Deletar todas as mensagens existentes do match antes de sincronizar
                                # Isso garante que não haverá duplicação
                                session.query(Message).filter(Message.match_id == match.id).delete()
                                session.flush()
                                
                                # Adicionar todas as mensagens novamente
                                for msg in conversation:
                                    msg_repo.create(
                                        match_id=match.id,
                                        content=msg["content"],
                                        is_from_me=msg["is_from_me"]
                                    )
                                    messages_synced += 1
                                
                                # Atualizar status do match
                                last_msg = conversation[-1]
                                # Limpar texto da última mensagem (remove prefixos do Tinder)
                                cleaned_text = clean_message_preview(last_msg["content"], match.name)
                                match_repo.update(
                                    match,
                                    has_messages=True,
                                    awaiting_my_response=not last_msg["is_from_me"],
                                    last_message_text=cleaned_text,
                                    last_message_from_me=last_msg["is_from_me"],
                                    last_message_at=datetime.utcnow()
                                )
                    
                    await asyncio.sleep(1)  # Delay entre chats
                    
                except Exception as e:
                    logger.warning(f"Erro ao sincronizar mensagens de {chat.get('name', 'unknown')}: {e}")
                    continue
        else:
            log_file_only("Sincronização de mensagens desabilitada")
        
        # ============================================
        # 5. Log de estatísticas finais
        # ============================================
        if ignored_no_name > 0:
            log_file_only(f"Ignorados {ignored_no_name} matches sem nome (antigos)")
        
        # Resumo final no console
        console_sync_complete("Matches e conversas", {
            "total": len(synced_matches),
            "new": new_count,
            "updated": updated_count
        })
        
        logger.info(f"📊 Mensagens sincronizadas: {messages_synced}")
        
        console_complete("SINCRONIZAÇÃO", f"Total: {len(synced_matches)} matches | {messages_synced} mensagens")
        
        log_file_only(f"Sync completo: {new_count} novos, {updated_count} atualizados, {messages_synced} msgs")
        
        return {
            "success": True,
            "my_profile": my_profile_data,
            "total_matches": len(synced_matches),
            "new_matches": new_count,
            "updated_matches": updated_count,
            "ignored_no_name": ignored_no_name,
            "doubledates_ignored": doubledate_count,
            "messages_synced": messages_synced,
            "old_matches_deleted": old_matches_deleted,
            "matches": synced_matches
        }
        
    except Exception as e:
        console_error("Erro na sincronização", e)
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        # Garantir que is_syncing seja resetado
        state_manager.is_syncing = False
        await orchestrator.close()
