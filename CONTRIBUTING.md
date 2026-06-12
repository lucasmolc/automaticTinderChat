# Guia de Contribuição

Obrigado pelo interesse em contribuir! Este documento explica como participar do projeto.

## Antes de começar

Leia o [aviso de uso responsável](README.md#%EF%B8%8F-aviso-importante) — este é um projeto educacional. Contribuições que tenham como objetivo burlar mecanismos de detecção de plataformas **não serão aceitas**.

## Setup de desenvolvimento

```bash
git clone https://github.com/<seu-fork>/automaticTinderChat.git
cd automaticTinderChat
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/Mac
pip install -r requirements.txt
playwright install chromium
cp .env.example .env            # opcional: configure suas chaves
```

O banco padrão é SQLite (criado automaticamente em `data/`), então não é preciso instalar SQL Server nem PostgreSQL para desenvolver. Veja [docs/DATABASE.md](docs/DATABASE.md) para trocar de banco.

## Rodando os testes

```bash
pytest -m "not e2e"        # suite rápida (SQLite in-memory, IA mockada)
pytest                     # suite completa (exige Playwright)
pytest --cov=. --cov-report=term-missing
```

Todo PR deve manter a suite verde e cobrir o novo comportamento com testes.

## Convenções do projeto

- **Arquitetura SYNC/EXECUTE é inegociável**: execução nunca faz scraping; dados vêm sempre do banco (veja [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
- **Repositories** para todo acesso a dados — nada de SQL raw em serviços.
- **Provedores de IA** implementam `BaseAIProvider`; o acesso é sempre via `AIService`.
- **Prompts** são arquivos `.txt` em `config/prompts/` — não embuta prompt em código.
- **Logs**: console é só para WARNING+; use o logger (Loguru), nunca `print()`.
- Docstrings e comentários em português; nomes de classes/funções em inglês quando forem termos técnicos.

## Fluxo de contribuição

1. Abra uma issue descrevendo o bug/proposta antes de PRs grandes
2. Fork → branch a partir de `main` (`feat/...`, `fix/...`)
3. Commits no padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
4. Atualize `docs/CHANGELOG.md` na seção da próxima versão
5. Abra o PR descrevendo o problema, a solução e como testar

## Segurança e dados

- **Nunca** commite `.env`, `browser_data/`, `logs/`, `data/*.json` ou `config/prompts/personal_context.txt`
- Não inclua dados reais de pessoas (nomes, mensagens, IDs de matches) em testes, fixtures ou exemplos — use sempre dados fictícios
- Vulnerabilidades: veja [SECURITY.md](SECURITY.md)
