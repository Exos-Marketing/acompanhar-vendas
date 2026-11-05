async () => {
  // Coletor da TMB, portal do infoprodutor (skill acompanhar-vendas). Só faz GET.
  // O token é lido do cookie dentro da página e não sai dela.
  const CFG = __CFG__;
  const saida = { plataforma: 'tmb', coletado_em: new Date().toISOString() };
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

  const hash = async (texto) => {
    if (!texto) return null;
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(texto).trim().toLowerCase()));
    return [...new Uint8Array(bytes)].slice(0, 6).map(b => b.toString(16).padStart(2, '0')).join('');
  };

  // sem `status` a lista devolve todos os status (a tela é que assume 8, Efetivado)
  const base = '/Produtor/Vendas?membro_id=' + membro.id + CFG.produtos.map(p => '&produto_id=' + p).join('') + '&pageSize=200';
  const buscar = async (extra) => {
    const itens = [];
    let total = null;
    for (let pagina = 1; pagina <= 200; pagina++) {
      const resposta = await fetch(api + base + extra + '&pageNumber=' + pagina, { headers: cabecalhos });
      if (resposta.status === 401 || resposta.status === 403) throw new Error('sem_sessao');
      if (!resposta.ok) throw new Error('http_' + resposta.status);
      let corpo = JSON.parse(await resposta.text());
      if (typeof corpo === 'string') corpo = JSON.parse(corpo);
      const pagina_ = corpo.pagedResponse;
      total = pagina_.totalRecords;
      itens.push(...pagina_.data);
      if (pagina >= pagina_.totalPages || !pagina_.data.length) break;
    }
    return { itens, total };
  };

  try {
    const tudo = await buscar('');
    // a lista não traz a data de criação: pergunta dia a dia quais pedidos nasceram em cada um
    const criado = {};
    for (const dia of CFG.dias) {
      for (const v of (await buscar('&criado_em_ini=' + dia + '&criado_em_fim=' + dia)).itens) criado[v.pedido_id] = dia;
    }
    const linhas = [];
    for (const v of tudo.itens) {
      // contato só de quem não efetivou e nasceu na janela: é o que a recuperação usa
      const contato = v.status_pedido_id !== 8 && !!criado[v.pedido_id];
      linhas.push({
        id: v.pedido_id,
        produto_id: v.produto_id,
        produto: v.produto,
        oferta: v.oferta,
        status_id: v.status_pedido_id,
        status: v.status_pedido,
        financeiro: v.status_financeiro,
        cancelamento: v.status_cancelamento,
        valor: v.valor_principal,
        efetivado: v.efetivado_em,
        cancelado: v.cancelado_em,
        criado_dia: criado[v.pedido_id] || null,
        h_doc: await hash(String(v.cliente_documento || '').replace(/\D/g, '')),
        h_email: await hash(v.cliente_email),
        nome: contato ? v.cliente_nome : null,
        telefone: contato ? v.cliente_telefone_principal : null,
        email: contato ? v.cliente_email : null,
      });
    }
    return { ...saida, central_id: membro.id, total_api: tudo.total, linhas };
  } catch (erro) {
    return { ...saida, erro: String(erro.message || erro) };
  }
}
