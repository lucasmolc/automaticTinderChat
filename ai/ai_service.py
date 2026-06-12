"""
Serviço Centralizado de IA - Automatic Tinder Chat.

Este é o ÚNICO ponto de entrada para todas as operações de IA.
Funciona com qualquer provedor (OpenAI, DeepSeek, Claude, etc.)
de forma transparente e unificada.

Uso:
    from ai import get_ai_service, ai_chat
    
    # Método direto
    service = get_ai_service()
    result = service.generate_message(match_profile)
    
    # Helper function
    response = ai_chat([{"role": "user", "content": "Olá"}])
"""

import re
import time
import random
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from config import get_settings, PROMPTS_DIR
from utils.logger import get_logger, log_ai_decision, log_ai_raw_request, log_ai_raw_response, log_ai_raw_error
from utils.helpers import extract_json_from_text

from .provider_manager import get_ai_manager
from .base_provider import AIResponse, AIProviderError

logger = get_logger(__name__)


class AIService:
    """
    Serviço centralizado de IA.
    
    Características:
    - Provider-agnostic: funciona com qualquer provedor configurado
    - Métodos de alto nível para operações comuns
    - Cache de prompts
    - Fallback automático para respostas genéricas
    - Logging centralizado de custos e uso
    """
    
    # Mensagens genéricas de fallback
    GENERIC_MESSAGES = [
        "Oi! Curti muito seu perfil! O que você gosta de fazer nos fins de semana? 😊",
        "Oi! Tudo bem? Achei seu perfil muito interessante, adoraria te conhecer melhor!",
        "Olá! Vi que a gente deu match, como está sendo seu dia? 🌟",
        "Oi! Achei a gente bem compatível pelo perfil. Conta mais sobre você!",
        "E aí! Tudo bem? Curti seu perfil, parece que temos algumas coisas em comum!",
    ]
    
    def __init__(self):
        self.settings = get_settings()
        self._manager = None
        self._prompts_cache: Dict[str, str] = {}
        self._personal_context: Optional[str] = None
        self._personal_context_loaded: bool = False
    
    # ==================== PROPRIEDADES ====================
    
    @property
    def manager(self):
        """Lazy loading do provider manager."""
        if self._manager is None:
            self._manager = get_ai_manager()
        return self._manager
    
    @property
    def model(self) -> str:
        """Retorna o modelo ativo."""
        provider = self.manager.get_active_provider()
        return provider.current_model if provider else self.settings.openai_model
    
    @property
    def provider_id(self) -> Optional[str]:
        """Retorna ID do provedor ativo."""
        provider = self.manager.get_active_provider()
        return provider.PROVIDER_ID if provider else None
    
    def is_available(self) -> bool:
        """Verifica se há um provedor de IA disponível."""
        provider = self.manager.get_active_provider()
        return provider is not None and provider.is_enabled
    
    # ==================== PROMPTS ====================
    
    def _load_prompt(self, prompt_name: str) -> str:
        """Carrega template de prompt do arquivo."""
        if prompt_name in self._prompts_cache:
            return self._prompts_cache[prompt_name]
        
        prompt_file = PROMPTS_DIR / f"{prompt_name}.txt"
        
        if not prompt_file.exists():
            logger.error(f"Arquivo de prompt não encontrado: {prompt_file}")
            raise FileNotFoundError(f"Prompt '{prompt_name}' não encontrado")
        
        content = prompt_file.read_text(encoding="utf-8")
        self._prompts_cache[prompt_name] = content
        return content
    
    def _load_system_prompt(self, prompt_name: str) -> str:
        """Carrega prompt de sistema."""
        return self._load_prompt(f"system_{prompt_name}")
    
    def _load_personal_context(self) -> Optional[str]:
        """
        Carrega contexto pessoal do arquivo personal_context.txt.
        
        Este arquivo contém informações pessoais do usuário que são
        injetadas como contexto em TODAS as chamadas à IA para garantir
        respostas consistentes e personalizadas.
        
        Returns:
            Conteúdo do contexto pessoal ou None se não existir
        """
        if self._personal_context_loaded:
            return self._personal_context
        
        self._personal_context_loaded = True
        personal_file = PROMPTS_DIR / "personal_context.txt"
        
        if not personal_file.exists():
            logger.warning(
                "Arquivo personal_context.txt não encontrado em config/prompts/. "
                "Copie personal_context.example.txt e preencha com seus dados."
            )
            self._personal_context = None
            return None
        
        content = personal_file.read_text(encoding="utf-8").strip()
        
        # Verificar se o arquivo foi preenchido (não está vazio/template)
        if not content or all(
            line.strip().endswith(':') or line.strip().startswith('=') or not line.strip()
            for line in content.split('\n')
            if line.strip()
        ):
            logger.warning(
                "Arquivo personal_context.txt existe mas parece não estar preenchido. "
                "Preencha com seus dados pessoais para respostas mais precisas."
            )
            self._personal_context = None
            return None
        
        self._personal_context = content
        logger.debug("Contexto pessoal carregado com sucesso")
        return self._personal_context
    
    def _inject_personal_context(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Injeta contexto pessoal e temporal nas mensagens para a IA.
        
        Adiciona:
        1. Data/hora atual (para evitar respostas fora de contexto temporal)
        2. Conteúdo de personal_context.txt como mensagem de sistema
        
        Garante que a IA tenha informações corretas sobre o usuário
        e o momento atual em TODAS as interações.
        
        Args:
            messages: Lista de mensagens original
            
        Returns:
            Lista de mensagens com contexto injetado
        """
        from datetime import datetime
        import locale
        
        # Copiar para não alterar a lista original
        enriched = list(messages)
        
        # Encontrar posição após o último system message para inserir contexto
        insert_pos = 0
        for i, msg in enumerate(enriched):
            if msg.get("role") == "system":
                insert_pos = i + 1
        
        # Injetar contexto temporal (data, hora, dia da semana)
        now = datetime.now()
        dias_semana = {
            0: "segunda-feira", 1: "terça-feira", 2: "quarta-feira",
            3: "quinta-feira", 4: "sexta-feira", 5: "sábado", 6: "domingo"
        }
        dia_semana = dias_semana[now.weekday()]
        
        # Determinar período do dia
        hora = now.hour
        if 5 <= hora < 12:
            periodo = "manhã"
        elif 12 <= hora < 18:
            periodo = "tarde"
        elif 18 <= hora < 22:
            periodo = "noite"
        else:
            periodo = "madrugada"
        
        temporal_message = {
            "role": "system",
            "content": (
                f"CONTEXTO TEMPORAL: Agora são {now.strftime('%H:%M')} de "
                f"{dia_semana}, {now.strftime('%d/%m/%Y')} (período: {periodo}). "
                "Use esta informação para manter coerência temporal nas mensagens — "
                "por exemplo, NÃO mencione 'fim de semana' se for dia de semana, "
                "NÃO fale de 'bom dia/café da manhã' à noite, etc."
            )
        }
        enriched.insert(insert_pos, temporal_message)
        
        # Injetar contexto pessoal (se disponível)
        personal_context = self._load_personal_context()
        if personal_context:
            context_message = {
                "role": "system",
                "content": (
                    "CONTEXTO PESSOAL DO USUÁRIO (use como referência para manter "
                    "consistência nas respostas — NUNCA invente informações que "
                    "contradigam estes dados):\n\n"
                    f"{personal_context}"
                )
            }
            enriched.insert(insert_pos + 1, context_message)
        
        return enriched

    def clear_prompts_cache(self) -> None:
        """Limpa o cache de prompts."""
        self._prompts_cache.clear()
        self._personal_context = None
        self._personal_context_loaded = False
        logger.debug("Cache de prompts limpo")
    
    # ==================== UTILITÁRIOS ====================
    
    def _format_conversation_history(self, messages: list, match_name: str) -> str:
        """Formata histórico de conversa para a IA."""
        if not messages:
            return "(Nenhuma mensagem anterior)"
        
        formatted = []
        for msg in messages:
            sender = "EU" if msg.get("is_from_me") else match_name.upper()
            content = msg.get("content", "")
            formatted.append(f"{sender}: {content}")
        
        return "\n".join(formatted)
    
    def _build_ab_instructions(self, ab_variants: dict) -> str:
        """Constrói instruções A/B a partir das variantes."""
        if not ab_variants:
            return ""
        
        parts = ["===== INSTRUÇÕES DO TESTE A/B ====="]
        
        # Estilo
        style = ab_variants.get('style')
        style_map = {
            'playful': "ESTILO: Brincalhão e divertido, use humor leve",
            'confident': "ESTILO: Confiante e direto, mostre interesse sem rodeios",
            'intriguing': "ESTILO: Misterioso e intrigante, desperte curiosidade"
        }
        if style in style_map:
            parts.append(style_map[style])
        
        # Intensidade
        intensity = ab_variants.get('intensity')
        intensity_map = {
            'subtle': "FLERTE: Sutil, interesse nas entrelinhas",
            'moderate': "FLERTE: Moderado, interesse claro mas não exagerado",
            'direct': "FLERTE: Direto, demonstre interesse abertamente"
        }
        if intensity in intensity_map:
            parts.append(intensity_map[intensity])
        
        # Emoji
        emoji = ab_variants.get('emoji')
        emoji_map = {
            'no_emoji': "EMOJI: NÃO use nenhum emoji",
            'minimal': "EMOJI: Use no máximo 1 emoji",
            'flirty': "EMOJI: Use 1-2 emojis de flerte (😏🔥😉)"
        }
        if emoji in emoji_map:
            parts.append(emoji_map[emoji])
        
        return "\n".join(parts) if len(parts) > 1 else ""
    
    def _get_generic_message(self) -> str:
        """Retorna mensagem genérica aleatória."""
        return random.choice(self.GENERIC_MESSAGES)
    
    # ==================== CHAMADA PRINCIPAL ====================
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 500,
        interaction_type: str = 'chat',
        match_id: int = None,
        **kwargs
    ) -> AIResponse:
        """
        Executa chat completion com o provedor ativo.
        
        Este é o método base que todos os outros utilizam.
        
        Args:
            messages: Lista de mensagens [{"role": "...", "content": "..."}]
            temperature: Criatividade (0-1)
            max_tokens: Máximo de tokens na resposta
            interaction_type: Tipo para logging
            match_id: ID do match associado
            
        Returns:
            AIResponse com resultado
        """
        start_time = time.time()
        enriched_messages = messages  # fallback para log de erro
        
        try:
            # Injetar contexto pessoal nas mensagens
            enriched_messages = self._inject_personal_context(messages)
            
            # Log do request bruto ANTES do envio
            active_provider = self.manager.get_active_provider()
            provider_id = active_provider.PROVIDER_ID if active_provider else 'unknown'
            model_name = active_provider.current_model if active_provider else 'unknown'
            log_ai_raw_request(
                interaction_type=interaction_type,
                messages=enriched_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                provider=provider_id,
                model=model_name
            )
            
            response = self.manager.chat_completion(
                messages=enriched_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                interaction_type=interaction_type,
                **kwargs
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            # Log da response bruta APÓS recebimento
            log_ai_raw_response(
                interaction_type=interaction_type,
                response_content=response.content,
                provider=response.provider,
                model=response.model,
                tokens=response.total_tokens,
                cost=response.cost_estimate,
                response_time_ms=elapsed_ms
            )
            
            # Log da interação
            self._log_interaction(
                interaction_type=interaction_type,
                response=response,
                match_id=match_id,
                success=True
            )
            
            logger.debug(
                f"[AI] {response.provider}/{response.model} - "
                f"{response.total_tokens} tokens, "
                f"${response.cost_estimate:.6f}, "
                f"{elapsed_ms}ms"
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Erro na chamada de IA ({interaction_type}): {e}")
            log_ai_raw_error(
                interaction_type=interaction_type,
                error=str(e),
                messages=enriched_messages
            )
            self._log_interaction(
                interaction_type=interaction_type,
                response=None,
                match_id=match_id,
                success=False,
                error_message=str(e)
            )
            raise
    
    def _log_interaction(
        self,
        interaction_type: str,
        response: AIResponse = None,
        match_id: int = None,
        success: bool = True,
        error_message: str = None
    ):
        """Loga interação no banco de dados."""
        try:
            from database import get_db_manager, AIInteractionRepository
            
            db = get_db_manager()
            with db.get_session() as session:
                repo = AIInteractionRepository(session)
                
                interaction = repo.create(
                    interaction_type=interaction_type,
                    model_used=response.model if response else None,
                    match_id=match_id,
                    provider=response.provider if response else 'unknown'
                )
                
                if success and response:
                    repo.complete(
                        interaction,
                        response_content=response.content[:1000] if response.content else None,
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        response_time_ms=response.response_time_ms
                    )
                    interaction.estimated_cost = response.cost_estimate
                else:
                    repo.fail(interaction, error_message or "Unknown error")
                    
        except Exception as e:
            logger.warning(f"Erro ao logar interação: {e}")
    
    # ==================== MÉTODOS DE ALTO NÍVEL ====================
    
    def generate_message(
        self,
        match_profile: dict,
        conversation_history: list = None,
        last_message: str = None,
        ab_variants: dict = None,
        match_id: int = None
    ) -> dict:
        """
        Gera mensagem para um match (primeira ou resposta).
        
        Método unificado que decide automaticamente se é primeira
        mensagem ou resposta baseado no histórico.
        
        Args:
            match_profile: Dados do perfil do match
            conversation_history: Histórico de mensagens (opcional)
            last_message: Última mensagem recebida (opcional)
            ab_variants: Variantes do teste A/B
            match_id: ID do match para logging
            
        Returns:
            Dict com mensagem e metadata
        """
        # Se tem histórico, é resposta; senão, primeira mensagem
        if conversation_history and len(conversation_history) > 0:
            return self._generate_response(
                match_profile=match_profile,
                conversation_history=conversation_history,
                last_message=last_message or conversation_history[-1].get('content', ''),
                ab_variants=ab_variants,
                match_id=match_id
            )
        else:
            return self._generate_first_message(
                match_profile=match_profile,
                ab_variants=ab_variants,
                match_id=match_id
            )
    
    def _generate_first_message(
        self,
        match_profile: dict,
        ab_variants: dict = None,
        match_id: int = None
    ) -> dict:
        """Gera primeira mensagem personalizada."""
        match_name = match_profile.get('name', 'match')
        logger.info(f"Gerando primeira mensagem para {match_name}...")
        
        # Perfil vazio = mensagem genérica
        if not match_profile.get('bio') and not match_profile.get('interests'):
            logger.info(f"Perfil de {match_name} vazio, usando mensagem genérica")
            generic_msg = self._get_generic_message()
            
            log_ai_decision(
                decision_type="first_message",
                context={"match_name": match_name, "profile_empty": True},
                decision=generic_msg,
                reasoning="Perfil vazio - mensagem genérica"
            )
            
            return {
                "message": generic_msg,
                "reasoning": "Perfil vazio - mensagem genérica",
                "conversation_starters": [],
                "profile_empty": True,
                "_metadata": {'provider': 'fallback', 'model': 'generic'}
            }
        
        # Construir prompt
        ab_instructions = self._build_ab_instructions(ab_variants)
        
        # Extrair interesses em comum do match_profile (se existirem)
        common_interests = match_profile.get("common_interests", [])
        common_interests_str = ", ".join(common_interests) if common_interests else "Nenhum identificado"
        
        try:
            prompt_template = self._load_prompt("first_message")
            prompt = prompt_template.format(
                match_profile=match_profile,
                common_interests=common_interests_str,
                ab_instructions=ab_instructions
            )
        except Exception as e:
            logger.warning(f"Erro ao carregar prompt: {e}, usando fallback")
            prompt = f"""Gere uma primeira mensagem de abertura para um match do Tinder.

Perfil do match: {match_profile}
Interesses em comum: {common_interests_str}
{ab_instructions}

Responda em JSON com: message, reasoning, conversation_starters (array)"""
        
        try:
            system_prompt = self._load_system_prompt("first_message")
        except:
            system_prompt = "Você é um assistente especializado em conversas de dating apps. Seja natural e brasileiro."
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self.chat(
                messages=messages,
                temperature=0.8,
                max_tokens=self.settings.ai_max_tokens_first_message,
                interaction_type='first_message',
                match_id=match_id
            )
            
            result = extract_json_from_text(response.content)
            
            # Validar resultado
            if not result or not isinstance(result, dict):
                result = {}
            
            message = result.get("message", "")
            if not message or len(str(message).strip()) < 5:
                logger.warning(f"Mensagem inválida, usando fallback")
                result["message"] = self._get_generic_message()
            
            result.setdefault("reasoning", "Mensagem gerada pela IA")
            result.setdefault("conversation_starters", [])
            
            log_ai_decision(
                decision_type="first_message",
                context={
                    "match_name": match_name,
                    "has_bio": bool(match_profile.get("bio")),
                    "interests_count": len(match_profile.get("interests", []))
                },
                decision=result.get("message", "")[:100],
                reasoning=result.get("reasoning", "")
            )
            
            result["_metadata"] = {
                'provider': response.provider,
                'model': response.model,
                'tokens': response.total_tokens,
                'cost': response.cost_estimate
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Erro ao gerar primeira mensagem: {e}")
            fallback = self._get_generic_message()
            return {
                "message": fallback,
                "reasoning": f"Erro na IA: {str(e)}",
                "conversation_starters": [],
                "_metadata": {'provider': 'fallback', 'model': 'generic', 'error': str(e)}
            }
    
    def _generate_response(
        self,
        match_profile: dict,
        conversation_history: list,
        last_message: str,
        ab_variants: dict = None,
        match_id: int = None
    ) -> dict:
        """Gera resposta para conversa existente."""
        match_name = match_profile.get('name', 'match')
        logger.debug(f"Gerando resposta para {match_name}...")
        
        formatted_history = self._format_conversation_history(conversation_history, match_name)
        ab_instructions = self._build_ab_instructions(ab_variants)
        
        try:
            prompt_template = self._load_prompt("conversation_response")
            prompt = prompt_template.format(
                match_profile=match_profile,
                conversation_history=formatted_history,
                last_message=last_message,
                ab_instructions=ab_instructions
            )
        except Exception as e:
            logger.warning(f"Erro ao carregar prompt: {e}, usando fallback")
            prompt = f"""Analise esta conversa e gere uma resposta.

Perfil do match: {match_profile}
Histórico: {formatted_history}
Última mensagem: {last_message}
{ab_instructions}

Responda em JSON com: suggested_response, temperature_score (1-10), temperature_label, next_step_recommendation"""
        
        try:
            system_prompt = self._load_system_prompt("conversation_response")
        except:
            system_prompt = "Você é um assistente de conversas em dating apps. Analise o contexto e sugira respostas naturais."
        
        # Construir mensagens com histórico como roles nativos da API
        # Isso preserva o contexto conversacional melhor do que texto plano
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        
        # Injetar cada mensagem do histórico como user/assistant
        # user = mensagens DELA (match), assistant = mensagens MINHAS
        if conversation_history:
            for msg in conversation_history:
                content = msg.get("content", "").strip()
                if not content:
                    continue
                if msg.get("is_from_me"):
                    messages.append({"role": "assistant", "content": content})
                else:
                    messages.append({"role": "user", "content": f"[{match_name}]: {content}"})
        
        # Prompt final com instruções de análise e formato de saída
        messages.append({"role": "user", "content": prompt})
        
        response = self.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=self.settings.ai_max_tokens_conversation,
            interaction_type='conversation_response',
            match_id=match_id
        )
        
        result = extract_json_from_text(response.content)
        if not result:
            result = {}
        
        # Validações com fallbacks
        if not isinstance(result.get("temperature_score"), (int, float)):
            result["temperature_score"] = 5
        
        if not result.get("temperature_label"):
            result["temperature_label"] = "warm"
        
        if not result.get("next_step_recommendation"):
            result["next_step_recommendation"] = "continuar"
        
        suggested = result.get("suggested_response", "")
        if not suggested or len(str(suggested).strip()) < 3:
            result["suggested_response"] = "legal! e vc?"
        
        log_ai_decision(
            decision_type="conversation_response",
            context={
                "match_name": match_name,
                "temperature": result.get("temperature_label"),
                "next_step": result.get("next_step_recommendation")
            },
            decision=result.get("suggested_response", "")[:100],
            reasoning=result.get("context_analysis")
        )
        
        result["_metadata"] = {
            'provider': response.provider,
            'model': response.model,
            'tokens': response.total_tokens,
            'cost': response.cost_estimate
        }
        
        return result
    
    def analyze_profile(self, match_profile: dict) -> dict:
        """Analisa perfil do match."""
        logger.debug(f"Analisando perfil de {match_profile.get('name', 'match')}...")
        
        try:
            prompt_template = self._load_prompt("profile_analysis")
            prompt = prompt_template.format(
                profile_data=match_profile
            )
            system_prompt = self._load_system_prompt("profile_analysis")
        except:
            prompt = f"Analise este perfil: {match_profile}"
            system_prompt = "Você analisa perfis de dating apps."
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        response = self.chat(
            messages=messages,
            temperature=0.5,
            interaction_type='profile_analysis'
        )
        
        result = extract_json_from_text(response.content) or {}
        result["_metadata"] = {
            'provider': response.provider,
            'model': response.model
        }
        return result
    
    def generate_analytics_insights(self, analytics_data: dict) -> dict:
        """Gera insights a partir de dados analíticos."""
        logger.debug("Gerando insights analíticos...")
        
        try:
            prompt_template = self._load_prompt("analytics_insights")
            prompt = prompt_template.format(analytics_data=analytics_data)
            system_prompt = self._load_system_prompt("analytics_insights")
        except:
            prompt = f"Analise estes dados e gere insights: {analytics_data}"
            system_prompt = "Você é um analista de dados de dating apps."
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        response = self.chat(
            messages=messages,
            temperature=0.5,
            interaction_type='analytics_insights'
        )
        
        result = extract_json_from_text(response.content) or {}
        result["_metadata"] = {
            'provider': response.provider,
            'model': response.model
        }
        return result
    
    def generate_match_report(
        self,
        match_profile: dict,
        conversation_history: List[dict],
        **kwargs
    ) -> dict:
        """Gera relatório completo de um match."""
        logger.debug(f"Gerando relatório para {match_profile.get('name', 'match')}...")
        
        conversation_text = "\n".join([
            f"{'Eu' if msg.get('is_from_me') else match_profile.get('name', 'Match')}: {msg.get('content', '')}"
            for msg in conversation_history[-20:]
        ]) if conversation_history else "Nenhuma mensagem ainda"
        
        prompt = f"""Analise este match e gere um relatório detalhado em JSON.

**PERFIL:**
- Nome: {match_profile.get('name', 'N/A')}
- Idade: {match_profile.get('age', 'N/A')}
- Bio: {match_profile.get('bio', 'Sem bio')}
- Trabalho: {match_profile.get('job_title', 'N/A')}
- Interesses: {', '.join(match_profile.get('interests', [])) if match_profile.get('interests') else 'Nenhum'}

**CONVERSA ({len(conversation_history)} msgs):**
{conversation_text}

**Retorne JSON com:**
- conversation_summary: resumo
- topic_suggestions: [{{"topic": "", "reason": "", "example": ""}}]
- next_message_suggestions: ["msg1", "msg2"]
- temperature_score: 1-10
- engagement_score: 1-10
- recommended_actions: ["acao1"]
- warnings: ["alerta"] ou []
"""
        
        try:
            system_prompt = self._load_system_prompt("match_report")
        except:
            system_prompt = "Você é um analista de conversas em dating apps. Use tom brasileiro casual."
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        response = self.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=self.settings.ai_max_tokens_report,
            interaction_type='match_report'
        )
        
        result = extract_json_from_text(response.content)
        
        if not isinstance(result, dict):
            result = {
                "conversation_summary": "Erro ao processar",
                "topic_suggestions": [],
                "next_message_suggestions": [],
                "temperature_score": 5.0,
                "engagement_score": 5.0,
                "recommended_actions": [],
                "warnings": ["Erro ao gerar relatório"]
            }
        
        result["_metadata"] = {
            'provider': response.provider,
            'model': response.model
        }
        return result
    
    # ==================== ALIASES PARA COMPATIBILIDADE ====================
    
    def generate_first_message(
        self,
        match_profile: dict,
        ab_variants: dict = None,
        **kwargs
    ) -> dict:
        """
        Alias para _generate_first_message.
        Mantido para compatibilidade com código legado.
        """
        return self._generate_first_message(
            match_profile=match_profile,
            ab_variants=ab_variants
        )
    
    def analyze_conversation_and_respond(
        self,
        match_profile: dict,
        conversation_history: list,
        last_message: str,
        ab_variants: dict = None,
        **kwargs
    ) -> dict:
        """
        Alias para _generate_response.
        Mantido para compatibilidade com código legado.
        """
        return self._generate_response(
            match_profile=match_profile,
            conversation_history=conversation_history,
            last_message=last_message,
            ab_variants=ab_variants
        )


# ==================== SINGLETON E HELPERS ====================

_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    """Retorna instância singleton do serviço de IA."""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service


# Alias para compatibilidade com código legado
def get_openai_client() -> AIService:
    """
    DEPRECATED: Use get_ai_service().
    Mantido para compatibilidade.
    """
    return get_ai_service()


def ai_chat(
    messages: List[Dict[str, str]],
    interaction_type: str = 'chat',
    temperature: float = 0.7,
    max_tokens: int = 500,
    match_id: int = None,
    **kwargs
) -> AIResponse:
    """
    Helper function para chamada rápida de IA.
    
    Exemplo:
        response = ai_chat([{"role": "user", "content": "Olá"}])
        print(response.content)
    """
    return get_ai_service().chat(
        messages=messages,
        interaction_type=interaction_type,
        temperature=temperature,
        max_tokens=max_tokens,
        match_id=match_id,
        **kwargs
    )
