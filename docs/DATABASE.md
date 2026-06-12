# Banco de Dados

O projeto usa **SQLAlchemy 2.0** com o **Repository Pattern**, então o mesmo código roda em SQLite, PostgreSQL ou SQL Server. O schema é definido em `database/models.py` e criado automaticamente — você **não precisa** escrever SQL nem rodar migrations manualmente para começar.

## Início rápido (SQLite — padrão)

Não configure nada. Na primeira execução o app cria `data/automatic_tinder_chat.db` e todas as tabelas:

```bash
python main.py
```

Pronto. SQLite é embutido no Python; nenhum driver ou servidor é necessário.

## Como a criação automática funciona

Em `DatabaseManager.initialize()` (`database/connection.py`):

1. **Resolve a URL** do banco nesta ordem: `DATABASE_URL` → `SQL_SERVER_CONNECTION_STRING` (legado) → SQLite local.
2. **Garante o database** (`_ensure_database_exists`): SQLite cria o arquivo on-demand; SQL Server cria o database via `CREATE DATABASE` se faltar; outros dialetos assumem que já existe.
3. **Cria as tabelas** com `Base.metadata.create_all()` — idempotente, só cria o que falta.
4. **Migra colunas** (`_run_migrations`): apenas no SQL Server, para bancos antigos aos quais faltem colunas recentes (`pending_resend`, etc.). Bancos novos já nascem completos.

## Escolhendo outro banco

Defina `DATABASE_URL` no `.env`:

| Banco | `DATABASE_URL` | Driver a instalar |
|---|---|---|
| SQLite (padrão) | *(vazio)* ou `sqlite:///./data/automatic_tinder_chat.db` | nenhum |
| PostgreSQL | `postgresql+psycopg2://usuario:senha@localhost:5432/tinderchat` | `pip install psycopg2-binary` |
| SQL Server | `mssql+pyodbc://usuario:senha@host/banco?driver=ODBC+Driver+17+for+SQL+Server` | `pip install pyodbc` + [ODBC Driver](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) |

> **PostgreSQL/SQL Server:** o app cria as **tabelas**, mas o **database** em si precisa existir antes (exceto SQL Server, que tem criação automática quando você usa `SQL_SERVER_CONNECTION_STRING`). Crie com `CREATE DATABASE tinderchat;` antes de subir.

### SQL Server via connection string (legado)

Se preferir a connection string ODBC em vez de `DATABASE_URL`, deixe `DATABASE_URL` vazio e use:

```env
SQL_SERVER_CONNECTION_STRING=Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=AutomaticTinderChat;Trusted_Connection=yes
```

Nesse modo o database é criado automaticamente se não existir.

## Schema

12 tabelas. Todas têm `id` inteiro autoincremento como chave primária e `created_at`/`updated_at` quando aplicável.

### Perfil do usuário

**`my_profile`** — seu próprio perfil e análise.
`tinder_id`, `name`, `age`, `bio`, `location`, `job_title`, `company`, `school`, contadores de fotos/interesses, scores de análise (`bio_quality_score`, `photos_quality_score`, `completeness_score`, `match_potential_score`, `overall_score`) e análises textuais.

**`my_profile_photos`** — fotos do seu perfil (FK `profile_id` → `my_profile`). `photo_url`, `photo_order`, `description` (gerada por IA).

**`my_profile_interests`** — interesses do seu perfil (FK `profile_id`). `interest_name`.

### Matches

**`matches`** — perfis que deram match. Tabela central.
- Identidade: `tinder_match_id` (único), `tinder_person_id`, `name`, `age`, `bio`, `distance_km`, `job_title`, `company`, `school`
- Perfil estendido: `relationship_intent`, `sexual_orientations`, `gender`, `city`, `relationship_type`, `lifestyle_info`, `is_verified`, `profile_photo_url`
- Conversa: `last_message_text`, `last_message_from_me`, `has_messages`, `first_message_sent`, `awaiting_my_response`, `conversation_temperature` (cold/warm/hot), `temperature_score`, `temperature_history` (JSON)
- Progressão: `whatsapp_requested`, `whatsapp_obtained`, `whatsapp_number`, `date_suggested`, `date_confirmed`
- Reenvio: `pending_resend`, `resend_reason`, `resend_at`
- Controle: `is_blocked`, `blocked_reason`, `blocked_at`, `is_unmatched`, `unmatched_at`
- Scores: `bio_quality_score`, `photos_quality_score`, `compatibility_score`, `overall_score`
- Índices compostos para queries de matches ativos/pendentes (ver `__table_args__`)

**`match_photos`** — fotos dos matches (FK `match_id`). `photo_url`, `photo_order`, `description`.

**`match_interests`** — interesses dos matches (FK `match_id`). `interest_name`, `is_common` (em comum com você).

### Mensagens e análise

**`messages`** — mensagens trocadas (FK `match_id`). `content`, `is_from_me`, `message_type`, `ai_generated`, `ai_analysis`, `sent_at`. Índices em `match_id` e `sent_at`.

**`match_reports`** — relatórios/sugestões por match (FK `match_id`). `report_type`, `conversation_summary`, `topic_suggestions` (JSON), `next_message_suggestions` (JSON), `compatibility_analysis`, scores de engajamento/progressão.

**`ai_interactions`** — log de cada chamada à IA. `interaction_type`, `provider`, `model_used`, `prompt_template`, `response_content`, tokens (`prompt_tokens`/`completion_tokens`/`total_tokens`), `estimated_cost`, `success`, `response_time_ms`. Índices por tipo/provedor/data para relatórios de gasto.

### Operação e métricas

**`execution_logs`** — log de execuções. `execution_type`, contadores (`matches_processed`, `messages_sent`, `messages_analyzed`, `errors_count`), `status`, tempos.

**`analytics`** — métricas agregadas por dia. Matches, mensagens, `response_rate`, conversões (WhatsApp/encontros), temperatura média, custo de IA acumulado.

**`notifications`** — notificações para a interface web. `notification_type`, `title`, `message`, `icon`, `color`, `is_read`, FK opcional `match_id`.

### Diagrama de relacionamentos

```
my_profile ─┬─< my_profile_photos
            └─< my_profile_interests

matches ─┬─< match_photos
         ├─< match_interests
         ├─< messages
         ├─< match_reports
         ├─< ai_interactions   (FK opcional)
         └─< notifications      (FK opcional)
```

## Recriar ou inspecionar o banco (SQLite)

```bash
# Recriar do zero: basta apagar o arquivo; ele é recriado no próximo start
rm data/automatic_tinder_chat.db

# Inspecionar
sqlite3 data/automatic_tinder_chat.db ".tables"
sqlite3 data/automatic_tinder_chat.db ".schema matches"
```

## Migrações (roadmap)

Hoje a evolução de schema é coberta por `create_all()` (colunas novas em bancos novos) e por uma migração T-SQL pontual no SQL Server. Para mudanças mais complexas em produção, o roadmap prevê adotar **Alembic** — veja [TECHNOLOGY.md](TECHNOLOGY.md). Em desenvolvimento com SQLite, recriar o arquivo costuma ser suficiente.
