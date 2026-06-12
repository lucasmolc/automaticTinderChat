# Arquitetura

Visão técnica do Automatic Dating Chat. Para instalação e uso, veja o [README](../README.md).

## Visão geral

O sistema integra quatro domínios:

| Domínio | Tecnologia | Responsabilidade |
|---|---|---|
| Automação de navegador | Playwright (async) | Navegar na UI, extrair dados, enviar mensagens |
| Inteligência Artificial | OpenAI / DeepSeek / Claude | Análise de perfil, geração de mensagens, classificação |
| Persistência | SQLAlchemy 2.0 (SQLite padrão / PostgreSQL / SQL Server) | Matches, mensagens, interações de IA, experimentos |
| Interface | Flask + WebSocket | Dashboard, analytics, painel de controle |

## Princípio central: SYNC ≠ EXECUTE

A regra mais importante da arquitetura (v2.0+): **execução nunca faz scraping para obter dados**.

```
┌──────────────────────────────────────────────────────────────┐
│                  ORQUESTRADOR (run_automation)                │
│                                                              │
│  EXECUTE (browser visível)                                   │
│  ExecutionService ◄── MatchDataService ◄── BANCO             │
│  envia mensagens usando APENAS dados persistidos             │
│                          │                                   │
│                       [PAUSA]                                 │
│                          │                                   │
│  SYNC (browser headless, durante a pausa)                    │
│  ProfileSyncer ──► DataValidationService ──► BANCO           │
│  extrai da tela, valida rigorosamente, persiste              │
└──────────────────────────────────────────────────────────────┘
```

| Componente | Responsabilidade | Acessa a tela? |
|---|---|---|
| `ProfileSyncer` | Sincroniza dados UI → banco | Sim (headless na pausa) |
| `DataValidationService` | Valida campos antes de salvar | Não |
| `MatchDataService` | Fornece dados do banco para execução | Não |
| `ExecutionService` | Envia/reenvia mensagens | Apenas para envio |

Matches com dados incompletos são sinalizados e pulados pela execução até o próximo sync.

## Camadas

```
Interface Web (Flask)  ──  Dashboard │ Matches │ Analytics │ Controle
        │
   API REST (/api/*)  +  WebSocket (tempo real, fallback polling)
        │
Orquestrador (automation/orchestrator.py)
   ExecutionService │ ProfileSyncer │ MatchDataService │ DataValidationService
        │
Playwright │ AIService (multi-provider) │ SQL Server │ Cache LRU
```

## Módulos

### `automation/`
| Arquivo | Papel |
|---|---|
| `orchestrator.py` | Ciclo principal SYNC/EXECUTE (~1.850 linhas) |
| `browser.py` | Controlador Playwright (singleton, suporte headless dinâmico) |
| `execution_service.py` | Envio e reenvio de mensagens |
| `profile_syncer.py` | Sincronização de perfis e mensagens |
| `match_data_service.py` | Dados do banco para execução |
| `data_validation_service.py` | Validação centralizada |
| `match_validation.py` / `match_fetching.py` | Validação e busca com retry/cache |
| `tinder_scraping.py` / `extractors.py` | Seletores e extração do DOM |
| `idempotency.py` | Proteção contra envio duplicado |
| `state_manager.py` | Estado da automação (locks, start/stop) |

### `ai/`
Strategy + Facade: `AIService` é o ponto único de entrada; provedores (`openai_provider`, `deepseek_provider`, `claude_provider`) implementam `BaseAIProvider` e são intercambiáveis em runtime via `provider_manager`. Toda chamada injeta o contexto pessoal (`config/prompts/personal_context.txt`) e é logada em formato bruto.

### `services/`
| Arquivo | Papel |
|---|---|
| `ml_adaptive.py` | Thompson Sampling para otimização de prompts |
| `scheduler_service.py` | Tarefas agendadas (auto-adjust, cleanup, sync A/B) |
| `embeddings_cache.py` | Cache de embeddings (SQLite + LRU, similaridade por cosseno) |
| `analytics_service.py` | Métricas e estatísticas |
| `notification_service.py` | Notificações em tempo real |

### `database/`
- `models.py` — 12 entidades SQLAlchemy (Match, Message, AIInteraction, etc.)
- `repositories.py` — Repository Pattern (7 repositórios), sem SQL raw
- `connection.py` — pool de conexões, bootstrap do banco e auto-migração (pontos com T-SQL específico de SQL Server; ver [TECHNOLOGY.md](TECHNOLOGY.md#banco-de-dados))

### `web/`
- `app.py` — Flask monolítico (~3.300 linhas): 5 views Jinja2 + ~30 endpoints REST
- `websocket.py` + `static/js/websocket.js` — Socket.IO com fallback de polling
- `templates/` — base.html (layout + CSS inline), dashboard, matches, messages, analytics, control

### `utils/`
Cache LRU com TTL, logger (Loguru), rate limiter, sanitização de input, detecção de WhatsApp/encontros, métricas Prometheus, A/B testing, audit log.

## Padrões utilizados

- **Repository** — abstração de dados (`database/repositories.py`)
- **Strategy** — provedores de IA intercambiáveis (`ai/base_provider.py`)
- **Facade** — `AIService` como ponto único de IA
- **Singleton** — `get_db_manager()`, `get_ai_service()`, browser controller
- **Service Layer** — separação SYNC/EXECUTE

## Pontos de atenção conhecidos

1. **Async/sync misturado** — a automação é async (Playwright), o web é Flask síncrono e o ORM é usado de forma síncrona; a ponte é feita com `asyncio.run()`. Já causou bug real (v2.6.0: `await` faltando). Plano de correção em [TECHNOLOGY.md](TECHNOLOGY.md).
2. **Seletores frágeis** — os seletores CSS do Tinder (em `tinder_scraping.py`/`extractors.py`) quebram quando a plataforma atualiza a UI. São o componente de maior manutenção do projeto.
3. **`web/app.py` monolítico** — API e views no mesmo arquivo; candidato a Blueprints ou migração para FastAPI.
4. **Singletons globais** — simplificam o uso, mas dificultam testes de concorrência; o estado é coordenado pelo `state_manager`.

## Testes

~24 arquivos / ~409 testes (`pytest`). A maioria roda sem dependências externas: o `conftest.py` usa SQLite in-memory e mocks dos provedores de IA. Testes E2E e de browser exigem Playwright real e são marcados (`-m "not e2e"` para pular).
