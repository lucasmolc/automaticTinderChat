"""
Sistema de A/B Testing para mensagens.
Permite testar variações de mensagens e medir performance.

Funcionalidades:
- Criação de experimentos com múltiplas variantes
- Distribuição determinística de usuários (hash-based)
- Tracking de métricas por variante
- Dashboard de resultados

Uso:
    ab_manager = get_ab_manager()
    
    # Definir experimento
    ab_manager.create_experiment(
        name='first_message_style',
        variants=['casual', 'formal', 'playful'],
        weights=[0.33, 0.33, 0.34]
    )
    
    # Obter variante para um match
    variant = ab_manager.get_variant('first_message_style', match_id='abc123')
    
    # Registrar conversão
    ab_manager.record_conversion('first_message_style', match_id='abc123', 
                                  conversion_type='response')
"""

import os
import json
import threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger

# Para hash determinístico
try:
    import mmh3
    MMHASH_AVAILABLE = True
except ImportError:
    import hashlib
    MMHASH_AVAILABLE = False
    logger.warning("mmh3 não instalado. Usando hashlib como fallback.")


@dataclass
class Variant:
    """Representa uma variante em um experimento."""
    name: str
    weight: float = 1.0
    
    # Métricas
    impressions: int = 0  # Quantas vezes foi exibida
    conversions: int = 0  # Conversões gerais
    responses: int = 0    # Respostas recebidas
    whatsapp: int = 0     # WhatsApp obtidos
    dates: int = 0        # Encontros confirmados
    
    def conversion_rate(self) -> float:
        """Taxa de conversão geral."""
        return self.conversions / self.impressions if self.impressions > 0 else 0.0
    
    def response_rate(self) -> float:
        """Taxa de resposta."""
        return self.responses / self.impressions if self.impressions > 0 else 0.0


@dataclass
class Experiment:
    """Representa um experimento A/B."""
    name: str
    variants: List[Variant] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    description: str = ""
    
    # Alocações de usuários (match_id -> variant_name)
    allocations: Dict[str, str] = field(default_factory=dict)
    
    def get_total_impressions(self) -> int:
        return sum(v.impressions for v in self.variants)
    
    def get_winning_variant(self) -> Optional[Variant]:
        """Retorna variante com melhor taxa de conversão."""
        if not self.variants:
            return None
        return max(self.variants, key=lambda v: v.conversion_rate())
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'variants': [
                {
                    'name': v.name,
                    'weight': v.weight,
                    'impressions': v.impressions,
                    'conversions': v.conversions,
                    'responses': v.responses,
                    'whatsapp': v.whatsapp,
                    'dates': v.dates,
                    'conversion_rate': round(v.conversion_rate() * 100, 2),
                    'response_rate': round(v.response_rate() * 100, 2)
                }
                for v in self.variants
            ],
            'total_impressions': self.get_total_impressions()
        }


class ABTestManager:
    """
    Gerencia experimentos A/B.
    Thread-safe e persistente em arquivo JSON.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._experiments: Dict[str, Experiment] = {}
        self._lock = threading.Lock()
        
        # Path para persistência
        if storage_path is None:
            from config.settings import PROJECT_ROOT
            storage_path = PROJECT_ROOT / 'data' / 'ab_experiments.json'
        
        self._storage_path = storage_path
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Carregar experimentos existentes
        self._load()
    
    def _hash_to_bucket(self, key: str, num_buckets: int = 100) -> int:
        """
        Gera bucket determinístico para uma chave.
        Usa MurmurHash3 se disponível (mais rápido e uniforme).
        """
        if MMHASH_AVAILABLE:
            return mmh3.hash(key, signed=False) % num_buckets
        else:
            # Fallback para hashlib
            hash_bytes = hashlib.md5(key.encode()).digest()
            hash_int = int.from_bytes(hash_bytes[:4], 'little')
            return hash_int % num_buckets
    
    def _select_variant(self, experiment: Experiment, key: str) -> Variant:
        """
        Seleciona variante de forma determinística baseada na chave.
        Usa weighted random com hash para distribuição consistente.
        """
        # Normalizar pesos
        total_weight = sum(v.weight for v in experiment.variants)
        
        # Gerar valor de 0-99 baseado no hash
        bucket = self._hash_to_bucket(f"{experiment.name}:{key}")
        
        # Selecionar variante baseado no peso acumulado
        cumulative = 0.0
        for variant in experiment.variants:
            cumulative += (variant.weight / total_weight) * 100
            if bucket < cumulative:
                return variant
        
        # Fallback para última variante
        return experiment.variants[-1]
    
    def create_experiment(
        self,
        name: str,
        variants: List[str],
        weights: Optional[List[float]] = None,
        description: str = ""
    ) -> Experiment:
        """
        Cria novo experimento A/B.
        
        Args:
            name: Nome único do experimento
            variants: Lista de nomes das variantes
            weights: Pesos de distribuição (opcional, default igual)
            description: Descrição do experimento
            
        Returns:
            Experimento criado
        """
        with self._lock:
            if name in self._experiments:
                logger.warning(f"Experimento '{name}' já existe, retornando existente")
                return self._experiments[name]
            
            # Criar variantes com pesos
            if weights is None:
                weights = [1.0] * len(variants)
            
            variant_objects = [
                Variant(name=v, weight=w)
                for v, w in zip(variants, weights)
            ]
            
            experiment = Experiment(
                name=name,
                variants=variant_objects,
                description=description
            )
            
            self._experiments[name] = experiment
            self._save()
            
            logger.info(f"🧪 Experimento criado: {name} com variantes {variants}")
            
            return experiment
    
    def get_variant(
        self,
        experiment_name: str,
        match_id: str,
        record_impression: bool = True
    ) -> Optional[str]:
        """
        Obtém variante para um match específico.
        Distribuição é determinística (mesmo match sempre recebe mesma variante).
        
        Args:
            experiment_name: Nome do experimento
            match_id: ID único do match
            record_impression: Se deve registrar impressão
            
        Returns:
            Nome da variante selecionada ou None se experimento não existe
        """
        with self._lock:
            experiment = self._experiments.get(experiment_name)
            
            if not experiment or not experiment.is_active:
                return None
            
            # Verificar se já tem alocação
            if match_id in experiment.allocations:
                variant_name = experiment.allocations[match_id]
                variant = next(
                    (v for v in experiment.variants if v.name == variant_name),
                    None
                )
            else:
                # Selecionar variante
                variant = self._select_variant(experiment, match_id)
                experiment.allocations[match_id] = variant.name
            
            # Registrar impressão
            if record_impression and variant:
                variant.impressions += 1
                self._save()
            
            return variant.name if variant else None
    
    def record_conversion(
        self,
        experiment_name: str,
        match_id: str,
        conversion_type: str = 'general'
    ) -> bool:
        """
        Registra conversão para um match.
        
        Args:
            experiment_name: Nome do experimento
            match_id: ID do match
            conversion_type: Tipo de conversão (general, response, whatsapp, date)
            
        Returns:
            True se conversão foi registrada
        """
        with self._lock:
            experiment = self._experiments.get(experiment_name)
            
            if not experiment:
                return False
            
            # Buscar variante alocada
            variant_name = experiment.allocations.get(match_id)
            if not variant_name:
                return False
            
            variant = next(
                (v for v in experiment.variants if v.name == variant_name),
                None
            )
            
            if not variant:
                return False
            
            # Registrar conversão
            if conversion_type == 'response':
                variant.responses += 1
            elif conversion_type == 'whatsapp':
                variant.whatsapp += 1
            elif conversion_type == 'date':
                variant.dates += 1
            
            variant.conversions += 1
            
            self._save()
            
            logger.debug(
                f"🧪 Conversão registrada: {experiment_name}/{variant_name} "
                f"({conversion_type}) para match {match_id[:8]}..."
            )
            
            return True
    
    def get_experiment(self, name: str) -> Optional[Experiment]:
        """Retorna experimento pelo nome."""
        return self._experiments.get(name)
    
    def get_all_experiments(self) -> List[Dict]:
        """Retorna todos os experimentos como dicionários."""
        with self._lock:
            return [exp.to_dict() for exp in self._experiments.values()]
    
    def get_experiment_results(self, name: str) -> Optional[Dict]:
        """
        Retorna resultados detalhados de um experimento.
        Inclui estatísticas e análise de significância.
        """
        experiment = self._experiments.get(name)
        
        if not experiment:
            return None
        
        result = experiment.to_dict()
        
        # Adicionar análise
        winning = experiment.get_winning_variant()
        if winning:
            result['winning_variant'] = winning.name
            result['winning_conversion_rate'] = round(winning.conversion_rate() * 100, 2)
        
        # Calcular lift relativo à primeira variante (controle)
        if len(experiment.variants) > 1:
            control = experiment.variants[0]
            control_rate = control.conversion_rate()
            
            for variant_data in result['variants'][1:]:
                variant_rate = variant_data['conversion_rate'] / 100
                if control_rate > 0:
                    lift = ((variant_rate - control_rate) / control_rate) * 100
                    variant_data['lift_vs_control'] = round(lift, 2)
                else:
                    variant_data['lift_vs_control'] = 0
        
        return result
    
    def pause_experiment(self, name: str) -> bool:
        """Pausa um experimento."""
        with self._lock:
            if name in self._experiments:
                self._experiments[name].is_active = False
                self._save()
                return True
            return False
    
    def resume_experiment(self, name: str) -> bool:
        """Retoma um experimento."""
        with self._lock:
            if name in self._experiments:
                self._experiments[name].is_active = True
                self._save()
                return True
            return False
    
    def delete_experiment(self, name: str) -> bool:
        """Remove um experimento."""
        with self._lock:
            if name in self._experiments:
                del self._experiments[name]
                self._save()
                return True
            return False
    
    def _save(self):
        """Persiste experimentos em arquivo JSON."""
        try:
            data = {}
            for name, exp in self._experiments.items():
                data[name] = {
                    'name': exp.name,
                    'description': exp.description,
                    'is_active': exp.is_active,
                    'created_at': exp.created_at.isoformat(),
                    'variants': [
                        {
                            'name': v.name,
                            'weight': v.weight,
                            'impressions': v.impressions,
                            'conversions': v.conversions,
                            'responses': v.responses,
                            'whatsapp': v.whatsapp,
                            'dates': v.dates
                        }
                        for v in exp.variants
                    ],
                    'allocations': exp.allocations
                }
            
            with open(self._storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Erro ao salvar experimentos: {e}")
    
    def _load(self):
        """Carrega experimentos de arquivo JSON."""
        if not self._storage_path.exists():
            return
        
        try:
            with open(self._storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for name, exp_data in data.items():
                variants = [
                    Variant(
                        name=v['name'],
                        weight=v.get('weight', 1.0),
                        impressions=v.get('impressions', 0),
                        conversions=v.get('conversions', 0),
                        responses=v.get('responses', 0),
                        whatsapp=v.get('whatsapp', 0),
                        dates=v.get('dates', 0)
                    )
                    for v in exp_data.get('variants', [])
                ]
                
                experiment = Experiment(
                    name=exp_data['name'],
                    variants=variants,
                    description=exp_data.get('description', ''),
                    is_active=exp_data.get('is_active', True),
                    created_at=datetime.fromisoformat(
                        exp_data.get('created_at', datetime.utcnow().isoformat())
                    ),
                    allocations=exp_data.get('allocations', {})
                )
                
                self._experiments[name] = experiment
            
            logger.info(f"📂 Carregados {len(self._experiments)} experimentos A/B")
            
        except Exception as e:
            logger.error(f"Erro ao carregar experimentos: {e}")


# Instância global
_ab_manager: Optional[ABTestManager] = None


def get_ab_manager() -> ABTestManager:
    """Retorna instância global do gerenciador de A/B testing."""
    global _ab_manager
    if _ab_manager is None:
        _ab_manager = ABTestManager()
    return _ab_manager


# ==========================================
# Experimentos pré-configurados
# ==========================================

def setup_default_experiments():
    """
    Configura experimentos padrão.
    Chamar na inicialização da aplicação.
    TODOS focados em FLERTE e ATRAÇÃO - sem variantes neutras.
    """
    manager = get_ab_manager()
    
    # Experimento de estilo de FLERTE (não mais estilo neutro)
    if not manager.get_experiment('first_message_style'):
        manager.create_experiment(
            name='first_message_style',
            variants=['playful', 'confident', 'intriguing'],
            weights=[0.33, 0.33, 0.34],
            description='Testa estilos de flerte: brincalhão vs confiante vs misterioso'
        )
    
    # Experimento de intensidade do flerte
    if not manager.get_experiment('flirt_intensity'):
        manager.create_experiment(
            name='flirt_intensity',
            variants=['subtle', 'moderate', 'direct'],
            weights=[0.33, 0.33, 0.34],
            description='Testa intensidade do flerte: sutil vs moderado vs direto'
        )
    
    # Experimento de uso de emoji (focado em flerte)
    if not manager.get_experiment('emoji_usage'):
        manager.create_experiment(
            name='emoji_usage',
            variants=['no_emoji', 'minimal', 'flirty'],
            weights=[0.33, 0.33, 0.34],
            description='Testa emojis: sem vs mínimo vs emojis de flerte'
        )
    
    logger.info("🧪 Experimentos A/B de FLERTE configurados")
