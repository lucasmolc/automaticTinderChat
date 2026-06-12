"""
Gerador de relatórios e analytics.
Gera insights sobre performance e recomendações.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from config import REPORTS_DIR, get_settings
from database import (
    get_db_manager, MatchRepository, MessageRepository,
    ExecutionLogRepository, AIInteractionRepository, AnalyticsRepository
)
from database.models import Match, Message, Analytics
from ai import get_openai_client
from utils.logger import get_logger
from utils.helpers import safe_json_loads, safe_json_dumps, format_datetime

logger = get_logger(__name__)

# Configurar estilo dos gráficos
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)


class ReportGenerator:
    """Gerador de relatórios e análises."""
    
    def __init__(self):
        self.settings = get_settings()
        self.db = get_db_manager()
        self.openai = get_openai_client()
        self.output_dir = REPORTS_DIR / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_matches_dataframe(self) -> pd.DataFrame:
        """Retorna DataFrame com todos os matches."""
        with self.db.get_session() as session:
            matches = session.query(Match).all()
            
            data = []
            for m in matches:
                data.append({
                    "id": m.id,
                    "tinder_id": m.tinder_match_id,
                    "name": m.name,
                    "age": m.age,
                    "has_bio": bool(m.bio),
                    "bio_length": len(m.bio) if m.bio else 0,
                    "photos_count": m.photos_count,
                    "interests_count": m.interests_count,
                    "overall_score": m.overall_score,
                    "has_messages": m.has_messages,
                    "first_message_sent": m.first_message_sent,
                    "awaiting_response": m.awaiting_my_response,
                    "temperature": m.conversation_temperature,
                    "temperature_score": m.temperature_score,
                    "whatsapp_requested": m.whatsapp_requested,
                    "whatsapp_obtained": m.whatsapp_obtained,
                    "date_suggested": m.date_suggested,
                    "date_confirmed": m.date_confirmed,
                    "matched_at": m.matched_at,
                    "last_message_at": m.last_message_at,
                    "created_at": m.created_at
                })
            
            return pd.DataFrame(data)
    
    def _get_messages_dataframe(self) -> pd.DataFrame:
        """Retorna DataFrame com todas as mensagens."""
        with self.db.get_session() as session:
            messages = session.query(Message).all()
            
            data = []
            for m in messages:
                data.append({
                    "id": m.id,
                    "match_id": m.match_id,
                    "content": m.content,
                    "content_length": len(m.content) if m.content else 0,
                    "is_from_me": m.is_from_me,
                    "message_type": m.message_type,
                    "ai_generated": m.ai_generated,
                    "sent_at": m.sent_at,
                    "created_at": m.created_at
                })
            
            return pd.DataFrame(data)
    
    def generate_summary_stats(self) -> Dict:
        """Gera estatísticas resumidas."""
        logger.info("Gerando estatísticas resumidas...")
        
        matches_df = self._get_matches_dataframe()
        messages_df = self._get_messages_dataframe()
        
        if matches_df.empty:
            return {"error": "Sem dados para análise"}
        
        stats = {
            "general": {
                "total_matches": len(matches_df),
                "matches_with_messages": matches_df["has_messages"].sum(),
                "first_messages_sent": matches_df["first_message_sent"].sum(),
                "awaiting_response": matches_df["awaiting_response"].sum(),
            },
            "conversions": {
                "whatsapp_requested": matches_df["whatsapp_requested"].sum(),
                "whatsapp_obtained": matches_df["whatsapp_obtained"].sum(),
                "dates_suggested": matches_df["date_suggested"].sum(),
                "dates_confirmed": matches_df["date_confirmed"].sum(),
            },
            "rates": {},
            "temperatures": {},
            "messages": {}
        }
        
        # Calcular taxas
        if stats["general"]["first_messages_sent"] > 0:
            with_response = matches_df[
                matches_df["first_message_sent"] & matches_df["has_messages"]
            ]
            stats["rates"]["response_rate"] = round(
                len(with_response) / stats["general"]["first_messages_sent"] * 100, 2
            )
        
        if stats["general"]["total_matches"] > 0:
            stats["rates"]["engagement_rate"] = round(
                stats["general"]["matches_with_messages"] / stats["general"]["total_matches"] * 100, 2
            )
        
        if stats["conversions"]["whatsapp_requested"] > 0:
            stats["rates"]["whatsapp_conversion"] = round(
                stats["conversions"]["whatsapp_obtained"] / stats["conversions"]["whatsapp_requested"] * 100, 2
            )
        
        # Temperaturas
        temp_counts = matches_df["temperature"].value_counts().to_dict()
        stats["temperatures"] = {
            "cold": temp_counts.get("cold", 0),
            "warm": temp_counts.get("warm", 0),
            "hot": temp_counts.get("hot", 0)
        }
        
        # Estatísticas de mensagens
        if not messages_df.empty:
            my_messages = messages_df[messages_df["is_from_me"]]
            their_messages = messages_df[~messages_df["is_from_me"]]
            
            stats["messages"] = {
                "total": len(messages_df),
                "sent_by_me": len(my_messages),
                "received": len(their_messages),
                "ai_generated": messages_df["ai_generated"].sum(),
                "avg_length_mine": round(my_messages["content_length"].mean(), 1) if len(my_messages) > 0 else 0,
                "avg_length_theirs": round(their_messages["content_length"].mean(), 1) if len(their_messages) > 0 else 0
            }
        
        return stats
    
    def generate_conversion_funnel(self) -> Dict:
        """Gera dados do funil de conversão."""
        matches_df = self._get_matches_dataframe()
        
        if matches_df.empty:
            return {}
        
        funnel = {
            "stages": [
                {"name": "Total Matches", "count": len(matches_df)},
                {"name": "Primeira Msg Enviada", "count": int(matches_df["first_message_sent"].sum())},
                {"name": "Resposta Recebida", "count": int(matches_df[matches_df["has_messages"] & matches_df["first_message_sent"]].shape[0])},
                {"name": "Conversa Quente", "count": int((matches_df["temperature"] == "hot").sum())},
                {"name": "WhatsApp Pedido", "count": int(matches_df["whatsapp_requested"].sum())},
                {"name": "WhatsApp Obtido", "count": int(matches_df["whatsapp_obtained"].sum())},
                {"name": "Encontro Sugerido", "count": int(matches_df["date_suggested"].sum())},
                {"name": "Encontro Confirmado", "count": int(matches_df["date_confirmed"].sum())}
            ]
        }
        
        # Calcular taxa de conversão entre etapas
        for i in range(1, len(funnel["stages"])):
            prev_count = funnel["stages"][i-1]["count"]
            curr_count = funnel["stages"][i]["count"]
            if prev_count > 0:
                funnel["stages"][i]["conversion_rate"] = round(curr_count / prev_count * 100, 1)
            else:
                funnel["stages"][i]["conversion_rate"] = 0
        
        return funnel
    
    def generate_time_analysis(self, days: int = 30) -> Dict:
        """Analisa performance ao longo do tempo."""
        with self.db.get_session() as session:
            analytics_repo = AnalyticsRepository(session)
            start_date = datetime.utcnow() - timedelta(days=days)
            
            analytics_list = analytics_repo.get_range(start_date, datetime.utcnow())
            
            if not analytics_list:
                return {}
            
            data = []
            for a in analytics_list:
                data.append({
                    "date": a.date.strftime("%Y-%m-%d"),
                    "new_matches": a.new_matches,
                    "messages_sent": a.first_messages_sent,
                    "responses": a.responses_received,
                    "response_rate": a.response_rate,
                    "whatsapp": a.whatsapp_conversions,
                    "dates": a.dates_confirmed,
                    "ai_cost": a.total_ai_cost
                })
            
            df = pd.DataFrame(data)
            
            return {
                "daily_data": data,
                "totals": {
                    "matches": int(df["new_matches"].sum()),
                    "messages": int(df["messages_sent"].sum()),
                    "responses": int(df["responses"].sum()),
                    "avg_response_rate": round(df["response_rate"].mean(), 2) if len(df) > 0 else 0,
                    "whatsapp": int(df["whatsapp"].sum()),
                    "dates": int(df["dates"].sum()),
                    "total_ai_cost": round(df["ai_cost"].sum(), 4)
                }
            }
    
    def generate_ai_insights(self) -> Dict:
        """Gera insights usando IA."""
        logger.info("Gerando insights com IA...")
        
        # Coletar dados para análise
        summary = self.generate_summary_stats()
        funnel = self.generate_conversion_funnel()
        time_data = self.generate_time_analysis()
        
        analytics_data = {
            "summary_stats": summary,
            "conversion_funnel": funnel,
            "time_analysis": time_data
        }
        
        # Chamar IA para análise
        insights = self.openai.generate_analytics_insights(analytics_data)
        
        return insights
    
    def plot_conversion_funnel(self, save: bool = True) -> Optional[str]:
        """Gera gráfico do funil de conversão."""
        funnel = self.generate_conversion_funnel()
        
        if not funnel or "stages" not in funnel:
            return None
        
        stages = funnel["stages"]
        names = [s["name"] for s in stages]
        counts = [s["count"] for s in stages]
        
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Criar barras horizontais
        colors = sns.color_palette("Blues_r", len(stages))
        bars = ax.barh(names[::-1], counts[::-1], color=colors)
        
        # Adicionar valores nas barras
        for bar, count in zip(bars, counts[::-1]):
            ax.text(
                bar.get_width() + max(counts) * 0.02,
                bar.get_y() + bar.get_height()/2,
                f'{count}',
                va='center',
                fontsize=12,
                fontweight='bold'
            )
        
        ax.set_xlabel("Quantidade", fontsize=12)
        ax.set_title("Funil de Conversão - Tinder Automation", fontsize=14, fontweight='bold')
        
        plt.tight_layout()
        
        if save:
            filepath = self.output_dir / f"funnel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()
            return str(filepath)
        
        plt.show()
        return None
    
    def plot_temperature_distribution(self, save: bool = True) -> Optional[str]:
        """Gera gráfico de distribuição de temperatura das conversas."""
        matches_df = self._get_matches_dataframe()
        
        if matches_df.empty:
            return None
        
        temp_df = matches_df[matches_df["temperature"].notna()]
        
        if temp_df.empty:
            return None
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        colors = {"cold": "#3498db", "warm": "#f39c12", "hot": "#e74c3c"}
        temp_counts = temp_df["temperature"].value_counts()
        
        ax.pie(
            temp_counts.values,
            labels=[f"{k.upper()}\n({v})" for k, v in temp_counts.items()],
            colors=[colors.get(k, "#95a5a6") for k in temp_counts.index],
            autopct='%1.1f%%',
            startangle=90,
            textprops={'fontsize': 12}
        )
        
        ax.set_title("Temperatura das Conversas", fontsize=14, fontweight='bold')
        
        plt.tight_layout()
        
        if save:
            filepath = self.output_dir / f"temperature_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()
            return str(filepath)
        
        plt.show()
        return None
    
    def plot_messages_over_time(self, days: int = 30, save: bool = True) -> Optional[str]:
        """Gera gráfico de mensagens ao longo do tempo."""
        time_data = self.generate_time_analysis(days)
        
        if not time_data or "daily_data" not in time_data:
            return None
        
        df = pd.DataFrame(time_data["daily_data"])
        
        if df.empty:
            return None
        
        df["date"] = pd.to_datetime(df["date"])
        
        fig, ax = plt.subplots(figsize=(14, 6))
        
        ax.plot(df["date"], df["messages_sent"], marker='o', label="Mensagens Enviadas", linewidth=2)
        ax.plot(df["date"], df["responses"], marker='s', label="Respostas Recebidas", linewidth=2)
        
        ax.set_xlabel("Data", fontsize=12)
        ax.set_ylabel("Quantidade", fontsize=12)
        ax.set_title(f"Mensagens nos Últimos {days} Dias", fontsize=14, fontweight='bold')
        ax.legend()
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        if save:
            filepath = self.output_dir / f"messages_time_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()
            return str(filepath)
        
        plt.show()
        return None
    
    def generate_full_report(self) -> Dict:
        """Gera relatório completo com todos os dados e gráficos."""
        logger.info("Gerando relatório completo...")
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "summary": self.generate_summary_stats(),
            "funnel": self.generate_conversion_funnel(),
            "time_analysis": self.generate_time_analysis(),
            "ai_insights": {},
            "charts": []
        }
        
        # Gerar gráficos
        funnel_chart = self.plot_conversion_funnel()
        if funnel_chart:
            report["charts"].append({"name": "funnel", "path": funnel_chart})
        
        temp_chart = self.plot_temperature_distribution()
        if temp_chart:
            report["charts"].append({"name": "temperature", "path": temp_chart})
        
        time_chart = self.plot_messages_over_time()
        if time_chart:
            report["charts"].append({"name": "messages_time", "path": time_chart})
        
        # Gerar insights com IA
        try:
            report["ai_insights"] = self.generate_ai_insights()
        except Exception as e:
            logger.error(f"Erro ao gerar insights com IA: {e}")
            report["ai_insights"] = {"error": str(e)}
        
        # Salvar relatório em JSON
        report_path = self.output_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            import json
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        
        report["report_path"] = str(report_path)
        
        logger.info(f"Relatório salvo em: {report_path}")
        
        return report
    
    def export_to_excel(self) -> str:
        """Exporta dados para Excel."""
        logger.info("Exportando dados para Excel...")
        
        matches_df = self._get_matches_dataframe()
        messages_df = self._get_messages_dataframe()
        
        filepath = self.output_dir / f"data_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            matches_df.to_excel(writer, sheet_name='Matches', index=False)
            messages_df.to_excel(writer, sheet_name='Messages', index=False)
            
            # Resumo
            summary = pd.DataFrame([self.generate_summary_stats()])
            summary.to_excel(writer, sheet_name='Summary', index=False)
        
        logger.info(f"Dados exportados para: {filepath}")
        return str(filepath)


def generate_report() -> Dict:
    """Função de conveniência para gerar relatório."""
    generator = ReportGenerator()
    return generator.generate_full_report()
