<div align="center">

# 🔥 Automatic Tinder Chat

**Estudo de caso de integração entre IA generativa, automação de navegador e persistência de dados — com dashboard web em tempo real.**

![Version](https://img.shields.io/badge/Version-2.7.0-blue.svg)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB.svg?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.40-2EAD33.svg?logo=playwright&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-000000.svg?logo=flask)
![Database](https://img.shields.io/badge/DB-SQLite%20%7C%20PostgreSQL%20%7C%20SQL%20Server-336791.svg)
![Tests](https://github.com/lucasmolc/automaticTinderChat/actions/workflows/tests.yml/badge.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Uso-Educacional-yellow.svg)

[Arquitetura](docs/ARCHITECTURE.md) · [Banco de Dados](docs/DATABASE.md) · [Configuração](docs/CONFIGURATION.md) · [Tecnologia](docs/TECHNOLOGY.md) · [Changelog](docs/CHANGELOG.md) · [Contribuindo](CONTRIBUTING.md)

</div>

---

## ⚠️ Aviso Importante

> **Projeto desenvolvido exclusivamente para fins de estudo e aprendizado.**
>
> Automatizar contas **viola os Termos de Serviço do Tinder** e da maioria das plataformas, e pode resultar em **banimento permanente**. Usar IA para conversar com pessoas sem o conhecimento delas envolve questões éticas reais. Use apenas em ambientes controlados, por sua conta e risco. Detalhes em [SECURITY.md](SECURITY.md).

## 📖 O que é

Este projeto demonstra, de ponta a ponta, como integrar tecnologias modernas em um sistema real:

- 🤖 **IA multi-provider** — OpenAI, Anthropic Claude e DeepSeek intercambiáveis em runtime, com prompts versionados em arquivos, contexto pessoal injetado e rastreamento de custo por token
- 🌐 **Automação de navegador** — Playwright async com simulação de comportamento humano e separação rígida entre sincronização (scraping) e execução (ações)
- 🗄️ **Persistência plugável** — SQLAlchemy 2.0 + Repository Pattern: roda em **SQLite (padrão, zero config)**, PostgreSQL ou SQL Server, com criação automática de schema
- 📊 **Dashboard em tempo real** — Flask + WebSocket: matches, conversas, analytics, funil de conversão e painel de controle
- 🧠 **ML aplicado** — otimização de prompts via Thompson Sampling, A/B testing com tracking de conversões e cache de embeddings com busca por similaridade

## ✨ Funcionalidades

| Módulo | Descrição |
|--------|-----------|
| Análise de perfil | Extrai e analisa perfis usando IA |
| Geração de mensagens | Mensagens contextualizadas por perfil e histórico de conversa |
| Classificação de conversas | Temperatura (fria/morna/quente) e progressão |
| Detecção de padrões | Reconhece troca de telefone e confirmações de encontro |
| Dashboard analytics | Métricas, gráficos e funil de conversão em tempo real |
| A/B testing | Variantes de estilo/tamanho/emoji com tracking automático |
| ML adaptive | Thompson Sampling para otimizar prompts continuamente |
| Scheduler | Tarefas agendadas (auto-ajuste de pesos, limpeza de logs) |
| Reenvio inteligente | Detecção e reenvio de mensagens incompletas |
| Sync headless | Sincronização em segundo plano durante as pausas |

## 🏗️ Arquitetura em 30 segundos

O princípio central é a separação **SYNC ≠ EXECUTE**: o scraping (SYNC) valida e persiste dados no banco; a execução (EXECUTE) age usando **exclusivamente** dados persistidos — nunca dados lidos da tela na hora.

```
EXECUTE (browser visível)              SYNC (headless, durante a pausa)
ExecutionService ◄─ MatchDataService   ProfileSyncer ─► DataValidationService
        ▲                  ▲                                   │
        └── envia msgs     └────────── BANCO ◄─────────────────┘
```

Camadas: `web/` (Flask + WebSocket) → `automation/` (orquestrador + serviços) → `ai/` (multi-provider) + `database/` (repositories) + `services/` (ML, scheduler, embeddings). Detalhes em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 🚀 Começando

### Pré-requisitos

- Python 3.9+
- Uma chave de API de pelo menos um provedor (OpenAI, Anthropic ou DeepSeek) — opcional para subir a interface, necessária para gerar mensagens
- **Banco de dados: nenhum setup.** Por padrão o app usa SQLite local. PostgreSQL/SQL Server são opcionais — veja [docs/DATABASE.md](docs/DATABASE.md).

### Instalação automática

```bash
git clone https://github.com/lucasmolc/automaticTinderChat.git
cd automaticTinderChat
python main.py
```

O `main.py` cria o `.venv`, instala dependências e navegadores Playwright, gera o `.env` a partir do exemplo e sobe a aplicação. Na primeira execução o banco SQLite e todas as tabelas são criados automaticamente.

### Instalação manual

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac
pip install -r requirements.txt
playwright install chromium
cp .env.example .env            # configure suas chaves (opcional)
python run_web.py
```

### Configuração

Tudo é opcional para começar. Para personalizar (chave de IA, banco, prompts), edite o `.env` e copie `config/prompts/personal_context.example.txt` → `personal_context.txt`. Variáveis documentadas em [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## 🗄️ Banco de Dados

Funciona out-of-the-box com **SQLite** — o arquivo e as 12 tabelas são criados sozinhos. Para trocar de banco, basta definir `DATABASE_URL` no `.env`:

```env
# SQLite (padrão) — não precisa configurar nada
# PostgreSQL:
DATABASE_URL=postgresql+psycopg2://usuario:senha@localhost:5432/tinderchat
# SQL Server:
DATABASE_URL=mssql+pyodbc://usuario:senha@host/banco?driver=ODBC+Driver+17+for+SQL+Server
```

Schema completo, diagrama de relacionamentos e guia de criação/migração em **[docs/DATABASE.md](docs/DATABASE.md)**.

## 🏃 Modos de execução

```bash
python main.py                # interface web (padrão) → http://localhost:5000
python main.py -a [minutos]   # automação contínua (intervalo entre ciclos)
python main.py -s             # apenas sincronização
python main.py -r             # gerar relatórios
python main.py --reset        # limpar estado travado
```

## 🌐 Interface Web

`http://localhost:5000` — tema escuro, atualização em tempo real via WebSocket (com fallback de polling).

| Rota | Descrição |
|------|-----------|
| `/` | Dashboard com estatísticas em tempo real |
| `/matches` | Lista de matches com filtros, busca e detalhes |
| `/messages` | Histórico de mensagens geradas |
| `/analytics` | Gráficos, funil de conversão, A/B testing e ML insights |
| `/control` | Iniciar/parar automação e gerenciar provedores de IA |

A API REST (`/api/*`) cobre stats, matches, mensagens, automação, ML, scheduler e cache — endpoints listados em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Plano de modernização da interface em [docs/UI_MODERNIZATION.md](docs/UI_MODERNIZATION.md).

## 🧪 Testes

400+ testes em ~24 arquivos, rodando sem dependências externas (SQLite in-memory, provedores de IA mockados):

```bash
pytest -m "not e2e"                          # suite rápida
pytest --cov=. --cov-report=term-missing     # com cobertura
```

O CI no GitHub Actions roda a suite em Python 3.9, 3.11 e 3.12 a cada push/PR.

## 📚 Documentação

| Documento | Conteúdo |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Arquitetura, módulos, padrões e pontos de atenção |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema das 12 tabelas, criação automática e setup por banco |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Variáveis de ambiente, prompts e dados de runtime |
| [docs/TECHNOLOGY.md](docs/TECHNOLOGY.md) | Por que Python (e não C#/TS) + roadmap de modernização |
| [docs/UI_MODERNIZATION.md](docs/UI_MODERNIZATION.md) | Diagnóstico e plano de redesign da interface |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Histórico de versões |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup de dev, convenções e fluxo de PR |
| [SECURITY.md](SECURITY.md) | Política de segurança e uso responsável |

## 🗺️ Roadmap

- [x] Banco plugável: SQLite por padrão, PostgreSQL/SQL Server opcionais
- [ ] Flask → FastAPI (async nativo + OpenAPI automático)
- [ ] Redesign da interface (HTMX + Alpine.js + design tokens)
- [ ] Migrações com Alembic
- [ ] Docker Compose para onboarding em um comando

Detalhes e justificativas em [docs/TECHNOLOGY.md](docs/TECHNOLOGY.md).

## 🤝 Contribuindo

Contribuições são bem-vindas! Leia o [CONTRIBUTING.md](CONTRIBUTING.md) e o [Código de Conduta](CODE_OF_CONDUCT.md). Contribuições voltadas a evadir detecção de plataformas não são aceitas.

## 📄 Licença

[MIT](LICENSE) © Lucas Mol

---

<div align="center">

**⭐ Se este projeto foi útil para seu aprendizado, considere dar uma estrela!**

</div>
