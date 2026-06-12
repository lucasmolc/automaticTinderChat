# Configuração

## Variáveis de ambiente (`.env`)

Copie `.env.example` para `.env`. Nunca commite o `.env`.

### Provedores de IA

| Variável | Descrição | Padrão |
|---|---|---|
| `OPENAI_API_KEY` | Chave da OpenAI (obrigatória se OpenAI ativo) | — |
| `OPENAI_MODEL` | Modelo OpenAI | `gpt-4o` |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | Alternativa de menor custo | `deepseek-chat` |
| `CLAUDE_API_KEY` / `CLAUDE_MODEL` | Anthropic Claude | — |

O provedor ativo e o modelo podem ser trocados em runtime pelo Painel de Controle (`/control`), sem editar arquivos.

### Banco de dados

| Variável | Descrição |
|---|---|
| `SQL_SERVER_CONNECTION_STRING` | Connection string ODBC. Com `Trusted_Connection=yes` usa autenticação Windows; com `UID`/`PWD`, autenticação SQL. |

O banco é criado automaticamente na primeira execução, e colunas novas são adicionadas por auto-migração.

### Navegador

| Variável | Descrição | Padrão |
|---|---|---|
| `CHROME_USER_DATA_DIR` | Perfil do Chrome para manter sessão logada | — |
| `CHROME_PROFILE` | Nome do perfil | `Default` |
| `BROWSER_HEADLESS` | Browser invisível | `false` |

A sessão do Playwright fica em `browser_data/` — **nunca commite essa pasta**, ela contém tokens de sessão autenticada.

### Automação

| Variável | Descrição | Padrão |
|---|---|---|
| `ACTION_DELAY_MIN` / `ACTION_DELAY_MAX` | Atraso entre ações (s), simula comportamento humano | 2 / 5 |
| `MAX_MESSAGES_PER_RUN` | Limite de mensagens por execução | 20 |
| `DAYS_WITHOUT_INTERACTION` | Dias para considerar conversa fria | 7 |
| `IGNORE_DOUBLEDATE` | Ignorar matches em dupla | `true` |

### Logs

| Variável | Descrição | Padrão |
|---|---|---|
| `LOG_LEVEL` | Nível de log dos arquivos | `INFO` |
| `LOG_RETENTION_DAYS` | Retenção dos logs | 10 |

Console exibe apenas WARNING+; arquivos em `logs/` recebem DEBUG+. Chamadas de IA são gravadas em formato bruto em `logs/ai_raw_YYYY-MM-DD.log`.

## Prompts (`config/prompts/`)

Todos os prompts são arquivos `.txt` editáveis sem mexer em código. Após editar, use `clear_prompts_cache()` ou reinicie.

| Arquivo | Tipo | Uso |
|---|---|---|
| `system_first_message.txt` / `first_message.txt` | system / user | Primeira mensagem |
| `system_conversation_response.txt` / `conversation_response.txt` | system / user | Respostas em conversa |
| `system_profile_analysis.txt` / `profile_analysis.txt` | system / user | Análise de perfil |
| `system_analytics_insights.txt` / `analytics_insights.txt` | system / user | Insights analíticos |
| `system_match_report.txt` | system | Relatório de match |
| `personal_context.txt` | system | **Seus dados pessoais — nunca commitado** |
| `personal_context.example.txt` | — | Template fictício versionado |

### Contexto pessoal

`personal_context.txt` é injetado em **todas** as chamadas à IA para que respostas nunca inventem dados incorretos (cidade, profissão, etc.):

1. Copie `personal_context.example.txt` → `personal_context.txt`
2. Preencha com seus dados
3. O `.gitignore` já protege o arquivo — confirme antes de commitar

## Dados em runtime

| Pasta | Conteúdo | Versionado? |
|---|---|---|
| `data/` | Estado da automação, experimentos A/B, ML adaptive (JSON) | Não (apenas `*.template.json`) |
| `browser_data/` | Perfil do navegador (sessão autenticada) | **Nunca** |
| `logs/` | Logs diários | Não |
| `reports/output/` | Relatórios e gráficos gerados | Não |
