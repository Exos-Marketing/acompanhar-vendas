#!/usr/bin/env python3
"""Deck Slidev da revisão de vendas por expert (semana, mês e ano) para a call de sócios.

Lê o dicionário de `vendas.dados_deck` e escreve um deck com a identidade Exos:
capa, panorama por expert, um slide por expert, comercial VS2A, considerações (se houver),
o ano por expert e pontos de atenção. Só números: nenhum dado de comprador entra no deck.
O molde visual fica em ./deck (estilos, rodapé, componente PlStage, logo).
"""
import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

AQUI = Path(__file__).resolve().parent
MOLDE = AQUI / "deck"
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
# validadas no validate_palette (modo escuro, fundo #030b1a), nesta ordem de vizinhança
CORES = ["#2b8de9", "#d95926", "#199e70", "#9085e9"]
SIMBOLO = {"BRL": "R$", "USD": "US$", "EUR": "€"}


# ───────────────────────────── números ─────────────────────────────

def _num(v, casas=0):
    texto = "{:,.{c}f}".format(float(v), c=casas)
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def curto(valor, moeda="BRL"):
    """R$ 1,26 mi · R$ 124,4 mil · R$ 656."""
    simbolo, v = SIMBOLO.get(moeda, moeda), float(valor or 0)
    if abs(v) >= 1e6:
        return "%s %s mi" % (simbolo, _num(v / 1e6, 2))
    if abs(v) >= 1e3:
        return "%s %s mil" % (simbolo, _num(v / 1e3, 1))
    return "%s %s" % (simbolo, _num(v))


def compacto(valor):
    """Para rótulo de barra estreita: 1,3 mi · 124 mil · 656."""
    v = float(valor or 0)
    if abs(v) >= 1e6:
        return "%s mi" % _num(v / 1e6, 1)
    if abs(v) >= 1e3:
        return "%s mil" % _num(v / 1e3)
    return _num(v)


def valor(s, campo="valor"):
    """Real e as outras moedas de repasse, sem converter: 'R$ 124,4 mil + US$ 406'."""
    partes = [curto(s[campo])] if s.get(campo) else []
    partes += [curto(v[campo], m) for m, v in (s.get("moedas") or {}).items() if v.get(campo)]
    return " + ".join(partes) or "R$ 0"


def _extra(s):
    """Linha pequena com as moedas de repasse que não são real (para não estourar a coluna)."""
    return "".join("<small>+ %s</small>" % _esc(curto(v["valor"], m)) for m, v in (s.get("moedas") or {}).items() if v.get("valor"))


def pct(a, b):
    return int(round(100.0 * a / b)) if b else 0


def _vendas(n):
    return "%d venda%s" % (n, "" if n == 1 else "s")


def _data(x):
    return x if isinstance(x, (dt.date, dt.datetime)) else dt.date.fromisoformat(str(x)[:10])


def _dia(d):
    d = _data(d)
    return "%s %s" % (DIAS[d.weekday()], d.strftime("%d/%m"))


def _rotulo_mes(par):
    a, b = _data(par[0]), _data(par[1])
    fim_do_mes = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    nome = MESES[a.month - 1].capitalize()
    return "%s (fechado)" % nome if b == fim_do_mes else "%s até %s" % (nome, b.strftime("%d/%m"))


def _esc(texto):
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ───────────────────────────── blocos ─────────────────────────────

def _periodo(d):
    rotulo = "Semana em andamento" if d.get("parcial") else "Semana"
    return "%s · %s a %s" % (rotulo, _dia(d["inicio"]), _dia(d["fim"]))


def _experts_ativos(d):
    """Experts com venda no ano; a cor vem do config ou da posição na carteira, para não mudar de uma semana a outra."""
    for i, e in enumerate(d["experts"]):
        e["cor"] = e.get("cor") or CORES[i % len(CORES)]
    return [e for e in d["experts"] if e["ano"]["total"] or e["mes"]["total"] or e["semana"]["total"]]


def _barra(com, nao, escala, dica):
    """Barra comercial (dourado) × não comercial (ardósia), largura relativa à escala."""
    if not escala or not (com or nao):
        return '<div class="vs-bar"></div>'
    partes = []
    if com:
        partes.append('<span class="com" style="width:%.2f%%" title="%s · comercial"></span>' % (100.0 * com / escala, _esc(dica)))
    if nao:
        partes.append('<span class="nao" style="width:%.2f%%" title="%s · não comercial"></span>' % (100.0 * nao / escala, _esc(dica)))
    return '<div class="vs-bar pl-grow">%s</div>' % "".join(partes)


def _mini(valores, cor, moeda="BRL"):
    """Faixa de uma série (sem legenda: o título nomeia). O maior mês fica com 70% da altura."""
    maior = max(valores) if valores else 0
    colunas = []
    for v in valores:
        altura = (70.0 * v / maior) if maior else 0
        colunas.append('<div class="c"><b>%s</b><i style="height:%.2f%%;background:%s"></i></div>'
                       % (compacto(v) if v else "–", altura, cor))
    return "".join(colunas)


def _grade(n):
    return 'style="grid-template-columns:repeat(%d,minmax(0,1fr))"' % n


def _eixo(meses):
    return "".join('<div class="vx-axis">%s</div>' % MESES[_data(a).month - 1][:3] for a, _ in meses)


# ───────────────────────────── slides ─────────────────────────────

def _cabecalho(d):
    titulo = "Vendas Exos · %s" % _periodo(d).lower()
    return "\n".join([
        "---", "theme: default", "title: %s" % titulo, "info: |",
        "  Revisão de vendas por expert para a call de sócios: semana, mês e ano, comercial × não comercial.",
        "  Fontes: TMB (API), Voomp (painel) e Hotmart (API). Gerado pelo deck_vendas.py da skill acompanhar-vendas.",
        "colorSchema: dark", "layout: cover", "routerMode: hash", "transition: slide-left | slide-right", "clickAnimation: up",
        "comark: true", "fonts:", "  sans: Hanken Grotesk", "  serif: Sora", "  mono: JetBrains Mono", "---", ""])


def _capa(d, ativos):
    t = d["total"]
    mes = _rotulo_mes(d["mes"])
    lido = _data(d["lido_em"]) if d.get("lido_em") else None
    linhas = [
        '<div class="cover-brand"><img src="/exos-mark.png" alt="" /><span>EXOS</span></div>',
        '<div class="cover-text">',
        '<div class="eyebrow">Call de sócios · %s</div>' % _esc(_periodo(d).lower()),
        '<h1>Vendas da semana: <em>%s</em></h1>' % _esc(valor(t["semana"])),
        '<p class="lead">%s, %s pelo comercial. %s: %s · %d até %s: %s.</p>' % (
            _vendas(t["semana"]["total"]).capitalize(), t["semana"]["comercial"], _esc(mes), _esc(valor(t["mes"])),
            _data(d["fim"]).year, _data(d["fim"]).strftime("%d/%m"), _esc(valor(t["ano"]))),
        '<div class="vs-cover-stats">',
        '<div class="gold"><b>%d</b><span>vendas na semana</span></div>' % t["semana"]["total"],
        '<div><b>%s</b><span>%s</span></div>' % (_esc(curto(t["mes"]["valor"])), _esc(mes.lower())),
        '<div><b>%s</b><span>em %d</span></div>' % (_esc(curto(t["ano"]["valor"])), _data(d["fim"]).year),
        '<div><b>%d%%</b><span>do valor do mês pelo comercial</span></div>' % pct(t["mes"]["valor_comercial"], t["mes"]["valor"]),
        '</div>',
        '<div class="cover-meta">%s%s</div>' % (" · ".join(_esc(e["curto"]) for e in ativos),
                                                 " · lido em %s" % lido.strftime("%d/%m") if lido else ""),
        '</div>',
        '<div class="cover-num pl-num-in">%d</div>' % t["semana"]["total"],
        "", "<!--", "Roteiro: panorama, uma expert por slide, comercial VS2A, o ano e os pontos de atenção.", "-->", ""]
    return "\n".join(linhas)


def _panorama(d, ativos):
    t = d["total"]
    mes = _rotulo_mes(d["mes"])
    lider = max(ativos, key=lambda e: e["mes"]["valor"]) if ativos else None
    if lider and t["mes"]["valor"]:
        titulo = "%s fez %d%% do valor de %s" % (lider["curto"], pct(lider["mes"]["valor"], t["mes"]["valor"]),
                                                 MESES[_data(d["mes"][0]).month - 1])
    else:
        titulo = "Panorama por expert"
    escala = max([e["mes"]["valor"] for e in ativos] + [0])
    linhas = ["---", "layout: default", "chapter: Panorama", "---", "",
              '<div class="eyebrow">Por expert · %s · %s</div>' % (_esc(_periodo(d).lower()), _esc(mes.lower())),
              "<h1>%s</h1>" % _esc(titulo), "<PlStage>", '<div class="vs-rows">']
    for i, e in enumerate(ativos):
        m, s = e["mes"], e["semana"]
        cap = "semana <b>%d</b> · %s &nbsp;|&nbsp; mês <b>%d</b>: comercial <b>%d</b> · não comercial <b>%d</b>" % (
            s["total"], _esc(valor(s)), m["total"], m["comercial"], m["nao_comercial"])
        linhas.append(
            '<div class="vs-row pl-pop" style="--d:%.2fs;grid-template-columns:11rem 1fr 10.5rem"><div class="nm"><i class="vx-dot" style="background:%s"></i>%s'
            '<small>%s</small></div><div>%s<div class="vs-cap">%s</div></div><div class="v">%s%s<small>ano %s</small></div></div>'
            % (0.05 + 0.1 * i, e["cor"], _esc(e["curto"]), _esc(e["nome"]),
               _barra(m["valor_comercial"], m["valor_nao_comercial"], escala, e["curto"]), cap,
               _esc(curto(m["valor"])) if m["valor"] else "–", _extra(m), _esc(valor(e["ano"]))))
    linhas += ["</div>", "</PlStage>",
               '<div class="vs-legend" style="margin-top:.9rem"><span><i class="vs-sw com"></i>comercial (VS2A)</span>'
               '<span><i class="vs-sw nao"></i>não comercial</span><span>barra = valor do mês em real</span></div>']
    if d.get("mes_novo"):
        linhas.append('<div class="vx-note">%s: %s, %s.</div>' % (
            _esc(_rotulo_mes(d["mes_novo"]["periodo"])), _vendas(d["mes_novo"]["total"]["total"]), _esc(valor(d["mes_novo"]["total"]))))
    linhas.append("")
    return "\n".join(linhas)


def _expert(d, e):
    m, s, a = e["mes"], e["semana"], e["ano"]
    ant = e.get("semana_anterior")
    produtos = [p for p in e["produtos"] if p["ano"]["total"] or p["mes"]["total"] or p["semana"]["total"]]
    parados = [p["nome"] for p in e["produtos"] if p not in produtos]
    mes_nome = MESES[_data(d["mes"][0]).month - 1]
    if m["total"]:
        titulo = "%s: %s no mês, %s" % (e["curto"], valor(m), _vendas(m["total"]))
    else:
        titulo = "%s: sem vendas em %s; %d no ano (%s)" % (e["curto"], mes_nome, a["total"], valor(a))
    if m["comercial"]:
        titulo += ", %d pelo comercial" % m["comercial"]
    delta = ""
    if ant is not None:
        delta = "semana anterior: %s · %s" % (_vendas(ant["total"]), valor(ant))
    zoom = "zoom: 0.86\n" if len(produtos) > 4 else ""
    linhas = ["---", "layout: default", "chapter: %s" % e["curto"], zoom + "---" if zoom else "---", "",
              '<div class="eyebrow">%s · %s</div>' % (_esc(e["nome"]), _esc(_periodo(d).lower())),
              "<h1>%s</h1>" % _esc(titulo), "<PlStage>", '<div class="vs-kpis">',
              '<div class="vs-kpi pl-pop" style="--d:.05s"><b>%d<small>na semana</small></b><span>%s%s</span></div>'
              % (s["total"], _esc(valor(s)), (" · " + _esc(delta)) if delta else ""),
              '<div class="vs-kpi main pl-pop" style="--d:.15s"><b>%d<small>%s</small></b><span>%s · comercial %d%% do valor</span></div>'
              % (m["total"], _esc(_rotulo_mes(d["mes"]).lower()), _esc(valor(m)), pct(m["valor_comercial"], m["valor"])),
              '<div class="vs-kpi pl-pop" style="--d:.25s"><b>%d<small>em %d</small></b><span>%s · comercial %d%% do valor</span></div>'
              % (a["total"], _data(d["fim"]).year, _esc(valor(a)), pct(a["valor_comercial"], a["valor"])),
              "</div>",
              '<table class="vx-table cn pl-pop" style="--d:.35s"><thead><tr><th>Produto</th><th>Semana</th><th>%s</th>'
              '<th>Valor no mês</th><th>%d</th></tr></thead><tbody>' % (_esc(MESES[_data(d["mes"][0]).month - 1][:3]), _data(d["fim"]).year)]

    def cel(x):
        if not x["total"]:
            return '<td class="zero">–</td>'
        return '<td>%d <span class="vx-sub">c %d · n %d</span></td>' % (x["total"], x["comercial"], x["nao_comercial"])

    for p in produtos:
        linhas.append('<tr><td>%s</td>%s%s<td>%s</td><td>%d <span class="vx-sub">%s</span></td></tr>' % (
            _esc(p["nome"]), cel(p["semana"]), cel(p["mes"]), _esc(valor(p["mes"])) if p["mes"]["total"] else "–",
            p["ano"]["total"], _esc(valor(p["ano"]))))
    linhas.append("</tbody></table>")
    moeda = "BRL" if any(x["valor"] for x in e["meses_ano"]) else next(
        (mo for x in e["meses_ano"] for mo, v in (x.get("moedas") or {}).items() if v.get("valor")), "BRL")
    serie = [(x["valor"] if moeda == "BRL" else (x.get("moedas") or {}).get(moeda, {}).get("valor", 0)) for x in e["meses_ano"]]
    n = len(d["meses_ano"])
    linhas += ['<div class="vx-strip pl-pop" style="--d:.45s"><h3>Valor por mês em %d (%s)</h3>' % (_data(d["fim"]).year, SIMBOLO.get(moeda, moeda)),
               '<div class="vx-grid vx-mini" %s>%s</div>' % (_grade(n), _mini(serie, e["cor"], moeda)),
               '<div class="vx-grid" %s>%s</div></div>' % (_grade(n), _eixo(d["meses_ano"])), "</PlStage>"]
    if parados:
        linhas.append('<div class="vx-note">Sem venda no ano: %s.</div>' % _esc(", ".join(parados)))
    linhas.append("")
    return "\n".join(linhas)


def _comercial(d, ativos):
    t = d["total"]
    titulo = "Comercial VS2A: %d%% do valor do mês e %d%% do ano" % (
        pct(t["mes"]["valor_comercial"], t["mes"]["valor"]), pct(t["ano"]["valor_comercial"], t["ano"]["valor"]))
    linhas = ["---", "layout: default", "chapter: Comercial VS2A", "---", "",
              '<div class="eyebrow">Comercial VS2A · peso por expert no ano</div>', "<h1>%s</h1>" % _esc(titulo),
              "<PlStage>", '<div class="vs-rows">']
    for i, e in enumerate(ativos):
        a, m = e["ano"], e["mes"]
        cap = "ano: <b>%d</b> de %d vendas · %s &nbsp;|&nbsp; mês: <b>%d</b> de %d" % (
            a["comercial"], a["total"], _esc(valor(a, "valor_comercial")) if a["comercial"] else "R$ 0",
            m["comercial"], m["total"])
        linhas.append(
            '<div class="vs-row pl-pop" style="--d:%.2fs"><div class="nm"><i class="vx-dot" style="background:%s"></i>%s</div>'
            '<div>%s<div class="vs-cap">%s</div></div><div class="v">%d%%<small>do valor do ano</small></div></div>'
            % (0.05 + 0.1 * i, e["cor"], _esc(e["curto"]),
               _barra(a["valor_comercial"], a["valor_nao_comercial"], a["valor"] or 0, e["curto"]), cap,
               pct(a["valor_comercial"], a["valor"])))
    serie = [x["valor_comercial"] for x in t["meses_ano"]]
    n = len(d["meses_ano"])
    linhas += ["</div>",
               '<div class="vx-strip pl-pop" style="--d:.5s"><h3>Valor vendido pelo comercial por mês (R$)</h3>',
               '<div class="vx-grid vx-mini" %s>%s</div>' % (_grade(n), _mini(serie, "var(--c-com)")),
               '<div class="vx-grid" %s>%s</div></div>' % (_grade(n), _eixo(d["meses_ano"])), "</PlStage>",
               '<div class="vx-note">Comercial = vendas com afiliação do Valmir (VS2A) na Voomp e na Hotmart e os produtos '
               '"C/Comercial" da TMB. Barras: valor em real do ano, comercial × não comercial.</div>', ""]
    return "\n".join(linhas)


def ler_consideracoes(caminho):
    """Cartões a partir de um .md: cada item '- **Título** · texto' (ou '- texto') vira um cartão."""
    if not caminho or not Path(caminho).exists():
        return None
    cartoes, titulo_pagina = [], None
    for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
        if linha.startswith("# "):
            titulo_pagina = linha[2:].strip()
        m = re.match(r"^[-*]\s+(.*)$", linha.strip())
        if not m:
            continue
        texto = m.group(1).strip()
        t = re.match(r"^\*\*(.+?)\*\*\s*[·:—-]?\s*(.*)$", texto)
        cartoes.append({"t": t.group(1), "d": t.group(2)} if t else {"t": texto, "d": ""})
    return {"titulo": titulo_pagina, "cartoes": cartoes} if cartoes else None


def _consideracoes(cons):
    linhas = ["---", "layout: default", "chapter: Para discutir", "---", "",
              '<div class="eyebrow gold">Para discutir com os sócios</div>',
              "<h1>%s</h1>" % _esc(cons.get("titulo") or "Considerações sobre o comercial VS2A"),
              '<div class="vs-points">']
    for c in cons["cartoes"][:6]:
        linhas.append('<div class="vs-pt" v-click><div class="t">%s</div><div class="d">%s</div></div>'
                      % (_esc(c["t"]), _esc(c["d"])))
    linhas += ["</div>", ""]
    return "\n".join(linhas)


def _ano(d, ativos):
    t = d["total"]
    reais = [e for e in ativos if e["ano"]["valor"]]
    meses = d["meses_ano"]
    totais = [x["valor"] for x in t["meses_ano"]]
    maior = max(totais) if totais else 0
    i_maior = totais.index(maior) if maior else 0
    titulo = "%d até %s: %s; o maior mês foi %s (%s)" % (
        _data(d["fim"]).year, _data(d["fim"]).strftime("%d/%m"), valor(t["ano"]),
        MESES[_data(meses[i_maior][0]).month - 1], curto(maior))
    linhas = ["---", "layout: default", "chapter: O ano", "---", "",
              '<div class="eyebrow">%d mês a mês · valor em real por expert</div>' % _data(d["fim"]).year,
              "<h1>%s</h1>" % _esc(titulo),
              '<div class="vs-legend">%s</div>' % "".join(
                  '<span><i class="vs-sw" style="background:%s"></i>%s</span>' % (e["cor"], _esc(e["curto"])) for e in reais),
              "<PlStage>", '<div class="vs-chart">', '<div class="vx-grid vx-cols" %s>' % _grade(len(meses))]
    for k in range(len(meses)):
        h = (80.0 * totais[k] / maior) if maior else 0
        segs = "".join('<i style="flex:%s;background:%s" title="%s · %s"></i>' % (
            max(e["meses_ano"][k]["valor"], 0), e["cor"], _esc(e["curto"]), _esc(curto(e["meses_ano"][k]["valor"])))
            for e in reversed(reais) if e["meses_ano"][k]["valor"])
        linhas.append('<div class="vs-col"><div class="vs-top"><b>%s</b></div><div class="vs-stack vs-up" style="height:%.2f%%;--d:%.2fs">%s</div></div>'
                      % (compacto(totais[k]) if totais[k] else "–", h, 0.05 * k, segs))
    linhas += ["</div>", '<div class="vx-grid" %s>%s</div>' % (_grade(len(meses)), _eixo(meses)), "</div>", "</PlStage>"]
    dolar = [(e["curto"], e["ano"]["moedas"][m]["valor"], m) for e in ativos for m in (e["ano"].get("moedas") or {})
             if e["ano"]["moedas"][m]["valor"]]
    if dolar:
        linhas.append('<div class="vx-note">Fora das barras, em moeda de repasse: %s.</div>' % _esc(
            " · ".join("%s %s" % (n, curto(v, m)) for n, v, m in dolar)))
    linhas.append("")
    return "\n".join(linhas)


def pontos(d, ativos):
    """Fatos automáticos, sem opinião."""
    t, cartoes = d["total"], []
    ant = t.get("semana_anterior")
    if ant is not None:
        dif = t["semana"]["valor"] - ant["valor"]
        cartoes.append({"k": valor(t["semana"]), "t": "Semana contra a anterior",
                        "d": "%s nesta semana; na anterior, %s e %s (%s%s)." % (
                            _vendas(t["semana"]["total"]), _vendas(ant["total"]), valor(ant),
                            "+" if dif >= 0 else "−", curto(abs(dif)))})
    if t["mes"]["valor"]:
        cartoes.append({"k": "%d%%" % pct(t["mes"]["valor_comercial"], t["mes"]["valor"]),
                        "t": "Peso do comercial no mês",
                        "d": "%s de %s; no ano, %d%% (%s)." % (
                            curto(t["mes"]["valor_comercial"]), curto(t["mes"]["valor"]),
                            pct(t["ano"]["valor_comercial"], t["ano"]["valor"]), curto(t["ano"]["valor_comercial"]))})
    prods = [(p, e) for e in ativos for p in e["produtos"] if p["mes"]["total"]]
    if prods:
        p, e = max(prods, key=lambda x: x[0]["mes"]["valor"])
        cartoes.append({"k": curto(p["mes"]["valor"]), "t": "Produto que mais vendeu no mês",
                        "d": "%s (%s): %s." % (p["nome"], e["curto"], _vendas(p["mes"]["total"]))})
    parados = [(p, e) for e in ativos for p in e["produtos"]
               if not p["mes"]["total"] and (p.get("mes_anterior") or {}).get("total")]
    if parados:
        cartoes.append({"k": str(len(parados)), "t": "Venderam no mês passado e ainda não neste",
                        "d": "; ".join("%s (%s, %d no mês passado)" % (p["nome"], e["curto"], p["mes_anterior"]["total"])
                                       for p, e in parados[:4]) + "."})
    dolar = (t["mes"].get("moedas") or {}).get("USD", {}).get("valor", 0)
    if dolar:
        quem = [e["curto"] for e in ativos if (e["mes"].get("moedas") or {}).get("USD", {}).get("valor")]
        cartoes.append({"k": curto(dolar, "USD"), "t": "Vendas em dólar no mês", "d": "Hotmart, repasse em dólar: %s." % ", ".join(quem)})
    return cartoes[:6]


def _pontos(d, ativos):
    linhas = ["---", "layout: default", "chapter: Pontos de atenção", "---", "",
              '<div class="eyebrow gold">O que os números mostram</div>', "<h1>Pontos de atenção</h1>",
              '<div class="vs-points">']
    for c in pontos(d, ativos):
        linhas.append('<div class="vs-pt" v-click><div class="k">%s</div><div class="t">%s</div><div class="d">%s</div></div>'
                      % (_esc(c["k"]), _esc(c["t"]), _esc(c["d"])))
    lido = _data(d["lido_em"]).strftime("%d/%m") if d.get("lido_em") else "—"
    linhas += ["</div>",
               '<div class="pl-src">Fontes: TMB (API), Voomp (painel) e Hotmart (API), lidas em %s. Uma venda por aluna e produto '
               'no mês, pela data do pagamento; renovação de assinatura não entra; dólar fica em dólar.</div>' % lido, ""]
    return "\n".join(linhas)


def montar_slides(d, consideracoes=None):
    ativos = _experts_ativos(d)
    partes = [_cabecalho(d) + _capa(d, ativos), _panorama(d, ativos)]
    partes += [_expert(d, e) for e in ativos if e["ano"]["total"] or e["mes"]["total"]]
    partes.append(_comercial(d, ativos))
    if consideracoes:
        partes.append(_consideracoes(consideracoes))
    partes += [_ano(d, ativos), _pontos(d, ativos)]
    return "\n".join(p.rstrip("\n") + "\n" for p in partes)


# ───────────────────────────── pasta do deck ─────────────────────────────

def _json(x):
    if isinstance(x, dict):
        return {k: _json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json(v) for v in x]
    return x.isoformat() if isinstance(x, (dt.date, dt.datetime)) else x


def _modulos_prontos(destino, modulos=None):
    if (destino / "node_modules").exists():
        return
    candidatos = [Path(modulos)] if modulos else []
    pasta = destino.parent
    candidatos += sorted((p / "node_modules" for p in pasta.glob("vendas-*") if p != destino), reverse=True)
    origem = next((c for c in candidatos if c.exists()), None)
    if origem:
        subprocess.run(["cp", "-cR", str(origem), str(destino / "node_modules")], check=True)
    else:
        subprocess.run(["npm", "install", "--silent"], cwd=str(destino), check=True)


def gerar(d, destino, modulos=None, exportar=True, consideracoes=None):
    """Escreve o deck em `destino` (molde + slides.md + dados.json) e, se pedido, o PDF. Devolve o PDF."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    nome = destino.name
    pdf_nome = "Vendas-%s" % nome.replace("vendas-", "")
    ini, fim = _data(d["inicio"]), _data(d["fim"])
    fmt_ini = "%d" if ini.month == fim.month else "%d-%m"
    titulo_pdf = "Vendas Exos - semana %s a %s%s" % (ini.strftime(fmt_ini), fim.strftime("%d-%m-%Y"),
                                                      " (em andamento)" if d.get("parcial") else "")
    for item in MOLDE.rglob("*"):
        if item.is_file():
            alvo = destino / item.relative_to(MOLDE)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            texto = None
            if item.suffix in (".vue", ".json"):
                texto = item.read_text(encoding="utf-8").replace("__NOME__", nome).replace("__PDF__", pdf_nome)
                texto = texto.replace("__RODAPE__", "Vendas Exos · %s" % _periodo(d).lower())
            if texto is not None:
                alvo.write_text(texto, encoding="utf-8")
            else:
                shutil.copyfile(item, alvo)
    cons = ler_consideracoes(consideracoes) if isinstance(consideracoes, (str, Path)) else consideracoes
    (destino / "slides.md").write_text(montar_slides(d, cons), encoding="utf-8")
    (destino / "dados.json").write_text(json.dumps(_json(d), ensure_ascii=False, indent=1), encoding="utf-8")
    if not exportar:
        return None
    _modulos_prontos(destino, modulos)
    (destino / "exports").mkdir(exist_ok=True)
    pdf = destino / "exports" / ("%s.pdf" % titulo_pdf)
    subprocess.run(["npx", "slidev", "export", "slides.md", "--output", str(pdf.relative_to(destino)), "--wait", "1500"],
                   cwd=str(destino), check=True, capture_output=True, timeout=900)
    return pdf


def gerar_web(destino):
    """Versão para o navegador: build estático com caminhos relativos e navegação por âncora, em `artifact/`,
    sem o esqueleto <html>/<head>/<body> (a publicação põe o dela). Devolve a lista de arquivos a publicar."""
    destino = Path(destino)
    subprocess.run(["npx", "slidev", "build", "slides.md", "--base", "./"], cwd=str(destino), check=True,
                   capture_output=True, timeout=900)
    dist, pub = destino / "dist", destino / "artifact"
    if pub.exists():
        shutil.rmtree(pub)
    shutil.copytree(dist, pub, ignore=shutil.ignore_patterns("404.html", "_redirects", "index.html"))
    html = (dist / "index.html").read_text(encoding="utf-8")
    html = re.sub(r"<!DOCTYPE[^>]*>", "", html, flags=re.I)
    html = re.sub(r"</?(html|head|body)\b[^>]*>", "", html, flags=re.I)
    html = re.sub(r'<meta (charset|name="viewport"|http-equiv)[^>]*>\s*', "", html)
    html = re.sub(r'<link rel="icon"[^>]*>\s*', "", html)
    html = re.sub(r"<title>.*?</title>", "", html, flags=re.S)
    topo = ("<title>Revisão de Vendas Exos</title>\n<style>:root{color-scheme:dark;--fundo:#030b1a}"
            "html,body{background:var(--fundo);margin:0;height:100%}#app{height:100%}</style>\n")
    (pub / "index.html").write_text(topo + html.strip() + "\n", encoding="utf-8")
    arquivos = sorted(str(f.relative_to(pub)) for f in pub.rglob("*") if f.is_file() and f.name != "index.html")
    (destino / "artifact-files.json").write_text(json.dumps([{"path": a} for a in arquivos]), encoding="utf-8")
    return pub / "index.html", arquivos

