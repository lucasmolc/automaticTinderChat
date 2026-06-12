# Changelog

Histórico de mudanças do projeto. Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento: [SemVer](https://semver.org/lang/pt-BR/).

## [2.7.0] - 2026-02-12
- Logging bruto de requests/responses da IA em `logs/ai_raw_YYYY-MM-DD.log`
- Contexto pessoal (`config/prompts/personal_context.txt`) injetado em todas as chamadas à IA
- Segurança: `personal_context.txt` no `.gitignore`

## [2.6.0] - 2026-02-11
- Reenvio de mensagens incompletas (flag `pending_resend` por match)
- Sync durante pausas com browser headless
- Auto-migração de colunas no SQL Server
- Fixes: `await` faltando em `_apply_human_delay()`, `state_manager.start()` duplicado, contador `matches_processed`

## [2.5.0] - 2026-02-06
- Módulo de IA centralizado e provider-agnostic; suporte a Claude (Anthropic)
- ML Adaptive (Thompson Sampling), Scheduler Service, cache de embeddings (SQLite + LRU)
- Endpoints REST para ML, Scheduler e Cache; dashboard ML Insights

## [2.4.0] - 2026-02-06
- Prompts centralizados em `config/prompts/`
- Fix de dry run e `KeyError` em templates
- Segurança: `data/ab_experiments.json` removido do repositório

## [2.3.0] - 2026-02-04
- Configuração simplificada; provedores de IA gerenciáveis via web
- Fixes: detecção de emoji, ordenação de mensagens, reset de status

## [2.2.x] - 2026-02-03/04
- A/B Testing integrado com tracking de conversões
- Console limpo (WARNING+), modais customizados, seletores Tinder 2026

## [2.1.0] - 2026-02-03
- Polling isento de rate limit; AI Logger via singleton; `prompt_template` VARCHAR(500)

## [2.0.0] - 2026-02-03
- Refatoração SYNC/EXECUTE (ProfileSyncer, ExecutionService, MatchDataService, DataValidationService)
- Cache LRU, métricas Prometheus, A/B Testing, audit log, WebSocket

## [1.5.0] - 2026-01-15
- Cache LRU com TTL, rate limiting, notificações em tempo real

## [1.0.0] - 2025-12-01
- Versão inicial: OpenAI + Playwright + SQL Server
