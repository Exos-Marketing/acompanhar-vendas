async () => {
  // Coletor da Voomp Creators (skill acompanhar-vendas). Só faz GET.
  // O token é lido do cookie dentro da página e não sai dela.
  const CFG = __CFG__;
  const saida = { plataforma: 'voomp', coletado_em: new Date().toISOString() };
  if (location.hostname !== 'adm.voompcreators.com.br') return { ...saida, erro: 'sem_sessao', url: location.href };
  const api = 'https://apiadm.voompcreators.com.br/api';

  // O token dura 30 minutos e o painel só o renova alguns segundos depois de carregar a página.
  // Espera a renovação antes de concluir que a sessão caiu.
  let cabecalhos = null;
  for (let tentativa = 0; tentativa < 6 && !cabecalhos; tentativa++) {
    const bruto = document.cookie.split('; ').find(c => c.startsWith('access_token='));
    if (bruto) {
      const token = decodeURIComponent(bruto.slice('access_token='.length));
      const tentar = { Authorization: /^bearer /i.test(token) ? token : 'Bearer ' + token, Accept: 'application/json' };
      if ((await fetch(api + '/login/get-user', { headers: tentar })).ok) cabecalhos = tentar;
    }
    if (!cabecalhos) await new Promise(resolver => setTimeout(resolver, 2500));
  }
  if (!cabecalhos) return { ...saida, erro: 'sem_sessao', url: location.href };

  const hash = async (texto) => {
    if (!texto) return null;
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(texto).trim().toLowerCase()));
    return [...new Uint8Array(bytes)].slice(0, 6).map(b => b.toString(16).padStart(2, '0')).join('');
  };

  // sem status[] a API devolve todos os status; type=created_at filtra pela data de criação
  const filtro = 'type=created_at&per_page=100'
    + '&date_start=' + encodeURIComponent(CFG.desde + 'T03:00:00.000Z')
    + '&date_end=' + encodeURIComponent(new Date(Date.now() + 864e5).toISOString())
    + CFG.produtos.map(p => '&products[]=' + p).join('');

  const linhas = [];
  let total = null;
  let paginas = 1;
  for (let pagina = 1; pagina <= paginas && pagina <= 300; pagina++) {
    const resposta = await fetch(api + '/sale?' + filtro + '&page=' + pagina, { headers: cabecalhos });
    if (resposta.status === 401 || resposta.status === 403) return { ...saida, erro: 'sem_sessao', http: resposta.status };
    if (!resposta.ok) return { ...saida, erro: 'http_' + resposta.status, pagina };
    const dados = (await resposta.json()).data;
    total = dados.total;
    paginas = dados.last_page;
    for (const v of dados.data) {
      const cliente = v.client || {};
      // contato só de quem não pagou e tentou há pouco: é o que a recuperação usa
      const contato = v.status !== 'paid' && (v.created_at || '') >= CFG.contato_desde;
      linhas.push({
        id: v.id,
        produto_id: v.product_id,
        tipo: v.type,
        oferta_id: v.offer_id,
        oferta: v.offer ? v.offer.name : null,
        status: v.status,
        metodo: v.method,
        parcelas: v.installments,
        valor: v.amount,
        total: v.total,
        criado: v.created_at,
        pago: v.paid_at,
        reembolsado: v.refunded_at,
        vencimento: v.boleto_expiration_date,
        afiliado_id: v.affiliate_id,
        afiliado: v.affiliate ? String(v.affiliate.name || '').split(' ')[0] : null,
        contrato_id: v.contract_id,
        h_doc: await hash(String(cliente.document || '').replace(/\D/g, '')),
        h_email: await hash(cliente.email),
        nome: contato ? cliente.name : null,
        telefone: contato ? cliente.cellphone : null,
        email: contato ? cliente.email : null,
      });
    }
  }
  return { ...saida, total_api: total, linhas };
}
