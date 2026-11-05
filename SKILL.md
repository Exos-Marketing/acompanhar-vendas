---
name: acompanhar-vendas
description: Acompanha as vendas de um projeto da Exos (lançamento, Black Friday, perpétuo) na TMB e na Voomp e compara com a meta do planejamento. Conta matrículas efetivadas por aluna única, separa as fases do projeto, lista quem está aguardando pagamento (boleto, Pix, cartão recusado), mostra a posição contra a meta do dia e projeta o fechamento, sempre com a configuração do próprio projeto (produtos, ofertas, janela, meta e régua). Use quando o usuário pedir para acompanhar, monitorar ou atualizar as vendas de um projeto, ou disser "como estão as vendas", "atualiza as vendas da Black", "quantas matrículas temos", "boletos aguardando pagamento", "estamos batendo a meta?", "liga o monitoramento de vendas", "retoma o acompanhamento", "configura o acompanhamento de vendas do projeto novo". Também faz o resumo semanal da carteira (toda segunda: semana e mês de cada produto, comercial × não comercial): "vendas da semana", "resumo semanal de vendas", "como foi a semana por produto".
---

# Acompanhar vendas (TMB + Voomp)

Lê as vendas de um projeto nas duas plataformas, aplica sempre o mesmo critério e compara com o plano do
projeto. O motor é `scripts/vendas.py` (Python puro, com testes). Cada projeto tem a sua pasta de dados:
`<Expert>/08-Resultados-Relatorios/Vendas [SUFIXO]/` com `config.json`, `historico.csv`, `pendentes.csv`
e `leituras/`. Regras de contagem, schema do config e detalhes das plataformas: [REFERENCE.md](REFERENCE.md).

```bash
SK=~/.claude/skills/acompanhar-vendas/scripts
python3 $SK/vendas.py listar          # projetos configurados e o caminho de cada config
```

Sem projeto dito pelo usuário: se houver um só em andamento, é ele. Sem config: fluxo "Configurar".

## De onde vem cada dado

| Fonte | O que traz | Precisa de |
|---|---|---|
| Voomp, pelo navegador | tudo: pagas, aguardando, recusadas, reembolsos | sessão logada no Playwright MCP; renova ao recarregar, se isso acontecer ao menos a cada 8 h |
| TMB, pela API oficial | pedidos efetivados e cancelados | token no Keychain `tmb-exos-api`; não precisa de login |
| Hotmart, pela API oficial (só carteira) | todas as vendas, afiliado e câmbio | credencial no Keychain `hotmart-exos-api`; não precisa de login |
| TMB, pelo portal | boletos gerados e a oferta de cada pedido | portal logado; a sessão dura 60 min e não renova |

## Leitura

1. **Voomp.** Selecione (ou abra) a aba e faça `browser_navigate` para
   `https://adm.voompcreators.com.br/dashboard`: isso renova o token. Não navegue para `/vendas`, que
   lista compradoras e o navegador grava um retrato de cada página aberta. Caiu na tela de login: pare.
2. `python3 $SK/vendas.py coletor --config "$CFG" --plataforma voomp` e passe a função inteira ao
   `browser_evaluate`, com `filename` = `<pasta do projeto>/leituras/voomp-AAAA-MM-DD_HHMM.json`
   (caminho relativo à raiz do workspace). Com `filename` o resultado vai direto ao arquivo.
3. **TMB pela API:**
   `TMB_API_TOKEN=$(security find-generic-password -s tmb-exos-api -w) python3 -I $SK/vendas.py tmb-api --config "$CFG"`
4. **TMB pelo portal, só se já estiver logado.** Aba em `produtor.tmbeducacao.com.br` com `/login` na
   URL: pule o passo. Logada: `coletor --plataforma tmb` no `browser_evaluate`, com `filename` =
   `…/leituras/tmb-AAAA-MM-DD_HHMM.json`. Não navegue para a raiz `/` nem para `/dashboard/transacoes`.
5. `python3 -I $SK/vendas.py analisar --config "$CFG"`. Usa a última coleta de cada fonte, imprime o
   relatório e o resumo, grava `historico.csv` e `pendentes.csv` e guarda as 3 últimas coletas.
6. **Entregar.** No chat: se estamos no plano, o que mudou e quem está aguardando. No canal do config,
   **só se o `analisar` disser `POSTAR NO CANAL: SIM`** (`clickup_send_chat_message`,
   `content_format: text/md`): o bloco "RESUMO PARA O CANAL" como saiu. Com `POSTAR NO CANAL: NÃO` o
   número de efetivadas não mudou desde a leitura anterior: não poste, e diga isso em uma linha no chat.
   A leitura de fechamento do projeto é a exceção e vai ao canal de qualquer jeito.

Se o `analisar` parar com `SESSAO_EXPIRADA`, ou um coletor devolver `erro`, avise qual sessão caiu e não
entregue número parcial. Em leitura agendada, poste no canal uma linha dizendo que a leitura não saiu e por quê.

## Configurar um projeto novo

1. Identifique sufixo, expert e produto. Leia o planejamento no ClickUp (marco `Planejamento Estratégico
   [SUFIXO]`, com `include: ["description"]`): meta, abertura e fechamento das vendas, fases e preços.
   Se houver régua por dia (plano de reta final), use a acumulada.
2. Descubra produtos, ofertas e afiliados: `python3 $SK/vendas.py descobrir --plataforma voomp --busca "Estomat"`
   no `browser_evaluate` (sem `filename`; não traz dado de comprador). O mesmo com `--plataforma tmb`,
   que precisa do portal logado.
3. Monte o config a partir de [scripts/config_exemplo.json](scripts/config_exemplo.json), mostre ao
   usuário e **confirme antes de gravar**: quais ofertas são de qual fase, o que conta para a meta e o canal.
4. Faça a primeira leitura e um aceite: `analisar --corte AAAA-MM-DDTHH:MM:SS` tem de reproduzir um
   número que o time já conhece.

## Revisão semanal em deck (toda segunda e sob demanda)

Fora de campanha, a revisão é semanal e sai **em deck para a call de sócios, dividido por expert**: semana
fechada (seg a dom), mês até o domingo e o ano, comercial × não comercial, nas três plataformas. A carteira fica
em `Exos/Vendas Semanais/config.json` (`"tipo": "carteira"`; ver [REFERENCE.md](REFERENCE.md)).

1. Coletar: Voomp (passos 1 e 2 da leitura, `filename` = `Vendas Semanais/leituras/voomp-AAAA-MM-DD_HHMM.json`;
   o coletor da carteira não traz contato), TMB (passo 3) e Hotmart:
   `HOTMART_CRED=$(security find-generic-password -s hotmart-exos-api -w) python3 -I $SK/vendas.py hotmart-api --config "$CARTEIRA"`.
   **Voomp nunca em coleta completa:** ela já travou 30 min. Recarregar `/dashboard`, coletar só desde o mês anterior
   (`per_page=50`, timeout por página), gravar como `voomp-delta-*.json`, juntar por id à última `voomp-2*.json` e
   apagar o delta. Venda criada antes do corte que mudou de status não é atualizada: avisar no resumo.
2. `semanal --sem-gravar` para ler os números e escrever `consideracoes/<segunda>.md` (até 6 pontos sobre o
   comercial VS2A para os sócios: só fatos verificados, em forma de pergunta).
3. `CLICKUP_TOKEN=$(security find-generic-password -s clickup-exos-api -w) python3 -I $SK/vendas.py deck --config "$CARTEIRA" --clickup`:
   deck em `Exos/presentations/vendas-semana-<segunda>/` + PDF, grava o histórico, anexa o PDF e comenta na call de
   sócios o link da apresentação. Com `--web` gera também `artifact/` (versão para o navegador).
   Pedido no meio da semana: `--parcial` (semana em andamento) e sem `--clickup` se ele não pedir.
3b. Publicar `artifact/index.html` com a ferramenta Artifact **no mesmo link** (`entrega.call_socios.link_deck`):
   `url` = esse link (ler antes, se a conversa ainda não publicou nele), `files` = `artifact-files.json`, `root` = `artifact`.
4. Conferir os slides em PNG (`npx slidev export --format png`) antes de entregar; abrir a pasta.
5. **Deck da VS2A (call com o Valmir):** `Exos/presentations/vendas-vs2a-<segunda>/`, a partir do da semana anterior
   (porta 3037). Resultado, mês a mês, preços da semana, inbound e planilha × plataformas pelas planilhas ROAS
   COMERCIAL, combinados da call anterior e pontos para alinhar. Sem tom interno de sócios. PDF anexado na call
   `Vendas VS2A <> EXOS` aberta: ela cria uma task por semana e não se finaliza sem o sim do Cleber.
   Antes de citar uma mensagem do canal, conferir a data pelo timestamp dela.

Visão do ano à parte: `vendas.py anual --config "$CARTEIRA" --json …`. Produto novo: acrescentar o id à linha
do produto na carteira (o relatório avisa "fora da carteira").

## Ligar e desligar o monitoramento

`CronCreate` nos horários de `leituras` do config (padrão do Cleber: 7h e 22h, `3 7,22 * * *`), com o
prompt `Rodar a leitura de vendas do projeto [SUFIXO] com a skill acompanhar-vendas; postar no canal só se
o número de efetivadas mudou`.
Crie também um disparo único logo depois do fechamento. Onde houver mais de 7 horas entre duas leituras,
crie disparos só para **renovar a sessão da Voomp** (`33 3,12,17 * * *` para leituras às 7h e 22h):
navegar a aba para `/dashboard`, sem leitura e sem postar. Diga ao usuário os limites: vive só na sessão
atual, expira em 7 dias e só dispara com a sessão ociosa e o Mac acordado. Para desligar: `CronList` e `CronDelete`.

## Regras

- **Só leitura nas plataformas.** Os coletores fazem apenas GET. Nunca clique em cancelar, estornar,
  revogar, editar ou "Finalizar sessão". Gerar token ou mudar algo na conta só com o sim explícito do usuário.
- **Segredos não aparecem.** Token e senha nunca vão para o chat nem para arquivo; não digite senha
  pelo usuário e não tente logar.
- **Dado pessoal fica no chat com o dono e em `pendentes.csv`.** No canal vão só números.
- **Não altere meta, fases ou régua do `config.json` sem confirmar.**
- **Mexeu no motor?** Teste antes: `cd $SK && python3 -m unittest test_vendas`.
