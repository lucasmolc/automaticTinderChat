"""
App factory: cria e configura a aplicação Flask.

Mantém a inicialização (CORS, config, métricas, A/B testing, rate limiting,
WebSocket) num único lugar. As extensões que dependem do app (``limiter``,
``socketio``) são atribuídas em ``web.extensions`` para que blueprints e helpers
as acessem sem dependência circular.
"""

from flask import Flask
from flask_cors import CORS
from loguru import logger

from web import extensions


def create_app() -> Flask:
    """Cria, configura e retorna a aplicação Flask."""
    app = Flask(__name__)

    # WebSocket (opcional)
    if extensions.WEBSOCKET_ENABLED:
        from web.websocket import create_socketio

        extensions.socketio = create_socketio(app)
        logger.debug("✅ WebSocket habilitado")

    # CORS restrito a origens conhecidas
    CORS(
        app,
        origins=[
            "http://localhost:5000",
            "http://127.0.0.1:5000",
            "http://localhost:3000",
        ],
    )

    app.config["JSON_AS_ASCII"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Métricas Prometheus (opcional)
    if extensions.METRICS_ENABLED:
        from utils.metrics import init_metrics

        init_metrics(app)
        logger.debug("✅ Prometheus metrics habilitado")

    # A/B Testing (opcional)
    if extensions.AB_TESTING_ENABLED:
        from utils.ab_testing import setup_default_experiments

        setup_default_experiments()
        logger.debug("✅ A/B Testing habilitado")

    # Rate limiting (opcional, com suporte a Redis)
    if extensions.RATE_LIMITING_ENABLED:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address

        from utils.rate_limiter import RateLimitConfig

        extensions.limiter = Limiter(
            key_func=get_remote_address,
            app=app,
            default_limits=RateLimitConfig.get_default_limits(),
            storage_uri=RateLimitConfig.get_storage_uri(),
        )

    # Background tasks (opcional)
    if extensions.BACKGROUND_TASKS_ENABLED:
        from utils.background_tasks import get_task_manager

        get_task_manager()
        logger.debug("✅ Background Tasks habilitado")

    # Filtro Jinja para tempo relativo (usado nos fragmentos HTMX)
    from datetime import datetime

    @app.template_filter("relative_time")
    def _relative_time(value):
        if not value:
            return "-"
        try:
            diff = datetime.utcnow() - value
        except TypeError:
            return "-"
        minutes = int(diff.total_seconds() // 60)
        if minutes < 1:
            return "Agora"
        if minutes < 60:
            return f"{minutes}m atrás"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h atrás"
        days = hours // 24
        if days < 7:
            return f"{days}d atrás"
        return value.strftime("%d/%m/%Y")

    return app
