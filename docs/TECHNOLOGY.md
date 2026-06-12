# Decisões de Tecnologia

Análise de stack feita em jun/2026 para a abertura do projeto. Complementa os estudos anteriores já presentes no repositório: [FASTAPI_MIGRATION_REPORT.md](FASTAPI_MIGRATION_REPORT.md) e [PYTHON_VS_TYPESCRIPT_ANALYSIS.md](PYTHON_VS_TYPESCRIPT_ANALYSIS.md).

## Pergunta: migrar para C#/.NET?

**Decisão: não. Permanecer em Python e modernizar.**

### Comparativo objetivo

| Critério | Python (atual) | C#/.NET | Vencedor |
|---|---|---|---|
| Playwright | Maduro, async-first | Suporte oficial | Empate |
| SDKs de IA (OpenAI/Anthropic/DeepSeek) | Oficiais e sempre primeiro a receber features | Oficiais, mas atrás em features | Python |
| Ecossistema ML (Thompson Sampling, embeddings, similaridade) | NumPy/SciPy/FAISS/ChromaDB nativos | Limitado (ML.NET, bindings) | **Python, com folga** |
| Performance de API | Flask ~centenas req/s (FastAPI ~milhares) | ASP.NET 10k+ req/s | .NET — **irrelevante**: app local, usuário único |
| Tipagem/manutenção em escala | Pydantic + type hints parciais | Forte, nativa | .NET |
| Custo de migração | Zero | Reescrita ~3-4 meses, ~409 testes a portar, alto risco de regressão | Python |

### Por que a reescrita não se justifica

1. **O diferencial do projeto é IA/ML, não throughput.** `services/ml_adaptive.py` (bandits), cache de embeddings com similaridade de cosseno e o pipeline de prompts são exatamente o terreno onde o ecossistema Python é imbatível.
2. **A arquitetura atual é sólida.** Separação SYNC/EXECUTE, Repository Pattern, provedores plugáveis — os problemas existentes (Flask monolítico, async/sync misturado) se resolvem **dentro** do Python por fração do custo.
3. **Para open source, Python maximiza contribuidores.** O público de um projeto de automação + IA está majoritariamente em Python; uma base C# reduziria o funil de contribuição.
4. **Reescrever é trocar bugs conhecidos por bugs desconhecidos.** São ~400 testes e dezenas de correções de comportamento do Tinder acumuladas no código atual.

## Roadmap de modernização (em Python)

### Fase 1 — Destravar open source (antes de publicar)
- [ ] Suporte a **SQLite por padrão** e PostgreSQL/SQL Server opcionais. O ORM já é agnóstico (os testes rodam em SQLite in-memory); falta isolar o T-SQL de `database/connection.py` (criação de banco via `sys.databases` e auto-migração via `INFORMATION_SCHEMA`) atrás de um seletor de dialeto, ou adotar Alembic. Exigir SQL Server é a maior barreira de entrada para novos usuários.
- [ ] Executar o checklist de segurança ([OPEN_SOURCE_CHECKLIST.md](OPEN_SOURCE_CHECKLIST.md)).

### Fase 2 — Web moderno
- [ ] **Flask → FastAPI** (plano detalhado no relatório existente): async nativo elimina a ponte `asyncio.run()`, validação Pydantic nos endpoints, OpenAPI/Swagger automático — documentação de API de graça para contribuidores.
- [ ] Quebrar `web/app.py` (~3.300 linhas) em routers por domínio (matches, automação, analytics, ML).
- [ ] Redesign de interface — plano em [UI_MODERNIZATION.md](UI_MODERNIZATION.md).

### Fase 3 — Infra de qualidade
- [ ] CI no GitHub Actions (pytest + ruff em cada PR)
- [ ] Alembic para migrações (substituir `_run_migrations()` artesanal)
- [ ] SQLAlchemy async (`AsyncSession`) junto com a migração FastAPI
- [ ] Docker Compose (app + banco) para onboarding em um comando

### O que NÃO fazer
- Reescrever em C#/.NET ou TypeScript (análises neste diretório)
- Adicionar Redis/Celery agora — escala de usuário único não justifica; LRU em memória + threads atendem

## Banco de dados

Acoplamento atual ao SQL Server é **pequeno e localizado**:

| Local | Dependência | Correção |
|---|---|---|
| `database/connection.py` (bootstrap) | `CREATE DATABASE` via `sys.databases` + pyodbc | Pular quando dialeto ≠ mssql |
| `database/connection.py` (migração) | `ALTER TABLE` via `INFORMATION_SCHEMA` | Alembic |
| `config/settings.py` | Connection string ODBC | `DATABASE_URL` genérica |
| `models.py` / `repositories.py` | Nenhuma — ORM puro | — |

Estimativa: 1–2 dias de trabalho para tornar o banco plugável.
