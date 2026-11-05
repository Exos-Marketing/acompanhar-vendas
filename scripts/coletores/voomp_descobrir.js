async () => {
  // Descoberta na Voomp Creators (skill acompanhar-vendas): produtos, ofertas e afiliados de um
  // produto, para montar o config de um projeto novo. Só faz GET e não devolve dado de comprador.
  const CFG = __CFG__;
  const saida = { plataforma: 'voomp' };
  if (location.hostname !== 'adm.voompcreators.com.br') return { ...saida, erro: 'sem_sessao', url: location.href };
  const api = 'https://apiadm.voompcreators.com.br/api';
  // o painel renova o token alguns segundos depois de carregar a página: espera por ele
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
  const get = async (caminho) => {
    const resposta = await fetch(api + caminho, { headers: cabecalhos });
    if (resposta.status === 401 || resposta.status === 403) throw new Error('sem_sessao');
    if (!resposta.ok) throw new Error('http_' + resposta.status);
    return resposta.json();
  };
  try {
    const busca = new RegExp(CFG.busca, 'i');
    const todos = await get('/product?list=true&per_page=500');
    const produtos = (Array.isArray(todos) ? todos : (todos.data && todos.data.data) || todos.data || [])
      .filter(p => busca.test(p.name || ''));
    if (!produtos.length) return { ...saida, produtos: [], aviso: 'nenhum produto casa com a busca' };

    const desde = new Date(Date.now() - CFG.dias * 864e5).toISOString();
    const filtro = 'type=created_at&per_page=100&date_start=' + encodeURIComponent(desde)
      + '&date_end=' + encodeURIComponent(new Date(Date.now() + 864e5).toISOString())
      + produtos.map(p => '&products[]=' + p.id).join('');
    const ofertas = {};
    const afiliados = {};
    let paginas = 1;
    for (let pagina = 1; pagina <= paginas && pagina <= 100; pagina++) {
      const dados = (await get('/sale?' + filtro + '&page=' + pagina)).data;
      paginas = dados.last_page;
      for (const v of dados.data) {
        const o = ofertas[v.offer_id] = ofertas[v.offer_id] || {
          id: v.offer_id, produto_id: v.product_id, nome: v.offer ? v.offer.name : null,
          valor: v.offer ? v.offer.amount : null, vendas: {},
        };
        o.vendas[v.status] = (o.vendas[v.status] || 0) + 1;
        if (v.affiliate_id) {
          const a = afiliados[v.affiliate_id] = afiliados[v.affiliate_id] || {
            id: v.affiliate_id, nome: v.affiliate ? String(v.affiliate.name || '').split(' ')[0] : null, vendas: 0,
          };
          a.vendas++;
        }
      }
    }
    return {
      ...saida,
      periodo_dias: CFG.dias,
      produtos: produtos.map(p => ({ id: p.id, nome: p.name, tipo: p.type, valor: p.amount })),
      ofertas: Object.values(ofertas),
      afiliados: Object.values(afiliados),
    };
  } catch (erro) {
    return { ...saida, erro: String(erro.message || erro) };
  }
}
