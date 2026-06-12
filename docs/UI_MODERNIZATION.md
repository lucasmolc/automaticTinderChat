# Plano de Modernização da Interface

Estado atual, diagnóstico e plano de redesign da interface web.

## Diagnóstico do frontend atual

Stack: Flask + Jinja2 + Bootstrap 5.3 (CDN) + Chart.js + Socket.IO com fallback de polling. Tema escuro fixo com gradiente rosa/vermelho (#fe3c72 → #ff6b6b), fonte Inter.

| Débito | Onde | Impacto |
|---|---|---|
| ~1.000 linhas de CSS inline | `web/templates/base.html` | Impossível reutilizar/temar; difícil de contribuir |
| ~2.000 linhas de JS inline espalhadas | todos os templates | Sem modularização, helpers duplicados por página |
| Modais reimplementados à mão | `base.html` | Reinventa o que Bootstrap 5 já oferece |
| CDNs sem Subresource Integrity | `base.html` | Risco de supply chain |
| Sem build system | — | Sem minificação, sem tree-shaking, sem lint de JS |
| Respostas de API inconsistentes | `web/app.py` | Alguns endpoints retornam `{success, data}`, outros JSON direto |

## Decisão de abordagem

Três opções avaliadas:

| Opção | Prós | Contras | Veredicto |
|---|---|---|---|
| (a) Manter Jinja2 + redesign CSS | Zero migração | Não resolve JS inline nem reatividade | Insuficiente |
| (b) SPA (React/Vue/Svelte) | DX excelente, escala | Build pipeline, CORS, duplicação de rotas — peso alto para app local single-user | Overkill |
| **(c) HTMX + Alpine.js** | Mantém Flask/Jinja2, ~14KB total, refactor incremental, sem bundler obrigatório | Paradigma menos conhecido que React | **Escolhida** |

**Justificativa:** o backend já renderiza templates e expõe API REST. HTMX permite migrar página por página (fragmentos Jinja2 renderizados pelo servidor), Alpine cobre a interatividade local (tabs, modais, toggles), e o WebSocket existente continua cuidando do tempo real. Para um dashboard local de usuário único, uma SPA adicionaria complexidade sem benefício proporcional — e dificultaria contribuições casuais.

## Direção visual ("tema")

Manter a identidade dark + gradiente quente, mas formalizada como design system:

- **Design tokens em CSS custom properties** (`static/css/tokens.css`): cores, espaçamentos, raios, sombras, tipografia — preparado para tema claro futuro via `data-theme`.
- **Paleta**: fundo `#0f1117` / superfície `#171a23` / gradiente de marca `#fe3c72 → #ff6b6b` / acentos semânticos (verde sucesso, âmbar morno, azul info) já usados na classificação de temperatura de conversas.
- **Tipografia**: Inter (atual) para UI; tabular numerals nos cards de métricas.
- **Componentes a padronizar**: stat cards com sparkline, badges de temperatura (fria/morna/quente), timeline de mensagens estilo chat, tabela de matches com avatar + estado, painel de controle com switch grande iniciar/parar.
- **Acessibilidade**: contraste AA no dark theme, `prefers-reduced-motion`, foco visível.

## Plano de execução incremental

### Fase 1 — Extração (sem mudança visual)
1. `base.html` → extrair CSS para `static/css/main.css` + `tokens.css`
2. Helpers JS globais (formatDate, toasts, modais) → `static/js/app.js`
3. Substituir modais artesanais pelos modais nativos do Bootstrap 5
4. Adicionar SRI aos CDNs (ou vendorizar os assets)

### Fase 2 — HTMX nos fluxos de dados
1. Endpoints de fragmento (`/fragments/stats`, `/fragments/matches-table`, …) renderizando parciais Jinja2
2. Páginas trocam `fetch` + manipulação manual de DOM por `hx-get`/`hx-trigger`
3. Polling fallback vira `hx-trigger="every 10s"` onde WebSocket não estiver disponível

### Fase 3 — Redesign visual
1. Aplicar tokens e novos componentes página a página: Dashboard → Matches → Control → Analytics → Messages
2. Estados vazios ilustrados, skeleton loaders em vez de spinners
3. Tema claro opcional

### Fase 4 — Padronização de API
1. Envelope único `{success, data, error}` em todos os endpoints
2. (Com a migração FastAPI) schemas Pydantic + Swagger automático

## Critérios de aceitação

- Nenhum `<style>` ou `<script>` com lógica de página dentro de templates
- Lighthouse ≥ 90 em performance/acessibilidade no dashboard
- Tema controlado exclusivamente por tokens (trocar 5 variáveis muda a marca)
- Qualquer página renderiza estado vazio e estado de erro decentes
