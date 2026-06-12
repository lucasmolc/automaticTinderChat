# Checklist de Publicação Open Source

Status em 2026-06-12: este repositório (`automaticTinderChat`) foi criado **do zero**, a partir de uma cópia sanitizada do projeto original. O histórico do git começa limpo — nenhum dado sensível jamais foi commitado aqui. ✅ **Pronto para publicar.**

## ✅ Bloqueantes — resolvidos por construção

### 1. Histórico do git limpo

Diferente do repositório original (cujo histórico continha `browser_data/` com tokens de sessão e `data/*.json` com IDs de matches), este repo nasce com um único commit inicial sobre uma árvore já sanitizada. Não há nada a expurgar.

### 2. Arquivos sensíveis não copiados

A migração **excluiu** estes itens (e o `.gitignore` impede que voltem):

| Arquivo/Pasta | Status |
|---|---|
| `config/prompts/personal_context.txt` | ✅ Não copiado (só o `.example.txt` fictício) |
| `.env` | ✅ Não copiado (só o `.env.example`) |
| `browser_data/` | ✅ Não copiado |
| `data/*.json` (não-template) | ✅ Removidos |
| `logs/` | ✅ Não copiado |
| `reports/output/` | ✅ Não copiado |

Varredura de segredos no código: nenhuma chave de API, telefone, dado pessoal ou caminho absoluto de usuário encontrado.

### 3. Rotacionar credenciais (recomendado)

Por precaução geral, vale gerar novas chaves de API e deslogar a sessão do Tinder usada no projeto original — embora nenhuma credencial tenha entrado neste repositório.

## ✅ Qualidade de open source

- [x] `LICENSE` (MIT)
- [x] `README.md` (reescrito para o novo repo, banco SQLite padrão)
- [x] `CONTRIBUTING.md`
- [x] `SECURITY.md`
- [x] `CODE_OF_CONDUCT.md`
- [x] `docs/` — arquitetura, banco, configuração, tecnologia, plano de UI, changelog
- [x] CI: `.github/workflows/tests.yml` (pytest em 3.9/3.11/3.12 + ruff)
- [x] Templates de issue (`.github/ISSUE_TEMPLATE/`) e de PR
- [x] Badge de CI dinâmica no README
- [x] Banco plugável com SQLite padrão — clone roda sem SQL Server (405 testes passando)

## ⚖️ Risco legal / Termos de Serviço

Automação de contas viola explicitamente os Termos de Uso do Tinder e pode resultar em banimento permanente. Além disso, usar IA para conversar com pessoas **sem que elas saibam** levanta questões éticas reais (consentimento, engano).

Mitigações aplicadas/recomendadas:
- Disclaimer educacional destacado no README (reforçado na reescrita)
- Seção de uso responsável no `SECURITY.md`
- Recomendação: manter o projeto como estudo de caso de integração IA + automação + dados, sem oferecer suporte a evasão de detecção

## Verificação final antes do push

```bash
# nada sensível rastreado
git ls-files | grep -E "\.env$|personal_context\.txt|browser_data|^logs/|^data/.*\.json$"   # vazio (exceto templates)

# nada sensível no histórico (após opção A ou B)
git log --all --name-only --pretty=format: | sort -u | grep -E "browser_data|\.env$|personal_context"  # vazio

# nenhum segredo no código
grep -rE "sk-[A-Za-z0-9]{20,}" --include="*.py" .   # vazio
```
