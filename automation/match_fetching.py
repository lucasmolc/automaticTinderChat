"""
Busca e extração de dados de matches.
Módulo especializado em fetching de dados com retry e cache.
"""

import re
import asyncio
from typing import Optional, Dict, List, Tuple
from functools import wraps

from database import MatchRepository, Match
from utils.logger import get_logger, log_automation_step
from utils.cache import get_profile_cache

logger = get_logger(__name__)


# ===================== VALIDAÇÃO DE NOME =====================

# Padrões de texto inválido que não são nomes reais
INVALID_NAME_PATTERNS = [
    r'você deu match',
    r'you matched',
    r'match com',
    r'matched with',
    r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}',  # Datas
    r'^\d+$',  # Só números
    r'^unknown$',
    r'^[^a-zA-ZÀ-ÿ]+$',  # Sem letras
]

INVALID_NAME_REGEX = re.compile('|'.join(INVALID_NAME_PATTERNS), re.IGNORECASE)


def validate_and_clean_name(name: Optional[str], fallback: str = "Unknown") -> str:
    """
    Valida e limpa o nome de um match.
    
    Rejeita nomes que:
    - São muito longos (> 50 chars) - provavelmente texto da tela errado
    - Contêm padrões de "Você deu Match com..." 
    - Contêm datas
    - Não têm letras
    
    Args:
        name: Nome a validar
        fallback: Valor padrão se inválido
        
    Returns:
        Nome limpo ou fallback
    """
    if not name or not isinstance(name, str):
        return fallback
    
    name = name.strip()
    
    # Muito curto
    if len(name) < 2:
        logger.debug(f"Nome rejeitado (muito curto): '{name}'")
        return fallback
    
    # Se tem texto de match ("Você deu Match com..." ou "You matched with..."), extrair nome
    if 'match' in name.lower() and len(name) > 30:
        # Tentar extrair nome do texto
        match = re.search(r'(?:com|with)\s+([A-Za-zÀ-ÿ]+)', name, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            if len(extracted) >= 2 and len(extracted) <= 30:
                logger.debug(f"Nome extraído de texto: '{name[:40]}...' -> '{extracted}'")
                return extracted
        logger.debug(f"Nome rejeitado (texto de match sem nome extraível): '{name[:40]}...'")
        return fallback
    
    # Muito longo (provavelmente texto errado)
    if len(name) > 50:
        logger.debug(f"Nome rejeitado (muito longo): '{name[:40]}...'")
        return fallback
    
    # Contém padrões inválidos
    if INVALID_NAME_REGEX.search(name):
        logger.debug(f"Nome rejeitado (padrão inválido): '{name[:30]}...'")
        return fallback
    
    # Se tem muitas palavras (> 3), pode ser texto errado
    words = name.split()
    if len(words) > 3:
        # Tentar extrair nome do texto
        match = re.search(r'(?:com|with)\s+([A-Za-zÀ-ÿ]+)', name, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            if len(extracted) >= 2 and not INVALID_NAME_REGEX.search(extracted):
                logger.debug(f"Nome extraído de texto: '{name[:30]}...' -> '{extracted}'")
                return extracted
        logger.debug(f"Nome rejeitado (muitas palavras): '{name[:30]}...'")
        return fallback
    
    return name


# ===================== RETRY DECORATOR =====================

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
    """
    Decorator para retry com backoff exponencial.
    
    Args:
        max_retries: Número máximo de tentativas
        base_delay: Delay base em segundos
        max_delay: Delay máximo em segundos
    
    Usage:
        @retry_with_backoff(max_retries=3)
        async def fetch_data():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        # Calcular delay com backoff exponencial
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            f"Tentativa {attempt + 1}/{max_retries} falhou para {func.__name__}: {e}. "
                            f"Aguardando {delay:.1f}s antes de retry..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"Todas as {max_retries} tentativas falharam para {func.__name__}: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


# ===================== MATCH DATA FETCHER =====================

class MatchDataFetcher:
    """
    Busca dados do match de forma inteligente: banco primeiro, tela se necessário.
    Centraliza lógica duplicada em send_first_messages() e respond_to_messages().
    """
    
    def __init__(self, match_repo: MatchRepository, extractor, my_profile_data: Dict):
        """
        Args:
            match_repo: Repositório de matches
            extractor: TinderDataExtractor
            my_profile_data: Dados do meu perfil (para interesses em comum)
        """
        self.match_repo = match_repo
        self.extractor = extractor
        self.my_profile_data = my_profile_data
        self.my_interests = set(my_profile_data.get('interests', []))
        self._cache = get_profile_cache()
    
    def get_match_profile_from_db(self, match: Match) -> Dict:
        """
        Extrai dados do match do banco de dados.
        Valida o nome para garantir que não é texto incorreto.
        
        Args:
            match: Match do banco
            
        Returns:
            Dict com dados do perfil
        """
        # Validar nome do banco (pode estar incorreto de sincronizações anteriores)
        validated_name = validate_and_clean_name(match.name, "Unknown")
        
        return {
            'name': validated_name,
            'age': match.age,
            'bio': match.bio,
            'distance_km': match.distance_km,
            'job_title': match.job_title,
            'school': match.school,
            'gender': match.gender,
            'city': match.city,
            'relationship_intent': match.relationship_intent,
            'sexual_orientations': match.sexual_orientations,
            'interests': self.match_repo.get_interests(match),
            'photos_count': match.photos_count,
            'is_verified': match.is_verified,
        }
    
    def needs_screen_fetch(self, match: Match) -> bool:
        """
        Verifica se precisa buscar dados na tela.
        
        Returns:
            True se falta info importante (nome válido ou bio/job)
        """
        # Validar se o nome é válido ou é "Unknown"/inválido
        validated_name = validate_and_clean_name(match.name, None)
        has_valid_name = validated_name is not None and validated_name != "Unknown"
        
        return not has_valid_name or (not match.bio and not match.job_title)
    
    @retry_with_backoff(max_retries=2, base_delay=2.0)
    async def fetch_from_screen(self, match: Match) -> Optional[Dict]:
        """
        Busca dados do perfil na tela do Tinder com retry.
        
        Returns:
            Dict com dados do perfil ou None se unmatch
        """
        log_automation_step(f"Buscando dados na tela para {match.name or match.tinder_match_id}...")
        
        fetched = await self.extractor.extract_match_profile(match.tinder_match_id)
        
        # Verificar unmatch
        if fetched.get('not_found') or fetched.get('unmatched'):
            return None
        
        return fetched
    
    async def get_match_data_for_ai(self, match: Match) -> Tuple[Optional[Dict], bool]:
        """
        Obtém dados completos do match para enviar para IA.
        Busca do banco primeiro, complementa com tela se necessário.
        SEMPRE valida o nome para evitar textos incorretos.
        
        Args:
            match: Match a buscar dados
            
        Returns:
            Tuple (profile_data: Optional[Dict], was_unmatched: bool)
            - (None, True) se foi unmatch
            - (Dict, False) se obteve dados com sucesso
        """
        # 0. Verificar cache primeiro
        cached = self._cache.get(match.tinder_match_id)
        if cached:
            # Validar nome mesmo do cache
            cached['name'] = validate_and_clean_name(cached.get('name'), "Unknown")
            logger.debug(f"Cache hit para {cached['name']} ({match.tinder_match_id[:12]}...)")
            return cached, False
        
        # 1. Buscar dados do banco (já valida o nome)
        profile_data = self.get_match_profile_from_db(match)
        
        # 2. Verificar se precisa buscar na tela
        if not self.needs_screen_fetch(match):
            self._cache.set(match.tinder_match_id, profile_data)
            return profile_data, False
        
        # 3. Buscar na tela
        try:
            fetched = await self.fetch_from_screen(match)
            
            if fetched is None:
                # Unmatch detectado
                return None, True
            
            # 4. Mesclar dados da tela no profile
            # IMPORTANTE: Validar nome da tela antes de usar
            for key in ['bio', 'age', 'job_title', 'school', 'distance_km',
                       'interests', 'gender', 'city', 'relationship_intent',
                       'sexual_orientations', 'relationship_type', 'lifestyle_info']:
                if fetched.get(key):
                    profile_data[key] = fetched.get(key)
            
            # Tratar nome separadamente com validação
            fetched_name = fetched.get('name')
            if fetched_name:
                validated_fetched_name = validate_and_clean_name(fetched_name)
                # Só atualiza se o nome da tela é válido E melhor que "Unknown"
                if validated_fetched_name != "Unknown" or profile_data.get('name') == "Unknown":
                    profile_data['name'] = validated_fetched_name
            
            if fetched.get('verified'):
                profile_data['is_verified'] = fetched.get('verified')
            
            # 5. Atualizar banco com dados novos (com nome validado)
            fetched['name'] = profile_data['name']  # Usar nome validado
            fetched['my_interests'] = list(self.my_interests)
            self.match_repo.update_from_profile(match, fetched)
            
            # 6. Cachear resultado
            self._cache.set(match.tinder_match_id, profile_data)
            
            return profile_data, False
            
        except Exception as e:
            logger.warning(f"Erro ao buscar dados da tela para {profile_data.get('name', match.tinder_match_id)}: {e}")
            # Retornar dados do banco mesmo com erro na tela
            return profile_data, False
    
    def get_common_interests(self, match_interests: List[str]) -> List[str]:
        """
        Calcula interesses em comum entre meu perfil e o match.
        
        Args:
            match_interests: Lista de interesses do match
            
        Returns:
            Lista de interesses em comum
        """
        match_interests_set = set(match_interests or [])
        return list(self.my_interests & match_interests_set)


# ===================== PROFILE EXTRACTION HELPER =====================

async def extract_complete_profile(extractor, match_id: str) -> Dict:
    """
    Extrai perfil completo de um match, combinando dados do perfil com fallbacks do header.
    
    Centraliza a lógica duplicada em sync_matches_only() que extrai perfil
    e depois faz fallback para dados do header.
    
    Args:
        extractor: TinderDataExtractor
        match_id: ID do match no Tinder
        
    Returns:
        Dict com todos os dados disponíveis do perfil
    """
    # Extrair perfil principal
    profile = await extractor.extract_match_profile(match_id)
    
    # Extrair dados do header como fallback
    if not profile.get('age'):
        header_age = await extractor.extract_match_age_from_header()
        if header_age:
            profile['age'] = header_age
    
    if not profile.get('matched_at'):
        matched_at = await extractor.extract_match_date_from_current_page()
        if matched_at:
            profile['matched_at'] = matched_at
    
    if not profile.get('name'):
        header_name = await extractor.extract_match_name_from_header()
        if header_name:
            profile['name'] = header_name
    
    # Foto do header sempre é útil
    header_photo = await extractor.extract_match_photo_from_header()
    if header_photo:
        profile['profile_photo_url'] = header_photo
    
    return profile
