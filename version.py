"""
Versionamento do projeto Automatic Tinder Chat.

Segue Semantic Versioning (SemVer): MAJOR.MINOR.PATCH

- MAJOR: Mudanças incompatíveis na API
- MINOR: Novas funcionalidades compatíveis
- PATCH: Correções de bugs compatíveis
"""

__version__ = "2.8.0"

# Changelog resumido
CHANGELOG = {
    "2.8.0": {
        "date": "2026-06-12",
        "changes": [
            "Tooling: ruff (lint+format) e config consolidada em pyproject.toml; .editorconfig",
            "Qualidade: imports ordenados em todo o projeto",
            "Deps: removidas dependências mortas (selenium, webdriver-manager, aiohttp, "
            "lxml, beautifulsoup4, cachetools, asyncio); versões atualizadas",
            "UI: CSS/JS inline extraídos de base.html (1626 -> 152 linhas) para "
            "static/css/{tokens,main}.css e static/js/app.js",
            "Backend: app factory (web/factory.py) + estado compartilhado "
            "(web/extensions.py) + extração de rotas auxiliares para blueprint "
            "(web/app.py 3300 -> 1885 linhas)",
            "Infra: Docker/docker-compose para onboarding + Makefile de DX",
            "Correção: logger reconfigura stdout/stderr para UTF-8 (consoles Windows)",
            "CI: fixture impede launch de navegador real em testes unitários",
        ]
    },
    "2.7.0": {
        "date": "2026-02-12",
        "changes": [
            "Feature: Logging bruto de requests/responses da IA (logs/ai_raw_YYYY-MM-DD.log)",
            "Feature: Contexto pessoal (personal_context.txt) injetado em todas as chamadas à IA",
            "Feature: Arquivo .example com template preenchido para referência",
            "Melhoria: log_ai_raw_request(), log_ai_raw_response(), log_ai_raw_error() em utils/logger.py",
            "Melhoria: _inject_personal_context() e _load_personal_context() no AIService",
            "Melhoria: clear_prompts_cache() agora também limpa cache do contexto pessoal",
            "Segurança: personal_context.txt adicionado ao .gitignore",
        ]
    },
    "2.6.0": {
        "date": "2026-02-11",
        "changes": [
            "Feature: Flag de reenvio por match (pending_resend) para mensagens incompletas",
            "Feature: Sync durante pausa com browser headless (otimização de performance)",
            "Feature: Auto-migração de colunas no SQL Server (_run_migrations)",
            "Fix: await faltando em _apply_human_delay() no orchestrator (bug crítico)",
            "Fix: state_manager.start() chamado duas vezes no run_automation",
            "Fix: matches_processed nunca incrementado no run_efficient_cycle",
            "Melhoria: sync_messages_only usa active_match_filter() (DRY)",
            "Melhoria: BrowserController aceita headless override no construtor",
            "Melhoria: reset_browser() para trocar modo headless/visível em runtime",
            "Testes: 30 novos testes (test_resend_feature.py, test_headless_sync.py)",
            "Testes: 405 testes passando no total",
        ]
    },
    "2.5.0": {
        "date": "2026-02-06",
        "changes": [
            "Módulo AI centralizado reescrito (ai_service.py)",
            "Suporte a Claude (Anthropic) adicionado",
            "ML Adaptive System com Thompson Sampling",
            "Dashboard ML Insights na página Analytics",
            "Scheduler Service para tarefas agendadas",
            "Cache de Embeddings com SQLite + LRU",
            "Endpoints REST para ML, Scheduler e Cache",
            "Documentação: relatórios FastAPI e Python vs TS",
            "Testes para ML Adaptive e Embeddings Cache",
        ]
    },
    "2.4.0": {
        "date": "2026-02-06",
        "changes": [
            "Prompts centralizados em config/prompts/ (9 arquivos)",
            "Removida duplicação de persona nos user prompts",
            "Adicionado clear_prompts_cache() para recarregar prompts em runtime",
            "Correção dry run: mensagens dry_run não bloqueiam envio real",
            "LOG_RETENTION_DAYS alterado de 30 para 10 dias",
            "Testes de prompts atualizados para nova estrutura",
        ]
    },
    "2.3.0": {
        "date": "2026-02-04",
        "changes": [
            "Configuração simplificada: removidos campos não utilizados do .env",
            "Modelo padrão alterado de gpt-4o-mini para gpt-4o",
            "Correção de detecção de emoji (falso positivo em '??')",
            "Correção de ordenação de mensagens (cronológica)",
            "Correção de reset de status awaiting_my_response",
            "Provedores de IA gerenciáveis via interface web",
        ]
    },
    "2.2.0": {
        "date": "2026-02-04",
        "changes": [
            "Integração completa do A/B Testing com automação de mensagens",
            "Prompts dinâmicos baseados em variantes A/B (estilo, tamanho, emoji)",
            "Tracking automático de conversões (resposta/whatsapp/encontro)",
            "Correção de escape em templates de prompt (KeyError em JSON)",
            "Dashboard Analytics exibe resultados de A/B Testing em tempo real",
        ]
    },
    "2.1.0": {
        "date": "2026-02-03",
        "changes": [
            "Rate Limiting: endpoints de polling isentos",
            "AI Logger: corrigido uso de singleton DatabaseManager",
            "Banco de Dados: coluna prompt_template aumentada para VARCHAR(500)",
            "Seletores de Mensagem: atualizados para Tinder 2026",
        ]
    },
    "2.0.0": {
        "date": "2026-02-03",
        "changes": [
            "Refatoração completa da arquitetura SYNC/EXECUTE",
            "Novo MatchDataService: dados APENAS do banco",
            "Novo ExecutionService: execução usando dados persistidos",
            "Novo DataValidationService: validação centralizada",
            "Separação clara de responsabilidades (SRP)",
            "Eliminação de dependência de dados em memória",
        ]
    },
    "1.5.0": {
        "date": "2026-01-15",
        "changes": [
            "Sistema de cache LRU com TTL",
            "Rate limiting configurável",
            "Notificações em tempo real",
        ]
    },
    "1.0.0": {
        "date": "2025-12-01",
        "changes": [
            "Versão inicial do sistema",
            "Integração com OpenAI",
            "Automação básica com Playwright",
        ]
    }
}


def get_version() -> str:
    """Retorna a versão atual do projeto."""
    return __version__


def get_version_info() -> dict:
    """Retorna informações detalhadas da versão."""
    return {
        "version": __version__,
        "changelog": CHANGELOG.get(__version__, {})
    }
