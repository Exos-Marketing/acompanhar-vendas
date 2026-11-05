# acompanhar-vendas

Skill do Claude Code que acompanha as vendas de um projeto da Exos (lançamento, Black Friday, perpétuo) na TMB e na
Voomp e compara com a meta do planejamento. Conta matrículas efetivadas por aluna única, separa as fases, lista quem
está aguardando pagamento (boleto, Pix, cartão recusado), mostra a posição contra a meta do dia e projeta o
fechamento. Toda segunda faz também a revisão semanal da carteira em deck para a call de sócios: semana, mês e ano
por expert, comercial × não comercial, na TMB, na Voomp e na Hotmart.

```
Voomp e TMB (navegador)  +  TMB e Hotmart (API)  →  vendas.py analisar  →  relatório, historico.csv, pendentes.csv  →  canal do ClickUp (só números)
```

## Instalação

```bash
git clone https://github.com/Exos-Marketing/acompanhar-vendas.git \
  ~/.claude/skills/acompanhar-vendas
```

Requisitos:

- Python 3.9+ (o motor só usa a biblioteca padrão).
- O MCP do Playwright com a Voomp logada (e o portal da TMB, quando for ler boletos).
- Credenciais no Keychain, cada uma no seu serviço:
  - `tmb-exos-api`: token da API da TMB;
  - `hotmart-exos-api`: credencial da API da Hotmart (só na revisão semanal);
  - `clickup-exos-api`: token do ClickUp (deck semanal com `--clickup`).
- Node.js, para o deck da revisão semanal (Slidev; o molde fica em `scripts/deck/`).
- A pasta de trabalho da Exos em `~/Documents/Exos`: cada projeto guarda os dados em
  `<Expert>/08-Resultados-Relatorios/Vendas [SUFIXO]/`, e a carteira fica em `Vendas Semanais/`.

**Nenhuma credencial mora neste repo.**

## Uso

```bash
SK=~/.claude/skills/acompanhar-vendas/scripts
python3 $SK/vendas.py listar                                        # projetos configurados
python3 $SK/vendas.py coletor --config "$CFG" --plataforma voomp    # função para o browser_evaluate
TMB_API_TOKEN=$(security find-generic-password -s tmb-exos-api -w) python3 -I $SK/vendas.py tmb-api --config "$CFG"
python3 -I $SK/vendas.py analisar --config "$CFG"                   # relatório, histórico e pendentes
```

No Claude Code basta pedir "como estão as vendas da Black?" ou "vendas da semana". O passo a passo completo
(leitura, projeto novo, revisão semanal e monitoramento agendado) está no `SKILL.md`.

## Regras

- Só leitura nas plataformas: os coletores fazem apenas GET.
- Token e senha nunca vão para o chat nem para arquivo.
- Dado pessoal fica no chat com o dono e no `pendentes.csv`; no canal vão só números.
- Meta, fases e régua do config só mudam com confirmação.
- Mexeu no motor: `cd $SK && python3 -m unittest test_vendas`.

## O que tem aqui

| arquivo | o que faz |
|---|---|
| `SKILL.md` | leitura, projeto novo, revisão semanal em deck e monitoramento |
| `REFERENCE.md` | regras de contagem, schema do config e detalhes de cada plataforma |
| `scripts/vendas.py` | o motor: coleta pela API, analisa, grava histórico e pendentes e monta o resumo semanal |
| `scripts/deck_vendas.py` | deck Slidev da revisão semanal por expert |
| `scripts/deck/` | molde do deck (estilo, componentes e logo) |
| `scripts/coletores/` | funções para o `browser_evaluate`: coleta e descoberta de produtos e ofertas na TMB e na Voomp |
| `scripts/config_exemplo.json` | modelo de config de projeto |
| `scripts/test_vendas.py` | testes do motor |

---

Interno · Exos Marketing Digital e Internacionalização Ltda.
