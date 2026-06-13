"""
DataValidationService - Serviço de validação de dados para persistência.

Este serviço é responsável por:
- Validar e normalizar dados antes de salvar no banco
- Garantir integridade dos campos
- Rejeitar dados inválidos com logging
- Aplicar regras de negócio de validação

Usado pelo SYNC para garantir que apenas dados válidos são persistidos.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


# ==================== PADRÕES DE VALIDAÇÃO ====================

# Padrões de nome inválido
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

# Padrões de bio que indicam texto de UI (não bio real)
UI_TEXT_PATTERNS = [
    r'^sobre mim$',
    r'^about me$',
    r'^interesses$',
    r'^interests$',
    r'^básico$',
    r'^basic info$',
]

UI_TEXT_REGEX = re.compile('|'.join(UI_TEXT_PATTERNS), re.IGNORECASE)


class DataValidationService:
    """
    Serviço centralizado de validação de dados.
    
    Garante que todos os dados salvos no banco são válidos e normalizados.
    """
    
    @staticmethod
    def validate_name(name: Optional[str], fallback: str = "Unknown") -> Tuple[str, bool]:
        """
        Valida e normaliza nome de match.
        
        Extrai nome válido de textos como "Você deu Match com Maria em..."
        
        Args:
            name: Nome a validar
            fallback: Valor padrão se inválido
            
        Returns:
            Tuple (nome_validado, is_valid)
        """
        if not name or not isinstance(name, str):
            return fallback, False
        
        name = name.strip()
        
        # Muito curto
        if len(name) < 2:
            logger.debug(f"Nome rejeitado (muito curto): '{name}'")
            return fallback, False
        
        # Se contém texto de match, tentar extrair nome
        if 'match' in name.lower() and len(name) > 30:
            match = re.search(r'(?:com|with)\s+([A-Za-zÀ-ÿ]+)', name, re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                if len(extracted) >= 2 and len(extracted) <= 30:
                    logger.debug(f"Nome extraído de texto: '{name[:40]}...' -> '{extracted}'")
                    return extracted, True
            logger.debug(f"Nome rejeitado (texto de match): '{name[:40]}...'")
            return fallback, False
        
        # Muito longo
        if len(name) > 50:
            logger.debug(f"Nome rejeitado (muito longo): '{name[:40]}...'")
            return fallback, False
        
        # Contém padrões inválidos
        if INVALID_NAME_REGEX.search(name):
            logger.debug(f"Nome rejeitado (padrão inválido): '{name[:30]}...'")
            return fallback, False
        
        # Muitas palavras
        words = name.split()
        if len(words) > 3:
            match = re.search(r'(?:com|with)\s+([A-Za-zÀ-ÿ]+)', name, re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                if len(extracted) >= 2 and not INVALID_NAME_REGEX.search(extracted):
                    return extracted, True
            return fallback, False
        
        return name, True
    
    @staticmethod
    def validate_bio(bio: Optional[str]) -> Tuple[Optional[str], bool]:
        """
        Valida bio de perfil.
        
        Rejeita textos que são claramente UI do Tinder (não bio real).
        
        Args:
            bio: Bio a validar
            
        Returns:
            Tuple (bio_validada, is_valid)
        """
        if not bio or not isinstance(bio, str):
            return None, True  # Bio vazia é válida (campo opcional)
        
        bio = bio.strip()
        
        # Muito curta para ser útil
        if len(bio) < 5:
            return None, True
        
        # É texto de UI, não bio
        if UI_TEXT_REGEX.match(bio):
            logger.debug(f"Bio rejeitada (texto de UI): '{bio}'")
            return None, False
        
        # Limitar tamanho
        if len(bio) > 2000:
            bio = bio[:2000]
        
        return bio, True
    
    @staticmethod
    def validate_age(age: Optional[int]) -> Tuple[Optional[int], bool]:
        """
        Valida idade.
        
        Args:
            age: Idade a validar
            
        Returns:
            Tuple (idade_validada, is_valid)
        """
        if age is None:
            return None, True
        
        try:
            age = int(age)
        except (ValueError, TypeError):
            return None, False
        
        # Idade razoável para app de namoro
        if age < 18 or age > 100:
            logger.debug(f"Idade rejeitada (fora do range): {age}")
            return None, False
        
        return age, True
    
    @staticmethod
    def validate_photo_url(url: Optional[str]) -> Tuple[Optional[str], bool]:
        """
        Valida URL de foto.
        
        Args:
            url: URL a validar
            
        Returns:
            Tuple (url_validada, is_valid)
        """
        if not url or not isinstance(url, str):
            return None, True
        
        url = url.strip()
        
        # Verificar se é URL válida do Tinder
        if not url.startswith(('http://', 'https://')):
            return None, False
        
        # Rejeitar URLs de ícones/assets
        invalid_patterns = ['/icons/', 'static-assets', '.gif', '84x84', '84x106']
        for pattern in invalid_patterns:
            if pattern in url.lower():
                return None, False
        
        return url, True
    
    @staticmethod
    def validate_match_data(data: Dict) -> Tuple[Dict, List[str]]:
        """
        Valida todos os campos de um match.
        
        Args:
            data: Dict com dados do match
            
        Returns:
            Tuple (dados_validados, lista_de_warnings)
        """
        warnings = []
        validated = {}
        
        # Nome (obrigatório)
        name, name_valid = DataValidationService.validate_name(data.get("name"))
        validated["name"] = name
        if not name_valid:
            warnings.append(f"Nome inválido: '{data.get('name', '')[:30]}'")
        
        # Idade
        age, age_valid = DataValidationService.validate_age(data.get("age"))
        validated["age"] = age
        if not age_valid and data.get("age"):
            warnings.append(f"Idade inválida: {data.get('age')}")
        
        # Bio
        bio, bio_valid = DataValidationService.validate_bio(data.get("bio"))
        validated["bio"] = bio
        if not bio_valid:
            warnings.append("Bio rejeitada (texto de UI)")
        
        # Foto
        photo, photo_valid = DataValidationService.validate_photo_url(
            data.get("profile_photo_url")
        )
        validated["profile_photo_url"] = photo
        
        # Campos que não precisam validação especial (passar direto se existem)
        passthrough_fields = [
            "tinder_match_id", "distance_km", "job_title", "school",
            "gender", "city", "relationship_intent", "sexual_orientations",
            "relationship_type", "lifestyle_info", "is_verified", "matched_at",
            "interests", "photos", "has_messages", "last_message_preview"
        ]
        
        for field in passthrough_fields:
            if field in data and data[field] is not None:
                validated[field] = data[field]
        
        return validated, warnings
    
    @staticmethod
    def is_data_complete_for_ai(data: Dict) -> bool:
        """
        Verifica se dados são suficientes para enviar para IA.
        
        Args:
            data: Dict com dados validados
            
        Returns:
            True se dados são suficientes
        """
        name = data.get("name", "Unknown")
        
        # Nome deve ser válido (não "Unknown")
        if name == "Unknown":
            return False
        
        # Deve ter algum contexto sobre a pessoa (bio ou job)
        has_context = bool(data.get("bio") or data.get("job_title"))
        
        return has_context


# Singleton instance
_validation_service: Optional[DataValidationService] = None


def get_validation_service() -> DataValidationService:
    """Retorna instância singleton do serviço de validação."""
    global _validation_service
    if _validation_service is None:
        _validation_service = DataValidationService()
    return _validation_service
