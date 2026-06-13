"""
Sistema de ML Adaptativo para Prompts.
Usa dados do A/B testing para ajustar prompts automaticamente.

Funcionalidades:
- Analisa resultados de experimentos para identificar padrões de sucesso
- Ajusta pesos de variantes automaticamente baseado em performance
- Gera sugestões de novos prompts baseado em conversas bem-sucedidas
- Armazena embeddings de mensagens para matching de perfis similares

Fase 1 - Prompt Engineering Adaptativo:
- Thompson Sampling para alocação de variantes
- Ajuste automático de pesos baseado em conversões
- Sistema de scoring de prompts

Uso:
    from services.ml_adaptive import get_ml_service
    
    ml = get_ml_service()
    
    # Obter variante otimizada
    variant = ml.get_optimized_variant('first_message_style', match_profile)
    
    # Registrar resultado
    ml.record_outcome(match_id, 'response', message_sent)
"""

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from utils.ab_testing import ABTestManager, get_ab_manager
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PromptPerformance:
    """Métricas de performance de um prompt/variante."""
    variant_name: str
    experiment_name: str
    
    # Métricas brutas
    total_uses: int = 0
    responses: int = 0
    whatsapp: int = 0
    dates: int = 0
    
    # Métricas de qualidade (feedback implícito)
    avg_response_length: float = 0.0  # Comprimento médio das respostas (engajamento)
    avg_conversation_turns: float = 0.0  # Turnos de conversa antes de conversão
    
    # Thompson Sampling parameters (Beta distribution)
    alpha: float = 1.0  # Sucessos + prior
    beta: float = 1.0   # Falhas + prior
    
    # Timestamp
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def response_rate(self) -> float:
        """Taxa de resposta."""
        return self.responses / self.total_uses if self.total_uses > 0 else 0.0
    
    def success_rate(self) -> float:
        """Taxa de sucesso geral (whatsapp ou date)."""
        successes = self.whatsapp + self.dates
        return successes / self.total_uses if self.total_uses > 0 else 0.0
    
    def sample_thompson(self) -> float:
        """Amostra da distribuição Beta para Thompson Sampling."""
        return random.betavariate(self.alpha, self.beta)
    
    def update_thompson(self, success: bool):
        """Atualiza parâmetros da distribuição Beta."""
        if success:
            self.alpha += 1
        else:
            self.beta += 1
        self.last_updated = datetime.utcnow()


@dataclass  
class ConversationPattern:
    """Padrão identificado em conversas bem-sucedidas."""
    pattern_type: str  # 'opening', 'response', 'escalation'
    keywords: List[str] = field(default_factory=list)
    tone: str = ""  # 'playful', 'curious', 'casual', 'flirty'
    avg_length: int = 0
    success_count: int = 0
    example_messages: List[str] = field(default_factory=list)


class MLAdaptiveService:
    """
    Serviço de ML Adaptativo para otimização de prompts.
    
    Usa Thompson Sampling para exploração/exploração inteligente
    e análise de padrões para melhoria contínua.
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._performance_data: Dict[str, Dict[str, PromptPerformance]] = {}
        self._patterns: List[ConversationPattern] = []
        self._ab_manager = get_ab_manager()
        
        # Arquivo de persistência
        from config.settings import PROJECT_ROOT
        self._storage_path = PROJECT_ROOT / 'data' / 'ml_adaptive.json'
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Carregar dados
        self._load()
        
        # Sincronizar com A/B testing
        self._sync_with_ab()
        
        self._initialized = True
        logger.info("MLAdaptiveService inicializado")
    
    def _load(self):
        """Carrega dados do arquivo."""
        if not self._storage_path.exists():
            return
            
        try:
            with open(self._storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Carregar performance data
            for exp_name, variants in data.get('performance', {}).items():
                self._performance_data[exp_name] = {}
                for var_name, var_data in variants.items():
                    self._performance_data[exp_name][var_name] = PromptPerformance(
                        variant_name=var_name,
                        experiment_name=exp_name,
                        total_uses=var_data.get('total_uses', 0),
                        responses=var_data.get('responses', 0),
                        whatsapp=var_data.get('whatsapp', 0),
                        dates=var_data.get('dates', 0),
                        alpha=var_data.get('alpha', 1.0),
                        beta=var_data.get('beta', 1.0),
                        avg_response_length=var_data.get('avg_response_length', 0.0),
                        avg_conversation_turns=var_data.get('avg_conversation_turns', 0.0)
                    )
            
            # Carregar patterns
            for pattern_data in data.get('patterns', []):
                self._patterns.append(ConversationPattern(**pattern_data))
                
            logger.debug(f"ML Adaptive: carregados {len(self._performance_data)} experimentos")
            
        except Exception as e:
            logger.error(f"Erro ao carregar ML Adaptive data: {e}")
    
    def _save(self):
        """Salva dados no arquivo."""
        try:
            data = {
                'performance': {},
                'patterns': [asdict(p) for p in self._patterns],
                'last_updated': datetime.utcnow().isoformat()
            }
            
            for exp_name, variants in self._performance_data.items():
                data['performance'][exp_name] = {}
                for var_name, perf in variants.items():
                    data['performance'][exp_name][var_name] = {
                        'total_uses': perf.total_uses,
                        'responses': perf.responses,
                        'whatsapp': perf.whatsapp,
                        'dates': perf.dates,
                        'alpha': perf.alpha,
                        'beta': perf.beta,
                        'avg_response_length': perf.avg_response_length,
                        'avg_conversation_turns': perf.avg_conversation_turns
                    }
            
            with open(self._storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Erro ao salvar ML Adaptive data: {e}")
    
    def _sync_with_ab(self):
        """Sincroniza dados com o sistema de A/B testing."""
        try:
            experiments = self._ab_manager.get_all_experiments()
            
            # get_all_experiments retorna lista de dicts, não dict
            for exp_data in experiments:
                exp_name = exp_data.get('name')
                if not exp_name:
                    continue
                    
                if exp_name not in self._performance_data:
                    self._performance_data[exp_name] = {}
                
                for variant in exp_data.get('variants', []):
                    var_name = variant.get('name')
                    if var_name and var_name not in self._performance_data[exp_name]:
                        self._performance_data[exp_name][var_name] = PromptPerformance(
                            variant_name=var_name,
                            experiment_name=exp_name,
                            total_uses=variant.get('impressions', 0),
                            responses=variant.get('responses', 0),
                            whatsapp=variant.get('whatsapp', 0),
                            dates=variant.get('dates', 0)
                        )
                    elif var_name:
                        # Atualizar com dados do A/B testing
                        perf = self._performance_data[exp_name][var_name]
                        perf.total_uses = max(perf.total_uses, variant.get('impressions', 0))
                        perf.responses = max(perf.responses, variant.get('responses', 0))
                        perf.whatsapp = max(perf.whatsapp, variant.get('whatsapp', 0))
                        perf.dates = max(perf.dates, variant.get('dates', 0))
                        
        except Exception as e:
            logger.warning(f"Erro ao sincronizar com A/B testing: {e}")
    
    def get_optimized_variant(
        self, 
        experiment_name: str, 
        match_id: str = None,
        exploration_rate: float = 0.2
    ) -> Optional[str]:
        """
        Retorna variante otimizada usando Thompson Sampling.
        
        Args:
            experiment_name: Nome do experimento
            match_id: ID do match (para alocação consistente)
            exploration_rate: Taxa de exploração (0-1)
            
        Returns:
            Nome da variante selecionada
        """
        if experiment_name not in self._performance_data:
            # Fallback para A/B testing padrão
            return self._ab_manager.get_variant(experiment_name, match_id)
        
        variants = self._performance_data[experiment_name]
        if not variants:
            return None
        
        # Verificar se já tem alocação (consistência)
        if match_id:
            existing = self._ab_manager.get_variant(experiment_name, match_id)
            if existing:
                return existing
        
        # Decidir entre explorar ou explorar
        if random.random() < exploration_rate:
            # Exploração: escolher aleatório
            selected = random.choice(list(variants.keys()))
            logger.debug(f"ML Adaptive: exploração - {experiment_name}:{selected}")
        else:
            # Exploração: Thompson Sampling
            samples = {
                name: perf.sample_thompson() 
                for name, perf in variants.items()
            }
            selected = max(samples, key=samples.get)
            logger.debug(f"ML Adaptive: Thompson Sampling - {experiment_name}:{selected} (score={samples[selected]:.3f})")
        
        # Registrar no A/B testing para consistência
        if match_id:
            self._ab_manager.get_variant(experiment_name, match_id)
        
        return selected
    
    def record_impression(self, experiment_name: str, variant_name: str, match_id: str = None):
        """Registra uma impressão (uso) de variante."""
        if experiment_name not in self._performance_data:
            self._performance_data[experiment_name] = {}
            
        if variant_name not in self._performance_data[experiment_name]:
            self._performance_data[experiment_name][variant_name] = PromptPerformance(
                variant_name=variant_name,
                experiment_name=experiment_name
            )
        
        self._performance_data[experiment_name][variant_name].total_uses += 1
        
        # Também registrar no A/B testing
        self._ab_manager.record_impression(experiment_name, match_id or 'unknown')
        
        self._save()
    
    def record_outcome(
        self, 
        experiment_name: str, 
        variant_name: str, 
        outcome_type: str,
        metadata: Dict = None
    ):
        """
        Registra um resultado (conversão).
        
        Args:
            experiment_name: Nome do experimento
            variant_name: Nome da variante
            outcome_type: Tipo de resultado ('response', 'whatsapp', 'date')
            metadata: Dados adicionais (ex: tamanho da resposta)
        """
        if experiment_name not in self._performance_data:
            return
        if variant_name not in self._performance_data[experiment_name]:
            return
        
        perf = self._performance_data[experiment_name][variant_name]
        metadata = metadata or {}
        
        if outcome_type == 'response':
            perf.responses += 1
            perf.update_thompson(success=True)
            
            # Atualizar métricas de qualidade
            if 'response_length' in metadata:
                # Média móvel
                n = perf.responses
                perf.avg_response_length = (
                    (perf.avg_response_length * (n - 1) + metadata['response_length']) / n
                )
        
        elif outcome_type == 'whatsapp':
            perf.whatsapp += 1
            perf.update_thompson(success=True)
            
        elif outcome_type == 'date':
            perf.dates += 1
            perf.update_thompson(success=True)
            
        elif outcome_type == 'no_response':
            perf.update_thompson(success=False)
        
        self._save()
        logger.debug(f"ML Adaptive: recorded {outcome_type} for {experiment_name}:{variant_name}")
    
    def get_experiment_insights(self, experiment_name: str) -> Dict[str, Any]:
        """
        Retorna insights sobre um experimento.
        
        Returns:
            Dict com métricas, variante vencedora e recomendações
        """
        if experiment_name not in self._performance_data:
            return {'error': 'Experimento não encontrado'}
        
        variants = self._performance_data[experiment_name]
        
        # Calcular métricas por variante
        results = []
        for name, perf in variants.items():
            results.append({
                'name': name,
                'total_uses': perf.total_uses,
                'response_rate': round(perf.response_rate() * 100, 2),
                'success_rate': round(perf.success_rate() * 100, 2),
                'responses': perf.responses,
                'whatsapp': perf.whatsapp,
                'dates': perf.dates,
                'thompson_score': round(perf.sample_thompson(), 4),
                'confidence': self._calculate_confidence(perf)
            })
        
        # Ordenar por taxa de sucesso
        results.sort(key=lambda x: x['success_rate'], reverse=True)
        
        # Identificar vencedor
        winner = results[0] if results else None
        
        # Calcular significância estatística
        significance = self._calculate_significance(variants)
        
        return {
            'experiment': experiment_name,
            'variants': results,
            'winner': winner,
            'statistical_significance': significance,
            'total_samples': sum(v.total_uses for v in variants.values()),
            'recommendation': self._generate_recommendation(results, significance)
        }
    
    def _calculate_confidence(self, perf: PromptPerformance) -> str:
        """Calcula nível de confiança baseado em amostras."""
        n = perf.total_uses
        if n < 10:
            return 'very_low'
        elif n < 30:
            return 'low'
        elif n < 100:
            return 'medium'
        elif n < 500:
            return 'high'
        else:
            return 'very_high'
    
    def _calculate_significance(self, variants: Dict[str, PromptPerformance]) -> Dict:
        """
        Calcula significância estatística usando aproximação normal do teste binomial.
        """
        if len(variants) < 2:
            return {'significant': False, 'p_value': 1.0}
        
        # Pegar as duas melhores variantes
        sorted_vars = sorted(
            variants.values(), 
            key=lambda v: v.response_rate(), 
            reverse=True
        )
        
        if len(sorted_vars) < 2:
            return {'significant': False, 'p_value': 1.0}
        
        best = sorted_vars[0]
        second = sorted_vars[1]
        
        # Se não tiver amostras suficientes
        if best.total_uses < 30 or second.total_uses < 30:
            return {
                'significant': False, 
                'p_value': None,
                'reason': 'Amostras insuficientes (mínimo 30 por variante)'
            }
        
        # Calcular z-score para diferença de proporções
        p1 = best.response_rate()
        p2 = second.response_rate()
        n1 = best.total_uses
        n2 = second.total_uses
        
        # Proporção pooled
        p_pooled = (best.responses + second.responses) / (n1 + n2)
        
        # Standard error
        se = math.sqrt(p_pooled * (1 - p_pooled) * (1/n1 + 1/n2))
        
        if se == 0:
            return {'significant': False, 'p_value': 1.0}
        
        z = (p1 - p2) / se
        
        # p-value aproximado (one-tailed)
        # Usando aproximação simples
        p_value = 0.5 * math.erfc(abs(z) / math.sqrt(2))
        
        return {
            'significant': p_value < 0.05,
            'p_value': round(p_value, 4),
            'z_score': round(z, 2),
            'best_variant': best.variant_name,
            'second_variant': second.variant_name,
            'difference': round((p1 - p2) * 100, 2)
        }
    
    def _generate_recommendation(self, results: List[Dict], significance: Dict) -> str:
        """Gera recomendação baseada nos resultados."""
        if not results:
            return "Sem dados suficientes para recomendação."
        
        total_samples = sum(r['total_uses'] for r in results)
        
        if total_samples < 50:
            return f"Continue coletando dados. Atualmente com {total_samples} amostras, recomendado mínimo de 50."
        
        if significance.get('significant'):
            winner = results[0]['name']
            diff = significance.get('difference', 0)
            return f"✅ Variante '{winner}' é estatisticamente superior (+{diff}% response rate). Considere aumentar seu peso."
        
        if total_samples < 200:
            return f"Diferenças não são estatisticamente significativas ainda. Continue até ~200 amostras ({total_samples} atual)."
        
        # Se após muitas amostras não há diferença significativa
        return "Variantes têm performance similar. Considere testar variações mais diferentes."
    
    def auto_adjust_weights(self, experiment_name: str, min_samples: int = 50):
        """
        Ajusta automaticamente os pesos das variantes baseado em performance.
        
        Só ajusta se tiver amostras suficientes e diferença significativa.
        """
        if experiment_name not in self._performance_data:
            return False
        
        variants = self._performance_data[experiment_name]
        total_samples = sum(v.total_uses for v in variants.values())
        
        if total_samples < min_samples:
            logger.debug(f"Auto-adjust: amostras insuficientes ({total_samples}/{min_samples})")
            return False
        
        # Calcular novos pesos baseado em Thompson Sampling
        scores = {name: perf.sample_thompson() for name, perf in variants.items()}
        total_score = sum(scores.values())
        
        if total_score == 0:
            return False
        
        new_weights = {name: score / total_score for name, score in scores.items()}
        
        # Aplicar suavização (não mudar muito de uma vez)
        # Peso final = 0.7 * peso_atual + 0.3 * peso_novo
        smoothed_weights = {}
        current_weights = self._get_current_weights(experiment_name)
        
        for name in new_weights:
            current = current_weights.get(name, 1.0 / len(new_weights))
            smoothed_weights[name] = 0.7 * current + 0.3 * new_weights[name]
        
        # Normalizar
        total = sum(smoothed_weights.values())
        smoothed_weights = {k: v/total for k, v in smoothed_weights.items()}
        
        # Atualizar no A/B testing
        try:
            self._ab_manager.update_weights(experiment_name, smoothed_weights)
            logger.info(f"Auto-adjust: pesos atualizados para {experiment_name}: {smoothed_weights}")
            return True
        except Exception as e:
            logger.warning(f"Erro ao atualizar pesos: {e}")
            return False
    
    def _get_current_weights(self, experiment_name: str) -> Dict[str, float]:
        """Obtém pesos atuais do A/B testing."""
        try:
            exp_data = self._ab_manager.get_experiment(experiment_name)
            if exp_data:
                return {v['name']: v['weight'] for v in exp_data.get('variants', [])}
        except:
            pass
        return {}
    
    def get_prompt_suggestions(self, experiment_name: str) -> List[str]:
        """
        Gera sugestões de novos prompts baseado em padrões de sucesso.
        
        Returns:
            Lista de sugestões textuais
        """
        insights = self.get_experiment_insights(experiment_name)
        suggestions = []
        
        winner = insights.get('winner')
        if winner and winner.get('response_rate', 0) > 30:
            suggestions.append(
                f"A variante '{winner['name']}' tem {winner['response_rate']}% de resposta. "
                f"Considere criar variações que sigam esse estilo."
            )
        
        # Analisar padrões de sucesso
        for pattern in self._patterns:
            if pattern.success_count > 5:
                suggestions.append(
                    f"Padrão de sucesso identificado: tom '{pattern.tone}' com "
                    f"comprimento médio de {pattern.avg_length} caracteres."
                )
        
        if not suggestions:
            suggestions.append(
                "Continue coletando dados. Sugestões serão geradas após mais conversas bem-sucedidas."
            )
        
        return suggestions
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas gerais do sistema ML."""
        total_experiments = len(self._performance_data)
        total_variants = sum(len(v) for v in self._performance_data.values())
        total_samples = sum(
            perf.total_uses 
            for variants in self._performance_data.values() 
            for perf in variants.values()
        )
        
        return {
            'total_experiments': total_experiments,
            'total_variants': total_variants,
            'total_samples': total_samples,
            'patterns_identified': len(self._patterns),
            'experiments': list(self._performance_data.keys())
        }


# Singleton
_ml_service: Optional[MLAdaptiveService] = None


def get_ml_service() -> MLAdaptiveService:
    """Retorna instância singleton do MLAdaptiveService."""
    global _ml_service
    if _ml_service is None:
        _ml_service = MLAdaptiveService()
    return _ml_service


def reset_ml_service():
    """Reseta o singleton (útil para testes)."""
    global _ml_service
    _ml_service = None
