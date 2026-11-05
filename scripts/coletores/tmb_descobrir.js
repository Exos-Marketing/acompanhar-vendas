async () => {
  // Descoberta na TMB (skill acompanhar-vendas): produtos e ofertas de um produto, para montar o
  // config de um projeto novo. Só faz GET e não devolve dado de comprador.
  const CFG = __CFG__;
  const saida = { plataforma: 'tmb' };
  const cookies = Object.fromEntries(document.cookie.split('; ').map(c => {
    const i = c.indexOf('=');
    return [c.slice(0, i), decodeURIComponent(c.slice(i + 1))];
  }));
  if (location.hostname !== 'produtor.tmbeducacao.com.br' || !cookies['tmb.token'] || !cookies['tmb.membro_produtor']) {
    return { ...saida, erro: 'sem_sessao', url: location.href };
  }
  const membro = JSON.parse(cookies['tmb.membro_produtor']);
  const token = cookies['tmb.token'];
  const cabecalhos = { Authorization: /^bearer /i.test(token) ? token : 'Bearer ' + token, Accept: 'application/json' };
  const api = 'https://api-produtor-prd.tmb.com.br/api';
  const get = async (caminho) => {
    const resposta = await fetch(api + caminho, { headers: cabecalhos });
    if (resposta.status === 401 || resposta.status === 403) throw new Error('sem_sessao');
    if (!resposta.ok) throw new Error('http_' + resposta.status);
    let corpo = JSON.parse(await resposta.text());
    if (typeof corpo === 'string') corpo = JSON.parse(corpo);
    return corpo;
  };
  try {
    const busca = new RegExp(CFG.busca, 'i');
    const produtos = (await get('/Produto/ObterProdutosSimples?membro_id=' + membro.id)).filter(p => busca.test(p.produto || ''));
    if (!produtos.length) return { ...saida, central_id: membro.id, produtos: [], aviso: 'nenhum produto casa com a busca' };
    const ids = new Set(produtos.map(p => p.id));
    const ofertas = (await get('/Ofertas/ObterOfertas?membro_id=' + membro.id)).filter(o => ids.has(o.produto_id));

    // vendas por oferta e status: efetivadas no período e, das não efetivadas, as criadas no período
    const desde = new Date(Date.now() - CFG.dias * 864e5).toISOString().slice(0, 10);
    const base = '/Produtor/Vendas?membro_id=' + membro.id + produtos.map(p => '&produto_id=' + p.id).join('') + '&pageSize=200';
    const vendas = {};
    for (const extra of ['&efetivado_em_ini=' + desde, '&criado_em_ini=' + desde]) {
      for (let pagina = 1; pagina <= 100; pagina++) {
        const dados = (await get(base + extra + '&pageNumber=' + pagina)).pagedResponse;
        for (const v of dados.data) {
          if (extra.startsWith('&criado') && v.status_pedido_id === 8) continue; // já contada como efetivada
          const chave = v.produto_id + '|' + v.oferta;
          vendas[chave] = vendas[chave] || {};
          vendas[chave][v.status_pedido] = (vendas[chave][v.status_pedido] || 0) + 1;
        }
        if (pagina >= dados.totalPages || !dados.data.length) break;
      }
    }
    return {
      ...saida,
      central_id: membro.id,
      periodo_dias: CFG.dias,
      produtos: produtos.map(p => ({ id: p.id, nome: p.produto })),
      // as ofertas com venda no período vêm com a contagem; as demais, só produto e título
      ofertas_com_venda: ofertas.filter(o => vendas[o.produto_id + '|' + o.titulo])
        .map(o => ({ id: o.id, titulo: o.titulo, produto_id: o.produto_id, vendas: vendas[o.produto_id + '|' + o.titulo] })),
      outras_ofertas: ofertas.filter(o => !vendas[o.produto_id + '|' + o.titulo]).map(o => o.produto_id + ' · ' + o.titulo),
    };
  } catch (erro) {
    return { ...saida, erro: String(erro.message || erro) };
  }
}
