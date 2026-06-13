"""
Blueprint de fragmentos HTML para HTMX.

Endpoints que retornam parciais Jinja (não JSON), consumidos via hx-get para
atualizar trechos da página sem JS manual. Início da migração para HTMX
(ver docs/UI_MODERNIZATION.md, Fase 2).
"""

from flask import Blueprint, render_template
from sqlalchemy import desc

import web.app as webapp  # noqa: E402
from database.models import Match, Message
from web.blueprints.matches_messages import compute_dashboard_stats

bp_fragments = Blueprint("fragments", __name__)


def _match_status(m):
    """Rótulo/cor de status para exibição (espelha a lógica de /api/matches)."""
    if m.is_blocked:
        return "Bloqueado", "danger"
    if not m.has_messages:
        return "Novo", "success"
    if m.awaiting_my_response:
        return "Aguardando", "warning"
    return "Ativo", "primary"


@bp_fragments.route("/fragments/stats")
def fragment_stats():
    """Cards de estatísticas do dashboard (HTML para HTMX)."""
    try:
        with webapp.db.get_session() as session:
            stats = compute_dashboard_stats(session)
    except Exception:
        # Em caso de erro, zera os contadores para não quebrar o layout.
        stats = {
            k: 0
            for k in (
                "total_matches", "new_matches", "awaiting_response", "whatsapp_obtained",
                "active_matches", "messages_sent", "messages_received", "blocked_matches",
                "pending_resend",
            )
        }
    return render_template("partials/_stats.html", stats=stats)


@bp_fragments.route("/fragments/recent-matches")
def fragment_recent_matches():
    """Tabela de matches recentes (linhas <tr> para HTMX)."""
    matches = []
    try:
        with webapp.db.get_session() as session:
            rows = (
                session.query(Match)
                .filter(Match.name.isnot(None))
                .order_by(desc(Match.created_at))
                .limit(5)
                .all()
            )
            for m in rows:
                if not m.name or not m.name.strip():
                    continue
                label, color = _match_status(m)
                matches.append({
                    "name": m.name,
                    "age": m.age,
                    "photo_url": m.profile_photo_url,
                    "status_label": label,
                    "status_color": color,
                    "created_at": m.created_at,
                })
    except Exception:
        matches = []
    return render_template("partials/_recent_matches.html", matches=matches)


@bp_fragments.route("/fragments/recent-messages")
def fragment_recent_messages():
    """Tabela de mensagens recentes (linhas <tr> para HTMX)."""
    messages = []
    try:
        with webapp.db.get_session() as session:
            rows = (
                session.query(Message, Match)
                .join(Match, Message.match_id == Match.id)
                .order_by(desc(Message.sent_at))
                .limit(5)
                .all()
            )
            for msg, match in rows:
                messages.append({
                    "content": msg.content,
                    "is_from_me": msg.is_from_me,
                    "sent_at": msg.sent_at,
                    "match_name": match.name,
                    "photo_url": match.profile_photo_url,
                })
    except Exception:
        messages = []
    return render_template("partials/_recent_messages.html", messages=messages)
