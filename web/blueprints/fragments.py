"""
Blueprint de fragmentos HTML para HTMX.

Endpoints que retornam parciais Jinja (não JSON), consumidos via hx-get para
atualizar trechos da página sem JS manual. Início da migração para HTMX
(ver docs/UI_MODERNIZATION.md, Fase 2).
"""

from flask import Blueprint, render_template

import web.app as webapp  # noqa: E402
from web.blueprints.matches_messages import compute_dashboard_stats

bp_fragments = Blueprint("fragments", __name__)


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
