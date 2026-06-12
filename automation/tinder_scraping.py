"""
Módulo centralizado com funções de extração compartilhadas.
Evita duplicação de código entre extractors.py, profile_syncer.py e sync_handler.py.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Set
from playwright.async_api import Page

from utils.logger import get_logger

logger = get_logger(__name__)


# =====================================================
# JAVASCRIPT COMPARTILHADO PARA EXTRAÇÃO DE FOTOS
# =====================================================

# Script JavaScript para extrair fotos de perfil do Tinder
# Usado tanto para meu perfil quanto para perfis de matches
EXTRACT_PHOTOS_JS = '''
    () => {
        const photos = [];
        const seen = new Set();
        
        // Função para validar se é foto de perfil válida
        function isValidProfilePhoto(url) {
            if (!url) return false;
            // Deve ser do Tinder CDN
            if (!url.includes('gotinder.com')) return false;
            // Ignorar GIFs e ícones
            if (url.toLowerCase().includes('.gif')) return false;
            if (url.includes('/icons/') || url.includes('static-assets')) return false;
            // Ignorar thumbnails muito pequenos da sidebar (84x84, 84x106)
            if (url.includes('84x84') || url.includes('84x106')) return false;
            // Ignorar URLs de proxy
            if (url.includes('u=https')) return false;
            return true;
        }
        
        // Função para extrair URL de background-image
        function extractBgUrl(element) {
            const style = element.getAttribute('style') || '';
            const match = style.match(/background-image:\\s*url\\(["']?([^"')]+)["']?\\)/i);
            return match ? match[1] : null;
        }
        
        // =====================================================
        // 1. PRINCIPAL: Buscar nas divs com classe específica do Tinder
        // Estrutura: div.profileCard__slider__img.sentry-block com background-image
        // =====================================================
        const sliderPhotos = document.querySelectorAll(
            '.profileCard__slider__img.sentry-block, ' +
            '.profileCard__slider__img[style*="background-image"], ' +
            '[class*="profileCard__slider__img"][style*="background-image"]'
        );
        sliderPhotos.forEach((div) => {
            const url = extractBgUrl(div);
            if (url && isValidProfilePhoto(url) && !seen.has(url)) {
                seen.add(url);
                photos.push({ url: url, order: photos.length });
            }
        });
        
        // 2. Buscar dentro de keen-slider__slide (estrutura do carrossel)
        if (photos.length === 0) {
            const slides = document.querySelectorAll('.keen-slider__slide, [class*="keen-slider__slide"]');
            slides.forEach((slide) => {
                const bgDivs = slide.querySelectorAll('[style*="background-image"]');
                bgDivs.forEach((div) => {
                    const url = extractBgUrl(div);
                    if (url && isValidProfilePhoto(url) && !seen.has(url)) {
                        seen.add(url);
                        photos.push({ url: url, order: photos.length });
                    }
                });
            });
        }
        
        // 3. Fallback: Buscar qualquer div com background-image do gotinder
        if (photos.length === 0) {
            const allBgDivs = document.querySelectorAll('[style*="background-image"]');
            allBgDivs.forEach((div) => {
                const url = extractBgUrl(div);
                if (url && isValidProfilePhoto(url) && !seen.has(url)) {
                    seen.add(url);
                    photos.push({ url: url, order: photos.length });
                }
            });
        }
        
        // 4. Último recurso: tags img
        if (photos.length === 0) {
            const imgs = document.querySelectorAll('img[src*="gotinder.com"]');
            imgs.forEach((img) => {
                const src = img.src;
                if (isValidProfilePhoto(src) && !seen.has(src)) {
                    seen.add(src);
                    photos.push({ url: src, order: photos.length });
                }
            });
        }
        
        return photos.slice(0, 9); // Máximo 9 fotos como no Tinder
    }
'''


# Script JavaScript para extrair a bio do perfil
EXTRACT_BIO_JS = '''
    () => {
        // Lista de textos a ignorar completamente
        const SKIP_TEXTS = [
            'pular para o conteúdo principal',
            'skip to main content',
            'pular para',
            'skip to'
        ];
        
        function shouldSkip(text) {
            if (!text) return true;
            const lower = text.toLowerCase().trim();
            for (const skip of SKIP_TEXTS) {
                if (lower.includes(skip)) return true;
            }
            return false;
        }
        
        // Método 1: Buscar seção "About me" pela estrutura exata
        const h2Elements = document.querySelectorAll('h2');
        for (const h2 of h2Elements) {
            const h2Text = h2.textContent?.toLowerCase() || '';
            if (h2Text.includes('about me') || h2Text.includes('sobre mim')) {
                let container = h2.parentElement;
                for (let i = 0; i < 3 && container; i++) {
                    if (container.nextElementSibling) {
                        const bioDiv = container.nextElementSibling;
                        const bioText = bioDiv.textContent?.trim();
                        if (bioText && bioText.length > 20 && !shouldSkip(bioText)) {
                            return bioText;
                        }
                    }
                    container = container.parentElement;
                }
            }
        }
        
        // Método 2: Buscar pelo padrão de classes específico da bio
        const bioDivs = document.querySelectorAll('div');
        for (const div of bioDivs) {
            const cls = div.className || '';
            if (cls.includes('C($c-ds-text-primary)') && cls.includes('Typs(body-1-regular)')) {
                const text = div.textContent?.trim();
                if (text && text.length > 20 && !shouldSkip(text)) {
                    return text;
                }
            }
        }
        
        // Método 3: textarea
        const textarea = document.querySelector('textarea');
        if (textarea && textarea.value?.trim().length > 10) {
            const val = textarea.value.trim();
            if (!shouldSkip(val)) return val;
        }
        
        return null;
    }
'''


# Script JavaScript para extrair lista de matches
EXTRACT_MATCHES_LIST_JS = '''
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
            
            // Verificar se há preview de mensagem
            const messagePreview = link.querySelector('span[class*="Ell"]');
            const allSpans = link.querySelectorAll('span');
            let textSpans = 0;
            
            allSpans.forEach(span => {
                const text = span.textContent?.trim();
                if (text && text.length > 0 && !text.includes(name)) {
                    textSpans++;
                }
            });
            
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
'''


# =====================================================
# FUNÇÕES COMPARTILHADAS EM PYTHON
# =====================================================

async def extract_photos_from_page(page: Page) -> List[Dict]:
    """
    Extrai todas as fotos visíveis do perfil na página atual.
    
    Função centralizada usada por:
    - extract_my_profile()
    - extract_match_profile()
    
    Args:
        page: Playwright Page
        
    Returns:
        Lista de dicts com {url, order}
    """
    try:
        photos_data = await page.evaluate(EXTRACT_PHOTOS_JS)
        return photos_data if photos_data else []
    except Exception as e:
        logger.debug(f"Erro ao extrair fotos via JS: {e}")
        return []


async def extract_bio_from_page(page: Page) -> Optional[str]:
    """
    Extrai a bio do perfil da página atual.
    
    Função centralizada usada por:
    - extract_my_profile()
    - extract_match_profile()
    
    Args:
        page: Playwright Page
        
    Returns:
        Texto da bio ou None
    """
    try:
        bio_text = await page.evaluate(EXTRACT_BIO_JS)
        
        # Filtro final de segurança
        if bio_text and len(bio_text) > 15:
            skip_check = bio_text.lower().strip()
            if 'pular' in skip_check or 'skip to' in skip_check:
                return None
            return bio_text
        return None
        
    except Exception as e:
        logger.debug(f"Erro ao extrair bio via JS: {e}")
        return None


async def extract_matches_list_from_page(page: Page) -> List[Dict]:
    """
    Extrai lista de matches da página atual (aba Matches ou Mensagens).
    
    Função centralizada usada por:
    - extract_matches_list()
    - extract_messages_list()
    
    Args:
        page: Playwright Page
        
    Returns:
        Lista de dicts com dados dos matches
    """
    try:
        cards_data = await page.evaluate(EXTRACT_MATCHES_LIST_JS)
        return cards_data if cards_data else []
    except Exception as e:
        logger.debug(f"Erro ao extrair lista de matches via JS: {e}")
        return []


def parse_match_date(text: str, is_portuguese: bool = True) -> Optional[datetime]:
    """
    Faz parsing de uma data de match a partir de texto.
    
    Função centralizada usada por:
    - extract_match_profile()
    - extract_match_date_from_current_page()
    
    Args:
        text: Texto contendo a data (ex: "1/23/2026")
        is_portuguese: Se o idioma é português (afeta ordem dia/mês)
        
    Returns:
        datetime ou None
    """
    if not text:
        return None
    
    # Escolher formato baseado no idioma
    if is_portuguese:
        formats = ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%m/%d/%Y', '%m-%d-%Y']
    else:
        formats = ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y', '%m-%d-%y', '%d/%m/%Y', '%d-%m-%Y']
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            # Validar que a data não está no futuro
            if parsed <= datetime.now():
                return parsed
        except ValueError:
            continue
    
    return None


def extract_date_from_text(page_text: str) -> Optional[datetime]:
    """
    Extrai data de match de um texto de página.
    
    Args:
        page_text: Texto da página
        
    Returns:
        datetime ou None
    """
    # Detectar idioma
    is_portuguese = 'você' in page_text.lower() or 'match com' in page_text.lower()
    
    # Padrões para encontrar data
    date_patterns = [
        r'(?:You matched with|Você deu match com)\s+.+?\s+(?:on|em)\s+([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})',
        r'(?:em|on)[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})',
        r'Match(?:ed)?[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})'
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            parsed = parse_match_date(date_str, is_portuguese)
            if parsed:
                return parsed
    
    return None


def filter_valid_photos(photos: List[Dict]) -> List[Dict]:
    """
    Filtra lista de fotos removendo inválidas.
    
    Args:
        photos: Lista de {url, order}
        
    Returns:
        Lista filtrada
    """
    return [
        p for p in photos
        if p.get('url')
        and 'gotinder.com' in p.get('url', '')
        and '/icons/' not in p.get('url', '')
        and 'static-assets' not in p.get('url', '')
        and '.gif' not in p.get('url', '').lower()
        and '84x84' not in p.get('url', '')
        and '84x106' not in p.get('url', '')
    ]


# =====================================================
# VALIDADOR DE MATCH ID
# =====================================================

# Regex para validar match_id (alfanumérico com alguns caracteres especiais)
VALID_MATCH_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{5,100}$')


def validate_match_id(match_id: str) -> bool:
    """
    Valida que o match_id é seguro para uso em URLs.
    
    Args:
        match_id: ID do match a validar
        
    Returns:
        True se válido, False caso contrário
    """
    if not match_id or not isinstance(match_id, str):
        return False
    return bool(VALID_MATCH_ID_PATTERN.match(match_id))


# =====================================================
# NAVEGAÇÃO COMPARTILHADA
# =====================================================

async def navigate_to_match_chat(page: Page, match_id: str, timeout: int = 30000) -> bool:
    """
    Navega para o chat de um match, evitando reload se já estiver lá.
    
    Função centralizada para evitar duplicação entre:
    - TinderDataExtractor._navigate_to_match_if_needed()
    - ProfileSyncer._navigate_to_match_chat()
    
    Args:
        page: Playwright Page
        match_id: ID do match no Tinder
        timeout: Timeout para navegação em ms
        
    Returns:
        True se navegou com sucesso
        
    Raises:
        ValueError: Se match_id for inválido
    """
    if not validate_match_id(match_id):
        raise ValueError(f"match_id inválido: {match_id}")
    
    target_path = f"/messages/{match_id}"
    current_url = page.url
    
    # Verificar se já está na URL correta
    if target_path in current_url:
        logger.debug(f"Já está na página do chat {match_id}, pulando navegação")
        return True
    
    # Navegar apenas se necessário
    try:
        await page.goto(f"https://tinder.com/app/messages/{match_id}", timeout=timeout)
        await page.wait_for_load_state("networkidle")
        return True
    except Exception as e:
        logger.error(f"Erro ao navegar para chat {match_id}: {e}")
        return False


async def navigate_to_matches_page(page: Page, matches_url: str) -> bool:
    """
    Navega para a página de matches apenas se não estiver lá.
    
    Args:
        page: Playwright Page
        matches_url: URL da página de matches
        
    Returns:
        True se navegou com sucesso
    """
    current_url = page.url
    
    if "/app/matches" in current_url or "/app/recs" in current_url:
        logger.debug("Já está na página de matches, pulando navegação")
        return True
    
    try:
        await page.goto(matches_url)
        await page.wait_for_load_state("networkidle")
        return True
    except Exception as e:
        logger.error(f"Erro ao navegar para matches: {e}")
        return False
