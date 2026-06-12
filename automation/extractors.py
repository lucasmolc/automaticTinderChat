"""
Extratores de dados do Tinder.
Parsers para perfis, matches e mensagens.
"""

import re
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import Page

from config import get_settings, TINDER_MATCHES_URL
from utils.logger import get_logger, log_automation_step
from utils.helpers import async_random_delay, sanitize_text, clean_message_preview, parse_name_and_age, normalize_message_content, clean_city

# Importar funções compartilhadas para evitar duplicação de código
from .tinder_scraping import (
    EXTRACT_PHOTOS_JS,
    EXTRACT_BIO_JS,
    EXTRACT_MATCHES_LIST_JS,
    extract_photos_from_page,
    extract_bio_from_page,
    extract_matches_list_from_page,
    extract_date_from_text,
    filter_valid_photos,
    validate_match_id,
    navigate_to_match_chat
)

logger = get_logger(__name__)


class TinderDataExtractor:
    """Extrai dados do Tinder via scraping."""
    
    def __init__(self, page: Page):
        self.page = page
        self.settings = get_settings()
    
    def _validate_match_id(self, match_id: str) -> bool:
        """
        Valida que o match_id é seguro para uso em URLs.
        Usa função centralizada de shared_extractors.
        """
        return validate_match_id(match_id)
    
    async def _navigate_to_match_if_needed(self, match_id: str) -> None:
        """
        Navega para o chat de um match, evitando reload se já estiver lá.
        Usa função centralizada de shared_extractors.
        """
        await navigate_to_match_chat(self.page, match_id)

    async def extract_my_profile(self) -> Dict:
        """
        Extrai dados do meu perfil.
        
        Returns:
            Dict com informações do perfil
        """
        log_automation_step("Extraindo dados do meu perfil...")
        
        profile_data = {
            "name": None,
            "age": None,
            "bio": None,
            "job_title": None,
            "company": None,
            "school": None,
            "location": None,
            "photos": [],
            "interests": [],
            "extracted_at": datetime.utcnow().isoformat()
        }
        
        try:
            # Navegar para página de edição de perfil
            await self.page.click('a[href*="/app/profile"]')
            await self.page.wait_for_load_state("networkidle")
            await async_random_delay(0.5, 1)
            
            # Aguardar a página carregar completamente
            await self.page.wait_for_timeout(1000)
            
            # Extrair nome e idade
            name_el = await self.page.query_selector('[class*="Typs(display-1-strong)"], h1')
            if name_el:
                raw_text = await name_el.inner_text()
                name, age = parse_name_and_age(raw_text)
                profile_data["name"] = name
                if age:
                    profile_data["age"] = age
            
            # Extrair bio usando função centralizada
            bio_text = await extract_bio_from_page(self.page)
            if bio_text:
                profile_data["bio"] = sanitize_text(bio_text)
                log_automation_step(f"Bio extraída: {bio_text[:50]}...")
            
            # Extrair fotos usando função centralizada
            # As fotos do Tinder estão em divs com classe 'profileCard__slider__img sentry-block'
            photos_data = await extract_photos_from_page(self.page)
            if photos_data:
                profile_data["photos"] = photos_data
                log_automation_step(f"Fotos extraídas: {len(photos_data)}")
            
            # Extrair trabalho/escola
            info_elements = await self.page.query_selector_all(
                '[class*="profileCard__info"] span, '
                '[class*="jobTitle"], [class*="school"]'
            )
            for el in info_elements:
                text = await el.inner_text()
                if "trabalha" in text.lower() or "work" in text.lower():
                    profile_data["job_title"] = sanitize_text(text)
                elif "estuda" in text.lower() or "school" in text.lower():
                    profile_data["school"] = sanitize_text(text)
            
            # Extrair interesses/paixões
            interest_elements = await self.page.query_selector_all(
                '[class*="passions"] span, '
                '[class*="interest"] span, '
                '.Pill__pill span'
            )
            for el in interest_elements:
                interest = sanitize_text(await el.inner_text())
                if interest and interest not in profile_data["interests"]:
                    profile_data["interests"].append(interest)
            
            log_automation_step(
                "Perfil extraído com sucesso",
                {"name": profile_data.get("name"), "photos": len(profile_data["photos"])}
            )
            
        except Exception as e:
            logger.error(f"Erro ao extrair meu perfil: {e}")
        
        return profile_data
    
    async def extract_matches_list(self) -> List[Dict]:
        """
        Extrai lista de matches do painel lateral.
        Inclui tanto matches novos quanto conversas existentes.
        CLICA EM CADA CARD para identificar matches novos de forma confiável.
        EXCLUI DoubleDates da verificação.
        
        Returns:
            Lista de dicts com info básica dos matches
        """
        log_automation_step("Extraindo lista de matches e conversas...")
        matches = []
        seen_ids = set()  # Evitar duplicatas
        
        try:
            # Aguardar carregar a página
            await self.page.wait_for_load_state("networkidle")
            await async_random_delay(0.3, 0.8)
            
            # =====================================================
            # 1. Buscar matches NOVOS (sem mensagens) - CLICANDO EM CADA CARD
            # =====================================================
            log_automation_step("Buscando matches novos...")
            
            # Clicar na aba/seção de matches novos
            try:
                matches_tab = await self.page.query_selector(
                    'button:has-text("Matches"), a:has-text("Matches")'
                )
                if not matches_tab:
                    matches_tab = await self.page.query_selector(
                        'a[href*="/app/matches"], [data-testid*="match-tab"]'
                    )
                
                if matches_tab:
                    await matches_tab.click()
                    await self.page.wait_for_load_state("networkidle")
                    await async_random_delay(0.5, 1)
                    log_automation_step("Clicou na aba Matches")
            except Exception as e:
                logger.debug(f"Não conseguiu clicar na aba matches: {e}")
            
            # Aguardar um pouco mais para os cards carregarem
            await async_random_delay(0.5, 1)
            
            # Fazer scroll na área de matches novos para carregar todos
            try:
                await self.page.evaluate('''
                    () => {
                        const selectors = [
                            'div[class*="Ov(a)"]',
                            'div[class*="matchList"]',
                            'div[class*="Scroll"]',
                            'main div[class*="Ov"]'
                        ];
                        
                        for (const selector of selectors) {
                            try {
                                const containers = document.querySelectorAll(selector);
                                for (const container of containers) {
                                    if (container.scrollWidth > container.clientWidth) {
                                        for (let i = 0; i < 10; i++) {
                                            container.scrollLeft = container.scrollWidth;
                                        }
                                    }
                                }
                            } catch(e) {}
                        }
                    }
                ''')
                await async_random_delay(0.3, 0.8)
            except:
                pass
            
            # =====================================================
            # Extrair todos os cards da aba Matches
            # Excluir: "Likes You" e matches em dupla (nome com "&")
            # =====================================================
            log_automation_step("Extraindo cards de matches...")
            
            # Extrair dados dos cards diretamente
            cards_data = await self.page.evaluate('''
                () => {
                    const cards = [];
                    
                    // Buscar todos os links com classe matchListItem
                    document.querySelectorAll('a.matchListItem').forEach(link => {
                        const href = link.getAttribute('href') || '';
                        
                        // Ignorar "Likes You"
                        if (href.includes('/likes-you')) return;
                        
                        // Extrair nome do span dentro do card
                        const nameEl = link.querySelector('span div div');
                        const name = nameEl ? nameEl.textContent.trim() : '';
                        
                        // Ignorar matches em dupla (nome contém "&" ou " e " entre nomes)
                        if (name.includes('&') || / e /i.test(name)) return;
                        
                        // Extrair ID do match da URL
                        // Formato: /app/messages/ID
                        const idMatch = href.match(/\\/app\\/messages\\/([a-zA-Z0-9]+)/);
                        if (!idMatch) return;
                        
                        const matchId = idMatch[1];
                        
                        // Extrair foto (background-image do div com sentry-block)
                        let photoUrl = null;
                        const photoDiv = link.querySelector('div.sentry-block[style*="background-image"]');
                        if (photoDiv) {
                            const style = photoDiv.getAttribute('style') || '';
                            const urlMatch = style.match(/url\\(["']?([^"'\\)]+)["']?\\)/);
                            if (urlMatch) photoUrl = urlMatch[1];
                        }
                        
                        // Verificar se tem mensagens:
                        // 1. Se o card está na seção de mensagens (lista vertical), tem mensagens
                        // 2. Se o card está na seção de "New Matches" (lista horizontal), não tem
                        // Verificar pela estrutura do elemento e presença de preview de mensagem
                        
                        // Verificar se há preview de mensagem (texto abaixo do nome)
                        const messagePreview = link.querySelector('span[class*="Ell"]');
                        const allSpans = link.querySelectorAll('span');
                        let hasMessagePreview = false;
                        
                        // Se tem mais de 2 spans com texto, provavelmente tem preview de mensagem
                        let textSpans = 0;
                        allSpans.forEach(span => {
                            const text = span.textContent?.trim();
                            if (text && text.length > 0 && !text.includes(name)) {
                                textSpans++;
                            }
                        });
                        
                        // Também verificar se o link está em uma lista vertical (mensagens) vs horizontal (new matches)
                        const parentSection = link.closest('section, div[class*="Scroll"]');
                        const isInMessagesList = parentSection ? 
                            parentSection.scrollHeight > parentSection.scrollWidth : false;
                        
                        const hasMessages = textSpans > 0 || isInMessagesList || (messagePreview && messagePreview.textContent?.trim());
                        
                        cards.push({
                            tinder_match_id: matchId,
                            name: name || 'Unknown',
                            profile_photo_url: photoUrl,
                            href: href,
                            has_messages: hasMessages
                        });
                    });
                    
                    return cards;
                }
            ''')
            
            log_automation_step(f"Encontrados {len(cards_data) if cards_data else 0} cards (excluindo duplas)")
            
            # Adicionar os matches extraídos
            new_matches_count = 0
            if cards_data:
                for card in cards_data:
                    match_id = card.get('tinder_match_id')
                    if match_id and match_id not in seen_ids:
                        has_msgs = card.get('has_messages', False)
                        matches.append({
                            "tinder_match_id": match_id,
                            "name": card.get('name', 'Unknown'),
                            "age": None,
                            "profile_photo_url": card.get('profile_photo_url'),
                            "last_message_preview": None,
                            "has_new_message": False,
                            "has_messages": has_msgs,
                            "is_doubledate": False,
                            "matched_at": None
                        })
                        seen_ids.add(match_id)
                        if not has_msgs:
                            new_matches_count += 1
            
            log_automation_step(f"Total: {len(matches)} matches/conversas (excluindo duplas), {new_matches_count} sem mensagens")
            
        except Exception as e:
            logger.error(f"Erro ao extrair lista de matches: {e}")
        
        return matches
    
    async def extract_messages_list(self) -> List[Dict]:
        """
        Extrai lista de conversas da aba Mensagens.
        Retorna apenas matches que têm conversas/mensagens.
        
        Returns:
            Lista de dicts com info dos matches com mensagens
        """
        log_automation_step("Extraindo lista de conversas (aba Mensagens)...")
        conversations = []
        seen_ids = set()
        
        try:
            # Clicar na aba Mensagens
            try:
                messages_tab = await self.page.query_selector(
                    'button:has-text("Messages"), a:has-text("Messages"), '
                    'button:has-text("Mensagens"), a:has-text("Mensagens")'
                )
                if messages_tab:
                    await messages_tab.click()
                    await self.page.wait_for_load_state("networkidle")
                    await async_random_delay(0.3, 0.8)
                    log_automation_step("Clicou na aba Mensagens")
            except Exception as e:
                logger.debug(f"Não conseguiu clicar na aba mensagens: {e}")
            
            await async_random_delay(0.3, 0.8)
            
            # Scroll para carregar mais conversas
            for _ in range(5):
                await self.page.evaluate('''
                    () => {
                        const containers = document.querySelectorAll('div[class*="messageList"], div[class*="Ov(a)"]');
                        containers.forEach(c => c.scrollTop = c.scrollHeight);
                    }
                ''')
                await async_random_delay(0.2, 0.5)
            # Extrair conversas - buscar links de mensagens
            cards_data = await self.page.evaluate('''
                () => {
                    const cards = [];
                    
                    // Buscar todos os links para mensagens
                    document.querySelectorAll('a[href*="/app/messages/"]').forEach(link => {
                        const href = link.getAttribute('href') || '';
                        
                        // Ignorar "Likes You"
                        if (href.includes('/likes-you')) return;
                        
                        // Extrair ID do match
                        const idMatch = href.match(/\\/app\\/messages\\/([a-zA-Z0-9]+)/);
                        if (!idMatch) return;
                        
                        const matchId = idMatch[1];
                        
                        // Extrair nome
                        const nameEl = link.querySelector('span div div') || link.querySelector('span');
                        let name = nameEl ? nameEl.textContent.trim() : '';
                        
                        // Ignorar matches em dupla
                        if (name.includes('&') || / e /i.test(name)) return;
                        
                        // Extrair foto
                        let photoUrl = null;
                        const photoDiv = link.querySelector('div[style*="background-image"]');
                        if (photoDiv) {
                            const style = photoDiv.getAttribute('style') || '';
                            const urlMatch = style.match(/url\\(["']?([^"'\\)]+)["']?\\)/);
                            if (urlMatch) photoUrl = urlMatch[1];
                        }
                        
                        // Extrair preview da última mensagem
                        let lastMessage = null;
                        const spans = link.querySelectorAll('span');
                        for (const span of spans) {
                            const text = span.textContent?.trim();
                            // Preview geralmente é o texto menor abaixo do nome
                            if (text && text !== name && text.length > 0 && text.length < 100) {
                                lastMessage = text;
                            }
                        }
                        
                        cards.push({
                            tinder_match_id: matchId,
                            name: name || 'Unknown',
                            profile_photo_url: photoUrl,
                            last_message_preview: lastMessage,
                            has_messages: true
                        });
                    });
                    
                    return cards;
                }
            ''')
            
            if cards_data:
                for card in cards_data:
                    match_id = card.get('tinder_match_id')
                    if match_id and match_id not in seen_ids:
                        conversations.append({
                            "tinder_match_id": match_id,
                            "name": card.get('name', 'Unknown'),
                            "age": None,
                            "profile_photo_url": card.get('profile_photo_url'),
                            "last_message_preview": card.get('last_message_preview'),
                            "has_new_message": False,
                            "has_messages": True,
                            "is_doubledate": False,
                            "matched_at": None
                        })
                        seen_ids.add(match_id)
            
            log_automation_step(f"Total: {len(conversations)} conversas encontradas na aba Mensagens")
            
        except Exception as e:
            logger.error(f"Erro ao extrair lista de conversas: {e}")
        
        return conversations

    async def _extract_match_element(self, el) -> Optional[Dict]:
        """
        Extrai dados de um elemento de match/conversa.
        
        Args:
            el: Elemento do Playwright
            
        Returns:
            Dict com dados do match ou None
        """
        try:
            match_data = {
                "tinder_match_id": None,
                "name": None,
                "age": None,
                "profile_photo_url": None,
                "last_message_preview": None,
                "has_new_message": False,
                "has_messages": False,
                "is_doubledate": False,
                "matched_at": None
            }
            
            # Extrair ID do match da URL
            href = await el.get_attribute("href")
            if href:
                # Tentar extrair de /messages/ID ou /matches/ID
                id_match = re.search(r'/(?:messages|matches)/([a-zA-Z0-9]+)', href)
                if id_match:
                    match_data["tinder_match_id"] = id_match.group(1)
                
                # Detectar DoubleDate pela URL
                if "doubledate" in href.lower() or "double-date" in href.lower():
                    match_data["is_doubledate"] = True
            
            if not match_data["tinder_match_id"]:
                return None
            
            # =====================================================
            # Extrair FOTO de perfil
            # =====================================================
            try:
                photo_selectors = [
                    'img[src*="images-ssl.gotinder.com"]',
                    'img[class*="photo"]',
                    'img[class*="Photo"]',
                    'img[class*="avatar"]',
                    'img[class*="Avatar"]',
                    'div[style*="background-image"] ',
                    'img'
                ]
                for selector in photo_selectors:
                    photo_el = await el.query_selector(selector)
                    if photo_el:
                        src = await photo_el.get_attribute("src")
                        if src and ("gotinder.com" in src or "tinder" in src.lower()):
                            match_data["profile_photo_url"] = src
                            break
                        # Tentar background-image
                        style = await photo_el.get_attribute("style")
                        if style and "background-image" in style:
                            url_match = re.search(r'url\(["\']?([^"\']+)["\']?\)', style)
                            if url_match:
                                match_data["profile_photo_url"] = url_match.group(1)
                                break
            except:
                pass
            
            # Tentar extrair foto do elemento pai se não encontrou
            if not match_data["profile_photo_url"]:
                try:
                    parent_html = await el.evaluate('(el) => el.outerHTML')
                    img_match = re.search(r'<img[^>]+src=["\']([^"\']*gotinder\.com[^"\']*)["\']', parent_html)
                    if img_match:
                        match_data["profile_photo_url"] = img_match.group(1)
                except:
                    pass
            
            # =====================================================
            # Detectar DoubleDate APENAS por URL explícita
            # =====================================================
            # Removido: detecção por HTML/classes era muito agressiva
            # DoubleDates serão detectados apenas pelo nome (dois nomes separados)
            
            # =====================================================
            # Extrair NOME e IDADE
            # =====================================================
            name_selectors = [
                '[class*="Typs(display-1-strong)"]',
                '[class*="name"]', 
                '[class*="Name"]',
                'span[class*="Fz"]',
                'div > span'
            ]
            for selector in name_selectors:
                try:
                    name_el = await el.query_selector(selector)
                    if name_el:
                        text = await name_el.inner_text()
                        if text and len(text.strip()) > 0 and len(text.strip()) < 50:
                            full_text = sanitize_text(text)
                            
                            # Extrair nome e idade usando função robusta
                            name, age = parse_name_and_age(full_text)
                            if name:
                                match_data["name"] = name
                            if age:
                                match_data["age"] = age
                            break
                except Exception as e:
                    logger.debug(f"Erro ao extrair nome com seletor: {e}")
                    continue
            
            # =====================================================
            # Detectar DoubleDate pelo nome
            # =====================================================
            if match_data["name"] and not match_data["is_doubledate"]:
                name = match_data["name"]
                
                # Padrões ESPECÍFICOS de DoubleDates - APENAS com símbolos claros
                # NÃO detecta " e " pois muitos nomes brasileiros contêm "e"
                doubledate_patterns = [
                    # "Ana & Maria" - com &
                    r'^[A-Z][a-záàâãéèêíïóôõöúç]+\s*&\s*[A-Z][a-záàâãéèêíïóôõöúç]+',
                    # "Ana + Maria" - com +
                    r'^[A-Z][a-záàâãéèêíïóôõöúç]+\s*\+\s*[A-Z][a-záàâãéèêíïóôõöúç]+',
                ]
                
                for pattern in doubledate_patterns:
                    if re.match(pattern, name):
                        match_data["is_doubledate"] = True
                        if self.settings.ignore_doubledate:
                            logger.debug(f"🚫 Ignorando DoubleDate: {name}")
                            return None
                        break
            
            # Se for DoubleDate e configurado para ignorar, retornar None
            if match_data["is_doubledate"] and self.settings.ignore_doubledate:
                logger.debug(f"🚫 Ignorando DoubleDate: {match_data.get('name', match_data['tinder_match_id'])}")
                return None
            
            # =====================================================
            # Verificar se há mensagem nova (badge/indicador)
            # =====================================================
            try:
                badge = await el.query_selector(
                    '[class*="badge"], [class*="unread"], [class*="Badge"], '
                    '[class*="indicator"], [class*="dot"], [class*="Bgc(#"]'
                )
                match_data["has_new_message"] = badge is not None
            except Exception as e:
                logger.debug(f"Erro ao detectar badge: {e}")
            
            # =====================================================
            # Extrair ÚLTIMA MENSAGEM (preview)
            # =====================================================
            try:
                preview_selectors = [
                    '[class*="preview"]',
                    '[class*="Preview"]',
                    '[class*="messagePreview"]',
                    '[class*="lastMessage"]',
                    '[class*="LastMessage"]',
                    '[class*="Ell"]',  # Elipsis - texto truncado
                    'span[class*="C($c-secondary)"]',  # Cor secundária geralmente é a mensagem
                ]
                for selector in preview_selectors:
                    preview_el = await el.query_selector(selector)
                    if preview_el:
                        text = await preview_el.inner_text()
                        # Evitar pegar o nome como mensagem
                        if text and len(text.strip()) > 0:
                            clean_text = sanitize_text(text)
                            # Limpar padrões duplicados de preview
                            clean_text = clean_message_preview(clean_text, match_data.get("name"))
                            # Se não for só o nome, é a mensagem
                            if match_data["name"] and clean_text.lower() != match_data["name"].lower():
                                match_data["last_message_preview"] = clean_text
                                break
                            elif not match_data["name"]:
                                match_data["last_message_preview"] = clean_text
                                break
            except Exception as e:
                logger.debug(f"Erro ao extrair preview da mensagem: {e}")
            
            return match_data
            
        except Exception as e:
            logger.debug(f"Erro ao extrair elemento de match: {e}")
            return None
    
    async def extract_match_date_from_current_page(self) -> Optional[datetime]:
        """
        Extrai a data do match da página atual (já na conversa).
        Procura por "You matched with Nome on M/D/YYYY" no header h1
        
        Returns:
            datetime ou None
        """
        try:
            # Primeiro tentar extrair do h1 que contém "You matched with X on DATE"
            header_text = await self.page.evaluate('''
                () => {
                    const h1 = document.querySelector('h1');
                    if (h1) return h1.textContent;
                    return null;
                }
            ''')
            
            if header_text:
                # Padrão: "You matched with Luiza on 1/23/2026" ou "Você deu match com Luiza em 23/01/2026"
                match = re.search(r'(?:You matched with|Você deu match com)\s+.+?\s+(?:on|em)\s+([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})', header_text, re.IGNORECASE)
                if match:
                    date_str = match.group(1)
                    # Detectar idioma pelo texto para escolher formato correto
                    is_portuguese = 'você' in header_text.lower() or 'em ' in header_text.lower()
                    
                    # Se português, usar formato BR primeiro (dd/mm/yyyy)
                    # Se inglês, usar formato US primeiro (mm/dd/yyyy)
                    if is_portuguese:
                        formats = ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%m/%d/%Y', '%m-%d-%Y']
                    else:
                        formats = ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y', '%d/%m/%Y', '%d-%m-%Y']
                    
                    for fmt in formats:
                        try:
                            matched_at = datetime.strptime(date_str, fmt)
                            # Validar que a data não está no futuro
                            if matched_at > datetime.now():
                                continue
                            log_automation_step(f"Data do match extraída do header: {matched_at}")
                            return matched_at
                        except ValueError:
                            continue
            
            # Fallback: buscar no body inteiro
            page_text = await self.page.inner_text('body')
            
            # Detectar idioma
            is_portuguese = 'você' in page_text.lower() or 'match com' in page_text.lower()
            
            # Padrões para data do match
            date_patterns = [
                r'(?:You matched with|Você deu match com)\s+.+?\s+(?:on|em)\s+([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})',
                r'(?:em|on)[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})',
                r'Match(?:ed)?[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})'
            ]
            
            for pattern in date_patterns:
                date_match = re.search(pattern, page_text, re.IGNORECASE)
                if date_match:
                    date_str = date_match.group(1)
                    # Escolher formato baseado no idioma
                    if is_portuguese:
                        formats = ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%m/%d/%Y', '%m-%d-%Y']
                    else:
                        formats = ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y', '%d/%m/%Y', '%d-%m-%Y']
                    
                    for fmt in formats:
                        try:
                            matched_at = datetime.strptime(date_str, fmt)
                            # Validar que a data não está no futuro
                            if matched_at > datetime.now():
                                continue
                            log_automation_step(f"Data do match extraída: {matched_at}")
                            return matched_at
                        except ValueError:
                            continue
        except Exception as e:
            logger.debug(f"Não foi possível extrair data do match: {e}")
        
        return None
    
    async def extract_match_age_from_header(self) -> Optional[int]:
        """
        Extrai a idade do match do header da conversa.
        A idade aparece ao lado do nome, ex: "Luiza, 25" ou "Luiza 25"
        
        Returns:
            Idade como int ou None
        """
        try:
            # O header da conversa geralmente tem o nome e idade
            # Buscar elementos que parecem ser o header
            header_data = await self.page.evaluate('''
                () => {
                    // Buscar h1, h2 ou elementos com classe de título
                    const selectors = [
                        'h1', 'h2', 
                        '[class*="Typs(display"]',
                        '[class*="header"] span',
                        '[class*="Header"] span',
                        'button[class*="profile"] span',
                        'a[class*="profile"] span'
                    ];
                    
                    for (const sel of selectors) {
                        const elements = document.querySelectorAll(sel);
                        for (const el of elements) {
                            const text = el.textContent?.trim();
                            // Procurar padrão "Nome, XX" ou "Nome XX" onde XX é idade
                            if (text) {
                                // Padrão: Nome seguido de vírgula e número
                                const match1 = text.match(/^([A-Za-zÀ-ÿ]+)[,\\s]+?(\\d{2})$/);
                                if (match1) {
                                    return { name: match1[1], age: parseInt(match1[2]) };
                                }
                                // Padrão: Nome colado com número
                                const match2 = text.match(/^([A-Za-zÀ-ÿ]+)(\\d{2})$/);
                                if (match2) {
                                    return { name: match2[1], age: parseInt(match2[2]) };
                                }
                            }
                        }
                    }
                    return null;
                }
            ''')
            
            if header_data and header_data.get('age'):
                age = header_data['age']
                if 18 <= age <= 100:
                    log_automation_step(f"Idade extraída do header: {age}")
                    return age
                    
        except Exception as e:
            logger.debug(f"Não foi possível extrair idade do header: {e}")
        
        return None
    
    async def extract_match_name_from_header(self) -> Optional[str]:
        """
        Extrai o nome do match do header da conversa.
        O header contém "You matched with NAME on DATE"
        
        Returns:
            Nome como string ou None
        """
        try:
            header_text = await self.page.evaluate('''
                () => {
                    const h1 = document.querySelector('h1');
                    if (h1) return h1.textContent;
                    return null;
                }
            ''')
            
            if header_text:
                # Padrão: "You matched with Luiza on 1/23/2026"
                match = re.search(r'(?:You matched with|Você deu match com)\s+([A-Za-zÀ-ÿ]+)', header_text, re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                    log_automation_step(f"Nome extraído do header: {name}")
                    return name
                    
        except Exception as e:
            logger.debug(f"Não foi possível extrair nome do header: {e}")
        
        return None
    
    async def extract_match_photo_from_header(self) -> Optional[str]:
        """
        Extrai a URL da foto do match do header da conversa.
        Evita pegar a foto do próprio usuário.
        
        Returns:
            URL da foto ou None
        """
        try:
            photo_url = await self.page.evaluate('''
                () => {
                    // Primeiro, identificar a foto do próprio usuário para evitar
                    // A foto do usuário geralmente está no botão de perfil no canto
                    const myPhotoSelectors = [
                        'button[aria-label*="Profile"] div[style*="background-image"]',
                        'a[href*="/app/profile"] div[style*="background-image"]',
                        'nav div[style*="background-image"]',
                        '[class*="navBar"] div[style*="background-image"]'
                    ];
                    
                    let myPhotoUrl = null;
                    for (const sel of myPhotoSelectors) {
                        const el = document.querySelector(sel);
                        if (el) {
                            const style = el.getAttribute('style') || '';
                            const match = style.match(/url\\(["']?([^"')]+)["']?\\)/);
                            if (match) {
                                myPhotoUrl = match[1];
                                break;
                            }
                        }
                    }
                    
                    // Agora buscar a foto do match, excluindo a foto do usuário
                    const selectors = [
                        'div[role="img"][style*="background-image"]',
                        'div.sentry-block[style*="background-image"]',
                        'div[class*="profileCard"] div[style*="background-image"]',
                        'button div[style*="background-image"]',
                        'a div[style*="background-image"]'
                    ];
                    
                    for (const selector of selectors) {
                        const elements = document.querySelectorAll(selector);
                        for (const el of elements) {
                            const style = el.getAttribute('style') || '';
                            // Verificar se contém URL de foto do Tinder
                            if (style.includes('gotinder.com') || style.includes('images-ssl')) {
                                const match = style.match(/url\\(["']?([^"')]+)["']?\\)/);
                                if (match) {
                                    const photoUrl = match[1];
                                    // Verificar se NÃO é a foto do usuário
                                    if (myPhotoUrl && photoUrl === myPhotoUrl) {
                                        continue; // Pular minha própria foto
                                    }
                                    return photoUrl;
                                }
                            }
                        }
                    }
                    
                    return null;
                }
            ''')
            
            if photo_url:
                log_automation_step(f"Foto extraída do header")
                return photo_url
                    
        except Exception as e:
            logger.debug(f"Não foi possível extrair foto do header: {e}")
        
        return None
    
    async def extract_match_profile(self, match_id: str) -> Dict:
        """
        Extrai perfil completo de um match específico.
        
        Args:
            match_id: ID do match no Tinder
            
        Returns:
            Dict com dados completos do perfil
        """
        log_automation_step(f"Extraindo perfil do match {match_id}...")
        
        profile = {
            "tinder_match_id": match_id,
            "name": None,
            "age": None,
            "bio": None,
            "distance_km": None,
            "job_title": None,
            "company": None,
            "school": None,
            "gender": None,
            "city": None,
            "relationship_intent": None,
            "sexual_orientations": None,
            "photos": [],
            "interests": [],
            "matched_at": None
        }
        
        try:
            # Navegar para conversa APENAS se necessário
            await self._navigate_to_match_if_needed(match_id)
            await async_random_delay(0.5, 1)
            
            # =====================================================
            # Extrair DATA DO MATCH ("Você deu match com Nome em: Data")
            # =====================================================
            try:
                # Buscar elemento que contém a data do match
                match_date_selectors = [
                    '[class*="matchDate"]',
                    '[class*="MatchDate"]',
                    '[class*="timestamp"]',
                    'span[class*="C($c-secondary)"]',
                    'div[class*="Fz($xs)"]'
                ]
                
                page_text = await self.page.inner_text('body')
                
                # Padrão: "Você deu match com Nome em: DD/MM/YYYY" ou "em DD/MM/YYYY"
                date_patterns = [
                    r'(?:Você deu match|You matched).+?(?:em|on)[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})',
                    r'(?:em|on)[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})',
                    r'Match(?:ed)?[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})'
                ]
                
                for pattern in date_patterns:
                    date_match = re.search(pattern, page_text, re.IGNORECASE)
                    if date_match:
                        date_str = date_match.group(1)
                        # Detectar idioma
                        is_portuguese = 'você' in page_text.lower() or 'match com' in page_text.lower()
                        
                        # Escolher formato baseado no idioma
                        if is_portuguese:
                            formats = ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%m/%d/%Y', '%m-%d-%Y']
                        else:
                            formats = ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y', '%d/%m/%Y', '%d-%m-%Y']
                        
                        for fmt in formats:
                            try:
                                parsed_date = datetime.strptime(date_str, fmt)
                                # Validar que a data não está no futuro
                                if parsed_date <= datetime.now():
                                    profile["matched_at"] = parsed_date
                                    log_automation_step(f"Data do match extraída: {profile['matched_at']}")
                                    break
                            except ValueError:
                                continue
                        if profile["matched_at"]:
                            break
            except Exception as e:
                logger.debug(f"Não foi possível extrair data do match: {e}")
            
            # Clicar para abrir perfil
            profile_opener = await self.page.query_selector(
                '[class*="profileCard"], [data-testid="profileCard"], '
                'button[class*="profile"], .Expand'
            )
            if profile_opener:
                log_automation_step("Clicando para abrir perfil expandido...")
                await profile_opener.click()
                await self.page.wait_for_load_state("networkidle")
                await async_random_delay(0.5, 1)
            else:
                # Tentar outros seletores para abrir perfil
                log_automation_step("Tentando seletores alternativos para abrir perfil...")
                alt_selectors = [
                    'img[class*="photo"]',
                    'div[class*="ProfileCard"]',
                    'button:has-text("Ver perfil")',
                    '[data-testid="profileCard"]',
                    'div[class*="matchAvatar"]',
                    'header img',  # Foto no header da conversa
                    'aside img'    # Foto na sidebar
                ]
                for sel in alt_selectors:
                    try:
                        el = await self.page.query_selector(sel)
                        if el:
                            log_automation_step(f"Abrindo perfil via: {sel}")
                            await el.click()
                            await self.page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue
            
            # Aguardar o perfil expandido carregar
            await self.page.wait_for_timeout(1500)
            
            # =====================================================
            # CICLAR PELAS FOTOS PARA CAPTURAR TODAS
            # =====================================================
            seen_photo_urls = set()
            max_photo_attempts = 15  # Máximo de tentativas de ciclar
            
            # Primeiro, capturar TODAS as fotos visíveis usando função centralizada
            # As fotos do Tinder estão em divs com classe 'profileCard__slider__img sentry-block'
            try:
                profile_photos = await extract_photos_from_page(self.page)
                
                log_automation_step(f"Fotos encontradas via JS centralizado: {len(profile_photos)}")
                for photo_data in profile_photos:
                    url = photo_data.get('url') if isinstance(photo_data, dict) else photo_data
                    if url and url not in seen_photo_urls:
                        seen_photo_urls.add(url)
                        profile["photos"].append({"url": url, "order": len(profile["photos"])})
                        log_automation_step(f"Foto {len(profile['photos'])} capturada: {url[:60]}...")
                        
            except Exception as e:
                logger.debug(f"Erro ao capturar fotos via função centralizada: {e}")
            
            # Ciclar pelas fotos clicando para capturar mais
            consecutive_no_new_photos = 0  # Contador de tentativas sem novas fotos
            max_no_new_photos = 10  # Parar após 10 tentativas consecutivas sem nova foto
            
            for attempt in range(max_photo_attempts):
                photos_before = len(profile["photos"])
                
                # Tentar clicar para próxima foto
                next_photo_clicked = False
                next_photo_selectors = [
                    'button[aria-label*="Next"]',
                    'button[aria-label*="next"]',
                    'button[aria-label*="Próxim"]',
                    '[class*="next"]',
                    '[class*="Next"]',
                    'button[class*="navButton"]:last-child',
                    '.keen-slider__next',
                    'span[class*="navButton"]:nth-child(2)'
                ]
                
                for selector in next_photo_selectors:
                    try:
                        next_btn = await self.page.query_selector(selector)
                        if next_btn:
                            is_visible = await next_btn.is_visible()
                            is_enabled = await next_btn.is_enabled()
                            if is_visible and is_enabled:
                                await next_btn.click()
                                await self.page.wait_for_timeout(500)
                                next_photo_clicked = True
                                break
                    except Exception:
                        continue
                
                # Se não encontrou botão, tentar clicar na área direita da foto
                if not next_photo_clicked:
                    try:
                        photo_container = await self.page.query_selector(
                            '[class*="keen-slider"], [class*="Slider"], [class*="mediaBox"], [class*="Carousel"]'
                        )
                        if photo_container:
                            box = await photo_container.bounding_box()
                            if box:
                                # Clicar na metade direita para avançar
                                await self.page.mouse.click(box['x'] + box['width'] * 0.8, box['y'] + box['height'] * 0.5)
                                await self.page.wait_for_timeout(500)
                                next_photo_clicked = True
                    except Exception:
                        pass
                
                # Capturar nova foto após clicar
                if next_photo_clicked:
                    try:
                        new_photos = await self.page.evaluate('''
                            () => {
                                const photos = [];
                                const imgs = document.querySelectorAll('[class*="keen-slider"] img, [class*="Slider"] img, [class*="mediaBox"] img');
                                imgs.forEach(img => {
                                    const src = img.src;
                                    if (src && src.includes('gotinder.com') && !src.includes('/icons/') && !src.includes('static-assets')) {
                                        photos.push(src);
                                    }
                                });
                                return photos;
                            }
                        ''')
                        for url in new_photos:
                            if url not in seen_photo_urls:
                                seen_photo_urls.add(url)
                                profile["photos"].append({"url": url, "order": len(profile["photos"])})
                                log_automation_step(f"Nova foto capturada após clique: {url[:60]}...")
                    except:
                        pass
                
                # Verificar se capturou nova foto nesta iteração
                photos_after = len(profile["photos"])
                if photos_after > photos_before:
                    consecutive_no_new_photos = 0  # Reset do contador
                else:
                    consecutive_no_new_photos += 1
                
                # Parar se não houver novas fotos por várias tentativas consecutivas
                if consecutive_no_new_photos >= max_no_new_photos:
                    log_automation_step(f"Parando ciclo: {max_no_new_photos} tentativas sem nova foto")
                    break
            
            # Tentar detectar quantidade total de fotos via indicadores (dots/bullets)
            try:
                total_photos_indicator = await self.page.evaluate('''
                    () => {
                        // Buscar indicadores de fotos (dots/bullets)
                        const indicators = document.querySelectorAll('[class*="bullet"], [class*="dot"], [class*="indicator"], [class*="Bullet"], [class*="Dot"]');
                        if (indicators.length > 1) return indicators.length;
                        
                        // Tentar contar spans dentro de containers de navegação
                        const navContainers = document.querySelectorAll('[class*="pageIndicator"], [class*="PageIndicator"], [class*="nav"]');
                        for (const nav of navContainers) {
                            const spans = nav.querySelectorAll('span, div');
                            if (spans.length > 1 && spans.length <= 10) return spans.length;
                        }
                        
                        return 0;
                    }
                ''')
                if total_photos_indicator > 0:
                    log_automation_step(f"Indicador mostra {total_photos_indicator} fotos no perfil")
            except:
                pass
            
            log_automation_step(f"Total de fotos capturadas: {len(profile['photos'])}")
            
            # Nome e idade - seletores específicos do perfil expandido
            # O nome aparece em "Nome, Idade" formato
            name_selectors = [
                'h1[class*="Typs"]',  # Tinder 2026 - classe Typography
                'h1[itemprop="name"]',
                '[class*="Heading"] h1',
                'div[class*="profileCard"] h1',
                '[class*="ExpandedCard"] h1',
                '[class*="ProfileCard"] h1'
            ]
            
            name_found = False
            for selector in name_selectors:
                name_el = await self.page.query_selector(selector)
                if name_el:
                    full_text = await name_el.inner_text()
                    full_text = full_text.strip()
                    
                    # Ignorar textos muito curtos (provavelmente errados)
                    if len(full_text) < 2:
                        continue
                    
                    # Separar nome e idade - formato "Nome, 25" ou "Nome 25"
                    match = re.match(r'^([A-Za-zÀ-ÿ\s]+?)\s*,?\s*(\d{2})$', full_text)
                    if match:
                        profile["name"] = match.group(1).strip()
                        profile["age"] = int(match.group(2))
                        name_found = True
                        log_automation_step(f"Nome extraído: {profile['name']}, {profile['age']} anos")
                        break
                    elif len(full_text) >= 2 and not full_text.isdigit():
                        # Nome sem idade
                        profile["name"] = full_text
                        name_found = True
                        log_automation_step(f"Nome extraído (sem idade): {profile['name']}")
                        break
            
            # Fallback: buscar via JavaScript se não encontrou
            if not name_found or not profile["name"] or len(profile["name"]) < 2:
                try:
                    name_data = await self.page.evaluate('''
                        () => {
                            // Buscar h1 que contém nome e idade no formato "Nome, Idade"
                            const h1s = document.querySelectorAll('h1');
                            for (const h1 of h1s) {
                                const text = h1.innerText.trim();
                                // Deve ter pelo menos 2 caracteres e conter letras
                                if (text.length >= 2 && /[A-Za-zÀ-ÿ]/.test(text)) {
                                    const match = text.match(/^([A-Za-zÀ-ÿ\\s]+?)\\s*,?\\s*(\\d{2})?$/);
                                    if (match && match[1].length >= 2) {
                                        return {
                                            name: match[1].trim(),
                                            age: match[2] ? parseInt(match[2]) : null
                                        };
                                    }
                                }
                            }
                            return null;
                        }
                    ''')
                    if name_data and name_data.get('name') and len(name_data['name']) >= 2:
                        profile["name"] = name_data['name']
                        if name_data.get('age'):
                            profile["age"] = name_data['age']
                        log_automation_step(f"Nome extraído via JS: {profile['name']}, {profile.get('age')} anos")
                except Exception as e:
                    logger.debug(f"Erro ao extrair nome via JS: {e}")
            
            # =====================================================
            # BIO / SOBRE MIM - Extração robusta
            # =====================================================
            bio_selectors = [
                '[class*="bio"]',
                '[class*="Bio"]',
                '[class*="Mstart"]',
                '[itemprop="description"]',
                'div[class*="BreakWord"]',
                'div[class*="about"]',
                'div[class*="About"]',
                'span[class*="userBio"]',
                '[class*="profileSection"] > div'
            ]
            
            for selector in bio_selectors:
                bio_el = await self.page.query_selector(selector)
                if bio_el:
                    bio_text = sanitize_text(await bio_el.inner_text())
                    # Verificar se tem conteúdo relevante
                    # NÃO deve ser apenas título "Sobre mim"
                    # NÃO deve parecer mensagem (formato "Nome: texto" ou muito curto)
                    if bio_text and len(bio_text) > 10 and bio_text.lower() not in ['sobre mim', 'about me', 'bio']:
                        # Ignorar se parece mensagem (formato "Nome: texto")
                        if re.match(r'^[A-Za-zÀ-ÿ\s]{2,20}:\s+', bio_text):
                            continue
                        # Ignorar se parece horário ou data
                        if re.match(r'^\d{1,2}:\d{2}', bio_text):
                            continue
                        profile["bio"] = bio_text
                        log_automation_step(f"Bio capturada: {bio_text[:50]}...")
                        break
            
            # Se não encontrou bio nos seletores específicos, buscar via texto
            if not profile["bio"]:
                try:
                    bio_via_js = await self.page.evaluate('''
                        () => {
                            // =====================================================
                            // ESTRATÉGIA: Buscar APENAS a bio real do perfil
                            // A bio está na seção "Sobre mim" - texto livre escrito pelo usuário
                            // IGNORAR todas as seções estruturadas/badges do Tinder
                            // =====================================================
                            
                            // Buscar o painel de perfil expandido
                            const profilePanel = document.querySelector('[class*="BottomSheet"]') ||
                                               document.querySelector('[class*="ProfileCard"]') ||
                                               document.querySelector('[class*="ExpandedCard"]') ||
                                               document.querySelector('[class*="profileCard"]') ||
                                               document.querySelector('[role="dialog"]');
                            
                            if (!profilePanel) {
                                return null;
                            }
                            
                            const allText = profilePanel.innerText;
                            
                            // =====================================================
                            // LISTA COMPLETA de seções estruturadas do Tinder
                            // Estas seções têm formato "Título\\nValor" e NÃO são bio
                            // =====================================================
                            const structuredSections = [
                                // Seções principais
                                'sobre mim', 'about me',
                                'interesses', 'interests', 'passions',
                                'informações básicas', 'basic info', 'basics',
                                'tô procurando', 'looking for',
                                'estilo de vida', 'lifestyle',
                                'mais sobre mim', 'more about me',
                                'o que procura', 'what i want',
                                
                                // Seções de "Mais sobre mim"
                                'estilo de comunicação', 'communication style',
                                'linguagem do amor', 'love language',
                                'tipo de personalidade', 'personality type',
                                'formação', 'education level', 'education',
                                'signo', 'zodiac', 'star sign',
                                'pets', 'animais de estimação',
                                'frequência de exercício', 'workout', 'exercise',
                                'hábitos de bebida', 'drinking', 'drinks',
                                'hábitos de fumar', 'smoking', 'smokes',
                                'hábitos alimentares', 'dietary preference', 'diet',
                                'redes sociais', 'social media',
                                'hábitos de sono', 'sleeping habits', 'sleep',
                                'filhos', 'children', 'kids',
                                'planos para filhos', 'family plans',
                                'vacinas', 'vaccinated', 'covid',
                                'altura', 'height',
                                
                                // Valores de badges (não títulos)
                                'gestos de serviço', 'acts of service',
                                'palavras de afirmação', 'words of affirmation',
                                'tempo de qualidade', 'quality time',
                                'toque físico', 'physical touch',
                                'presentes', 'receiving gifts',
                                'odeio falar por mensagem', 'big time texter',
                                'gosto de ligar', 'phone caller',
                                'prefiro vídeo', 'video chatter',
                                'textos longos', 'better in person',
                                'socialmente ativo', 'social butterfly',
                                'introvertido', 'introvert',
                                'extrovertido', 'extrovert',
                                'curso técnico', 'ensino médio', 'graduação', 'pós-graduação',
                                'bacharelado', 'mestrado', 'doutorado', 'high school', 'bachelors', 'masters', 'phd',
                                'relacionamento sério', 'algo casual', 'novas amizades', 'ainda não sei',
                                'long-term', 'short-term', 'new friends', 'not sure',
                                'bebe socialmente', 'não bebe', 'bebe frequentemente',
                                'social drinker', 'never drinks', 'drinks frequently',
                                'não fuma', 'fuma socialmente', 'fuma', 'fumante',
                                'non-smoker', 'social smoker', 'smoker',
                                'vegano', 'vegetariano', 'onívoro', 'pescetariano',
                                'vegan', 'vegetarian', 'omnivore', 'pescatarian',
                                'gato', 'cachorro', 'pássaro', 'peixe', 'réptil', 'outros pets',
                                'cat', 'dog', 'bird', 'fish', 'reptile', 'other pets',
                                'ativo', 'às vezes', 'quase nunca',
                                'active', 'sometimes', 'almost never',
                                // Signos
                                'áries', 'touro', 'gêmeos', 'câncer', 'leão', 'virgem',
                                'libra', 'escorpião', 'sagitário', 'capricórnio', 'aquário', 'peixes',
                                'aries', 'taurus', 'gemini', 'cancer', 'leo', 'virgo',
                                'scorpio', 'sagittarius', 'capricorn', 'aquarius', 'pisces',
                                // Tipos de personalidade
                                'intj', 'intp', 'entj', 'entp', 'infj', 'infp', 'enfj', 'enfp',
                                'istj', 'isfj', 'estj', 'esfj', 'istp', 'isfp', 'estp', 'esfp'
                            ];
                            
                            // Função para verificar se texto é seção estruturada
                            const isStructuredContent = (text) => {
                                const lower = text.toLowerCase();
                                return structuredSections.some(section => lower.includes(section));
                            };
                            
                            // Função para verificar se parece mensagem (formato "Nome: texto")
                            const isMessageFormat = (text) => {
                                return /^[A-Za-zÀ-ÿ\\s]{2,20}:\\s+/.test(text);
                            };
                            
                            // Função para verificar se é horário ou data
                            const isTimeOrDate = (text) => {
                                return /^\\d{1,2}[:\\/\\-]\\d{1,2}/.test(text);
                            };
                            
                            // =====================================================
                            // MÉTODO 1: Buscar texto após "Sobre mim" até próxima seção
                            // =====================================================
                            const sobreMimMatch = allText.match(/(?:Sobre mim|About me)\\s*\\n+([\\s\\S]+?)(?=\\n(?:Interesses|Interests|Informações|Basic info|Tô procurando|Looking for|Estilo de vida|Lifestyle|Mais sobre mim|More about me|O que procura|Passions)|$)/i);
                            
                            if (sobreMimMatch && sobreMimMatch[1]) {
                                let bioText = sobreMimMatch[1].trim();
                                
                                // Pegar apenas a primeira "linha" de conteúdo (antes de badges)
                                // A bio real geralmente é um parágrafo contínuo
                                const lines = bioText.split('\\n').filter(l => l.trim());
                                
                                if (lines.length > 0) {
                                    // Juntar linhas que parecem ser parte da mesma bio
                                    let realBio = '';
                                    for (const line of lines) {
                                        const trimmed = line.trim();
                                        // Parar se encontrar conteúdo estruturado
                                        if (isStructuredContent(trimmed)) break;
                                        // Parar se linha muito curta (provavelmente badge)
                                        if (trimmed.length < 5) continue;
                                        // Ignorar se parece mensagem
                                        if (isMessageFormat(trimmed)) continue;
                                        // Ignorar se é horário ou data
                                        if (isTimeOrDate(trimmed)) continue;
                                        // Parar se parece ser título de seção (apenas 1-2 palavras)
                                        if (trimmed.split(' ').length <= 2 && !trimmed.includes(',') && !trimmed.includes('.')) continue;
                                        
                                        realBio += (realBio ? ' ' : '') + trimmed;
                                    }
                                    
                                    // Verificar se é uma bio válida (não é mensagem)
                                    if (realBio.length > 10 && realBio.length < 600 && 
                                        !isStructuredContent(realBio) && 
                                        !isMessageFormat(realBio)) {
                                        return realBio;
                                    }
                                }
                            }
                            
                            // Se não encontrou bio após "Sobre mim", não há bio
                            return null;
                        }
                    ''')
                    if bio_via_js:
                        # Validação adicional: não deve parecer mensagem
                        if not re.match(r'^[A-Za-zÀ-ÿ\s]{2,20}:\s+', bio_via_js):
                            profile["bio"] = sanitize_text(bio_via_js)
                            log_automation_step(f"Bio capturada via JS: {profile['bio'][:50]}...")
                except Exception as e:
                    logger.debug(f"Erro ao buscar bio via JS: {e}")
            
            # =====================================================
            # EXTRAÇÃO DE DADOS BÁSICOS (distância, trabalho, escola, etc)
            # Focando APENAS no painel de perfil expandido
            # =====================================================
            try:
                basic_info = await self.page.evaluate('''
                    () => {
                        const info = {
                            distance: null,
                            job_title: null,
                            school: null,
                            city: null,
                            gender: null
                        };
                        
                        // Buscar o painel de perfil expandido (não a conversa, não a sidebar)
                        const profilePanel = document.querySelector('[class*="BottomSheet"]') ||
                                           document.querySelector('[class*="ProfileCard"]') ||
                                           document.querySelector('[class*="ExpandedCard"]') ||
                                           document.querySelector('[class*="profileCard"]') ||
                                           document.querySelector('[role="dialog"]');
                        
                        // Usar painel de perfil se encontrado, senão usar body como fallback
                        const searchRoot = profilePanel || document.body;
                        const bodyText = searchRoot.innerText;
                        
                        // Distância - "a X quilômetros" ou "X km away"
                        const distMatch = bodyText.match(/(?:a\\s*)?(\\d+)\\s*(?:quil[oô]metros|km)/i);
                        if (distMatch) {
                            info.distance = parseInt(distMatch[1]);
                        }
                        
                        // Cidade - geralmente aparece como "Mora em X" ou "Lives in X"
                        const cityMatch = bodyText.match(/(?:Mora em|Lives in|Vive em)\\s*([^\\n]+)/i);
                        if (cityMatch) {
                            let cityCandidate = cityMatch[1].trim();
                            // Validar que não é horário ou outro texto inválido
                            if (cityCandidate && 
                                !cityCandidate.match(/^\\d{1,2}:\\d{2}/) &&  // Não é horário
                                !cityCandidate.match(/^\\d+$/) &&  // Não é só número
                                cityCandidate.length > 2 && 
                                cityCandidate.length < 50) {
                                info.city = cityCandidate;
                            }
                        }
                        
                        // Buscar elementos específicos de info do perfil DENTRO do painel
                        const infoElements = searchRoot.querySelectorAll('[class*="info"], [class*="Info"], [class*="badge"], [class*="Badge"], [class*="detail"], [class*="Detail"]');
                        
                        infoElements.forEach(el => {
                            const text = el.innerText.trim();
                            if (!text || text.length > 100) return; // Ignorar textos muito longos
                            
                            // Trabalho - geralmente tem ícone de maleta ou padrão "X em/at Y"
                            if (text && !info.job_title) {
                                if (el.querySelector('[class*="work"]') || 
                                    el.querySelector('[class*="job"]') ||
                                    text.match(/^[A-Za-zÀ-ÿ\\s]+ (em|at|@|na|no) /i)) {
                                    info.job_title = text;
                                }
                            }
                            
                            // Escola - geralmente tem ícone de formação
                            if (text && !info.school) {
                                if (el.querySelector('[class*="school"]') || 
                                    el.querySelector('[class*="education"]') ||
                                    text.match(/universidade|faculdade|university|college|escola|school/i)) {
                                    info.school = text;
                                }
                            }
                        });
                        
                        // Gênero - pode aparecer em badges ou texto do painel
                        // Se não encontrar explicitamente, assume female (contexto: app de relacionamento heteronormativo)
                        const genderPatterns = [
                            { pattern: /\\b(Mulher|Woman|Feminino|Female)\\b/i, value: 'female' },
                            { pattern: /\\b(Homem|Man|Masculino|Male)\\b/i, value: 'male' },
                            { pattern: /\\b(Não-binárie|Non-binary)\\b/i, value: 'non-binary' }
                        ];
                        
                        let foundGender = false;
                        for (const {pattern, value} of genderPatterns) {
                            if (pattern.test(bodyText)) {
                                info.gender = value;
                                foundGender = true;
                                break;
                            }
                        }
                        
                        // Default para female se não encontrou gênero explícito
                        // (assumindo uso heteronormativo padrão do Tinder)
                        if (!foundGender) {
                            info.gender = 'female';
                        }
                        
                        return info;
                    }
                ''')
                
                if basic_info:
                    if basic_info.get('distance'):
                        profile['distance_km'] = basic_info['distance']
                    if basic_info.get('job_title'):
                        profile['job_title'] = sanitize_text(basic_info['job_title'])
                    if basic_info.get('school'):
                        profile['school'] = sanitize_text(basic_info['school'])
                    if basic_info.get('city'):
                        profile['city'] = clean_city(basic_info['city'])
                    if basic_info.get('gender'):
                        profile['gender'] = basic_info['gender']
                        
            except Exception as e:
                logger.debug(f"Erro ao extrair info básica via JS: {e}")
            
            # Fallback para seletores diretos se não conseguiu via JS
            if not profile.get('distance_km'):
                distance_el = await self.page.query_selector('[class*="distance"]')
                if distance_el:
                    dist_text = await distance_el.inner_text()
                    dist_match = re.search(r'(\d+)', dist_text)
                    if dist_match:
                        profile["distance_km"] = float(dist_match.group(1))
            
            if not profile.get('job_title'):
                job_el = await self.page.query_selector('[class*="job"], [class*="work"]')
                if job_el:
                    profile["job_title"] = sanitize_text(await job_el.inner_text())
            
            if not profile.get('school'):
                school_el = await self.page.query_selector('[class*="school"]')
                if school_el:
                    profile["school"] = sanitize_text(await school_el.inner_text())
            
            # Se poucas fotos após ciclar, tentar buscar via JavaScript adicional
            if len(profile["photos"]) < 3:
                try:
                    additional_photos = await self.page.evaluate('''
                        () => {
                            const photos = [];
                            const seen = new Set();
                            
                            // Função para extrair URL de background-image
                            function extractBgUrl(element) {
                                const style = element.getAttribute('style') || '';
                                const match = style.match(/background-image:\\s*url\\(["']?([^"')]+)["']?\\)/i);
                                return match ? match[1] : null;
                            }
                            
                            // Função para validar URL
                            function isValidUrl(url) {
                                if (!url) return false;
                                return url.includes('images-ssl.gotinder.com') && 
                                       !url.includes('.gif') && 
                                       !url.includes('/icons/') &&
                                       !url.includes('static-assets') &&
                                       !url.includes('84x84') &&
                                       !url.includes('84x106');
                            }
                            
                            // 1. Buscar em divs com background-image (estrutura principal do Tinder)
                            const bgDivs = document.querySelectorAll(
                                '.profileCard__slider__img[style*="background-image"], ' +
                                '[class*="profileCard__slider__img"][style*="background-image"], ' +
                                '.keen-slider__slide [style*="background-image"]'
                            );
                            bgDivs.forEach(div => {
                                const url = extractBgUrl(div);
                                if (url && isValidUrl(url) && !seen.has(url)) {
                                    seen.add(url);
                                    photos.push(url);
                                }
                            });
                            
                            // 2. Fallback para tags img
                            if (photos.length === 0) {
                                const containers = document.querySelectorAll(
                                    '[class*="keen-slider"], [class*="profileCard__slider"], ' +
                                    '[class*="ExpandedProfile"], [class*="Carousel"]'
                                );
                                
                                containers.forEach(container => {
                                    const images = container.querySelectorAll('img');
                                    images.forEach(img => {
                                        const src = img.src || img.getAttribute('data-src');
                                        if (isValidUrl(src) && !seen.has(src)) {
                                            seen.add(src);
                                            photos.push(src);
                                        }
                                    });
                                });
                            }
                            
                            return photos;
                        }
                    ''')
                    
                    for url in additional_photos:
                        if url not in seen_photo_urls:
                            seen_photo_urls.add(url)
                            profile["photos"].append({"url": url, "order": len(profile["photos"])})
                except Exception as e:
                    logger.debug(f"Erro ao buscar fotos adicionais via JS: {e}")
            
            # =====================================================
            # EXTRAÇÃO VIA JAVASCRIPT - Mais robusta
            # =====================================================
            # Limpar fotos que podem ter sido adicionadas erroneamente antes do filtro
            profile["photos"] = [p for p in profile["photos"] 
                                if 'gotinder.com' in p.get('url', '') 
                                and '/icons/' not in p.get('url', '')
                                and 'static-assets' not in p.get('url', '')]
            seen_photo_urls = {p['url'] for p in profile['photos']}
            
            try:
                extracted_data = await self.page.evaluate('''
                    () => {
                        const data = {
                            interests: [],
                            relationship_intent: null,
                            bio: null,
                            distance: null,
                            lifestyle: {},
                            basics: {},
                            photos: []
                        };
                        
                        // ===============================================
                        // ESTRATÉGIA: Buscar conteúdo do PERFIL, não da interface
                        // ===============================================
                        
                        // O Tinder tem um layout com:
                        // - Barra lateral esquerda (lista de matches)  
                        // - Área central (chat ou perfil expandido)
                        // - Possível painel direito (detalhes do perfil)
                        
                        // Palavras que NUNCA devem aparecer na bio (são da interface)
                        const uiWords = ['BOOST', 'Explorar', 'Modo trabalho', 'Kit de ferramentas', 
                                        'segurança', 'Mensagens', 'Matches', 'Configurações',
                                        'Descobrir', 'Likes', 'Super Likes', 'Prioridade',
                                        'Recomendar perfil', 'Denunciar', 'Desfazer match'];
                        
                        // Coletar TODO o texto visível da página
                        const bodyText = document.body.innerText || '';
                        const lines = bodyText.split('\\n').map(l => l.trim()).filter(l => l && l.length > 1);
                        
                        // ===============================================
                        // "Tô procurando" - Buscar no texto completo
                        // ===============================================
                        for (let i = 0; i < lines.length; i++) {
                            const line = lines[i].toLowerCase();
                            if (line.includes('tô procurando') || line === 'looking for') {
                                // Próxima linha é o que ela procura
                                for (let j = i + 1; j < Math.min(i + 3, lines.length); j++) {
                                    const nextLine = lines[j];
                                    if (nextLine && 
                                        nextLine.length > 2 && 
                                        nextLine.length < 100 &&
                                        !nextLine.toLowerCase().includes('sobre') &&
                                        !uiWords.some(w => nextLine.includes(w))) {
                                        data.relationship_intent = nextLine;
                                        break;
                                    }
                                }
                                break;
                            }
                        }
                        
                        // ===============================================
                        // "Sobre mim" / Bio - Buscar seção específica
                        // ===============================================
                        for (let i = 0; i < lines.length; i++) {
                            const line = lines[i].toLowerCase();
                            if (line === 'sobre mim' || line === 'about me' || line === 'bio') {
                                let bioLines = [];
                                for (let j = i + 1; j < Math.min(i + 10, lines.length); j++) {
                                    const nextLine = lines[j];
                                    
                                    // Parar em seções conhecidas
                                    if (/^(informações básicas|interesses|mais sobre|estilo de vida|tô procurando|minhas músicas)/i.test(nextLine)) {
                                        break;
                                    }
                                    
                                    // Ignorar linhas da interface
                                    if (uiWords.some(w => nextLine.includes(w))) {
                                        continue;
                                    }
                                    
                                    // Linha de bio válida
                                    if (nextLine.length > 2 && nextLine.length < 300) {
                                        bioLines.push(nextLine);
                                    }
                                    
                                    // Máximo 5 linhas de bio
                                    if (bioLines.length >= 5) break;
                                }
                                
                                if (bioLines.length > 0) {
                                    data.bio = bioLines.join(' ');
                                }
                                break;
                            }
                        }
                        
                        // ===============================================
                        // Distância - "a X quilômetros"
                        // ===============================================
                        const distMatch = bodyText.match(/a\\s*(\\d+)\\s*quil[oô]metros/i);
                        if (distMatch) {
                            data.distance = parseInt(distMatch[1]);
                        }
                        
                        // ===============================================
                        // Interesses - Seção específica
                        // ===============================================
                        for (let i = 0; i < lines.length; i++) {
                            if (lines[i].toLowerCase() === 'interesses' || 
                                lines[i].toLowerCase() === 'interests') {
                                // Coletar próximas linhas como interesses
                                for (let j = i + 1; j < Math.min(i + 15, lines.length); j++) {
                                    const interest = lines[j];
                                    // Parar em próxima seção
                                    if (/^(desfazer|bloquear|mais sobre|estilo|tô procurando|sobre mim)/i.test(interest)) {
                                        break;
                                    }
                                    // Ignorar palavras da interface
                                    if (uiWords.some(w => interest.includes(w))) {
                                        continue;
                                    }
                                    // Interesses são geralmente curtos
                                    if (interest.length > 1 && interest.length < 30) {
                                        data.interests.push(interest);
                                    }
                                }
                                break;
                            }
                        }
                        
                        // ===============================================
                        // Tags como "Monogamia" - geralmente perto de "Tô procurando"
                        // ===============================================
                        const relationshipTypes = ['Monogamia', 'Poliamoroso', 'Não-monogâmico', 'Monogamy', 'ENM', 'Poliamor'];
                        for (const line of lines) {
                            for (const type of relationshipTypes) {
                                if (line.toLowerCase().includes(type.toLowerCase())) {
                                    data.basics.relationship_type = type;
                                    break;
                                }
                            }
                        }
                        
                        // ===============================================
                        // "Mais sobre mim" / Estilo de vida
                        // ===============================================
                        const lifestyleKeywords = {
                            'communication_style': ['Estilo de comunicação', 'Communication style'],
                            'drinking': ['Bebida', 'Drinking'],
                            'exercise': ['Atividade física', 'Exercise'],
                            'smoking': ['Você fuma', 'Smoking'],
                            'pets': ['Pets', 'Animais de estimação'],
                            'children': ['Filhos', 'Children'],
                            'education': ['Escolaridade', 'Education'],
                            'zodiac': ['Signo', 'Zodiac'],
                            'height': ['Altura', 'Height']
                        };
                        
                        for (let i = 0; i < lines.length; i++) {
                            for (const [key, keywords] of Object.entries(lifestyleKeywords)) {
                                for (const keyword of keywords) {
                                    if (lines[i].toLowerCase().includes(keyword.toLowerCase())) {
                                        // Próxima linha é o valor
                                        if (i + 1 < lines.length) {
                                            const value = lines[i + 1];
                                            if (value && value.length < 100 && 
                                                !/^(estilo|bebida|atividade|você fuma|pets|filhos)/i.test(value)) {
                                                data.lifestyle[key] = value;
                                            }
                                        }
                                        break;
                                    }
                                }
                            }
                        }
                        
                        // ===============================================
                        // Foto verificada
                        // ===============================================
                        if (/foto\\s*(e identidade\\s*)?verificada|verified/i.test(bodyText)) {
                            data.basics.verified = true;
                        }
                        
                        // ===============================================
                        // Fotos - Buscar usando background-image (estrutura do Tinder)
                        // ===============================================
                        
                        // Função para extrair URL de background-image
                        function extractBgUrl(element) {
                            const style = element.getAttribute('style') || '';
                            const match = style.match(/background-image:\\s*url\\(["']?([^"')]+)["']?\\)/i);
                            return match ? match[1] : null;
                        }
                        
                        // Função para validar URL de foto
                        function isValidPhotoUrl(url) {
                            if (!url) return false;
                            return url.includes('images-ssl.gotinder.com') && 
                                   !url.includes('.gif') &&
                                   !url.includes('/icons/') &&
                                   !url.includes('static-assets') &&
                                   !url.includes('84x84') &&
                                   !url.includes('84x106');
                        }
                        
                        const photoSeen = new Set();
                        
                        // 1. PRINCIPAL: Buscar nas divs com classe específica do Tinder
                        const sliderPhotos = document.querySelectorAll(
                            '.profileCard__slider__img.sentry-block, ' +
                            '.profileCard__slider__img[style*="background-image"], ' +
                            '[class*="profileCard__slider__img"][style*="background-image"]'
                        );
                        sliderPhotos.forEach((div) => {
                            const url = extractBgUrl(div);
                            if (url && isValidPhotoUrl(url) && !photoSeen.has(url)) {
                                photoSeen.add(url);
                                data.photos.push({ url: url, order: data.photos.length });
                            }
                        });
                        
                        // 2. Buscar dentro de keen-slider__slide
                        if (data.photos.length === 0) {
                            const slides = document.querySelectorAll('.keen-slider__slide, [class*="keen-slider__slide"]');
                            slides.forEach((slide) => {
                                const bgDivs = slide.querySelectorAll('[style*="background-image"]');
                                bgDivs.forEach((div) => {
                                    const url = extractBgUrl(div);
                                    if (url && isValidPhotoUrl(url) && !photoSeen.has(url)) {
                                        photoSeen.add(url);
                                        data.photos.push({ url: url, order: data.photos.length });
                                    }
                                });
                            });
                        }
                        
                        // 3. Fallback: qualquer div com background-image do gotinder
                        if (data.photos.length === 0) {
                            const allBgDivs = document.querySelectorAll('[style*="background-image"]');
                            allBgDivs.forEach((div) => {
                                const url = extractBgUrl(div);
                                if (url && isValidPhotoUrl(url) && !photoSeen.has(url)) {
                                    photoSeen.add(url);
                                    data.photos.push({ url: url, order: data.photos.length });
                                }
                            });
                        }
                        
                        // 4. Último recurso: tags img
                        if (data.photos.length === 0) {
                            const imgs = document.querySelectorAll('img[src*="gotinder.com"]');
                            imgs.forEach((img) => {
                                const src = img.src;
                                if (isValidPhotoUrl(src) && !photoSeen.has(src)) {
                                    photoSeen.add(src);
                                    data.photos.push({ url: src, order: data.photos.length });
                                }
                            });
                        }
                        
                        // Limitar a no máximo 10 fotos
                        data.photos = data.photos.slice(0, 10);
                        
                        return data;
                    }
                ''')
                
                log_automation_step(f"Dados extraídos via JS: bio={bool(extracted_data.get('bio'))}, intent={bool(extracted_data.get('relationship_intent'))}, interests={len(extracted_data.get('interests', []))}, photos={len(extracted_data.get('photos', []))}")
                
                # Aplicar dados extraídos via JS
                if extracted_data:
                    if extracted_data.get('relationship_intent') and not profile.get('relationship_intent'):
                        profile['relationship_intent'] = extracted_data['relationship_intent']
                        log_automation_step(f"Relationship intent: {profile['relationship_intent']}")
                    
                    if extracted_data.get('bio') and not profile.get('bio'):
                        profile['bio'] = extracted_data['bio']
                        log_automation_step(f"Bio extraída via JS: {profile['bio'][:50]}...")
                    
                    if extracted_data.get('distance') and not profile.get('distance_km'):
                        profile['distance_km'] = float(extracted_data['distance'])
                    
                    # Adicionar interesses únicos
                    existing_interests = set(profile.get('interests', []))
                    for interest in extracted_data.get('interests', []):
                        if interest not in existing_interests:
                            profile['interests'].append(interest)
                            existing_interests.add(interest)
                    
                    # Adicionar lifestyle como informações extras no bio ou campo separado
                    lifestyle = extracted_data.get('lifestyle', {})
                    if lifestyle:
                        lifestyle_text = []
                        if lifestyle.get('drinking'):
                            lifestyle_text.append(f"Bebida: {lifestyle['drinking']}")
                        if lifestyle.get('smoking'):
                            lifestyle_text.append(f"Fuma: {lifestyle['smoking']}")
                        if lifestyle.get('exercise'):
                            lifestyle_text.append(f"Exercício: {lifestyle['exercise']}")
                        if lifestyle.get('communication_style'):
                            lifestyle_text.append(f"Comunicação: {lifestyle['communication_style']}")
                        
                        if lifestyle_text:
                            profile['lifestyle_info'] = ' | '.join(lifestyle_text)
                            log_automation_step(f"Lifestyle: {profile['lifestyle_info']}")
                    
                    # Basics
                    basics = extracted_data.get('basics', {})
                    if basics.get('relationship_type'):
                        profile['relationship_type'] = basics['relationship_type']
                    if basics.get('verified'):
                        profile['verified'] = True
                    
                    # Fotos extraídas via JS (domínio gotinder)
                    js_photos = extracted_data.get('photos', [])
                    if js_photos:
                        for photo in js_photos:
                            if photo.get('url') and photo['url'] not in seen_photo_urls:
                                seen_photo_urls.add(photo['url'])
                                profile['photos'].append(photo)
                        log_automation_step(f"Fotos via JS: {len(js_photos)} encontradas")
                        
            except Exception as e:
                logger.debug(f"Erro na extração via JS: {e}")
            
            # Interesses (fallback para seletores tradicionais)
            if not profile.get('interests'):
                interest_elements = await self.page.query_selector_all(
                    '[class*="passion"] span, [class*="interest"] span'
                )
                for el in interest_elements:
                    interest = sanitize_text(await el.inner_text())
                    if interest:
                        profile["interests"].append(interest)
            
            # =====================================================
            # Extrair INFORMAÇÕES ADICIONAIS DO PERFIL
            # =====================================================
            try:
                # Cidade - geralmente aparece junto com distância
                if not profile.get("city"):
                    city_el = await self.page.query_selector('[class*="location"], [class*="city"]')
                    if city_el:
                        city_text = clean_city(await city_el.inner_text())
                        if city_text:
                            profile["city"] = city_text
                
                # Relationship Intent - "O que procura" (Relacionamento sério, Algo casual, Amizade, etc)
                # Buscar no texto da página por padrões conhecidos
                page_content = await self.page.content()
                
                # Padrões em português e inglês
                intent_patterns = {
                    'relationship': [
                        r'relacionamento\s+sério',
                        r'algo\s+sério',
                        r'long.?term',
                        r'relationship'
                    ],
                    'casual': [
                        r'algo\s+casual',
                        r'casual',
                        r'short.?term',
                        r'fun'
                    ],
                    'friendship': [
                        r'amizade',
                        r'amigos',
                        r'friend',
                        r'new\s+people'
                    ]
                }
                
                for intent_type, patterns in intent_patterns.items():
                    for pattern in patterns:
                        if re.search(pattern, page_content, re.IGNORECASE):
                            profile["relationship_intent"] = intent_type
                            break
                    if profile["relationship_intent"]:
                        break
                
                # Gender - extrair do perfil (Homem, Mulher, Não-binário, etc)
                # Só procurar se ainda não temos o gênero definido
                if not profile.get("gender"):
                    gender_patterns = {
                        'male': [r'\bmale\b', r'\bhomem\b', r'\bmasculino\b'],
                        'female': [r'\bfemale\b', r'\bmulher\b', r'\bfeminino\b'],
                        'non-binary': [r'non.?binary', r'não.?binário', r'nb\b']
                    }
                    
                    gender_found = False
                    for gender_type, patterns in gender_patterns.items():
                        for pattern in patterns:
                            if re.search(pattern, page_content, re.IGNORECASE):
                                profile["gender"] = gender_type
                                gender_found = True
                                break
                        if gender_found:
                            break
                    
                    # Se não encontrou, assume female (contexto: app de namoro heteronormativo)
                    if not gender_found:
                        profile["gender"] = "female"
                
                # Sexual Orientations - pode ter múltiplas
                orientation_keywords = []
                orientation_patterns = {
                    'straight': [r'\bstraight\b', r'\bhétero\b', r'\bheterossexual\b'],
                    'gay': [r'\bgay\b'],
                    'lesbian': [r'\blesbian\b', r'\blésbica\b'],
                    'bisexual': [r'\bbisexual\b', r'\bbi\b'],
                    'pansexual': [r'\bpansexual\b', r'\bpan\b'],
                    'asexual': [r'\basexual\b', r'\bace\b'],
                    'queer': [r'\bqueer\b']
                }
                
                for orientation, patterns in orientation_patterns.items():
                    for pattern in patterns:
                        if re.search(pattern, page_content, re.IGNORECASE):
                            orientation_keywords.append(orientation)
                            break
                
                if orientation_keywords:
                    profile["sexual_orientations"] = ', '.join(orientation_keywords)
                
            except Exception as e:
                logger.debug(f"Erro ao extrair informações adicionais do perfil: {e}")
            
            log_automation_step(
                "Perfil do match extraído",
                {"name": profile["name"], "has_bio": bool(profile["bio"])}
            )
            
        except Exception as e:
            logger.error(f"Erro ao extrair perfil do match {match_id}: {e}")
        
        return profile
    
    async def extract_conversation(self, match_id: str, max_messages: int = 50) -> List[Dict]:
        """
        Extrai mensagens de uma conversa.
        
        Args:
            match_id: ID do match
            max_messages: Número máximo de mensagens a extrair
            
        Returns:
            Lista de mensagens ordenadas (mais antiga primeiro)
        """
        log_automation_step(f"Extraindo conversa com match {match_id}...")
        messages = []
        
        try:
            # Navegar para conversa APENAS se necessário
            await self._navigate_to_match_if_needed(match_id)
            await async_random_delay(0.5, 1)
            
            # Aguardar mensagens carregarem
            await self.page.wait_for_timeout(1000)
            
            # Fazer scroll para cima várias vezes para carregar mensagens antigas
            for _ in range(5):
                await self.page.evaluate('''
                    () => {
                        // Encontrar o container de mensagens e fazer scroll para o topo
                        const containers = document.querySelectorAll('div[class*="Ov(a)"], div[class*="chat"], div[class*="message"]');
                        for (const container of containers) {
                            if (container.scrollHeight > container.clientHeight) {
                                container.scrollTop = 0;
                            }
                        }
                        // Também tentar scroll na janela
                        window.scrollTo(0, 0);
                    }
                ''')
                await self.page.wait_for_timeout(500)
            
            # Aguardar mais um pouco para mensagens carregarem após scroll
            await self.page.wait_for_timeout(1500)
            
            # =====================================================
            # EXTRAÇÃO DE MENSAGENS - Baseado na estrutura HTML real
            # =====================================================
            # Estrutura do Tinder:
            # - Cada mensagem está em div[role="article"]
            # - Texto da mensagem em span.text (classe "text D(ib) Va(t)")
            # - Mensagem recebida: div com classe "msg--received"
            # - Mensagem enviada: NÃO tem "msg--received"
            # - Timestamp em time[datetime]
            
            messages_data = await self.page.evaluate('''
                () => {
                    const messages = [];
                    const seen = new Set();
                    
                    // Buscar todas as mensagens pelo role="article"
                    const messageElements = document.querySelectorAll('div[role="article"]');
                    
                    messageElements.forEach((article, index) => {
                        try {
                            // Buscar o span com classe "text" que contém o texto da mensagem
                            const textSpan = article.querySelector('span.text');
                            if (!textSpan) return;
                            
                            const text = textSpan.textContent?.trim();
                            if (!text || text.length < 1) return;
                            
                            // Determinar se é minha mensagem ou da outra pessoa
                            // Mensagens recebidas têm classe "msg--received"
                            const msgDiv = article.querySelector('div.msg');
                            let isFromMe = true;
                            
                            if (msgDiv) {
                                const classList = msgDiv.className || '';
                                if (classList.includes('msg--received')) {
                                    isFromMe = false;
                                }
                            }
                            
                            // Alternativamente, verificar alinhamento do article
                            // Ta(e) = text-align: end (minha mensagem)
                            // Ta(start) = text-align: start (mensagem recebida)
                            const articleClass = article.className || '';
                            if (articleClass.includes('Ta(start)') || articleClass.includes('Pstart(42px)') || articleClass.includes('Pend(90px)')) {
                                isFromMe = false;
                            } else if (articleClass.includes('Ta(e)') || articleClass.includes('Pstart(100px)')) {
                                isFromMe = true;
                            }
                            
                            // Extrair timestamp se disponível
                            const timeEl = article.querySelector('time[datetime]');
                            let timestamp = null;
                            if (timeEl) {
                                timestamp = timeEl.getAttribute('datetime');
                            }
                            
                            // Criar chave única: conteúdo + remetente
                            // Isso evita duplicatas exatas, mas permite mensagens iguais de pessoas diferentes
                            const uniqueKey = `${isFromMe ? 'me' : 'them'}_${text}`;
                            if (seen.has(uniqueKey)) {
                                return; // Pular duplicata
                            }
                            seen.add(uniqueKey);
                            
                            messages.push({
                                content: text,
                                is_from_me: isFromMe,
                                timestamp: timestamp,
                                order: index
                            });
                        } catch (e) {
                            // Ignorar erros em mensagens individuais
                        }
                    });
                    
                    return messages;
                }
            ''')
            
            if messages_data and len(messages_data) > 0:
                # Ordenar por timestamp se disponível, senão por ordem de aparição
                def sort_key(msg):
                    ts = msg.get('timestamp')
                    if ts:
                        try:
                            # Parse ISO timestamp
                            return (0, datetime.fromisoformat(ts.replace('Z', '+00:00')))
                        except:
                            pass
                    # Fallback para ordem de aparição
                    return (1, datetime.min.replace(microsecond=msg.get('order', 0)))
                
                messages_data.sort(key=sort_key)
                
                # Deduplicação final no Python
                seen_messages = set()
                
                for msg in messages_data[-max_messages:]:
                    content = msg.get('content', '').strip()
                    is_from_me = msg.get('is_from_me', False)
                    
                    # Pular mensagens vazias
                    if not content:
                        continue
                    
                    # Normalizar conteúdo (tratar "??" como emoji)
                    content = normalize_message_content(content)
                    
                    # Chave única: conteúdo + remetente
                    unique_key = f"{'me' if is_from_me else 'them'}_{content}"
                    if unique_key in seen_messages:
                        continue
                    seen_messages.add(unique_key)
                    
                    messages.append({
                        "content": content,
                        "is_from_me": is_from_me,
                        "timestamp": msg.get('timestamp')
                    })
                
                log_automation_step(f"Extraídas {len(messages)} mensagens")
            else:
                log_automation_step("Nenhuma mensagem encontrada na primeira tentativa, tentando novamente...")
                
                # Segunda tentativa com mais espera
                await self.page.wait_for_timeout(3000)
                
                # Tentar scroll novamente
                await self.page.evaluate('''
                    () => {
                        const containers = document.querySelectorAll('div[class*="Ov(a)"]');
                        for (const container of containers) {
                            if (container.scrollHeight > container.clientHeight) {
                                container.scrollTop = 0;
                            }
                        }
                    }
                ''')
                await self.page.wait_for_timeout(2000)
                
                # Tentar extrair novamente
                messages_data = await self.page.evaluate('''
                    () => {
                        const messages = [];
                        const seen = new Set();
                        const messageElements = document.querySelectorAll('div[role="article"]');
                        
                        messageElements.forEach((article, index) => {
                            try {
                                const textSpan = article.querySelector('span.text');
                                if (!textSpan) return;
                                
                                const text = textSpan.textContent?.trim();
                                if (!text || text.length < 1) return;
                                
                                const msgDiv = article.querySelector('div.msg');
                                let isFromMe = true;
                                
                                if (msgDiv) {
                                    const classList = msgDiv.className || '';
                                    if (classList.includes('msg--received')) {
                                        isFromMe = false;
                                    }
                                }
                                
                                const articleClass = article.className || '';
                                if (articleClass.includes('Ta(start)')) {
                                    isFromMe = false;
                                } else if (articleClass.includes('Ta(e)')) {
                                    isFromMe = true;
                                }
                                
                                const timeEl = article.querySelector('time[datetime]');
                                let timestamp = null;
                                if (timeEl) {
                                    timestamp = timeEl.getAttribute('datetime');
                                }
                                
                                const uniqueKey = `${isFromMe ? 'me' : 'them'}_${text}`;
                                if (seen.has(uniqueKey)) return;
                                seen.add(uniqueKey);
                                
                                messages.push({
                                    content: text,
                                    is_from_me: isFromMe,
                                    timestamp: timestamp,
                                    order: index
                                });
                            } catch (e) {}
                        });
                        
                        return messages;
                    }
                ''')
                
                if messages_data and len(messages_data) > 0:
                    for msg in messages_data[-max_messages:]:
                        content = msg.get('content', '').strip()
                        if content:
                            # Normalizar conteúdo (tratar "??" como emoji)
                            content = normalize_message_content(content)
                            messages.append({
                                "content": content,
                                "is_from_me": msg.get('is_from_me', False),
                                "timestamp": msg.get('timestamp')
                            })
                    log_automation_step(f"Extraídas {len(messages)} mensagens (segunda tentativa)")
                else:
                    log_automation_step("Nenhuma mensagem encontrada")
            
        except Exception as e:
            logger.error(f"Erro ao extrair conversa: {e}")
        
        return messages
    
    async def send_message(self, match_id: str, message: str) -> bool:
        """
        Envia mensagem para um match.
        
        Args:
            match_id: ID do match
            message: Texto da mensagem
            
        Returns:
            True se enviou com sucesso
        """
        log_automation_step(f"Enviando mensagem para {match_id}...")
        logger.debug(f"[SEND_MESSAGE] Iniciando envio para match_id={match_id}, msg_len={len(message)}")
        
        try:
            # Navegar para conversa APENAS se necessário
            nav_success = await self._navigate_to_match_if_needed(match_id)
            logger.debug(f"[SEND_MESSAGE] Navegação completa, URL atual: {self.page.url}")
            await async_random_delay(0.5, 1)
            
            # Encontrar campo de texto - seletores atualizados Tinder 2026
            # Prioridade: placeholder específico > form textarea > fallback genérico
            input_field = await self.page.query_selector(
                'textarea[placeholder="Type a message"], '
                'textarea[placeholder="Digite uma mensagem"], '
                'form textarea[maxlength="5000"], '
                'form textarea'
            )
            
            if not input_field:
                # Tentar esperar o form carregar e buscar novamente
                logger.warning("[SEND_MESSAGE] Campo não encontrado, aguardando 30s...")
                await self.page.wait_for_timeout(30000)
                input_field = await self.page.query_selector('form textarea, textarea[placeholder*="message" i]')
            
            if not input_field:
                logger.error("[SEND_MESSAGE] Campo de mensagem não encontrado após retry - verificar seletores")
                # Log do HTML do form para debug
                form_html = await self.page.query_selector('form')
                if form_html:
                    logger.debug(f"[SEND_MESSAGE] Form encontrado mas sem textarea")
                else:
                    logger.debug(f"[SEND_MESSAGE] Nenhum form encontrado na página")
                return False
            
            logger.debug("[SEND_MESSAGE] Campo de texto encontrado, clicando...")
            
            # Clicar e focar no campo
            await input_field.click()
            await self.page.wait_for_timeout(300)
            
            # Limpar campo se tiver texto residual
            await input_field.fill("")
            
            # Digitar mensagem com delay humanizado
            logger.debug(f"[SEND_MESSAGE] Digitando mensagem ({len(message)} chars)...")
            await self.page.keyboard.type(message, delay=50)
            logger.debug("[SEND_MESSAGE] Mensagem digitada com sucesso")
            
            await async_random_delay(0.3, 0.6)
            
            # Aguardar botão ficar habilitado (remove disabled quando há texto)
            await self.page.wait_for_timeout(500)
            
            # Encontrar e clicar botão de enviar - seletores atualizados Tinder 2026
            # O botão tem type="submit" e contém <span>Send</span>
            send_button = await self.page.query_selector(
                'form button[type="submit"]:not([disabled]), '
                'form button[type="submit"]'
            )
            
            if send_button:
                # Verificar se botão está habilitado
                is_disabled = await send_button.get_attribute("disabled")
                aria_disabled = await send_button.get_attribute("aria-disabled")
                logger.debug(f"[SEND_MESSAGE] Botão encontrado - disabled={is_disabled}, aria-disabled={aria_disabled}")
                
                if is_disabled is None and aria_disabled != "true":
                    await send_button.click()
                    logger.debug("[SEND_MESSAGE] ✅ Clique no botão Send executado")
                    log_automation_step("Mensagem enviada via botão")
                else:
                    # Botão desabilitado, tentar Enter
                    logger.warning("[SEND_MESSAGE] Botão Send desabilitado, tentando Enter")
                    await self.page.keyboard.press("Enter")
                    logger.debug("[SEND_MESSAGE] ✅ Enter pressionado como fallback")
            else:
                # Fallback: Enter
                logger.warning("[SEND_MESSAGE] Botão Send não encontrado, tentando Enter")
                await self.page.keyboard.press("Enter")
                logger.debug("[SEND_MESSAGE] ✅ Enter pressionado como fallback")
            
            await async_random_delay(0.5, 1)
            
            log_automation_step("Mensagem enviada com sucesso")
            logger.debug(f"[SEND_MESSAGE] ✅ Processo completo para match_id={match_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")
            return False
