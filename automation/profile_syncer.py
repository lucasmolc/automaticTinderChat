"""
ProfileSyncer - Classe centralizada para sincronização de perfis e matches.
Refatoração do sync_matches_only() do orchestrator.py para código mais limpo e manutenível.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from config import TINDER_MATCHES_URL
from database import (
    Match,
    MatchRepository,
    Message,
    MessageRepository,
    MyProfileRepository,
    get_db_manager,
)
from utils.helpers import clean_message_preview
from utils.logger import (
    console_error,
    console_matches_loaded,
    console_processing_match,
    console_sync_complete,
    console_sync_start,
    console_warning,
    get_logger,
    log_file_only,
)

from .browser import BrowserController
from .data_validation_service import DataValidationService
from .extractors import TinderDataExtractor
from .match_helpers import extract_complete_profile, get_profile_cache

# Importar funções compartilhadas para evitar duplicação
from .tinder_scraping import navigate_to_match_chat, navigate_to_matches_page

logger = get_logger(__name__)


class ProfileSyncer:
    """
    Sincronizador centralizado de perfis, matches e mensagens.
    
    Responsabilidades:
    - Sincronizar meu perfil
    - Sincronizar lista de matches (abas Matches + Mensagens)
    - Extrair dados completos de matches novos
    - Sincronizar mensagens de cada chat
    - Otimizar navegações evitando reloads desnecessários
    """
    
    def __init__(self, browser: BrowserController, extractor: TinderDataExtractor):
        self.browser = browser
        self.extractor = extractor
        self.db = get_db_manager()
        self._profile_cache = get_profile_cache()
        
        # Estatísticas da sincronização
        self.stats = {
            "new_matches": 0,
            "updated_matches": 0,
            "messages_synced": 0,
            "old_matches_deleted": 0,
            "ignored_no_name": 0,
            "doubledates_ignored": 0,
            "errors": 0
        }
        
        # Controle de URL atual para evitar navegações desnecessárias
        self._current_url: Optional[str] = None
    
    async def _get_current_url(self) -> str:
        """Retorna a URL atual do navegador."""
        return self.browser.page.url
    
    async def _is_on_page(self, expected_url_part: str) -> bool:
        """Verifica se já está na página esperada."""
        current = await self._get_current_url()
        return expected_url_part in current
    
    async def _navigate_to_match_chat(self, match_id: str) -> None:
        """
        Navega para o chat de um match, evitando reload se já estiver lá.
        Usa função centralizada de shared_extractors.
        """
        await navigate_to_match_chat(self.browser.page, match_id)
        await asyncio.sleep(1)
    
    async def _navigate_to_matches_if_needed(self) -> None:
        """
        Navega para a página de matches apenas se não estiver lá.
        Usa função centralizada de shared_extractors.
        """
        await navigate_to_matches_page(self.browser.page, TINDER_MATCHES_URL)
        await asyncio.sleep(2)
    
    async def sync_my_profile(self) -> Optional[Dict]:
        """
        Sincroniza meu perfil do Tinder para o banco de dados.
        
        Returns:
            Dict com dados do perfil ou None se falhar
        """
        log_file_only("Sincronizando meu perfil...")
        
        try:
            # Extrair dados do perfil
            profile_data = await self.extractor.extract_my_profile()
            
            # Salvar no banco
            with self.db.get_session() as session:
                repo = MyProfileRepository(session)
                profile = repo.get_or_create()
                
                # Montar dados para atualização
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
                
                result = {
                    "id": profile.id,
                    "name": profile.name,
                    "age": profile.age,
                    "bio": profile.bio,
                    "photos_count": len(profile_data.get("photos", [])),
                    "interests": [i.interest_name for i in profile.interests] if profile.interests else []
                }
                
                # Salvar no cache singleton
                self._profile_cache.set("my_profile", result)
                
                log_file_only("Perfil sincronizado", result)
                return result
                
        except Exception as e:
            console_warning(f"Não foi possível sincronizar perfil: {e}")
            self.stats["errors"] += 1
            return None
    
    def _cleanup_old_matches(self, days: int = 365) -> int:
        """
        Remove matches antigos do banco de dados.
        
        Args:
            days: Número de dias para considerar como antigo
            
        Returns:
            Número de matches excluídos
        """
        with self.db.get_session() as session:
            match_repo = MatchRepository(session)
            # DESABILITADO: Não excluir mais matches antigos
            # deleted = match_repo.delete_old_matches(days=days)
            deleted = 0
            logger.debug("Exclusão de matches antigos desabilitada")
            if deleted > 0:
                log_file_only(f"Excluídos {deleted} matches com mais de {days} dias")
            return deleted
    
    async def _extract_all_matches_from_ui(self) -> List[Dict]:
        """
        Extrai todos os matches das abas Matches e Mensagens.
        
        Returns:
            Lista combinada de matches (sem duplicatas)
        """
        # Garantir que está na página de matches
        await self._navigate_to_matches_if_needed()
        
        # Extrair da aba Matches (matches novos sem mensagem)
        matches_data = await self.extractor.extract_matches_list()
        
        # Extrair da aba Mensagens (conversas existentes)
        conversations_data = await self.extractor.extract_messages_list()
        
        # Combinar os dois, evitando duplicatas
        all_matches = []
        seen_ids: Set[str] = set()
        
        # Primeiro adicionar matches novos
        for m in matches_data:
            tid = m.get("tinder_match_id")
            if tid and tid not in seen_ids:
                all_matches.append(m)
                seen_ids.add(tid)
        
        # Depois adicionar conversas (se não estiverem já)
        for c in conversations_data:
            tid = c.get("tinder_match_id")
            if tid and tid not in seen_ids:
                all_matches.append(c)
                seen_ids.add(tid)
            elif tid in seen_ids:
                # Atualizar has_messages se já existe
                for m in all_matches:
                    if m.get("tinder_match_id") == tid:
                        m["has_messages"] = True
                        if c.get("last_message_preview"):
                            m["last_message_preview"] = c.get("last_message_preview")
                        break
        
        log_file_only(f"Total combinado: {len(all_matches)} matches/conversas")
        return all_matches
    
    def _persist_matches_to_db(self, matches_data: List[Dict]) -> List[Dict]:
        """
        Persiste os matches no banco de dados.
        
        Usa DataValidationService para validar todos os campos antes de salvar.
        
        Args:
            matches_data: Lista de dados de matches extraídos
            
        Returns:
            Lista de matches sincronizados com IDs do banco
        """
        synced_matches = []
        validator = DataValidationService()
        
        with self.db.get_session() as session:
            match_repo = MatchRepository(session)
            
            for match_data in matches_data:
                match_id = match_data.get("tinder_match_id")
                if not match_id:
                    continue
                
                # VALIDAÇÃO CENTRALIZADA - todos os campos
                validated_data, warnings = validator.validate_match_data(match_data)
                
                # Log warnings
                for warning in warnings:
                    logger.debug(f"Validação match {match_id[:12]}...: {warning}")
                
                match_name = validated_data.get("name", "Unknown")
                
                if match_name == "Unknown":
                    self.stats["ignored_no_name"] += 1
                
                # Contar DoubleDates
                if match_data.get("is_doubledate"):
                    self.stats["doubledates_ignored"] += 1
                
                # Buscar ou criar match
                match, created = match_repo.get_or_create(match_id, name=match_name)
                
                if created:
                    self.stats["new_matches"] += 1
                else:
                    self.stats["updated_matches"] += 1
                
                # Montar dados para atualização usando dados validados
                update_data = {}
                
                # Só atualiza nome se o novo é válido E melhor que o atual
                if match_name != "Unknown":
                    update_data["name"] = match_name
                elif not match.name or match.name == "Unknown":
                    update_data["name"] = match_name
                
                # Idade validada
                if validated_data.get("age"):
                    update_data["age"] = validated_data.get("age")
                
                # Bio validada
                if validated_data.get("bio"):
                    update_data["bio"] = validated_data.get("bio")
                
                # Foto de perfil - evitar duplicação
                photo_url = validated_data.get("profile_photo_url")
                if photo_url and not match.profile_photo_url:
                    duplicate = match_repo.find_by_profile_photo(photo_url, exclude_match_id=match.id)
                    if not duplicate:
                        update_data["profile_photo_url"] = photo_url
                
                if match_data.get("last_message_preview"):
                    update_data["last_message_text"] = match_data.get("last_message_preview")
                    update_data["has_messages"] = True
                
                if match_data.get("has_messages"):
                    update_data["has_messages"] = True
                
                if match_data.get("matched_at"):
                    update_data["matched_at"] = match_data.get("matched_at")
                
                # Campos adicionais validados
                for field in ["job_title", "school", "distance_km", "city", 
                              "relationship_intent", "is_verified"]:
                    if validated_data.get(field):
                        update_data[field] = validated_data[field]
                
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
                    "has_messages": match_data.get("has_messages", False),
                    "data_complete": validator.is_data_complete_for_ai(validated_data)
                })
        
        return synced_matches
    
    async def _extract_full_profile_for_new_matches(self, synced_matches: List[Dict]) -> None:
        """
        Extrai dados completos dos matches novos (sem mensagem).
        
        Args:
            synced_matches: Lista de matches sincronizados
        """
        # Filtrar matches sem mensagens
        new_matches = [
            m for m in synced_matches 
            if not m.get("has_messages") and m.get("tinder_match_id")
        ]
        
        if not new_matches:
            return
        
        console_matches_loaded(len(new_matches), "para extração de dados completos")
        
        for match_info in new_matches:
            try:
                tinder_id = match_info.get("tinder_match_id")
                match_name = match_info.get("name", "Unknown")
                
                console_processing_match(match_name, "extraindo dados")
                
                # Navegar para o chat (otimizado para evitar reload)
                await self._navigate_to_match_chat(tinder_id)
                
                # Aguardar carregamento
                try:
                    await self.browser.page.wait_for_selector('h1', timeout=10000)
                except:
                    pass
                
                await asyncio.sleep(2)
                
                # Extrair perfil completo
                fetched_profile = await extract_complete_profile(self.extractor, tinder_id)
                
                # Atualizar no banco
                with self.db.get_session() as session:
                    match_repo = MatchRepository(session)
                    match = session.query(Match).filter(
                        Match.tinder_match_id == tinder_id
                    ).first()
                    
                    if match:
                        updated_fields = match_repo.update_from_profile(match, fetched_profile)
                        if updated_fields:
                            log_file_only(f"Dados atualizados para {match_name}: {list(updated_fields.keys())}")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                console_error(f"Erro ao extrair dados de {match_info.get('name', 'unknown')}: {e}")
                self.stats["errors"] += 1
    
    def _get_chats_to_sync(self, synced_matches: List[Dict]) -> List[Dict]:
        """
        Obtém lista de chats que precisam ter mensagens sincronizadas.
        
        Args:
            synced_matches: Lista de matches sincronizados
            
        Returns:
            Lista de chats para sincronizar
        """
        chats_with_messages = []
        
        with self.db.get_session() as session:
            from sqlalchemy import or_
            
            # Matches do banco com mensagens (excluindo bloqueados/finalizados)
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
        
        # Adicionar matches recém-sincronizados que têm mensagens
        seen_ids = {c["tinder_match_id"] for c in chats_with_messages}
        for synced in synced_matches:
            if synced.get("has_messages") and synced.get("tinder_match_id") not in seen_ids:
                chats_with_messages.append({
                    "id": synced.get("id"),
                    "tinder_match_id": synced.get("tinder_match_id"),
                    "name": synced.get("name")
                })
                seen_ids.add(synced.get("tinder_match_id"))
        
        return chats_with_messages
    
    async def _sync_chat_messages(self, chats: List[Dict]) -> None:
        """
        Sincroniza mensagens de todos os chats.
        
        Args:
            chats: Lista de chats para sincronizar
        """
        log_file_only(f"Sincronizando mensagens de {len(chats)} chats...")
        
        for chat in chats:
            try:
                tinder_id = chat.get("tinder_match_id")
                if not tinder_id:
                    continue
                
                chat_name = chat.get("name", tinder_id)
                console_processing_match(chat_name, "sincronizando mensagens")
                
                # Navegar para o chat (otimizado)
                await self._navigate_to_match_chat(tinder_id)
                
                # A função extract_conversation já espera estar na página correta
                # Vamos pular a navegação interna dela passando flag
                conversation = await self._extract_conversation_no_nav(tinder_id, max_messages=500)
                
                # Extrair perfil completo (já estamos na página)
                fetched_profile = await extract_complete_profile(self.extractor, tinder_id)
                
                # Persistir no banco
                with self.db.get_session() as session:
                    match_repo = MatchRepository(session)
                    msg_repo = MessageRepository(session)
                    
                    match = session.query(Match).filter(
                        Match.tinder_match_id == tinder_id
                    ).first()
                    
                    if not match:
                        final_name = fetched_profile.get('name') or chat.get('name') or 'Unknown'
                        match, _ = match_repo.get_or_create(tinder_id, name=final_name)
                        self.stats["new_matches"] += 1
                    
                    if match:
                        # Atualizar dados do perfil
                        match_repo.update_from_profile(match, fetched_profile)
                        
                        if conversation:
                            # Deletar mensagens existentes e adicionar novas
                            session.query(Message).filter(Message.match_id == match.id).delete()
                            session.flush()
                            
                            for msg in conversation:
                                msg_repo.create(
                                    match_id=match.id,
                                    content=msg["content"],
                                    is_from_me=msg["is_from_me"]
                                )
                                self.stats["messages_synced"] += 1
                            
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
                
                await asyncio.sleep(1)
                
            except Exception as e:
                console_error(f"Erro ao sincronizar mensagens de {chat.get('name', 'unknown')}: {e}")
                self.stats["errors"] += 1
    
    async def _extract_conversation_no_nav(self, match_id: str, max_messages: int = 50) -> List[Dict]:
        """
        Extrai conversa SEM fazer navegação (assume que já está na página correta).
        
        Args:
            match_id: ID do match
            max_messages: Máximo de mensagens a extrair
            
        Returns:
            Lista de mensagens
        """
        # Verificar se está na página correta
        if not await self._is_on_page(f"/messages/{match_id}"):
            # Se não estiver, navegar
            await self._navigate_to_match_chat(match_id)
        
        # Aguardar carregamento
        await asyncio.sleep(1)
        
        # Fazer scroll para carregar mensagens antigas
        for _ in range(5):
            await self.browser.page.evaluate('''
                () => {
                    const containers = document.querySelectorAll('div[class*="Ov(a)"], div[class*="chat"], div[class*="message"]');
                    for (const container of containers) {
                        if (container.scrollHeight > container.clientHeight) {
                            container.scrollTop = 0;
                        }
                    }
                    window.scrollTo(0, 0);
                }
            ''')
            await asyncio.sleep(0.3)
        
        await asyncio.sleep(1)
        
        # Usar o método de extração existente (que agora não vai navegar de novo)
        return await self.extractor._extract_messages_from_page(max_messages)
    
    async def sync_all(self) -> Dict:
        """
        Executa sincronização completa.
        
        Returns:
            Dict com resultado da sincronização
        """
        console_sync_start("completa")
        
        # Reset stats
        self.stats = {
            "new_matches": 0,
            "updated_matches": 0,
            "messages_synced": 0,
            "old_matches_deleted": 0,
            "ignored_no_name": 0,
            "doubledates_ignored": 0,
            "errors": 0
        }
        
        # 1. Sincronizar meu perfil
        my_profile_data = await self.sync_my_profile()
        
        # Voltar para matches se saiu da página
        await self._navigate_to_matches_if_needed()
        
        # 2. Limpar matches antigos
        self.stats["old_matches_deleted"] = self._cleanup_old_matches(days=365)
        
        # 3. Extrair todos os matches da UI
        all_matches_data = await self._extract_all_matches_from_ui()
        
        # 4. Persistir no banco
        synced_matches = self._persist_matches_to_db(all_matches_data)
        
        # 5. Extrair dados completos dos matches novos
        await self._extract_full_profile_for_new_matches(synced_matches)
        
        # 6. Sincronizar mensagens de cada chat
        chats_to_sync = self._get_chats_to_sync(synced_matches)
        await self._sync_chat_messages(chats_to_sync)
        
        # 7. Log final
        console_sync_complete(
            len(synced_matches),
            self.stats["new_matches"],
            self.stats["messages_synced"]
        )
        
        log_file_only(
            f"Sincronização COMPLETA concluída: total={len(synced_matches)}, novos={self.stats['new_matches']}, "
            f"atualizados={self.stats['updated_matches']}, msgs={self.stats['messages_synced']}, "
            f"antigos_excluidos={self.stats['old_matches_deleted']}, erros={self.stats['errors']}"
        )
        
        return {
            "success": True,
            "my_profile": my_profile_data,
            "total_matches": len(synced_matches),
            "new_matches": self.stats["new_matches"],
            "updated_matches": self.stats["updated_matches"],
            "ignored_no_name": self.stats["ignored_no_name"],
            "doubledates_ignored": self.stats["doubledates_ignored"],
            "messages_synced": self.stats["messages_synced"],
            "old_matches_deleted": self.stats["old_matches_deleted"],
            "matches": synced_matches
        }

    async def detect_unmatches(self) -> List[int]:
        """
        Detecta matches que fizeram unmatch.
        
        Compara matches ativos no banco com matches disponíveis no Tinder.
        Os que não existem mais no Tinder são marcados como unmatch.
        
        Returns:
            Lista de IDs de matches que deram unmatch
        """
        unmatched_ids = []
        
        try:
            # Garantir que está na página de matches
            await self._navigate_to_matches_if_needed()
            
            # Buscar matches ativos do Tinder
            tinder_matches = await self.extractor.extract_matches_list()
            tinder_ids = {m.get("tinder_match_id") for m in tinder_matches if m.get("tinder_match_id")}
            
            with self.db.get_session() as session:
                match_repo = MatchRepository(session)
                
                # Buscar matches ativos no banco
                active_matches = match_repo.get_active_matches()
                
                for match in active_matches:
                    if match.tinder_match_id and match.tinder_match_id not in tinder_ids:
                        # Match não está mais no Tinder - unmatch
                        match_repo.mark_as_unmatched(match)
                        unmatched_ids.append(match.id)
                        self.stats["errors"] += 0  # Contamos separadamente
                        console_warning(f"Unmatch detectado: {match.name}")
            
            if unmatched_ids:
                log_file_only(f"Total de unmatches detectados: {len(unmatched_ids)}")
                
        except Exception as e:
            logger.error(f"Erro ao detectar unmatches: {e}")
            self.stats["errors"] += 1
        
        return unmatched_ids

