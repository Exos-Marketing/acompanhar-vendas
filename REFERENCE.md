# Referência · acompanhar-vendas

## Regras de contagem

1. **O dia é o do pagamento**, no fuso do projeto. A Voomp devolve `paid_at` em UTC; a TMB devolve
   `efetivado_em` já em horário de Brasília.
2. **Matrícula efetivada:** `paid` na Voomp, `Efetivado` na TMB.
3. **Aluna única:** mesma pessoa é mesmo CPF ou mesmo e-mail, cruzando as duas plataformas. Cobrança em
   dobro e compra nas duas plataformas contam uma vez (vale onde pagou primeiro) e viram alerta.
4. **Assinatura:** só a primeira cobrança paga da aluna naquele produto é matrícula. O resto é mensalidade.
   O `contract_id` não serve de chave: na Pós da Elen (Voomp `10940`) um contrato junta 70 alunas
   (assinaturas migradas) e há aluna que ganha contrato novo ao renegociar.
   Por isso a Voomp é coletada com meses de folga (`coletar_desde`).
5. **Fase:** a venda vai para a fase que lista a sua oferta; se nenhuma lista, para a primeira fase cuja
   janela contém o pagamento. Sem fase, não entra em nada (venda de perpétuo antes do lançamento).
6. **Só fases com `conta_na_meta: true` somam para a meta.** As outras aparecem em linha à parte.
7. **Sai da conta:** `refunded` e `chargedback` na Voomp; Cancelado e Cancelamento Solicitado na TMB;
   itens de `ignorar`. Status que o motor não conhece vira alerta e não é contado.
8. **Aguardando pagamento** é pessoa, não cobrança: quem tentou dentro de uma fase (boleto ou Pix aberto,
   contrato sem assinatura, ou só cartão recusado) e **não tem nenhuma compra paga** em nenhuma das duas
   plataformas. Quem já é aluna de antes fica fora. Mensalidade de assinatura em aberto não é pendente e
   não aparece nos textos (o motor só a conta, em `mensalidades_abertas`).
9. **Comercial:** o que o config indicar. Na TMB, produtos; na Voomp, afiliados.

**Oferta abaixo do preço da fase não é, por si só, venda errada.** Pode ser o saldo de uma matrícula com
entrada paga por fora (Pix direto na conta da empresa): conta como uma matrícula, mas o valor na plataforma
fica menor que o preço e a entrada não aparece em nenhuma das duas. Na dúvida, pergunte ao dono e anote a
resposta em `observacoes` no config do projeto.

Diferença para a contagem "bruta" das telas (Efetivado + Pago): a bruta soma a cobrança em dobro e as
vendas de outra fase. Diferença para quem conta a TMB pela data de criação do pedido: o total é o mesmo,
muda o dia (pedido criado numa noite e efetivado no dia seguinte).

## config.json

```jsonc
{
  "projeto": "[XX][BF][POS][OUT][26]",        // sufixo do projeto
  "titulo": "Black Exemplo",                  // nome curto que abre o resumo
  "fuso": "America/Sao_Paulo",
  "plataformas": {                            // só as que o projeto usa
    "voomp": {
      "produtos": {"100": "avulso", "200": "recorrência"},   // id -> rótulo
      "assinatura": [200],                    // produtos cobrados por mês
      "comercial": {"afiliados": [9]},        // ou {"qualquer_afiliado": true}
      "coletar_desde": "2026-01-01"           // padrão: 120 dias antes da primeira janela
    },
    "tmb": {
      "central_id": "uuid da central",        // trava contra ler a central errada no portal
      "produtos": {"300": "C/Comercial", "301": "S/Comercial"},
      "comercial": {"produtos": [300],        // "produtos_desde": "AAAA-MM-DDTHH:MM:SS" quando o link
                    "produtos_desde": null},  // público caiu no produto do comercial até essa hora (vale a criação do pedido)
      "registros_ocultos": 1                  // pedidos que o portal conta e não devolve (status 9)
    }
  },
  "fases": [
    {"id": "F1", "nome": "Fase 1", "conta_na_meta": false,
     "ofertas": {"voomp": [11], "tmb": ["título exato da oferta"]}},   // casa pela oferta
    {"id": "F2", "nome": "Fase 2", "conta_na_meta": true,
     "inicio": "2026-10-07T20:00:00", "fim": "2026-10-16T23:59:59"}    // casa pela janela
  ],
  "meta": {
    "total": 82,
    "acumulada": {"2026-10-09": 58, "2026-10-10": 59},      // opcional: meta ao fim de cada dia
    "potencial_acumulado": {"2026-10-10": 59}               // opcional
  },
  "calendario": {"2026-10-11": "anúncio do sorteio, 19h"},  // opcional: foco de cada dia
  "entrega": {"clickup_canal_id": "8ckf9qa-00000", "clickup_canal_nome": "Canal"},
  "leituras": ["09:03", "13:03", "18:03", "22:03"],
  "ignorar": [{"plataforma": "voomp", "id": 123, "motivo": "teste da equipe"}]
}
```

- A régua `acumulada` inclui o dia anterior ao primeiro dia do plano, que é a base: a meta de um dia é
  a diferença para o dia anterior. Sem régua, o resumo mostra o ritmo necessário (o que falta dividido
  pelos dias até o fim da última fase que conta).
- Uma fase só com `ofertas` não pega nada pela data. Uma fase só com janela pega tudo o que foi pago
  dentro dela e não está listado em outra fase.

## O resumo do canal

Markdown, com os títulos das seções em negrito e uma lista em cada seção. A ordem é fixa: primeiro
**Estamos no plano?** (uma frase de sim ou não, o dia de hoje, o total e a projeção), depois o
**Plano dia a dia** (uma linha por dia do plano já começado, com ✅ ou ⚠️, e a meta de amanhã), e só então
onde vendeu, quem está aguardando, o que ficou fora da meta e os alertas. Projeto sem régua abre com
**Meta** e o ritmo necessário. O resumo traz só o que é da campanha: mensalidade de quem já é aluna não entra.

**Quando postar.** Só quando o número de efetivadas mudou desde a leitura anterior, para cima ou para
baixo (`deve_postar`, que compara com a última linha do `historico.csv`). Mudança só em quem está
aguardando não gera post. A primeira leitura de um projeto e a de fechamento vão sempre.

Para trocar uma mensagem já postada no canal: poste a nova e apague a antiga pela API do ClickUp, que
o MCP não tem essa operação. `DELETE https://api.clickup.com/api/v3/workspaces/<ws>/chat/messages/<id>`
com o token do Keychain `clickup-exos-api` devolve 204. Só com o pedido do usuário e sem respostas na mensagem.

## Arquivos do projeto

- `leituras/voomp-*.json`, `leituras/tmb-*.json` (portal) e `leituras/tmbapi-*.json` (API): ficam as 3
  últimas de cada. CPF e e-mail estão como hash; nome e telefone só de quem não pagou e tentou há pouco.
- `historico.csv`: uma linha por leitura. É de onde sai o "+N desde as HHhMM".
- `pendentes.csv`: quem está aguardando, com contato (`;` e UTF-8 com BOM, abre no Excel). Dado pessoal.
- `analisar --corte AAAA-MM-DDTHH:MM:SS` conta como se fosse aquele momento e não grava nada.

## Carteira e resumo semanal

A carteira (`Exos/Vendas Semanais/config.json`) lista todos os produtos das duas contas, um por linha:

```jsonc
{
  "tipo": "carteira",
  "fuso": "America/Sao_Paulo",
  "plataformas": {
    "voomp": {"coletar_desde": "2025-01-01",          // a conta começa em set/25: pega toda assinatura do início
              "assinatura": [10940, 12798],             // produtos SUBSCRIPTION
              "comercial": {"afiliados": [141527], "produtos": [16357]}},  // afiliado Valmir ou produto "Comercial"
    "tmb": {"comercial": {"produtos": [36730, 31364]}}  // os "C/Comercial" e "Comercial"
  },
  "produtos": [
    {"nome": "Pós em Odontologia Oncológica", "expert": "Leticia Lang",
     "voomp": {"12794": "avulso", "12798": "recorrência"}, "tmb": {"36730": "C/Comercial", "36731": "S/Comercial"}}
  ],
  "entrega": {"clickup_canal_id": "8ckf9qa-79653", "clickup_canal_nome": "Amigos do MKT"}
}
```

`plataformas.*.produtos` sai da lista `produtos` (`preparar_config`); id em duas linhas é erro.

**Regras do semanal** (`semanal`):
- Semana = segunda a domingo da última semana fechada antes do dia da leitura (`--hoje` muda o dia).
- Mês = do dia 1 ao domingo. Semana que vira o mês mostra os dois: o mês que fechou e o novo até o domingo.
- Venda = primeira compra paga da aluna naquele produto **no mês**, as duas plataformas juntas, pela data do
  pagamento. Cobrança em dobro no mês conta uma; renovação de assinatura não conta; quem já comprou em outro mês
  e compra de novo (troca para a oferta da Black, por exemplo) conta. Assim o mês bate com o fechamento da campanha.
- Comercial: TMB pelo produto; Voomp pelo afiliado ou pelo produto listado em `comercial.produtos`.
- Valor como a plataforma registra (assinatura: só a 1ª mensalidade). Reembolso da Voomp aparece na semana
  do reembolso; cancelamento da TMB não tem data na API e não aparece.
- Produto sem venda no mês vai numa linha só no fim. Total sempre aparece.
- Arquivos: `historico_semanal.csv` (uma linha por produto e semana; refazer a semana substitui) e
  `relatorios/semana-AAAA-MM-DD.md` com o texto postado. Coleta com mais de 6 h vira alerta.
- **Visão anual:** `anual --config "$CARTEIRA" [--ate AAAA-MM-DD] [--json saida.json]` dá o mês a mês do ano por
  produto, com o acumulado comercial × não comercial e o valor; mesma contagem do semanal. O JSON alimenta deck ou planilha.
- Aceite de 19/10/2026: a semana 12–18/10 deu 31 na Pós Onco (30 da Fase 2 + 1 da Fase 1) e o mês 103
  (as 102 da Black + 1 venda comum em 06/10).

## Voomp Creators

- Painel `adm.voompcreators.com.br` (plataforma Greenn). API interna: `apiadm.voompcreators.com.br/api`.
- Autenticação: cookie `access_token`, que já vem com `Bearer `. É um JWT de 30 minutos. O painel o
  renova com o `refresh_token` ao carregar qualquer página; um `fetch` direto não renova. Por isso a
  leitura navega para `/dashboard` antes de coletar, e o coletor espera alguns segundos pela renovação.
- O `refresh_token` é um cookie de **8 horas**, renovado a cada carregamento de página. Mais de 8 horas
  sem carregar nenhuma página e a sessão cai. Fechar a aba ou a janela não derruba (o cookie fica no
  perfil do navegador); "Finalizar sessão" derruba.
- A Voomp não tem API de consulta com token. Em Integrações só existem webhooks de envio, então a
  leitura depende dessa sessão.
- `GET /sale?type=created_at&date_start=…&date_end=…&per_page=100&page=N&products[]=ID`. Sem `status[]`
  vêm todos os status. O filtro de data é pela criação. Paginação em `data.last_page`.
- Status vistos: `paid`, `waiting_payment`, `refused`, `refunded`, `chargedback`.
- Assinatura (`type: SUBSCRIPTION`): cada cobrança mensal é uma linha com `contract_id`, mas o contrato pode ser
  compartilhado por várias alunas. A conta do Gabriel começa em set/25.
- Venda do comercial: `affiliate_id` preenchido. Um produto "Comercial" pode existir e não ser usado.
- `GET /product?list=true` lista os produtos da conta logada.

## Deck da revisão semanal

`deck_vendas.py` (molde em `scripts/deck/`) desenha o `dados_deck` do `vendas.py`:
capa · panorama por expert · um slide por expert (tabela de produtos com semana, mês e ano, e o valor por mês do
ano) · comercial VS2A (peso por expert e valor do comercial por mês) · considerações (`consideracoes/<segunda>.md`,
cartões `- **Título** · texto`) · o ano por expert (barras de valor em real; dólar anotado) · pontos de atenção
(fatos automáticos: semana × anterior, peso do comercial, produto do mês, parados, dólar).
- Experts com nome curto e cor em `experts` do config; as cores (azul, laranja, verde-água, violeta) passaram no
  validador da skill dataviz no fundo escuro.
- Comparação entre experts sempre por valor: ingresso barato (IDT) infla a contagem.
- `node_modules` é clonado (`cp -cR`) do último deck `vendas-*`; sem nenhum, `npm install`.
- PDF: `exports/Vendas Exos - semana DD a DD-MM-AAAA.pdf`.
- Versão web (`--web`): `slidev build --base ./` com `routerMode: hash` no cabeçalho; o `gerar_web` tira o esqueleto
  `<html>/<head>/<body>` (a publicação de artifact põe o dela), troca o `<title>` por "Revisão de Vendas Exos" e lista os
  107 arquivos em `artifact-files.json`. Página privada no claude.ai, sempre no mesmo link (`link_deck`): só o Cleber abre
  até ele compartilhar pelo menu Share. Testado localmente sob caminho aninhado antes da 1ª publicação (21/10/2026).
- `--clickup`: `entrega.call_socios.tarefa` é a task recorrente "Planejamento EXOS - Sócios" (`86ak95wxc`), que,
  ao ser finalizada, volta para a próxima segunda (mesmo id; o ClickUp guarda uma cópia finalizada). Se ela está
  vencida e aberta, o comando finaliza antes de anexar; não anexa duas vezes o mesmo arquivo. Anexo vai pela API
  REST (token `clickup-exos-api`), porque o MCP só anexa arquivo pequeno.

## Hotmart · API oficial

- Conta `exosmkt@gmail.com`: a Exos é coprodutora (ou produtora) dos produtos de Elen (DIAGNOSIS), Letícia
  (Lang & Carvalho) e Kleber (K M Odontologia). Credencial "Exos · acompanhamento de vendas" (produção),
  criada em 21/10/2026 com o sim do Cleber; a "Spedy" é do emissor de notas e não se mexe.
- Keychain `hotmart-exos-api`: JSON com `client_id`, `client_secret` e `basic`. O token
  (`POST https://api-sec-vlc.hotmart.com/security/oauth/token?grant_type=client_credentials&client_id=…&client_secret=…`,
  `Authorization: Basic …`) dura 48 h e o coletor pede um novo a cada leitura: ninguém precisa logar.
- `GET https://developers.hotmart.com/payments/api/v1/sales/history` (500 por página, `page_token`): sem
  `transaction_status` devolve só parte dos status; o coletor manda a lista toda menos `DISPUTE`, que dá 400.
  `start_date` antes de 2025 também dá 400 (`coletar_desde` 2025-01-01; os dados da conta começam em set/25).
- `GET …/sales/commissions`: por transação, quem recebe (`PRODUCER`, `COPRODUCER`, `AFFILIATE`, `ADDON`), a moeda
  de repasse e `exchange_rate_currency_payout`. O afiliado Valmir (VS2A) sai daqui; o `ucode` dele está no config.
- Valor: preço × câmbio = moeda de repasse do produto (real nos nacionais, dólar nos internacionais: Kleber,
  e-book ES). O relatório mostra real e dólar lado a lado, sem converter dólar.
- Sem CPF na venda: a mesma aluna nas outras plataformas só casa pelo e-mail. Sem data de reembolso: reembolso
  da Hotmart não aparece na semana (sai da conta, como na TMB). Não há assinatura nestes produtos.
- Linhas com produtos baratos agrupados (IDT, cursos curtos, ONCO, internacionais) usam `"contar": "por_produto"`.
- Produto pago que não está na carteira vira alerta "fora da carteira": acrescente o id à linha certa.

## TMB · API oficial

- Base `https://api.tmbeducacao.com.br/`, cabeçalho `Authorization: Bearer <token>`.
- `GET api/pedidos?produto_id=&data_inicio=&data_final=&pageNumber=&pageSize=`: só Efetivado, Cancelado
  e Cancelamento Solicitado. `pageSize` vai até 100. As datas filtram pela efetivação. Traz `criado_em`.
- `GET api/produtos`, `GET api/oferta?produto_id=` (título e valor de cada oferta),
  `GET api/pedidos/DetalhePedidoEfetivado?pedido_id=`.
- **A API não diz a oferta do pedido.** O motor infere pelo valor quando só uma oferta do produto tem
  aquele valor; se o portal já leu o pedido, vale a oferta de lá. Oferta de fase com o mesmo valor de
  outra oferta do produto só é identificada com a leitura do portal.
- **A API não traz boleto gerado.** Os pendentes da TMB vêm só do portal.
- Token: Portal › Configurações › TMB API. Fica no Keychain, serviço `tmb-exos-api`. Se a API responder
  401, o token foi revogado ou venceu: gerar outro lá (com o sim do usuário) e regravar sem exibir:
  `browser_evaluate` com `() => ({token: document.querySelector('#access-token').value})` e `filename`
  temporário; depois `security add-generic-password -U -a "$USER" -s tmb-exos-api -w "$(…)"` lendo o
  arquivo, e apagar o arquivo. Não tire retrato dessa página: o token fica visível nela.
- Documentação: `info.tmbeducacao.com.br/portal-do-produtor/central-de-ajuda/produto/integracoes/api-publica-beta`.

## TMB · portal do infoprodutor

- Portal `produtor.tmbeducacao.com.br`. API interna: `api-produtor-prd.tmb.com.br/api`.
- Autenticação: cookie `tmb.token`, JWT de **60 minutos, sem renovação**. O login pede senha e
  reCAPTCHA. A central em uso está no cookie `tmb.membro_produtor` (`id`).
- `GET /Produtor/Vendas?membro_id=&produto_id=&produto_id=&pageSize=200&pageNumber=N`. Sem `status`
  vêm todos (a tela é que assume 8). Aceita `criado_em_ini`, `criado_em_fim`, `efetivado_em_ini`,
  `efetivado_em_fim` em `AAAA-MM-DD`, com o fim incluído.
- Status: 8 Efetivado, 10 Boleto Gerado, 7 Aguardando Assinatura, 0 Cancelado, 23 Cancelamento
  Solicitado. Pedidos de status 9 entram no total e nunca são devolvidos (`registros_ocultos`).
- A lista não traz a data de criação. O coletor pergunta dia a dia, dentro da janela das fases, quais
  pedidos nasceram em cada dia. Boleto gerado sem dia na janela é pedido antigo e não conta como pendente.
- `GET /Produtor/Vendas/csv/all` devolve um CSV com "Criado Em" e UTMs, se um dia for preciso.
- `GET /Produto/ObterProdutosSimples` e `GET /Ofertas/ObterOfertas` (a resposta pode vir como JSON
  dentro de uma string).
- Com a sessão vencida o portal apaga os cookies e manda para `/login`. A raiz `/` é a tela de login.

## Webhook de vendas da TMB (não usado)

A TMB também avisa uma URL sua a cada Efetivado ou Cancelado (Produtos › Integrações › Webhook Vendas,
até 3 URLs). Serviria para avisar a venda na hora, mas pede um endereço público para receber e, como
a API, não cobre boleto gerado.

## Navegador da automação

- `browser_navigate` grava um retrato (`page-*.yml`) de cada página na pasta de saída do navegador.
  Não abra por navegação telas que listam compradoras nem a página do token.
- `browser_evaluate` com `filename` grava o resultado em caminho relativo à raiz do workspace e não
  devolve o conteúdo ao chat. É assim que as coletas e o token ficam fora da conversa.
- A conta logada define o que se vê: na Voomp, os produtos da conta; na TMB, a central selecionada.

## Acrescentar uma plataforma

Um coletor em `scripts/coletores/<nome>.js` que devolva `{plataforma, coletado_em, total_api, linhas}`,
um normalizador `_linha_<nome>` no motor, o nome em `PLATAFORMAS` e os casos em `test_vendas.py`. O
resto do motor (pessoas, fases, pendentes, régua, textos) não muda.
