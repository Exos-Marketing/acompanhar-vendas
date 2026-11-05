#!/usr/bin/env python3
"""Motor da skill acompanhar-vendas: conta as matrículas de um projeto na TMB e na Voomp.

Subcomandos:
  listar     projetos configurados (config.json nas pastas dos experts)
  coletor    imprime a função JavaScript de coleta de uma plataforma, pronta para o browser_evaluate
  descobrir  imprime a função JavaScript que lista produtos, ofertas e afiliados (projeto novo)
  hotmart-api lê as vendas da Hotmart pela API oficial (carteira)
  analisar   lê as coletas, aplica as regras de contagem e imprime o relatório
  semanal    resumo da semana fechada e do mês de cada produto da carteira (comercial × não comercial)
  anual      mês a mês do ano de cada produto da carteira, com o acumulado
  deck       apresentação da revisão de vendas por expert (semana, mês, ano) + PDF

As regras de contagem e o schema do config estão em ../REFERENCE.md.
Só usa a biblioteca padrão. As coletas são dado de fora: rodar o analisar com `python3 -I`.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

AQUI = Path(__file__).resolve().parent
RAIZ_PADRAO = Path.home() / "Documents" / "Exos"
PASTA_RESULTADOS = "08-Resultados-Relatorios"
PREFIXO_PASTA = "Vendas "
LEITURAS_GUARDADAS = 3
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
SEM_CONTATO = "9999-12-31"  # coletor da carteira: não traz contato de ninguém
COLETA_VELHA = dt.timedelta(hours=6)
PLATAFORMAS = ("tmb", "voomp", "hotmart")
NOME_PLATAFORMA = {"tmb": "TMB", "voomp": "Voomp", "hotmart": "Hotmart"}

VOOMP_ESTADO = {"paid": "paga", "waiting_payment": "aberta", "refused": "recusada",
                "refunded": "reembolsada", "chargedback": "reembolsada"}
VOOMP_METODO = {"CREDIT_CARD": "cartão", "PIX": "Pix", "BOLETO": "boleto", "PAYPAL": "PayPal"}
ORDEM_METODO = ["cartão", "Pix", "boleto", "PayPal"]
TMB_EFETIVADO, TMB_BOLETO_GERADO, TMB_AGUARDANDO_ASSINATURA = 8, 10, 7
TMB_CANCELADOS = (0, 23)  # Cancelado, Cancelamento Solicitado
TMB_API = "https://api.tmbeducacao.com.br/"
TMB_API_STATUS = {"Efetivado": TMB_EFETIVADO, "Cancelado": 0, "Cancelamento Solicitado": 23}  # a API só traz estes
KEYCHAIN_TMB = "tmb-exos-api"
HOTMART_TOKEN = "https://api-sec-vlc.hotmart.com/security/oauth/token"
HOTMART_API = "https://developers.hotmart.com/payments/api/v1/"
KEYCHAIN_HOTMART = "hotmart-exos-api"  # JSON com client_id, client_secret e basic
HOTMART_ESTADO = {"APPROVED": "paga", "COMPLETE": "paga", "REFUNDED": "reembolsada", "PARTIALLY_REFUNDED": "reembolsada",
                  "CHARGEBACK": "reembolsada", "CANCELLED": "cancelada", "EXPIRED": "cancelada", "BLOCKED": "cancelada",
                  "PROTESTED": "cancelada", "NO_FUNDS": "recusada", "WAITING_PAYMENT": "aberta",
                  "PRINTED_BILLET": "aberta", "OVERDUE": "aberta", "UNDER_ANALISYS": "aberta", "STARTED": "aberta",
                  "PROCESSING_TRANSACTION": "aberta", "PRE_ORDER": "aberta", "DISPUTE": "aberta"}
SIMBOLO_MOEDA = {"BRL": "R$", "USD": "US$", "EUR": "€"}
# status aceitos no filtro da consulta (DISPUTE dá 400); sem filtro a API só devolve parte deles
HOTMART_STATUS_CONSULTA = sorted(set(HOTMART_ESTADO) - {"DISPUTE"})
PORTAL_VELHO = dt.timedelta(minutes=90)

TIPOS_PENDENTE = ["tmb_boleto", "tmb_contrato", "voomp_boleto", "voomp_boleto_vencido", "voomp_pix",
                  "voomp_aguardando", "voomp_recusado"]
JANELA_MENSALIDADE = dt.timedelta(days=30)
MAX_DIAS_TMB = 62

_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


# ───────────────────────────── datas ─────────────────────────────

def _data(texto, fuso, sem_fuso_e_utc=False):
    """ISO de qualquer uma das plataformas -> datetime no fuso do projeto."""
    if not texto:
        return None
    m = _ISO.match(str(texto).strip())
    if not m:
        raise ValueError("Data em formato inesperado: %r" % (texto,))
    dia, hora, fracao, desloc = m.groups()
    if len(hora) == 5:
        hora += ":00"
    micro = int(((fracao or ".0")[1:] + "000000")[:6])  # o fromisoformat do 3.9 exige 6 casas
    d = dt.datetime.strptime(dia + " " + hora, "%Y-%m-%d %H:%M:%S").replace(microsecond=micro)
    if desloc in (None, ""):
        return d.replace(tzinfo=dt.timezone.utc).astimezone(fuso) if sem_fuso_e_utc else d.replace(tzinfo=fuso)
    if desloc == "Z":
        return d.replace(tzinfo=dt.timezone.utc).astimezone(fuso)
    sinal = 1 if desloc[0] == "+" else -1
    horas, minutos = int(desloc[1:3]), int(desloc[-2:])
    return d.replace(tzinfo=dt.timezone(sinal * dt.timedelta(hours=horas, minutes=minutos))).astimezone(fuso)


def _dia(texto):
    return dt.date.fromisoformat(str(texto)[:10]) if texto else None


def _quando(d):
    return "%s %s, %s" % (DIAS_SEMANA[d.weekday()], d.strftime("%d/%m"), d.strftime("%Hh%M"))


def _dia_curto(d):
    return "%s %s" % (DIAS_SEMANA[d.weekday()], d.strftime("%d/%m"))


# ───────────────────────────── linhas ─────────────────────────────

def _produto_comercial(produto_id, quando, comercial, fuso):
    """Produto do comercial; com `produtos_desde`, só vale a partir desse momento (antes, o link público caía nele)."""
    if produto_id not in (comercial.get("produtos") or []):
        return False
    desde = comercial.get("produtos_desde")
    return not desde or quando is None or quando >= _data(desde, fuso)


def _linha_voomp(l, cfg, fuso):
    pv = cfg["plataformas"]["voomp"]
    comercial = pv.get("comercial") or {}
    estado = VOOMP_ESTADO.get(l.get("status"), "outro")
    metodo = VOOMP_METODO.get(l.get("metodo"), l.get("metodo") or "?")
    aberta = {"boleto": "boleto", "Pix": "pix"}.get(metodo, "outra") if estado == "aberta" else None
    afiliado = l.get("afiliado_id")
    return {
        "p": "voomp", "id": l.get("id"), "produto_id": l.get("produto_id"),
        "oferta": l.get("oferta_id"), "oferta_nome": l.get("oferta"),
        "estado": estado, "status": l.get("status"), "aberta": aberta, "metodo": metodo,
        "valor": l.get("valor") or 0,
        "criado": _data(l.get("criado"), fuso, sem_fuso_e_utc=True), "criado_dia": None,
        "pago": _data(l.get("pago"), fuso, sem_fuso_e_utc=True),
        "vencimento": _dia(l.get("vencimento")),
        "comercial": (bool(afiliado) and (bool(comercial.get("qualquer_afiliado"))
                                          or afiliado in (comercial.get("afiliados") or [])))
                     or _produto_comercial(l.get("produto_id"),
                                           _data(l.get("criado") or l.get("pago"), fuso, sem_fuso_e_utc=True),
                                           comercial, fuso),
        "assinatura": l.get("produto_id") in (pv.get("assinatura") or []),
        "reembolsado": _data(l.get("reembolsado"), fuso, sem_fuso_e_utc=True),
        "contrato": l.get("contrato_id"),
        "h_doc": l.get("h_doc"), "h_email": l.get("h_email"),
        "nome": l.get("nome"), "telefone": l.get("telefone"), "email": l.get("email"),
    }


def _linha_tmb(l, cfg, fuso):
    pt = cfg["plataformas"]["tmb"]
    status = l.get("status_id")
    estado, aberta = "outro", None
    if status == TMB_EFETIVADO:
        estado = "paga"
    elif status == TMB_BOLETO_GERADO:
        estado, aberta = "aberta", "boleto"
    elif status == TMB_AGUARDANDO_ASSINATURA:
        estado, aberta = "aberta", "contrato"
    elif status in TMB_CANCELADOS:
        estado = "cancelada"
    return {
        "p": "tmb", "id": l.get("id"), "produto_id": l.get("produto_id"),
        "oferta": l.get("oferta"), "oferta_nome": l.get("oferta"),
        "estado": estado, "status": l.get("status"), "aberta": aberta, "metodo": "boleto parcelado",
        "valor": l.get("valor") or 0,
        "criado": None, "criado_dia": _dia(l.get("criado_dia")),
        "pago": _data(l.get("efetivado"), fuso),
        "vencimento": None,
        "comercial": _produto_comercial(l.get("produto_id"), _data(l.get("criado") or l.get("efetivado"), fuso),
                                        pt.get("comercial") or {}, fuso),
        "assinatura": False, "contrato": None,
        "h_doc": l.get("h_doc"), "h_email": l.get("h_email"),
        "nome": l.get("nome"), "telefone": l.get("telefone"), "email": l.get("email"),
    }


def _linha_hotmart(l, cfg, fuso):
    ph = cfg["plataformas"]["hotmart"]
    afiliados = set((ph.get("comercial") or {}).get("afiliados") or [])
    estado = HOTMART_ESTADO.get(l.get("status"), "outro")
    return {
        "p": "hotmart", "id": l.get("id"), "produto_id": l.get("produto_id"), "produto_nome": l.get("produto"),
        "oferta": l.get("oferta"), "oferta_nome": l.get("oferta"),
        "estado": estado, "status": l.get("status"), "aberta": "outra" if estado == "aberta" else None,
        "metodo": l.get("metodo") or "?", "valor": l.get("valor"), "moeda": l.get("moeda") or "BRL",
        "criado": _data(l.get("criado"), fuso), "criado_dia": None, "pago": _data(l.get("pago"), fuso),
        "vencimento": None, "comercial": bool(afiliados & set(l.get("afiliados") or [])),
        "assinatura": False, "contrato": None, "reembolsado": None,
        "h_doc": l.get("h_doc"), "h_email": l.get("h_email"), "nome": None, "telefone": None, "email": None,
    }


def hash_id(texto):
    """Mesmo hash dos coletores do navegador: SHA-256 do texto aparado e em minúsculas, 12 hex."""
    texto = str(texto).strip().lower() if texto is not None else ""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12] if texto else None


def hash_doc(texto):
    return hash_id(re.sub(r"\D", "", str(texto or "")))


def normalizar_tmb_api(pedidos, ofertas_por_produto):
    """Pedidos da API oficial da TMB no formato do coletor do portal, já sem dado pessoal.

    A API não diz por qual oferta o pedido entrou. A oferta é inferida pelo valor quando só uma
    oferta do produto tem aquele valor; se o portal já leu o pedido, vale a oferta de lá.
    """
    linhas = []
    for p in pedidos:
        produto = p.get("produto_id")
        ofertas = (ofertas_por_produto or {}).get(produto) or (ofertas_por_produto or {}).get(str(produto)) or []
        casam = [o["titulo"] for o in ofertas
                 if abs(float(o.get("valor_principal") or 0) - float(p.get("valor_total") or 0)) < 0.005]
        linhas.append({
            "id": p.get("pedido_id"), "produto_id": produto, "produto": p.get("lancamento"),
            "oferta": casam[0] if len(casam) == 1 else None,
            "status_id": TMB_API_STATUS.get(p.get("status_pedido")), "status": p.get("status_pedido"),
            "valor": p.get("valor_total"), "efetivado": p.get("data_efetivado"),
            "criado_dia": str(p.get("criado_em") or "")[:10] or None, "criado": p.get("criado_em"),
            "cancelamento": None,
            "h_doc": hash_doc(p.get("documento")), "h_email": hash_id(p.get("email")),
            "nome": None, "telefone": None, "email": None, "fonte": "api",
        })
    return linhas


def juntar_tmb(linhas_api, linhas_portal):
    """Uma lista só da TMB: o portal (todos os status, com a oferta) atualizado pela API."""
    por_id = {str(l["id"]): dict(l) for l in linhas_portal or []}
    for a in linhas_api or []:
        portal = por_id.get(str(a["id"]))
        if portal is None:
            por_id[str(a["id"])] = dict(a)
            continue
        portal.update(status_id=a["status_id"], status=a["status"],
                      efetivado=a.get("efetivado") or portal.get("efetivado"),
                      criado_dia=portal.get("criado_dia") or a.get("criado_dia"),
                      criado=portal.get("criado") or a.get("criado"),
                      oferta=portal.get("oferta") or a.get("oferta"))
        if a["status_id"] == TMB_EFETIVADO:
            portal.update(nome=None, telefone=None, email=None)
    return list(por_id.values())


def coletar_tmb_api(cfg, token):
    """Lê na API oficial da TMB os pedidos efetivados e cancelados dos produtos do projeto."""
    def get(caminho, **parametros):
        url = TMB_API + caminho + "?" + urllib.parse.urlencode(parametros)
        pedido = urllib.request.Request(url, headers={"Authorization": "Bearer " + token.strip(),
                                                      "Accept": "application/json",
                                                      "User-Agent": "exos-acompanhar-vendas"})
        with urllib.request.urlopen(pedido, timeout=60) as resposta:
            return json.loads(resposta.read().decode("utf-8"))

    saida = {"plataforma": "tmb", "fonte": "api",
             "coletado_em": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    pedidos, ofertas, total = [], {}, 0
    try:
        for produto in sorted(int(p) for p in cfg["plataformas"]["tmb"]["produtos"]):
            pagina = 1
            while True:
                corpo = get("api/pedidos", produto_id=produto, pageNumber=pagina, pageSize=100)
                pedidos += corpo["data"]
                if pagina >= (corpo.get("totalPages") or 1) or not corpo["data"]:
                    break
                pagina += 1
            total += corpo.get("totalRecords") or 0
            ofertas[str(produto)] = [{"titulo": o.get("titulo"), "valor_principal": o.get("valor_principal")}
                                     for o in get("api/oferta", produto_id=produto)]
    except urllib.error.HTTPError as erro:
        return dict(saida, erro="token_invalido" if erro.code in (401, 403) else "http_%d" % erro.code)
    except urllib.error.URLError as erro:
        return dict(saida, erro="rede: %s" % erro.reason)
    return dict(saida, total_api=total, ofertas=ofertas, linhas=normalizar_tmb_api(pedidos, ofertas))


def _iso_ms(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z") if ms else None


def normalizar_hotmart(vendas, comissoes):
    """Vendas da API da Hotmart no formato das coletas, sem dado pessoal (e-mail só como hash).

    O valor vai para a moeda de repasse do produto (real ou dólar) pelo câmbio que a própria Hotmart
    informa nas comissões; o afiliado sai das comissões (source AFFILIATE).
    """
    por_transacao = {c.get("transaction"): c for c in comissoes or []}
    linhas = []
    for v in vendas or []:
        compra, produto = v.get("purchase") or {}, v.get("product") or {}
        preco = compra.get("price") or {}
        c = por_transacao.get(compra.get("transaction")) or {}
        repasse = {(cm.get("commission") or {}).get("currency_code") for cm in c.get("commissions") or []} - {None}
        moeda_compra = preco.get("currency_code")
        if len(repasse) == 1 and c.get("exchange_rate_currency_payout") is not None:
            moeda, cambio = repasse.pop(), float(c["exchange_rate_currency_payout"])
        elif moeda_compra == "BRL":
            moeda, cambio = "BRL", 1.0
        else:
            moeda, cambio = moeda_compra, None  # sem câmbio: não soma valor
        valor = round(float(preco.get("value") or 0) * cambio, 2) if cambio is not None else None
        linhas.append({
            "id": compra.get("transaction"), "produto_id": produto.get("id"), "produto": produto.get("name"),
            "oferta": (compra.get("offer") or {}).get("code"), "status": compra.get("status"),
            "metodo": (compra.get("payment") or {}).get("type"),
            "parcelas": (compra.get("payment") or {}).get("installments_number"),
            "moeda_compra": moeda_compra, "valor_compra": preco.get("value"), "moeda": moeda, "valor": valor,
            "criado": _iso_ms(compra.get("order_date")), "pago": _iso_ms(compra.get("approved_date")),
            "afiliados": sorted({(cm.get("user") or {}).get("ucode") for cm in c.get("commissions") or []
                                 if cm.get("source") == "AFFILIATE"} - {None}),
            "h_doc": None, "h_email": hash_id((v.get("buyer") or {}).get("email")),
            "nome": None, "telefone": None, "email": None,
        })
    return linhas


def coletar_hotmart_api(cfg, cred):
    """Lê na API oficial da Hotmart todas as vendas e as comissões desde `coletar_desde` (a API só vai até 2025)."""
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    saida = {"plataforma": "hotmart", "fonte": "api",
             "coletado_em": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    desde = cfg["plataformas"]["hotmart"].get("coletar_desde") or "2025-01-01"
    inicio = int(dt.datetime.combine(dt.date.fromisoformat(desde), dt.time(), fuso).timestamp() * 1000)
    fim = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    cabecalho = {"Accept": "application/json", "User-Agent": "exos-acompanhar-vendas"}

    def abrir(pedido):
        with urllib.request.urlopen(pedido, timeout=60) as resposta:
            return json.loads(resposta.read().decode("utf-8"))

    try:
        q = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cred["client_id"],
                                    "client_secret": cred["client_secret"]})
        token = abrir(urllib.request.Request(HOTMART_TOKEN + "?" + q, method="POST", data=b"", headers=dict(
            cabecalho, Authorization="Basic " + cred["basic"], **{"Content-Type": "application/json"})))["access_token"]

        def todas(caminho, **parametros):
            itens, pagina, total = [], None, None
            while True:
                p = dict(parametros, max_results=500, start_date=inicio, end_date=fim)
                if pagina:
                    p["page_token"] = pagina
                corpo = abrir(urllib.request.Request(HOTMART_API + caminho + "?" + urllib.parse.urlencode(p, doseq=True),
                                                     headers=dict(cabecalho, Authorization="Bearer " + token)))
                itens += corpo.get("items") or []
                total = (corpo.get("page_info") or {}).get("total_results", total)
                pagina = (corpo.get("page_info") or {}).get("next_page_token")
                if not pagina:
                    return itens, total

        vendas, total = todas("sales/history", transaction_status=HOTMART_STATUS_CONSULTA)
        comissoes, _ = todas("sales/commissions")
    except urllib.error.HTTPError as erro:
        if erro.code in (401, 403):
            return dict(saida, erro="credencial_invalida")
        if erro.code == 400:
            return dict(saida, erro="http_400 (coletar_desde %s é antigo demais para a API?)" % desde)
        return dict(saida, erro="http_%d" % erro.code)
    except urllib.error.URLError as erro:
        return dict(saida, erro="rede: %s" % erro.reason)
    return dict(saida, total_api=total if total is not None else len(vendas), linhas=normalizar_hotmart(vendas, comissoes))


def _agrupar_pessoas(linhas):
    """Mesma pessoa = mesmo CPF ou mesmo e-mail (os dois chegam como hash), nas duas plataformas."""
    pai = {}

    def achar(x):
        pai.setdefault(x, x)
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    for i, l in enumerate(linhas):
        raiz = achar(("linha", i))
        for tipo in ("h_doc", "h_email"):
            if l[tipo]:
                pai[achar((tipo, l[tipo]))] = raiz
                raiz = achar(raiz)
    for i, l in enumerate(linhas):
        l["pessoa"] = achar(("linha", i))


def _chave_assinatura(l):
    """Assinatura é da aluna no produto. O contrato não serve de chave: na Voomp há contrato com dezenas de
    alunas (assinaturas migradas) e aluna que ganha contrato novo ao renegociar."""
    if l.get("pessoa") is not None:
        return (l["p"], l["produto_id"], l["pessoa"])
    return (l["p"], "contrato", l["contrato"]) if l["contrato"] else None


def _marcar_assinaturas(linhas):
    """Numa assinatura só a primeira cobrança paga da aluna no produto é matrícula; o resto é mensalidade."""
    pagas = defaultdict(list)
    for l in linhas:
        if l["assinatura"] and l["estado"] == "paga" and l["pago"] and _chave_assinatura(l):
            pagas[_chave_assinatura(l)].append(l)
    for cobrancas in pagas.values():
        cobrancas.sort(key=lambda l: (l["pago"], str(l["id"])))
        for l in cobrancas[1:]:
            l["renovacao"] = True
    for l in linhas:
        if l["assinatura"] and l["estado"] in ("aberta", "recusada") and l["criado"] and _chave_assinatura(l):
            primeira = pagas.get(_chave_assinatura(l))
            if primeira and primeira[0]["pago"] < l["criado"]:
                l["mensalidade"] = True


# ───────────────────────────── fases ─────────────────────────────

def _texto_igual(a):
    return " ".join(str(a).split()).casefold()


def _preparar_fases(cfg, fuso):
    fases = []
    for f in cfg["fases"]:
        g = dict(f)
        g["_inicio"] = _data(f["inicio"], fuso) if f.get("inicio") else None
        g["_fim"] = _data(f["fim"], fuso) if f.get("fim") else None
        g["_tem_janela"] = bool(f.get("inicio") or f.get("fim"))
        g["_ofertas"] = {p: {_texto_igual(o) for o in ofertas}
                         for p, ofertas in (f.get("ofertas") or {}).items()}
        fases.append(g)
    return fases


def _fase_de(l, fases, quando=None, dia=None):
    """Fase da linha: primeiro pela oferta listada; senão, pela janela que contém a data."""
    oferta = _texto_igual(l["oferta"]) if l["oferta"] is not None else None
    for f in fases:
        if oferta is not None and oferta in f["_ofertas"].get(l["p"], ()):
            return f
    for f in fases:
        if not f["_tem_janela"]:
            continue
        if quando is not None:
            if (f["_inicio"] is None or quando >= f["_inicio"]) and (f["_fim"] is None or quando <= f["_fim"]):
                return f
        elif dia is not None:
            if (f["_inicio"] is None or dia >= f["_inicio"].date()) and (f["_fim"] is None or dia <= f["_fim"].date()):
                return f
    return None


# ───────────────────────────── análise ─────────────────────────────

def analisar(cfg, voomp, tmb, agora, corte=None):
    """Aplica as regras de contagem. `voomp` e `tmb` são as listas `linhas` das coletas."""
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    agora = agora.astimezone(fuso)
    hoje = agora.date()
    fases = _preparar_fases(cfg, fuso)
    plataformas = [p for p in PLATAFORMAS if p in cfg["plataformas"]]
    ignorar = {(i["plataforma"], str(i["id"])) for i in cfg.get("ignorar") or []}
    alertas = []

    linhas = []
    if "voomp" in plataformas:
        linhas += [_linha_voomp(l, cfg, fuso) for l in voomp or []]
    if "tmb" in plataformas:
        linhas += [_linha_tmb(l, cfg, fuso) for l in tmb or []]
    linhas = [l for l in linhas if (l["p"], str(l["id"])) not in ignorar]
    if corte is not None:
        linhas = [l for l in linhas if not (l["pago"] and l["pago"] > corte)
                  and not (l["criado"] and l["criado"] > corte)
                  and not (l["criado_dia"] and l["criado_dia"] > corte.astimezone(fuso).date())]

    _agrupar_pessoas(linhas)
    _marcar_assinaturas(linhas)

    desconhecidos = Counter((l["p"], str(l["status"])) for l in linhas if l["estado"] == "outro")
    for (p, status), n in sorted(desconhecidos.items()):
        alertas.append("%s: %d venda(s) com status %s, que o motor não conhece e não contou"
                       % (NOME_PLATAFORMA[p], n, status))

    por_pessoa = defaultdict(list)
    for l in linhas:
        por_pessoa[l["pessoa"]].append(l)

    resumo_fases = {f["id"]: {"nome": f["nome"], "conta_na_meta": bool(f.get("conta_na_meta")),
                              "matriculas": 0, "pendentes": 0} for f in fases}

    # matrículas: uma por pessoa, na fase e na plataforma em que ela pagou primeiro
    matriculas = []
    for ls in por_pessoa.values():
        pagas = [(l, _fase_de(l, fases, quando=l["pago"])) for l in ls
                 if l["estado"] == "paga" and l["pago"] and not l.get("renovacao")]
        pagas = sorted([(l, f) for l, f in pagas if f], key=lambda x: (x[0]["pago"], str(x[0]["id"])))
        if not pagas:
            continue
        l, f = pagas[0]
        matriculas.append({"fase": f["id"], "conta_na_meta": bool(f.get("conta_na_meta")), "plataforma": l["p"],
                           "id": l["id"], "pago": l["pago"], "metodo": l["metodo"], "valor": l["valor"],
                           "produto_id": l["produto_id"], "oferta": l["oferta_nome"], "comercial": l["comercial"]})
        resumo_fases[f["id"]]["matriculas"] += 1
        if len(pagas) > 1:
            onde = sorted({NOME_PLATAFORMA[x[0]["p"]] for x in pagas})
            vendas = ", ".join("%s %s (%s)" % (NOME_PLATAFORMA[x[0]["p"]], x[0]["id"], _quando(x[0]["pago"]))
                               for x in pagas)
            if len(onde) > 1:
                alertas.append("Mesma aluna paga nas duas plataformas, contada uma vez: " + vendas)
            else:
                alertas.append("Cobrança em dobro na %s, contada uma vez: %s" % (onde[0], vendas))

    da_meta = [m for m in matriculas if m["conta_na_meta"]]
    total = len(da_meta)
    por_plataforma = {p: sum(1 for m in da_meta if m["plataforma"] == p) for p in plataformas}
    detalhe = {}
    if "voomp" in plataformas:
        c = Counter(m["metodo"] for m in da_meta if m["plataforma"] == "voomp")
        detalhe["voomp"] = {k: c[k] for k in ORDEM_METODO + sorted(set(c) - set(ORDEM_METODO)) if c[k]}
    if "tmb" in plataformas:
        rotulos = cfg["plataformas"]["tmb"].get("produtos") or {}
        c = Counter(rotulos.get(str(m["produto_id"]), str(m["produto_id"])) for m in da_meta
                    if m["plataforma"] == "tmb")
        detalhe["tmb"] = dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))
    por_dia = Counter(m["pago"].date().isoformat() for m in da_meta)
    por_dia = {d: por_dia[d] for d in sorted(por_dia)}

    # o que saiu da conta dentro de uma fase que vale para a meta
    saidas = {"reembolsos": 0, "cancelamentos": 0}
    for l in linhas:
        if l["estado"] not in ("reembolsada", "cancelada") or not (l["pago"] or l["criado"]):
            continue
        f = _fase_de(l, fases, quando=l["pago"] or l["criado"])
        if f and f.get("conta_na_meta"):
            saidas["reembolsos" if l["estado"] == "reembolsada" else "cancelamentos"] += 1

    # aguardando pagamento: quem tentou dentro de uma fase e não tem nenhuma compra paga
    pendentes = []
    for ls in por_pessoa.values():
        if any(l["estado"] == "paga" for l in ls):
            continue
        tentativas = []
        for l in ls:
            if l["estado"] in ("aberta", "recusada") and not l.get("mensalidade"):
                f = _fase_de(l, fases, quando=l["criado"], dia=l["criado_dia"])
                if f:
                    tentativas.append((l, f))
        if not tentativas:
            continue
        tipo, ref = _tipo_pendente([l for l, _ in tentativas], hoje)
        fase = next(f for l, f in tentativas if l is ref)

        def primeiro(campo):
            return next((l[campo] for l, _ in tentativas if l[campo]), None)

        pendentes.append({"tipo": tipo, "plataforma": ref["p"], "fase": fase["id"],
                          "conta_na_meta": bool(fase.get("conta_na_meta")), "id": ref["id"],
                          "oferta": ref["oferta_nome"], "valor": ref["valor"],
                          "criado": ref["criado"] or ref["criado_dia"], "vencimento": ref["vencimento"],
                          "tentativas": len(tentativas),
                          "nome": primeiro("nome"), "telefone": primeiro("telefone"), "email": primeiro("email")})
        resumo_fases[fase["id"]]["pendentes"] += 1
    pendentes.sort(key=lambda p: (not p["conta_na_meta"], TIPOS_PENDENTE.index(p["tipo"]),
                                  p["vencimento"] or dt.date.max, str(p["id"])))

    # parcela mensal de quem já é aluna: fica fora dos pendentes e dos textos, só é contada
    mensalidades = sum(1 for l in linhas if l.get("mensalidade") and l["estado"] == "aberta"
                       and l["criado"] and agora - l["criado"] <= JANELA_MENSALIDADE)

    meta = (cfg.get("meta") or {}).get("total")
    feitas_hoje = por_dia.get(hoje.isoformat(), 0)
    regua, ritmo = _regua(cfg, por_dia, hoje), None
    if regua is None and meta:
        fins = [f["_fim"].date() for f in fases if f.get("conta_na_meta") and f["_fim"]]
        dias = max(0, (max(fins) - hoje).days + 1) if fins else 0
        ritmo = {"faltam": max(0, meta - total), "dias": dias}

    return {"agora": agora, "total": total, "meta": meta, "faltam": max(0, meta - total) if meta else None,
            "por_plataforma": por_plataforma, "detalhe": detalhe,
            "comercial": sum(1 for m in da_meta if m["comercial"]),
            "por_dia": por_dia, "hoje": feitas_hoje, "fases": resumo_fases, "matriculas": matriculas,
            "pendentes": pendentes, "mensalidades_abertas": mensalidades, "saidas": saidas,
            "alertas": alertas, "regua": regua, "ritmo": ritmo}


def _tipo_pendente(ls, hoje):
    """Classifica a pessoa pelo sinal mais forte e devolve a linha que o representa."""
    def mais_recente(itens):
        return max(itens, key=lambda l: (l["criado"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                                        l["criado_dia"] or dt.date.min, str(l["id"])))

    def das(plataforma, aberta):
        return [l for l in ls if l["p"] == plataforma and l["aberta"] == aberta]

    if das("tmb", "boleto"):
        return "tmb_boleto", mais_recente(das("tmb", "boleto"))
    boletos = das("voomp", "boleto")
    if boletos:
        a_vencer = [l for l in boletos if l["vencimento"] is None or l["vencimento"] >= hoje]
        if a_vencer:
            return "voomp_boleto", max(a_vencer, key=lambda l: (l["vencimento"] or dt.date.max, str(l["id"])))
        return "voomp_boleto_vencido", max(boletos, key=lambda l: (l["vencimento"], str(l["id"])))
    if das("tmb", "contrato"):
        return "tmb_contrato", mais_recente(das("tmb", "contrato"))
    if das("voomp", "pix"):
        return "voomp_pix", mais_recente(das("voomp", "pix"))
    if das("voomp", "outra"):
        return "voomp_aguardando", mais_recente(das("voomp", "outra"))
    return "voomp_recusado", mais_recente(ls)


def _regua(cfg, por_dia, hoje):
    """Posição contra a régua acumulada do plano, quando o projeto tem uma.

    `situacao` responde "estamos no plano?": adiantado (a meta acumulada de hoje já foi batida),
    no_plano (fechou ontem em dia e o dia de hoje ainda está correndo) ou atrasado.
    """
    meta = cfg.get("meta") or {}
    acumulada = meta.get("acumulada")
    if not acumulada:
        return None
    datas, hoje_iso = sorted(acumulada), hoje.isoformat()
    ate_hoje = [d for d in datas if d <= hoje_iso]
    if not ate_hoje:
        return None

    def feitas_ate(dia):
        return sum(n for d, n in por_dia.items() if d <= dia)

    total, feitas_hoje = feitas_ate(hoje_iso), por_dia.get(hoje_iso, 0)
    meta_acumulada, final = acumulada[ate_hoje[-1]], acumulada[datas[-1]]
    meta_dia = 0
    if ate_hoje[-1] == hoje_iso:
        meta_dia = meta_acumulada - acumulada[ate_hoje[-2]] if len(ate_hoje) > 1 else None
    antes = [d for d in datas if d < hoje_iso]
    meta_ate_ontem = acumulada[antes[-1]] if antes else None
    if total >= meta_acumulada:
        situacao = "adiantado"
    elif meta_ate_ontem is None or total >= meta_ate_ontem:
        situacao = "no_plano"
    else:
        situacao = "atrasado"
    # placar dos dias já começados; a primeira data da régua é só a base de partida
    placar = [{"dia": dia, "feitas": por_dia.get(dia, 0), "meta_dia": acumulada[dia] - acumulada[anterior],
               "acumulado": feitas_ate(dia), "meta_acumulada": acumulada[dia]}
              for anterior, dia in zip(ate_hoje, ate_hoje[1:])]
    potencial = meta.get("potencial_acumulado") or {}
    return {"meta_dia": meta_dia, "feitas_hoje": feitas_hoje, "meta_acumulada": meta_acumulada,
            "saldo": total - meta_acumulada, "meta_final": final, "meta_ate_ontem": meta_ate_ontem,
            "situacao": situacao, "encerrado": hoje_iso > datas[-1], "placar": placar,
            "projecao": total + (final - meta_acumulada) + max(0, (meta_dia or 0) - feitas_hoje),
            "potencial_acumulado": potencial.get(hoje_iso)}


# ───────────────────────────── textos ─────────────────────────────

def _reais(valor):
    valor = float(valor or 0)
    if abs(valor - round(valor)) < 0.005:
        return "R$ " + "{:,.0f}".format(valor).replace(",", ".")
    return "R$ " + "{:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")


def _n(n, singular, plural):
    return "%d %s" % (n, singular if n == 1 else plural)


def _delta(r, anterior):
    if not anterior:
        return ""
    quando = dt.datetime.fromisoformat(anterior["lido_em"]).astimezone(r["agora"].tzinfo)
    desde = ("as " + quando.strftime("%Hh%M")) if quando.date() == r["agora"].date() \
        else quando.strftime("%d/%m, %Hh%M")
    diferenca = r["total"] - int(anterior["total"])
    if diferenca == 0:
        return "sem mudança desde " + desde
    return "%+d desde %s" % (diferenca, desde)


def deve_postar(r, anterior):
    """O canal só recebe a leitura em que o número de efetivadas mudou (regra do Cleber).

    Mudança só em quem está aguardando não conta. A primeira leitura do projeto sempre vai.
    """
    return anterior is None or r["total"] != int(anterior["total"])


def _linha_pendentes(pendentes, plataforma):
    c = Counter(p["tipo"] for p in pendentes if p["plataforma"] == plataforma)
    partes = []
    if c["tmb_boleto"]:
        partes.append(_n(c["tmb_boleto"], "boleto gerado", "boletos gerados"))
    if c["tmb_contrato"]:
        partes.append("%d aguardando assinatura do contrato" % c["tmb_contrato"])
    if c["voomp_boleto"]:
        vencem = Counter(p["vencimento"] for p in pendentes if p["tipo"] == "voomp_boleto" and p["vencimento"])
        quando = ", ".join("%d %s %s" % (n, "vence" if n == 1 else "vencem", d.strftime("%d/%m"))
                           for d, n in sorted(vencem.items()))
        partes.append(_n(c["voomp_boleto"], "boleto", "boletos") + (" (%s)" % quando if quando else ""))
    if c["voomp_boleto_vencido"]:
        partes.append(_n(c["voomp_boleto_vencido"], "boleto vencido", "boletos vencidos"))
    if c["voomp_pix"]:
        partes.append("%d Pix" % c["voomp_pix"])
    if c["voomp_aguardando"]:
        partes.append("%d aguardando" % c["voomp_aguardando"])
    if c["voomp_recusado"]:
        partes.append("%d só com cartão recusado" % c["voomp_recusado"])
    return "%s: %s" % (NOME_PLATAFORMA[plataforma], ", ".join(partes)) if partes else ""


def _veredito(r):
    """A resposta, em uma frase, para "estamos no plano?"."""
    regua, total = r["regua"], r["total"]
    falta_hoje = regua["meta_acumulada"] - total
    if regua["encerrado"]:
        if falta_hoje <= 0:
            return "Sim. O plano fechou com a meta batida: %d de %d." % (total, regua["meta_final"])
        return "Não. O plano fechou %d abaixo da meta (%d de %d)." % (falta_hoje, total, regua["meta_final"])
    if regua["situacao"] == "adiantado":
        frente = ", %d à frente." % regua["saldo"] if regua["saldo"] > 0 else "."
        return "Sim. A meta de hoje já está batida: %d de %d%s" % (total, regua["meta_acumulada"], frente)
    if regua["situacao"] == "no_plano":
        return "Sim, até aqui. Faltam %d hoje para fechar o dia na meta (%d de %d)." % (
            falta_hoje, total, regua["meta_acumulada"])
    return "Não. Estamos %d atrás do que o plano pedia até ontem (%d de %d). Para fechar hoje na meta faltam %d." % (
        regua["meta_ate_ontem"] - total, total, regua["meta_ate_ontem"], falta_hoje)


def _placar(r, cfg):
    """Uma linha por dia do plano já começado, mais a meta de amanhã."""
    regua, hoje = r["regua"], r["agora"].date()
    calendario = cfg.get("calendario") or {}
    acumulada = (cfg.get("meta") or {}).get("acumulada") or {}
    linhas = []
    for p in regua["placar"]:
        dia = dt.date.fromisoformat(p["dia"])
        linha = "- %s: %s (meta %d) · acumulado %d de %d" % (
            _dia_curto(dia), _n(p["feitas"], "feita", "feitas"), p["meta_dia"], p["acumulado"], p["meta_acumulada"])
        if p["acumulado"] >= p["meta_acumulada"]:
            linha += " ✅"
        elif dia == hoje:
            linha += " · em andamento"
        else:
            linha += " ⚠️"
        if dia == hoje and calendario.get(p["dia"]):
            linha += " · " + calendario[p["dia"]]
        linhas.append(linha)
    amanha = (hoje + dt.timedelta(days=1)).isoformat()
    if amanha in acumulada and hoje.isoformat() in acumulada:
        linha = "- Amanhã, %s: meta %d" % (_dia_curto(dt.date.fromisoformat(amanha)),
                                           acumulada[amanha] - acumulada[hoje.isoformat()])
        linhas.append(linha + (" · " + calendario[amanha] if calendario.get(amanha) else ""))
    return linhas


def resumo_canal(r, cfg, anterior=None):
    """Resumo só com números, em Markdown, para postar em canal. Não leva nome, telefone nem e-mail.

    Abre com a posição contra o plano, que é o que o time precisa ver primeiro.
    """
    regua = r["regua"]
    delta = _delta(r, anterior)
    blocos = [["**Vendas %s · %s**%s" % (cfg.get("titulo") or cfg["projeto"], _quando(r["agora"]),
                                         " (%s)" % delta if delta else "")]]

    contam = ", ".join(f["nome"] for f in r["fases"].values() if f["conta_na_meta"])
    efetivadas = "- Efetivadas (%s): %d" % (contam, r["total"])
    if r["meta"]:
        efetivadas += " de %d, faltam %d" % (r["meta"], r["faltam"])
    if regua:
        hoje = "- Hoje: " + _n(r["hoje"], "feita", "feitas")
        if regua["meta_dia"] is not None and not regua["encerrado"]:
            hoje += ", meta do dia %d" % regua["meta_dia"]
        bloco = ["**Estamos no plano?**", "- " + _veredito(r), hoje, efetivadas]
        if r["faltam"] and not regua["encerrado"]:
            bloco.append("- Cumprindo a meta dos dias que faltam, fecha em %d" % regua["projecao"])
        blocos += [bloco, ["**Plano dia a dia**"] + _placar(r, cfg)]
    else:
        bloco = ["**Meta**", efetivadas, "- Hoje: " + _n(r["hoje"], "feita", "feitas")]
        if r["ritmo"] and r["ritmo"]["dias"] and r["ritmo"]["faltam"]:
            por_dia = ("%.1f" % (r["ritmo"]["faltam"] / r["ritmo"]["dias"])).replace(".", ",")
            bloco.append("- Ritmo necessário: %s por dia (%d em %s)" % (
                por_dia, r["ritmo"]["faltam"], _n(r["ritmo"]["dias"], "dia", "dias")))
        blocos.append(bloco)

    bloco = ["**Onde vendeu**"]
    for p in PLATAFORMAS:
        if p in r["por_plataforma"]:
            detalhe = ", ".join("%s %d" % kv for kv in r["detalhe"].get(p, {}).items())
            bloco.append("- %s %d" % (NOME_PLATAFORMA[p], r["por_plataforma"][p]) + (" (%s)" % detalhe if detalhe else ""))
    bloco.append("- Pelo comercial: %d" % r["comercial"])
    blocos.append(bloco)

    da_meta = [p for p in r["pendentes"] if p["conta_na_meta"]]
    bloco = ["**Aguardando pagamento: %s**" % _n(len(da_meta), "pessoa", "pessoas")]
    bloco += ["- " + linha for linha in (_linha_pendentes(da_meta, p) for p in PLATAFORMAS) if linha]
    bloco += ["- " + nota for nota in r.get("notas") or []]
    blocos.append(bloco)

    bloco = []
    for f in r["fases"].values():
        if not f["conta_na_meta"] and (f["matriculas"] or f["pendentes"]):
            extra = ", %d aguardando" % f["pendentes"] if f["pendentes"] else ""
            bloco.append("- %s: %s%s" % (f["nome"], _n(f["matriculas"], "matrícula", "matrículas"), extra))
    if bloco:
        blocos.append(["**Fora da meta**"] + bloco)

    saidas = []
    if r["saidas"]["reembolsos"]:
        saidas.append(_n(r["saidas"]["reembolsos"], "reembolso", "reembolsos"))
    if r["saidas"]["cancelamentos"]:
        saidas.append(_n(r["saidas"]["cancelamentos"], "cancelamento", "cancelamentos"))
    if saidas:
        blocos.append(["**Saíram da conta**", "- " + ", ".join(saidas)])
    if r["alertas"]:
        blocos.append(["**Atenção**"] + ["- " + alerta for alerta in r["alertas"]])
    return "\n\n".join("\n".join(bloco) for bloco in blocos)


ROTULO_PENDENTE = {"tmb_boleto": "boleto gerado", "tmb_contrato": "contrato sem assinatura",
                   "voomp_boleto": "boleto", "voomp_boleto_vencido": "boleto vencido", "voomp_pix": "Pix não pago",
                   "voomp_aguardando": "aguardando pagamento", "voomp_recusado": "cartão recusado"}


def relatorio_chat(r, cfg, anterior=None):
    """Relatório completo para o Cleber: o resumo, quem está aguardando (com contato) e o dia a dia."""
    linhas = [resumo_canal(r, cfg, anterior), ""]
    if r["pendentes"]:
        linhas.append("**Quem está aguardando pagamento**")
        for p in r["pendentes"]:
            partes = [p["nome"] or "(sem nome)", NOME_PLATAFORMA[p["plataforma"]],
                      "%s de %s" % (ROTULO_PENDENTE[p["tipo"]], _reais(p["valor"]))]
            if p["vencimento"]:
                partes.append(("venceu " if p["tipo"] == "voomp_boleto_vencido" else "vence ")
                              + p["vencimento"].strftime("%d/%m"))
            if isinstance(p["criado"], dt.datetime):
                partes.append("tentou em " + p["criado"].strftime("%d/%m, %Hh%M"))
            elif p["criado"]:
                partes.append("gerado em " + p["criado"].strftime("%d/%m"))
            if p["tentativas"] > 1:
                partes.append("%d tentativas" % p["tentativas"])
            if p["telefone"]:
                partes.append(str(p["telefone"]))
            if not p["conta_na_meta"]:
                partes.append("fora da meta (%s)" % r["fases"][p["fase"]]["nome"])
            linhas.append("- " + " · ".join(partes))
        linhas.append("")
    if r["por_dia"]:
        acumulada = (cfg.get("meta") or {}).get("acumulada") or {}
        linhas.append("**Dia a dia desde a abertura**")
        soma = 0
        for dia, feitas in r["por_dia"].items():
            soma += feitas
            texto = "- %s: %d (acumulado %d" % (_dia_curto(dt.date.fromisoformat(dia)), feitas, soma)
            texto += ", meta %d)" % acumulada[dia] if dia in acumulada else ")"
            linhas.append(texto)
    return "\n".join(linhas).rstrip()


# ───────────────────────────── semanal (carteira) ─────────────────────────────

def preparar_config(cfg):
    """Na carteira, os produtos de cada plataforma saem da lista `produtos` (uma fonte só)."""
    if cfg.get("tipo") != "carteira":
        return cfg
    vistos = {}
    for prod in cfg["produtos"]:
        for p in PLATAFORMAS:
            for pid, rotulo in (prod.get(p) or {}).items():
                chave = (p, str(pid))
                if chave in vistos:
                    raise SystemExit("O produto %s da %s está em duas linhas da carteira: %s e %s."
                                     % (pid, NOME_PLATAFORMA[p], vistos[chave], prod["nome"]))
                vistos[chave] = prod["nome"]
                cfg["plataformas"].setdefault(p, {}).setdefault("produtos", {})[str(pid)] = \
                    "%s · %s" % (prod["nome"], rotulo)
    return cfg


def semana_anterior(hoje):
    """Segunda a domingo da última semana fechada antes de `hoje`."""
    fim = hoje - dt.timedelta(days=hoje.weekday() + 1)
    return fim - dt.timedelta(days=6), fim


def semana_em_andamento(hoje):
    """Segunda desta semana até hoje: a avaliação pedida no meio da semana."""
    return hoje - dt.timedelta(days=hoje.weekday()), hoje


def meses_da_semana(inicio, fim):
    """Cada mês que a semana toca, do dia 1 até o domingo (ou até o fim do mês, se ele fechou)."""
    meses, dia = [], inicio.replace(day=1)
    while dia <= fim:
        proximo = (dia.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        meses.append((dia, min(fim, proximo - dt.timedelta(days=1))))
        dia = proximo
    return meses


def _somar(vendas):
    """Contagem e valor; `valor*` é em real e as outras moedas de repasse (dólar) ficam em `moedas`."""
    com = [v for v in vendas if v["comercial"]]
    sem = [v for v in vendas if not v["comercial"]]

    def valor(vs, moeda="BRL"):
        return round(sum(float(v["valor"] or 0) for v in vs if (v.get("moeda") or "BRL") == moeda), 2)

    outras = sorted({v.get("moeda") or "BRL" for v in vendas} - {"BRL"})
    return {"total": len(vendas), "valor": valor(vendas), "comercial": len(com), "valor_comercial": valor(com),
            "nao_comercial": len(sem), "valor_nao_comercial": valor(sem),
            "moedas": {m: {"valor": valor(vendas, m), "valor_comercial": valor(com, m),
                           "valor_nao_comercial": valor(sem, m)} for m in outras}}


def _juntar(somas):
    """Soma de vários `_somar` (os produtos de uma expert, por exemplo)."""
    t = {"total": 0, "valor": 0.0, "comercial": 0, "valor_comercial": 0.0, "nao_comercial": 0,
         "valor_nao_comercial": 0.0, "moedas": {}}
    for s in somas:
        for k in ("total", "comercial", "nao_comercial"):
            t[k] += s[k]
        for k in ("valor", "valor_comercial", "valor_nao_comercial"):
            t[k] = round(t[k] + s[k], 2)
        for m, v in (s.get("moedas") or {}).items():
            d = t["moedas"].setdefault(m, {"valor": 0.0, "valor_comercial": 0.0, "valor_nao_comercial": 0.0})
            for k in d:
                d[k] = round(d[k] + v[k], 2)
    return t


def _dinheiro(valor, moeda="BRL"):
    texto = _reais(valor)
    return texto if moeda == "BRL" else texto.replace("R$", SIMBOLO_MOEDA.get(moeda, moeda), 1)


def _valores(s, campo="valor"):
    """'R$ 1.234 + US$ 56': o real e cada moeda de repasse, sem converter dólar em real."""
    partes = [_reais(s[campo])] if s[campo] or not s.get("moedas") else []
    partes += [_dinheiro(v[campo], m) for m, v in (s.get("moedas") or {}).items() if v[campo]]
    return " + ".join(partes) or _reais(0)


def _vendas_da_carteira(cfg, voomp, tmb, hotmart=None):
    """Linhas dos produtos da carteira e as vendas que contam.

    Venda = primeira compra paga da aluna naquele produto no mês (as plataformas juntas): cobrança
    em dobro no mesmo mês conta uma, renovação de assinatura não conta, e quem compra de novo em outro
    mês (troca de oferta, recompra) conta de novo. O dia é o do pagamento, no fuso da carteira.
    Linha com `"contar": "por_produto"` (cursos e e-books agrupados) conta cada produto da plataforma
    à parte, para não engolir quem compra dois itens diferentes da mesma linha no mês.
    """
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    produto_de = {(p, str(pid)): i for i, prod in enumerate(cfg["produtos"])
                  for p in PLATAFORMAS for pid in (prod.get(p) or {})}

    linhas = [_linha_voomp(l, cfg, fuso) for l in voomp or []] + [_linha_tmb(l, cfg, fuso) for l in tmb or []]
    if "hotmart" in cfg["plataformas"]:
        linhas += [_linha_hotmart(l, cfg, fuso) for l in hotmart or []]
    fora = Counter((l["p"], str(l["produto_id"]), l.get("produto_nome") or "") for l in linhas
                   if (l["p"], str(l["produto_id"])) not in produto_de and l["estado"] == "paga")
    linhas = [l for l in linhas if (l["p"], str(l["produto_id"])) in produto_de]
    for l in linhas:
        l["produto"] = produto_de[(l["p"], str(l["produto_id"]))]
    _agrupar_pessoas(linhas)
    _marcar_assinaturas(linhas)
    alertas = ["%s: %d venda(s) com status %s, que o motor não conhece e não contou" % (NOME_PLATAFORMA[p], n, st)
               for (p, st), n in sorted(Counter((l["p"], str(l["status"])) for l in linhas
                                                if l["estado"] == "outro").items())]
    alertas += ["%s: produto %s%s fora da carteira, com %d venda(s) paga(s); acrescente à linha do produto"
                % (NOME_PLATAFORMA[p], pid, " (%s)" % nome if nome else "", n) for (p, pid, nome), n in sorted(fora.items())]
    sem_cambio = sum(1 for l in linhas if l["estado"] == "paga" and l["valor"] is None)
    if sem_cambio:
        alertas.append("%d venda(s) paga(s) em moeda estrangeira sem câmbio da plataforma: contadas, sem valor" % sem_cambio)

    primeiras = {}
    for l in sorted((l for l in linhas if l["estado"] == "paga" and l["pago"] and not l.get("renovacao")),
                    key=lambda l: (l["pago"], str(l["id"]))):
        por_produto = cfg["produtos"][l["produto"]].get("contar") == "por_produto"
        chave = (l["p"], str(l["produto_id"])) if por_produto else None
        primeiras.setdefault((l["produto"], chave, l["pessoa"], l["pago"].year, l["pago"].month), l)
    return linhas, list(primeiras.values()), alertas


def _entre(vendas, a, b):
    return [v for v in vendas if a <= v["pago"].date() <= b]


def semanal(cfg, voomp, tmb, hoje, lido_em=None, hotmart=None, parcial=False):
    """Vendas da semana fechada (ou da semana em andamento, com `parcial`) e do mês, por produto da carteira."""
    inicio, fim = semana_em_andamento(hoje) if parcial else semana_anterior(hoje)
    meses = meses_da_semana(inicio, fim)
    linhas, novas, alertas = _vendas_da_carteira(cfg, voomp, tmb, hotmart)
    entre = _entre

    produtos = []
    for i, prod in enumerate(cfg["produtos"]):
        vs = [v for v in novas if v["produto"] == i]
        reembolsos = sum(1 for l in linhas if l["produto"] == i and l["estado"] == "reembolsada"
                         and l.get("reembolsado") and inicio <= l["reembolsado"].date() <= fim)
        produtos.append({"nome": prod["nome"], "expert": prod.get("expert"), "ordem": i,
                         "semana": _somar(entre(vs, inicio, fim)),
                         "meses": [_somar(entre(vs, a, b)) for a, b in meses], "reembolsos": reembolsos})
    total = {"semana": _somar(entre(novas, inicio, fim)), "meses": [_somar(entre(novas, a, b)) for a, b in meses],
             "reembolsos": sum(p["reembolsos"] for p in produtos)}
    return {"titulo": cfg.get("titulo"), "inicio": inicio, "fim": fim, "meses": meses, "lido_em": lido_em,
            "parcial": parcial, "produtos": produtos, "total": total, "alertas": alertas}


def mes_principal(r):
    """Índice, em r["meses"], do mês com mais dias da semana: na virada, o mês que fechou, não o que abriu ontem."""
    dias = [(min(b, r["fim"]) - max(a, r["inicio"])).days + 1 for a, b in r["meses"]]
    return dias.index(max(dias))


def dados_deck(cfg, r, r_ant, ra):
    """Junta a semana, a semana anterior e o ano por expert, no formato que o deck_vendas.py desenha."""
    info = cfg.get("experts") or {}
    i_mes = mes_principal(r)
    inicio_mes = r["meses"][i_mes][0]
    i_ano = next((i for i, (a, _) in enumerate(ra["meses"]) if a == inicio_mes), None)
    ordem = []
    for prod in cfg["produtos"]:
        if (prod.get("expert") or "Outros") not in ordem:
            ordem.append(prod.get("expert") or "Outros")

    def da(res, e):
        return [p for p in res["produtos"] if (p.get("expert") or "Outros") == e] if res else []

    experts = []
    for e in ordem:
        ps, pa, pant = da(r, e), da(ra, e), da(r_ant, e)
        produtos = [{"nome": p["nome"], "semana": p["semana"], "mes": p["meses"][i_mes], "ano": q["ano"],
                     "mes_anterior": q["meses"][i_ano - 1] if i_ano else None, "reembolsos": p["reembolsos"]}
                    for p, q in zip(ps, pa)]
        experts.append({
            "nome": e, "curto": (info.get(e) or {}).get("curto") or e.split(" ")[0],
            "cor": (info.get(e) or {}).get("cor"),
            "semana": _juntar(p["semana"] for p in ps), "mes": _juntar(p["meses"][i_mes] for p in ps),
            "ano": _juntar(q["ano"] for q in pa),
            "meses_ano": [_juntar(q["meses"][i] for q in pa) for i in range(len(ra["meses"]))],
            "semana_anterior": _juntar(p["semana"] for p in pant) if r_ant else None,
            "produtos": produtos})
    return {"titulo": cfg.get("titulo"), "parcial": r.get("parcial"), "inicio": r["inicio"], "fim": r["fim"],
            "mes": r["meses"][i_mes], "meses_ano": ra["meses"], "lido_em": r.get("lido_em"),
            "mes_novo": {"periodo": r["meses"][-1], "total": r["total"]["meses"][-1]} if i_mes < len(r["meses"]) - 1 else None,
            "total": {"semana": r["total"]["semana"], "mes": r["total"]["meses"][i_mes], "ano": ra["total"]["ano"],
                      "meses_ano": ra["total"]["meses"],
                      "semana_anterior": r_ant["total"]["semana"] if r_ant else None},
            "experts": experts, "alertas": list(r.get("alertas") or [])}


def anual(cfg, voomp, tmb, ano, ate, hotmart=None):
    """Mês a mês do ano até `ate`, por produto da carteira, com o acumulado do ano. Mesma contagem do semanal."""
    _, novas, alertas = _vendas_da_carteira(cfg, voomp, tmb, hotmart)
    meses = meses_da_semana(dt.date(ano, 1, 1), min(ate, dt.date(ano, 12, 31)))
    inicio, fim = meses[0][0], meses[-1][1]

    def bloco(vs):
        return {"meses": [_somar(_entre(vs, a, b)) for a, b in meses], "ano": _somar(_entre(vs, inicio, fim))}

    produtos = [dict(bloco([v for v in novas if v["produto"] == i]), nome=prod["nome"], expert=prod.get("expert"),
                     ordem=i) for i, prod in enumerate(cfg["produtos"])]
    return {"ano": ano, "inicio": inicio, "fim": fim, "meses": meses, "produtos": produtos,
            "total": bloco(novas), "alertas": alertas}


def resumo_anual(r):
    """Tabela do ano: vendas por mês de cada produto com venda, e o acumulado comercial × não comercial."""
    cabeca = [MESES[a.month - 1][:3] for a, _ in r["meses"]]
    linhas = ["**Vendas de %d · até %s**" % (r["ano"], r["fim"].strftime("%d/%m")), "",
              "| Produto | " + " | ".join(cabeca) + " | Ano | Comercial | Não comercial | Valor |",
              "|---|" + "---:|" * (len(cabeca) + 4)]
    com_venda = sorted((p for p in r["produtos"] if p["ano"]["total"]), key=lambda p: (-p["ano"]["total"], p["ordem"]))
    for p in com_venda + [dict(r["total"], nome="Total", expert=None)]:
        nome = "%s · %s" % (p["nome"], p["expert"]) if p.get("expert") else "**%s**" % p["nome"]
        a = p["ano"]
        linhas.append("| %s | %s | %d | %d | %d | %s |" % (nome, " | ".join(str(m["total"]) for m in p["meses"]),
                                                          a["total"], a["comercial"], a["nao_comercial"],
                                                          _valores(a)))
    sem = [p["nome"] for p in r["produtos"] if not p["ano"]["total"]]
    if sem:
        linhas += ["", "Sem vendas no ano: " + ", ".join(sem)]
    return "\n".join(linhas)


def _rotulo_mes(a, b):
    nome = MESES[a.month - 1].capitalize()
    fim_do_mes = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return "%s (fechado)" % nome if b == fim_do_mes else "%s até %s" % (nome, b.strftime("%d/%m"))


def _linha_periodo(rotulo, s):
    if not s["total"]:
        return "- %s: nenhuma venda" % rotulo
    def parte(nome, n, campo):
        return "%s %d (%s)" % (nome, n, _valores(s, campo)) if n else "%s 0" % nome
    return "- %s: %s, %s · %s · %s" % (rotulo, _n(s["total"], "venda", "vendas"), _valores(s),
                                      parte("comercial", s["comercial"], "valor_comercial"),
                                      parte("não comercial", s["nao_comercial"], "valor_nao_comercial"))


def resumo_semanal(r):
    """Resumo da semana para o chat e o canal: só números, títulos em negrito."""
    linhas = ["**Vendas da semana%s · %s a %s**" % (" em andamento" if r.get("parcial") else "",
                                                     _dia_curto(r["inicio"]), _dia_curto(r["fim"]))]
    lido = ("Leitura de %s. " % _quando(r["lido_em"])) if r.get("lido_em") else ""
    linhas += [lido + "Uma venda por aluna e produto no mês, no dia do pagamento; renovação de assinatura não entra.", ""]

    def bloco(titulo, item):
        saida = ["**%s**" % titulo, _linha_periodo("Semana", item["semana"])]
        saida += [_linha_periodo(_rotulo_mes(a, b), s) for (a, b), s in zip(r["meses"], item["meses"])]
        if item["reembolsos"]:
            saida.append("- Reembolsos na semana: %d" % item["reembolsos"])
        return saida + [""]

    com_venda = [p for p in r["produtos"] if any(s["total"] for s in p["meses"]) or p["reembolsos"]]
    com_venda.sort(key=lambda p: (-p["meses"][-1]["total"], -p["meses"][0]["total"], p["ordem"]))
    for p in com_venda:
        linhas += bloco("%s · %s" % (p["nome"], p["expert"]) if p.get("expert") else p["nome"], p)
    linhas += bloco("Total", r["total"])
    sem_venda = [p for p in r["produtos"] if p not in com_venda]
    if sem_venda:
        linhas += ["Sem vendas no mês: " + ", ".join(
            "%s (%s)" % (p["nome"], p["expert"]) if p.get("expert") else p["nome"] for p in sem_venda), ""]
    linhas.append("Valores como as plataformas registram: na assinatura entra só a 1ª mensalidade; "
                  "na Hotmart, venda em moeda estrangeira vai para o real ou o dólar de repasse pelo câmbio da Hotmart.")
    return "\n".join(linhas)


def _gravar_semanal(pasta, r, texto):
    """Uma linha por produto e semana em historico_semanal.csv (refazer a semana substitui) e o texto em relatorios/."""
    historico = pasta / "historico_semanal.csv"
    semana = r["inicio"].isoformat()
    (a, b), = r["meses"][-1:]
    campos = ["semana_inicio", "semana_fim", "produto", "expert", "semana_vendas", "semana_comercial",
              "semana_nao_comercial", "semana_valor", "semana_valor_comercial", "semana_valor_nao_comercial",
              "mes", "mes_ate", "mes_vendas", "mes_comercial", "mes_nao_comercial", "mes_valor",
              "mes_valor_comercial", "mes_valor_nao_comercial", "semana_valor_usd", "mes_valor_usd",
              "reembolsos_semana", "lido_em"]
    registros = []
    if historico.exists():
        with historico.open(encoding="utf-8", newline="") as f:
            registros = [x for x in csv.DictReader(f) if x["semana_inicio"] != semana]
    for p in r["produtos"] + [dict(r["total"], nome="Total", expert="")]:
        s, m = p["semana"], p["meses"][-1]
        registros.append({
            "semana_inicio": semana, "semana_fim": r["fim"].isoformat(), "produto": p["nome"],
            "expert": p.get("expert") or "", "semana_vendas": s["total"], "semana_comercial": s["comercial"],
            "semana_nao_comercial": s["nao_comercial"], "semana_valor": s["valor"],
            "semana_valor_comercial": s["valor_comercial"], "semana_valor_nao_comercial": s["valor_nao_comercial"],
            "mes": a.strftime("%Y-%m"), "mes_ate": b.isoformat(), "mes_vendas": m["total"],
            "mes_comercial": m["comercial"], "mes_nao_comercial": m["nao_comercial"], "mes_valor": m["valor"],
            "mes_valor_comercial": m["valor_comercial"], "mes_valor_nao_comercial": m["valor_nao_comercial"],
            "semana_valor_usd": (s.get("moedas") or {}).get("USD", {}).get("valor", 0),
            "mes_valor_usd": (m.get("moedas") or {}).get("USD", {}).get("valor", 0),
            "reembolsos_semana": p["reembolsos"],
            "lido_em": r["lido_em"].isoformat(timespec="seconds") if r.get("lido_em") else ""})
    with historico.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(registros)
    relatorios = pasta / "relatorios"
    relatorios.mkdir(exist_ok=True)
    (relatorios / ("semana-%s.md" % semana)).write_text(texto + "\n", encoding="utf-8")


# ───────────────────────────── coletores ─────────────────────────────

def _inicio_das_fases(cfg, fuso):
    inicios = [_data(f["inicio"], fuso) for f in cfg.get("fases") or [] if f.get("inicio")]
    return min(inicios) if inicios else None


def montar_coletor(cfg, plataforma, agora=None):
    """Função JavaScript de coleta, com os parâmetros do projeto, para rodar na aba logada."""
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    agora = (agora or dt.datetime.now(fuso)).astimezone(fuso)
    conf = cfg["plataformas"][plataforma]
    inicio = _inicio_das_fases(cfg, fuso) or agora - dt.timedelta(days=30)
    # contato só de quem tentou há pouco: é o que a recuperação usa
    contato_desde = (inicio - dt.timedelta(days=30)).date().isoformat()
    produtos = sorted(int(p) for p in conf["produtos"])
    if plataforma == "voomp":
        # folga de 4 meses para enxergar a primeira cobrança de cada assinatura
        desde = conf.get("coletar_desde") or (inicio - dt.timedelta(days=120)).date().isoformat()
        if cfg.get("tipo") == "carteira":
            contato_desde = SEM_CONTATO
        parametros = {"produtos": produtos, "desde": desde, "contato_desde": contato_desde}
    elif plataforma == "tmb":
        fins = [_data(f["fim"], fuso).date() for f in cfg.get("fases") or [] if f.get("fim")]
        ultimo = min(agora.date(), max(fins)) if fins else agora.date()
        dias, dia = [], inicio.date()
        while dia <= ultimo and len(dias) < MAX_DIAS_TMB:
            dias.append(dia.isoformat())
            dia += dt.timedelta(days=1)
        parametros = {"produtos": produtos, "dias": dias, "central_id": conf.get("central_id")}
    else:
        raise SystemExit("Plataforma desconhecida: %s" % plataforma)
    modelo = (AQUI / "coletores" / (plataforma + ".js")).read_text(encoding="utf-8")
    return modelo.replace("__CFG__", json.dumps(parametros, ensure_ascii=False))


def montar_descoberta(plataforma, busca, dias=30):
    modelo = (AQUI / "coletores" / (plataforma + "_descobrir.js")).read_text(encoding="utf-8")
    return modelo.replace("__CFG__", json.dumps({"busca": busca, "dias": dias}, ensure_ascii=False))


# ───────────────────────────── arquivos do projeto ─────────────────────────────

def _carregar_coleta(caminho, plataforma):
    coleta = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if coleta.get("plataforma") != plataforma:
        raise SystemExit("%s não é uma coleta da %s." % (caminho, NOME_PLATAFORMA[plataforma]))
    if coleta.get("erro") == "sem_sessao":
        raise SystemExit("SESSAO_EXPIRADA: a sessão da %s caiu. Peça o login na janela do navegador da "
                         "automação e rode a leitura de novo." % NOME_PLATAFORMA[plataforma])
    if coleta.get("erro"):
        raise SystemExit("A coleta da %s falhou: %s" % (NOME_PLATAFORMA[plataforma], coleta["erro"]))
    return coleta


def avisos_da_coleta(cfg, plataforma, coleta):
    """Confere se a plataforma devolveu tudo o que diz ter.

    A TMB conta pedidos de status 9 que a lista nunca devolve; a diferença já conhecida fica em
    `registros_ocultos` no config e só uma diferença nova vira aviso.
    """
    falta = (coleta.get("total_api") or 0) - len(coleta["linhas"])
    conhecida = 0 if coleta.get("fonte") == "api" else cfg["plataformas"][plataforma].get("registros_ocultos") or 0
    if falta == conhecida:
        return []
    return ["%s: a plataforma informa %d registros e devolveu %d (diferença de %d)."
            % (NOME_PLATAFORMA[plataforma], coleta.get("total_api") or 0, len(coleta["linhas"]), falta)]


def _ultima_coleta(pasta, plataforma):
    arquivos = sorted((pasta / "leituras").glob(plataforma + "-*.json"))
    return arquivos[-1] if arquivos else None


def _guardar_coleta(caminho, pasta):
    """Leva a coleta para leituras/ do projeto e mantém só as últimas de cada plataforma."""
    destino = pasta / "leituras"
    destino.mkdir(exist_ok=True)
    caminho = Path(caminho).resolve()
    if caminho.parent != destino.resolve():
        shutil.move(str(caminho), str(destino / caminho.name))
    plataforma = caminho.name.split("-")[0]
    for velho in sorted(destino.glob(plataforma + "-*.json"))[:-LEITURAS_GUARDADAS]:
        velho.unlink()


def _leitura_anterior(pasta):
    historico = pasta / "historico.csv"
    if not historico.exists():
        return None
    with historico.open(encoding="utf-8", newline="") as f:
        registros = list(csv.DictReader(f))
    return registros[-1] if registros else None


def _gravar_historico(pasta, r):
    historico = pasta / "historico.csv"
    regua = r["regua"] or {}
    da_meta = [p for p in r["pendentes"] if p["conta_na_meta"]]
    registro = {"lido_em": r["agora"].isoformat(timespec="seconds"), "total": r["total"],
                "tmb": r["por_plataforma"].get("tmb", ""), "voomp": r["por_plataforma"].get("voomp", ""),
                "comercial": r["comercial"], "hoje": r["hoje"], "aguardando": len(da_meta),
                "meta_acumulada": regua.get("meta_acumulada", ""), "saldo": regua.get("saldo", "")}
    novo = not historico.exists()
    with historico.open("a", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(registro))
        if novo:
            escritor.writeheader()
        escritor.writerow(registro)


def _gravar_pendentes(pasta, r):
    campos = ["nome", "telefone", "email", "plataforma", "situacao", "valor", "vencimento", "tentou_em",
              "tentativas", "oferta", "fase", "conta_na_meta", "id"]
    with (pasta / "pendentes.csv").open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        for p in r["pendentes"]:
            criado = p["criado"]
            escritor.writerow({
                "nome": p["nome"] or "", "telefone": p["telefone"] or "", "email": p["email"] or "",
                "plataforma": NOME_PLATAFORMA[p["plataforma"]], "situacao": ROTULO_PENDENTE[p["tipo"]],
                "valor": ("%.2f" % float(p["valor"] or 0)).replace(".", ","),
                "vencimento": p["vencimento"].strftime("%d/%m/%Y") if p["vencimento"] else "",
                "tentou_em": criado.strftime("%d/%m/%Y %H:%M") if isinstance(criado, dt.datetime)
                else (criado.strftime("%d/%m/%Y") if criado else ""),
                "tentativas": p["tentativas"], "oferta": p["oferta"] or "",
                "fase": r["fases"][p["fase"]]["nome"], "conta_na_meta": "sim" if p["conta_na_meta"] else "não",
                "id": p["id"]})


def projetos_configurados(raiz):
    for config in sorted(Path(raiz).glob("*/%s/%s*/config.json" % (PASTA_RESULTADOS, PREFIXO_PASTA))):
        try:
            yield config, json.loads(config.read_text(encoding="utf-8"))
        except ValueError as erro:
            print("Config inválido em %s: %s" % (config, erro), file=sys.stderr)


# ───────────────────────────── linha de comando ─────────────────────────────

def _cmd_listar(args):
    achou = False
    hoje = dt.date.today()
    for caminho, cfg in projetos_configurados(args.raiz):
        achou = True
        fins = [_dia(f["fim"]) for f in cfg["fases"] if f.get("fim")]
        situacao = "encerrado em %s" % max(fins).strftime("%d/%m/%Y") if fins and max(fins) < hoje else "em andamento"
        print("%s · %s · %s\n  %s" % (cfg["projeto"], cfg.get("titulo") or "", situacao, caminho))
    if not achou:
        print("Nenhum projeto configurado em %s." % args.raiz)


def _cmd_coletor(args):
    cfg = preparar_config(json.loads(Path(args.config).read_text(encoding="utf-8")))
    print(montar_coletor(cfg, args.plataforma))


def _cmd_descobrir(args):
    print(montar_descoberta(args.plataforma, args.busca, args.dias))


def _cmd_analisar(args):
    config = Path(args.config).resolve()
    pasta = config.parent
    cfg = json.loads(config.read_text(encoding="utf-8"))
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    usadas, avisos, notas = [], [], []

    def carregar(opcao, prefixo, plataforma):
        caminho = opcao or _ultima_coleta(pasta, prefixo)
        if not caminho:
            return None
        coleta = _carregar_coleta(caminho, plataforma)
        usadas.append(Path(caminho))
        avisos.extend(avisos_da_coleta(cfg, plataforma, coleta))
        return coleta

    voomp = portal = api = None
    if "voomp" in cfg["plataformas"]:
        voomp = carregar(args.voomp, "voomp", "voomp")
        if not voomp:
            raise SystemExit("Falta a coleta da Voomp (rode o coletor e passe --voomp).")
    if "tmb" in cfg["plataformas"]:
        # a API oficial lê os efetivados sem login; o portal traz os boletos em aberto e a oferta
        api = carregar(args.tmb_api, "tmbapi", "tmb")
        portal = carregar(args.tmb, "tmb", "tmb")
        if not (api or portal):
            raise SystemExit("Falta a coleta da TMB (rode `tmb-api` ou o coletor do portal).")
        central = cfg["plataformas"]["tmb"].get("central_id")
        if portal and central and portal.get("central_id") and central != portal["central_id"]:
            raise SystemExit("A TMB está aberta em outra central. Troque para a central do projeto.")

    def lido_em(coleta):
        return _data(coleta["coletado_em"], fuso, sem_fuso_e_utc=True)

    agora = _data(args.agora, fuso) if args.agora else max(lido_em(c) for c in (voomp, api or portal) if c)
    corte = _data(args.corte, fuso) if args.corte else None
    if api and portal and not corte and agora - lido_em(portal) > PORTAL_VELHO:
        notas.append("Boletos da TMB lidos do portal em %s; os novos só entram com o portal logado"
                     % _quando(lido_em(portal)))
    elif api and not portal:
        notas.append("TMB lida só pela API: os boletos em aberto dela não entram nesta leitura")
    tmb = juntar_tmb(api["linhas"] if api else [], portal["linhas"] if portal else [])

    r = analisar(cfg, voomp["linhas"] if voomp else [], tmb, agora=corte or agora, corte=corte)
    r["alertas"] = avisos + r["alertas"]
    r["notas"] = notas

    gravar = not (args.sem_gravar or corte)
    anterior = None if corte else _leitura_anterior(pasta)
    print("=== RELATÓRIO (para o chat; tem dados pessoais) ===")
    print(relatorio_chat(r, cfg, anterior))
    if deve_postar(r, anterior):
        print("\n=== POSTAR NO CANAL: SIM ===")
        print("=== RESUMO PARA O CANAL (só números) ===")
        print(resumo_canal(r, cfg, anterior))
    else:
        print("\n=== POSTAR NO CANAL: NÃO ===")
        print("As efetivadas continuam em %d, como na leitura anterior (%s). Não postar no canal."
              % (r["total"], _delta(r, anterior)))
    if gravar:
        _gravar_historico(pasta, r)
        _gravar_pendentes(pasta, r)
        for caminho in usadas:
            _guardar_coleta(caminho, pasta)
        print("\nGravado em %s: historico.csv, pendentes.csv e leituras/." % pasta)


def _cmd_tmb_api(args):
    config = Path(args.config).resolve()
    cfg = preparar_config(json.loads(config.read_text(encoding="utf-8")))
    token = os.environ.get("TMB_API_TOKEN")
    if not token:
        raise SystemExit("Falta o token: TMB_API_TOKEN=$(security find-generic-password -s %s -w) python3 ..."
                         % KEYCHAIN_TMB)
    coleta = coletar_tmb_api(cfg, token)
    if coleta.get("erro"):
        raise SystemExit("A API da TMB respondeu com erro: %s" % coleta["erro"])
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    destino = Path(args.saida) if args.saida else config.parent / "leituras" / (
        "tmbapi-%s.json" % dt.datetime.now(fuso).strftime("%Y-%m-%d_%H%M"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(coleta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("%d pedidos lidos da API da TMB (total informado: %d) -> %s"
          % (len(coleta["linhas"]), coleta["total_api"], destino))


def _cmd_semanal(args):
    config = Path(args.config).resolve()
    pasta = config.parent
    cfg = preparar_config(json.loads(config.read_text(encoding="utf-8")))
    if cfg.get("tipo") != "carteira":
        raise SystemExit("O semanal lê o config da carteira (\"tipo\": \"carteira\"), não o de um projeto.")
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    agora = dt.datetime.now(fuso)
    coletas, avisos = {}, []
    for prefixo, plataforma in (("voomp", "voomp"), ("tmbapi", "tmb"), ("hotmart", "hotmart")):
        if plataforma not in cfg["plataformas"]:
            continue
        caminho = _ultima_coleta(pasta, prefixo)
        if not caminho:
            raise SystemExit("Falta a coleta %s em %s/leituras." % (prefixo, pasta))
        coleta = _carregar_coleta(caminho, plataforma)
        lida = _data(coleta["coletado_em"], fuso, sem_fuso_e_utc=True)
        if agora - lida > COLETA_VELHA:
            avisos.append("A coleta da %s é de %s; colete de novo antes de fechar a semana."
                          % (NOME_PLATAFORMA[plataforma], _quando(lida)))
        avisos.extend(avisos_da_coleta(cfg, plataforma, coleta))
        coletas[plataforma] = (caminho, coleta, lida)
    lido_em = max(c[2] for c in coletas.values())
    hoje = dt.date.fromisoformat(args.hoje) if args.hoje else lido_em.date()
    r = semanal(cfg, coletas.get("voomp", (0, {"linhas": []}))[1]["linhas"],
                coletas.get("tmb", (0, {"linhas": []}))[1]["linhas"], hoje, lido_em=lido_em,
                hotmart=coletas.get("hotmart", (0, {"linhas": []}))[1]["linhas"])
    r["alertas"] = avisos + r["alertas"]
    texto = resumo_semanal(r)
    print("=== RESUMO DA SEMANA (só números; é o que vai para o canal) ===")
    print(texto)
    if r["alertas"]:
        print("\n=== ALERTAS (só no chat) ===")
        print("\n".join("- " + a for a in r["alertas"]))
    if not args.sem_gravar:
        _gravar_semanal(pasta, r, texto)
        for caminho, _, _ in coletas.values():
            _guardar_coleta(caminho, pasta)
        print("\nGravado em %s: historico_semanal.csv, relatorios/semana-%s.md e leituras/."
              % (pasta, r["inicio"].isoformat()))


def _cmd_anual(args):
    config = Path(args.config).resolve()
    pasta = config.parent
    cfg = preparar_config(json.loads(config.read_text(encoding="utf-8")))
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    coletas = {}
    for prefixo, plataforma in (("voomp", "voomp"), ("tmbapi", "tmb"), ("hotmart", "hotmart")):
        if plataforma in cfg["plataformas"]:
            caminho = _ultima_coleta(pasta, prefixo)
            if not caminho:
                raise SystemExit("Falta a coleta %s em %s/leituras." % (prefixo, pasta))
            coletas[plataforma] = _carregar_coleta(caminho, plataforma)
    lido = max(_data(c["coletado_em"], fuso, sem_fuso_e_utc=True) for c in coletas.values())
    ate = dt.date.fromisoformat(args.ate) if args.ate else lido.date() - dt.timedelta(days=1)
    r = anual(cfg, (coletas.get("voomp") or {}).get("linhas", []), (coletas.get("tmb") or {}).get("linhas", []),
              args.ano or ate.year, ate, hotmart=(coletas.get("hotmart") or {}).get("linhas", []))
    print(resumo_anual(r))
    if args.json:
        def limpo(x):
            if isinstance(x, dict):
                return {k: limpo(v) for k, v in x.items()}
            if isinstance(x, (list, tuple)):
                return [limpo(v) for v in x]
            return x.isoformat() if isinstance(x, dt.date) else x
        Path(args.json).write_text(json.dumps(limpo(r), ensure_ascii=False, indent=1), encoding="utf-8")
        print("\nJSON em %s" % args.json)


def _carregar_carteira(config):
    """Config da carteira e a última coleta de cada plataforma, com os avisos de coleta."""
    pasta = config.parent
    cfg = preparar_config(json.loads(config.read_text(encoding="utf-8")))
    if cfg.get("tipo") != "carteira":
        raise SystemExit("Este comando lê o config da carteira (\"tipo\": \"carteira\"), não o de um projeto.")
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    agora = dt.datetime.now(fuso)
    coletas, avisos = {}, []
    for prefixo, plataforma in (("voomp", "voomp"), ("tmbapi", "tmb"), ("hotmart", "hotmart")):
        if plataforma not in cfg["plataformas"]:
            continue
        caminho = _ultima_coleta(pasta, prefixo)
        if not caminho:
            raise SystemExit("Falta a coleta %s em %s/leituras." % (prefixo, pasta))
        coleta = _carregar_coleta(caminho, plataforma)
        lida = _data(coleta["coletado_em"], fuso, sem_fuso_e_utc=True)
        if agora - lida > COLETA_VELHA:
            avisos.append("A coleta da %s é de %s; colete de novo antes de fechar a semana."
                          % (NOME_PLATAFORMA[plataforma], _quando(lida)))
        avisos.extend(avisos_da_coleta(cfg, plataforma, coleta))
        coletas[plataforma] = coleta
    lido_em = max(_data(c["coletado_em"], fuso, sem_fuso_e_utc=True) for c in coletas.values())
    linhas = {p: (coletas.get(p) or {}).get("linhas", []) for p in PLATAFORMAS}
    return cfg, linhas, lido_em, avisos


CLICKUP_API = "https://api.clickup.com/api/v2/"


def precisa_finalizar(vencimento, status, hoje, status_fim="finalizada"):
    """A call da semana passada ainda aberta é finalizada; a recorrência traz a task para a próxima segunda."""
    return bool(vencimento) and vencimento < hoje and (status or "").lower() != status_fim.lower()


def anexar_na_call(call, pdf, token, hoje):
    """Anexa o PDF na call de sócios da semana no ClickUp (finaliza antes a call vencida). Devolve um resumo."""
    tarefa, status_fim = call["tarefa"], call.get("status_fim") or "finalizada"

    def pedir(metodo, caminho, corpo=None):
        dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        req = urllib.request.Request(CLICKUP_API + caminho, data=dados, method=metodo,
                                     headers={"Authorization": token.strip(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resposta:
            return json.loads(resposta.read().decode("utf-8") or "{}")

    def vence(t):
        return dt.datetime.fromtimestamp(int(t["due_date"]) / 1000).date() if t.get("due_date") else None

    t = pedir("GET", "task/%s" % tarefa)
    feito = []
    if precisa_finalizar(vence(t), (t.get("status") or {}).get("status"), hoje, status_fim):
        pedir("PUT", "task/%s" % tarefa, {"status": status_fim})
        feito.append("finalizei a call de %s" % vence(t).strftime("%d/%m"))
        t = pedir("GET", "task/%s" % tarefa)
    if pdf.name in [a.get("title") for a in t.get("attachments") or []]:
        feito.append("o PDF já estava anexado")
    else:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST",
                            CLICKUP_API + "task/%s/attachment" % tarefa, "-H", "Authorization: " + token.strip(),
                            "-F", 'attachment=@"%s";type=application/pdf' % pdf], capture_output=True, text=True)
        if r.stdout.strip() != "200":
            raise SystemExit("O ClickUp recusou o anexo (HTTP %s)." % r.stdout.strip())
        feito.append("anexei %s" % pdf.name)
    data = vence(t)
    return "Call de sócios (%s, %s): %s." % (t.get("name"), data.strftime("%d/%m") if data else "sem data",
                                           "; ".join(feito))


def comentar_link_na_call(call, token, rotulo):
    """Comenta na call de sócios o link da apresentação (página que abre no navegador), uma vez por semana."""
    link = call.get("link_deck")
    if not link:
        return "sem link_deck no config"
    tarefa = call["tarefa"]
    req = urllib.request.Request(CLICKUP_API + "task/%s/comment" % tarefa, headers={"Authorization": token.strip()})
    with urllib.request.urlopen(req, timeout=60) as resposta:
        comentarios = json.loads(resposta.read().decode("utf-8")).get("comments") or []
    if any(rotulo in (c.get("comment_text") or "") and link in (c.get("comment_text") or "") for c in comentarios):
        return "o link desta semana já estava comentado"
    texto = ("Apresentação de vendas · %s (abre no navegador): %s\n"
             "PDF anexado nesta task. O link é sempre o mesmo e mostra a revisão mais recente." % (rotulo, link))
    corpo = json.dumps({"comment_text": texto, "notify_all": False}).encode("utf-8")
    req = urllib.request.Request(CLICKUP_API + "task/%s/comment" % tarefa, data=corpo, method="POST",
                                 headers={"Authorization": token.strip(), "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=60).read()
    return "comentei o link da apresentação"


def _modulo_deck():
    import importlib.util
    spec = importlib.util.spec_from_file_location("deck_vendas", AQUI / "deck_vendas.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _cmd_deck(args):
    config = Path(args.config).resolve()
    cfg, l, lido_em, avisos = _carregar_carteira(config)
    hoje = dt.date.fromisoformat(args.hoje) if args.hoje else lido_em.date()
    comum = dict(lido_em=lido_em, hotmart=l["hotmart"], parcial=args.parcial)
    r = semanal(cfg, l["voomp"], l["tmb"], hoje, **comum)
    r_ant = semanal(cfg, l["voomp"], l["tmb"], hoje - dt.timedelta(days=7) if args.parcial else r["inicio"], **comum)
    ra = anual(cfg, l["voomp"], l["tmb"], r["fim"].year, r["fim"], hotmart=l["hotmart"])
    dados = dados_deck(cfg, r, r_ant, ra)
    dados["alertas"] = avisos + dados["alertas"]
    nome = "vendas-semana-%s" % r["inicio"].isoformat() + ("-parcial-%s" % hoje.isoformat() if args.parcial else "")
    destino = Path(args.saida) if args.saida else Path(args.raiz) / "presentations" / nome
    deck = _modulo_deck()
    cons = Path(args.consideracoes) if args.consideracoes else config.parent / "consideracoes" / ("%s.md" % r["inicio"].isoformat())
    pdf = deck.gerar(dados, destino, modulos=args.modulos, exportar=not args.sem_pdf,
                     consideracoes=cons if cons.exists() else None)
    if cons.exists():
        print("Considerações: %s" % cons)
    if not (args.parcial or args.sem_gravar):
        _gravar_semanal(config.parent, r, resumo_semanal(r))
    if args.clickup and pdf:
        call = (cfg.get("entrega") or {}).get("call_socios")
        token = os.environ.get("CLICKUP_TOKEN")
        if not call or not token:
            raise SystemExit("Para --clickup: entrega.call_socios no config e CLICKUP_TOKEN=$(security "
                             "find-generic-password -s clickup-exos-api -w).")
        print(anexar_na_call(call, Path(pdf), token, dt.date.today()))
        rotulo = "semana %s a %s" % (r["inicio"].strftime("%d/%m"), r["fim"].strftime("%d/%m"))
        print("Call de sócios: %s." % comentar_link_na_call(call, token, rotulo))
    if args.web:
        pagina, arquivos = deck.gerar_web(destino)
        print("Web: %s (%d arquivos em %s/artifact-files.json); publicar no link_deck com a ferramenta Artifact."
              % (pagina, len(arquivos), destino))
    print(resumo_semanal(r))
    if dados["alertas"]:
        print("\n=== ALERTAS (só no chat) ===")
        print("\n".join("- " + a for a in dados["alertas"]))
    print("\nDeck: %s/slides.md%s" % (destino, "\nPDF: %s" % pdf if pdf else ""))
    print("Abrir: cd \"%s\" && npm run dev" % destino)


def _cmd_hotmart_api(args):
    config = Path(args.config).resolve()
    cfg = preparar_config(json.loads(config.read_text(encoding="utf-8")))
    bruto = os.environ.get("HOTMART_CRED")
    if not bruto:
        raise SystemExit("Falta a credencial: HOTMART_CRED=$(security find-generic-password -s %s -w) python3 ..."
                         % KEYCHAIN_HOTMART)
    coleta = coletar_hotmart_api(cfg, json.loads(bruto))
    if coleta.get("erro"):
        raise SystemExit("A API da Hotmart respondeu com erro: %s" % coleta["erro"])
    fuso = ZoneInfo(cfg.get("fuso") or "America/Sao_Paulo")
    destino = Path(args.saida) if args.saida else config.parent / "leituras" / (
        "hotmart-%s.json" % dt.datetime.now(fuso).strftime("%Y-%m-%d_%H%M"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(coleta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("%d vendas lidas da API da Hotmart (total informado: %d) -> %s"
          % (len(coleta["linhas"]), coleta["total_api"], destino))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="comando", required=True)

    listar = sub.add_parser("listar", help="projetos configurados")
    listar.add_argument("--raiz", type=Path, default=RAIZ_PADRAO)
    listar.set_defaults(func=_cmd_listar)

    coletor = sub.add_parser("coletor", help="JavaScript de coleta de uma plataforma")
    coletor.add_argument("--config", required=True)
    coletor.add_argument("--plataforma", required=True, choices=PLATAFORMAS)
    coletor.set_defaults(func=_cmd_coletor)

    descobrir = sub.add_parser("descobrir", help="JavaScript que lista produtos, ofertas e afiliados")
    descobrir.add_argument("--plataforma", required=True, choices=PLATAFORMAS)
    descobrir.add_argument("--busca", required=True, help="trecho do nome do produto, como 'Oncol'")
    descobrir.add_argument("--dias", type=int, default=30, help="vendas dos últimos N dias")
    descobrir.set_defaults(func=_cmd_descobrir)

    tmb_api = sub.add_parser("tmb-api", help="lê os efetivados da TMB pela API oficial, sem login")
    tmb_api.add_argument("--config", required=True)
    tmb_api.add_argument("--saida", help="arquivo de saída (padrão: leituras/tmbapi-AAAA-MM-DD_HHMM.json)")
    tmb_api.set_defaults(func=_cmd_tmb_api)

    dk = sub.add_parser("deck", help="deck da revisão de vendas por expert (semana, mês e ano), com PDF")
    dk.add_argument("--config", required=True, help="config da carteira (tipo carteira)")
    dk.add_argument("--parcial", action="store_true", help="semana em andamento (segunda até hoje), para avaliação no meio da semana")
    dk.add_argument("--hoje", help="AAAA-MM-DD (padrão: o dia da coleta)")
    dk.add_argument("--saida", help="pasta do deck (padrão: <raiz>/presentations/vendas-semana-<segunda>)")
    dk.add_argument("--raiz", default=str(RAIZ_PADRAO))
    dk.add_argument("--modulos", help="node_modules de um deck Slidev pronto para clonar (padrão: o último deck de vendas)")
    dk.add_argument("--sem-pdf", action="store_true", help="não exporta o PDF")
    dk.add_argument("--sem-gravar", action="store_true", help="não grava historico_semanal.csv nem relatorios/")
    dk.add_argument("--clickup", action="store_true", help="anexa o PDF e comenta o link na call de sócios (entrega.call_socios do config)")
    dk.add_argument("--web", action="store_true", help="gera também a versão para o navegador em artifact/ (para publicar no link_deck)")
    dk.add_argument("--consideracoes", help=".md com os pontos para discutir (padrão: consideracoes/<segunda>.md da carteira)")
    dk.set_defaults(func=_cmd_deck)

    hot = sub.add_parser("hotmart-api", help="lê as vendas da Hotmart pela API oficial, sem login")
    hot.add_argument("--config", required=True)
    hot.add_argument("--saida", help="arquivo de saída (padrão: leituras/hotmart-AAAA-MM-DD_HHMM.json)")
    hot.set_defaults(func=_cmd_hotmart_api)

    an = sub.add_parser("analisar", help="aplica as regras e imprime o relatório")
    an.add_argument("--config", required=True)
    an.add_argument("--voomp", help="coleta da Voomp (padrão: a última em leituras/)")
    an.add_argument("--tmb", help="coleta do portal da TMB (padrão: a última em leituras/)")
    an.add_argument("--tmb-api", dest="tmb_api", help="coleta da API da TMB (padrão: a última em leituras/)")
    an.add_argument("--agora", help="momento da leitura, ISO (padrão: o da coleta)")
    an.add_argument("--corte", help="conta como se fosse este momento, ISO; não grava nada")
    an.add_argument("--sem-gravar", action="store_true", help="não mexe em historico.csv nem em pendentes.csv")
    an.set_defaults(func=_cmd_analisar)

    sem = sub.add_parser("semanal", help="semana fechada e mês de cada produto da carteira")
    sem.add_argument("--config", required=True, help="config da carteira (tipo carteira)")
    sem.add_argument("--hoje", help="AAAA-MM-DD; a semana é a última fechada antes deste dia (padrão: o da coleta)")
    sem.add_argument("--sem-gravar", action="store_true", help="não grava histórico nem relatório")
    sem.set_defaults(func=_cmd_semanal)

    an_ = sub.add_parser("anual", help="mês a mês do ano de cada produto da carteira")
    an_.add_argument("--config", required=True, help="config da carteira (tipo carteira)")
    an_.add_argument("--ano", type=int, help="padrão: o ano de --ate")
    an_.add_argument("--ate", help="AAAA-MM-DD, último dia contado (padrão: a véspera da coleta)")
    an_.add_argument("--json", help="grava o resultado em JSON (para deck ou planilha)")
    an_.set_defaults(func=_cmd_anual)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
