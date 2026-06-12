# Política de Segurança

## Reportando vulnerabilidades

Se você encontrar uma vulnerabilidade de segurança, **não abra uma issue pública**. Reporte de forma privada via [GitHub Security Advisories](../../security/advisories/new) do repositório. Você receberá retorno em até 7 dias.

Escopo de interesse: exposição de credenciais ou dados pessoais, injeção via dados extraídos da web, SSRF/execução de código na interface web, dependências vulneráveis.

## Dados sensíveis manipulados pelo projeto

Este projeto, por natureza, lida com dados sensíveis **locais**:

| Dado | Onde fica | Proteção |
|---|---|---|
| Chaves de API (OpenAI/DeepSeek/Anthropic) | `.env` | Ignorado pelo git; carregado via `python-dotenv` |
| Sessão autenticada do navegador | `browser_data/` | Ignorado pelo git |
| Dados pessoais do usuário | `config/prompts/personal_context.txt` | Ignorado pelo git |
| Dados de matches e conversas | Banco de dados local + `logs/` | Local; logs ignorados pelo git |

A interface web sobe em `0.0.0.0:5000` **sem autenticação** — não exponha a porta para fora da sua máquina/rede local.

## Aviso legal e uso responsável

- Automatizar contas viola os Termos de Serviço do Tinder e da maioria das plataformas, podendo resultar em **banimento permanente** da conta.
- Usar IA para conversar com pessoas sem o conhecimento delas envolve questões éticas sérias. As conversas armazenadas pertencem a terceiros que não consentiram com coleta — trate esses dados como confidenciais e nunca os publique.
- Este software é distribuído para fins **educacionais** (estudo de integração entre IA, automação de navegador e persistência de dados), "no estado em que se encontra", sem garantias (MIT). **Toda responsabilidade pelo uso é do usuário.**
- Contribuições destinadas a evadir mecanismos de detecção de plataformas não são aceitas.
