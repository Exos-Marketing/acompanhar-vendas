#!/usr/bin/env python3
"""Testes do motor de contagem da skill acompanhar-vendas.

Rodar na pasta scripts/:  python3 -m unittest -v test_vendas

Os casos são os que apareceram na Black ONCO+ de out/26 (aluna nas duas plataformas, cobrança em
dobro, mensalidade de assinatura, oferta de outra fase), com identificadores inventados.
"""
import copy
import datetime as dt
import itertools
import unittest
from zoneinfo import ZoneInfo

import vendas

TZ = ZoneInfo("America/Sao_Paulo")
_ids = itertools.count(1000)

CFG = {
    "projeto": "[XX][BF][POS][OUT][26]",
    "titulo": "Black Teste",
    "fuso": "America/Sao_Paulo",
    "plataformas": {
        "voomp": {
            "produtos": {"100": "avulso", "200": "recorrência"},
            "assinatura": [200],
            "comercial": {"afiliados": [9]},
            "coletar_desde": "2026-01-01",
        },
        "tmb": {
            "produtos": {"300": "C/Comercial", "301": "S/Comercial"},
            "comercial": {"produtos": [300]},
        },
    },
    "fases": [
        {"id": "F1", "nome": "Fase 1", "conta_na_meta": False,
         "ofertas": {"voomp": [11], "tmb": ["Oferta F1"]}},
        {"id": "F2", "nome": "Fase 2", "conta_na_meta": True,
         "inicio": "2026-10-07T20:00:00", "fim": "2026-10-16T23:59:59"},
    ],
    "meta": {"total": 82},
}

REGUA = {"2026-10-09": 58, "2026-10-10": 59, "2026-10-11": 60, "2026-10-12": 62,
         "2026-10-13": 66, "2026-10-14": 72, "2026-10-15": 76, "2026-10-16": 82}


def brt(texto):
    """'2026-10-08 15:00' em horário de Brasília."""
    return dt.datetime.strptime(texto, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


def utc_iso(texto):
    """Horário de Brasília -> ISO em UTC, que é como a Voomp devolve as datas."""
    if texto is None:
        return None
    return brt(texto).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


AGORA = brt("2026-10-10 15:50")


def cfg(**troca):
    c = copy.deepcopy(CFG)
    c.update(troca)
    return c


def voomp(pago=None, criado=None, status="paid", doc="doc-a", email=None, produto=100, oferta=20,
          metodo="CREDIT_CARD", valor=3897, afiliado=None, contrato=None, vencimento=None,
          nome=None, telefone=None, email_claro=None, id=None):
    return {
        "id": id or next(_ids), "produto_id": produto, "oferta_id": oferta, "oferta": "Oferta %s" % oferta,
        "status": status, "metodo": metodo, "parcelas": 1, "valor": valor, "total": valor if pago else 0,
        "criado": utc_iso(criado or pago), "pago": utc_iso(pago), "vencimento": vencimento,
        "afiliado_id": afiliado, "afiliado": "Comercial" if afiliado else None, "contrato_id": contrato,
        "h_doc": doc, "h_email": email, "nome": nome, "telefone": telefone, "email": email_claro,
    }


def tmb(efetivado=None, criado_dia=None, status_id=8, doc="doc-a", email=None, produto=301,
        oferta="Oferta Black", valor=4297, nome=None, telefone=None, email_claro=None, id=None, criado=None):
    nomes = {8: "Efetivado", 10: "Boleto Gerado", 7: "Aguardando Assinatura", 0: "Cancelado",
             23: "Cancelamento Solicitado"}
    return {
        "id": id or next(_ids), "produto_id": produto, "oferta": oferta, "status_id": status_id,
        "status": nomes.get(status_id, "Status %s" % status_id), "valor": valor,
        "efetivado": efetivado and brt(efetivado).strftime("%Y-%m-%dT%H:%M:%S.000000"),
        "criado_dia": criado_dia, "cancelamento": None,
        "criado": criado and brt(criado).strftime("%Y-%m-%dT%H:%M:%S"),
        "h_doc": doc, "h_email": email, "nome": nome, "telefone": telefone, "email": email_claro,
    }


def analisar(v=(), t=(), config=None, **kw):
    kw.setdefault("agora", AGORA)
    return vendas.analisar(config or cfg(), list(v), list(t), **kw)


def da_meta(r):
    return [p for p in r["pendentes"] if p["conta_na_meta"]]


class Contagem(unittest.TestCase):
    def test_aluna_nas_duas_plataformas_conta_uma(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1")],
                     [tmb(efetivado="2026-10-09 11:00", doc="d1")])
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["por_plataforma"], {"voomp": 1, "tmb": 0})  # vale onde pagou primeiro

    def test_aluna_nas_duas_plataformas_vira_alerta(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1")],
                     [tmb(efetivado="2026-10-09 11:00", doc="d1")])
        self.assertTrue(any("duas plataformas" in a for a in r["alertas"]), r["alertas"])

    def test_mesmo_cpf_com_emails_diferentes_e_a_mesma_aluna(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1", email="e1", produto=100),
                      voomp(pago="2026-10-09 10:00", doc="d1", email="e2", produto=100)])
        self.assertEqual(r["total"], 1)

    def test_mesmo_email_sem_cpf_e_a_mesma_aluna(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc=None, email="e1")],
                     [tmb(efetivado="2026-10-09 10:00", doc="d9", email="e1")])
        self.assertEqual(r["total"], 1)

    def test_cobranca_em_dobro_conta_uma(self):
        r = analisar([voomp(pago="2026-10-08 04:09", doc="d1"), voomp(pago="2026-10-08 04:11", doc="d1")])
        self.assertEqual(r["total"], 1)

    def test_cobranca_em_dobro_vira_alerta(self):
        r = analisar([voomp(pago="2026-10-08 04:09", doc="d1"), voomp(pago="2026-10-08 04:11", doc="d1")])
        self.assertTrue(any("em dobro" in a for a in r["alertas"]), r["alertas"])

    def test_renovacao_de_assinatura_nao_conta(self):
        r = analisar([voomp(pago="2026-09-08 01:05", produto=200, contrato=77, doc="d1"),
                      voomp(pago="2026-10-08 01:05", produto=200, contrato=77, doc="d1")])
        self.assertEqual(r["total"], 0)

    def test_primeira_cobranca_de_assinatura_conta(self):
        r = analisar([voomp(pago="2026-10-08 11:47", produto=200, contrato=88, doc="d1", valor=389.7)])
        self.assertEqual(r["total"], 1)

    def test_oferta_de_outra_fase_fica_fora_da_meta(self):
        r = analisar([voomp(pago="2026-10-09 14:00", oferta=11, doc="d1")],
                     [tmb(efetivado="2026-10-09 14:09", oferta="Oferta F1", doc="d2")])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["fases"]["F1"]["matriculas"], 2)

    def test_reembolso_sai_da_conta(self):
        r = analisar([voomp(pago="2026-10-08 12:29", status="refunded", doc="d1")])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["saidas"]["reembolsos"], 1)

    def test_cancelamento_na_tmb_sai_da_conta(self):
        r = analisar(t=[tmb(efetivado="2026-10-08 09:00", status_id=23, doc="d1")])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["saidas"]["cancelamentos"], 1)

    def test_dia_do_pagamento_e_o_de_brasilia(self):
        # 23h30 de sábado em Brasília já é domingo em UTC
        r = analisar([voomp(pago="2026-10-10 23:30", doc="d1")], agora=brt("2026-10-11 09:00"))
        self.assertEqual(r["por_dia"], {"2026-10-10": 1})

    def test_pagamento_antes_da_abertura_nao_conta(self):
        r = analisar([voomp(pago="2026-10-07 12:29", doc="d1")])
        self.assertEqual(r["total"], 0)

    def test_vendas_pelo_comercial(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1", afiliado=9),
                      voomp(pago="2026-10-08 11:00", doc="d3")],
                     [tmb(efetivado="2026-10-08 12:00", doc="d2", produto=300)])
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["comercial"], 2)

    def test_produto_comercial_so_conta_a_partir_de_produtos_desde(self):
        # a página usou o link do produto comercial até 12h30; depois disso ele é só do time
        c = cfg()
        c["plataformas"]["tmb"]["comercial"]["produtos_desde"] = "2026-10-08T12:30:00"
        r = analisar([], [tmb(efetivado="2026-10-08 12:00", doc="d1", produto=300),
                          tmb(efetivado="2026-10-08 13:00", doc="d2", produto=300),
                          tmb(efetivado="2026-10-08 14:00", doc="d3", produto=301)], config=c)
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["comercial"], 1)

    def test_produtos_desde_olha_a_criacao_do_pedido_quando_a_tmb_traz(self):
        # boleto gerado pela página às 12h, efetivado às 15h: o link foi o público, não é do comercial
        c = cfg()
        c["plataformas"]["tmb"]["comercial"]["produtos_desde"] = "2026-10-08T12:30:00"
        r = analisar([], [tmb(efetivado="2026-10-08 15:00", criado="2026-10-08 12:00", doc="d1", produto=300),
                          tmb(efetivado="2026-10-08 15:00", criado="2026-10-08 13:00", doc="d2", produto=300)],
                     config=c)
        self.assertEqual(r["comercial"], 1)

    def test_detalhe_por_produto_na_tmb_e_por_forma_de_pagamento_na_voomp(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1"),
                      voomp(pago="2026-10-08 11:00", doc="d2", metodo="PIX"),
                      voomp(pago="2026-10-09 16:15", doc="d3", metodo="BOLETO")],
                     [tmb(efetivado="2026-10-08 12:00", doc="d4", produto=300),
                      tmb(efetivado="2026-10-08 13:00", doc="d5", produto=301)])
        self.assertEqual(r["detalhe"]["voomp"], {"cartão": 1, "Pix": 1, "boleto": 1})
        self.assertEqual(r["detalhe"]["tmb"], {"C/Comercial": 1, "S/Comercial": 1})

    def test_corte_ignora_pagamentos_posteriores(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1"), voomp(pago="2026-10-10 10:00", doc="d2")],
                     corte=brt("2026-10-08 23:59"))
        self.assertEqual(r["total"], 1)

    def test_item_ignorado_sai_da_conta(self):
        config = cfg(ignorar=[{"plataforma": "voomp", "id": 5001, "motivo": "teste da equipe"}])
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1", id=5001)], config=config)
        self.assertEqual(r["total"], 0)

    def test_status_desconhecido_vira_alerta_e_nao_conta(self):
        r = analisar([voomp(pago="2026-10-08 10:00", status="em_disputa", doc="d1")])
        self.assertEqual(r["total"], 0)
        self.assertTrue(any("em_disputa" in a for a in r["alertas"]), r["alertas"])

    def test_hoje_conta_so_as_matriculas_do_dia(self):
        r = analisar([voomp(pago="2026-10-09 10:00", doc="d1"), voomp(pago="2026-10-10 11:40", doc="d2")])
        self.assertEqual(r["hoje"], 1)


class Pendentes(unittest.TestCase):
    def test_boleto_aberto_de_quem_nao_pagou_aparece(self):
        r = analisar([voomp(criado="2026-10-09 15:11", status="waiting_payment", metodo="BOLETO",
                            vencimento="2026-10-12", doc="d5", nome="Fulana Teste",
                            telefone="+5511999990000")])
        self.assertEqual(len(r["pendentes"]), 1)
        p = r["pendentes"][0]
        self.assertEqual(p["tipo"], "voomp_boleto")
        self.assertEqual(p["vencimento"], dt.date(2026, 10, 12))
        self.assertEqual(p["nome"], "Fulana Teste")
        self.assertEqual(p["fase"], "F2")

    def test_quem_pagou_por_outro_meio_nao_aparece(self):
        r = analisar([voomp(criado="2026-10-09 19:51", status="waiting_payment", metodo="BOLETO", doc="d5")],
                     [tmb(efetivado="2026-10-10 11:59", doc="d5", produto=300)])
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["pendentes"], [])

    def test_boleto_vencido_e_marcado(self):
        r = analisar([voomp(criado="2026-10-08 10:00", status="waiting_payment", metodo="BOLETO",
                            vencimento="2026-10-09", doc="d5")])
        self.assertEqual(r["pendentes"][0]["tipo"], "voomp_boleto_vencido")

    def test_boleto_que_vence_hoje_ainda_esta_aberto(self):
        r = analisar([voomp(criado="2026-10-08 10:00", status="waiting_payment", metodo="BOLETO",
                            vencimento="2026-10-10", doc="d5")])
        self.assertEqual(r["pendentes"][0]["tipo"], "voomp_boleto")

    def test_pix_nao_pago_aparece_como_pix(self):
        r = analisar([voomp(criado="2026-10-09 11:30", status="waiting_payment", metodo="PIX", doc="d5")])
        self.assertEqual(r["pendentes"][0]["tipo"], "voomp_pix")

    def test_so_cartao_recusado_aparece_como_recusado(self):
        r = analisar([voomp(criado="2026-10-08 08:53", status="refused", doc="d5"),
                      voomp(criado="2026-10-08 08:54", status="refused", doc="d5"),
                      voomp(criado="2026-10-08 16:24", status="refused", doc="d5")])
        self.assertEqual([p["tipo"] for p in r["pendentes"]], ["voomp_recusado"])

    def test_boleto_gerado_na_tmb_criado_na_janela_aparece(self):
        r = analisar(t=[tmb(status_id=10, criado_dia="2026-10-07", doc="d5")])
        self.assertEqual([p["tipo"] for p in r["pendentes"]], ["tmb_boleto"])

    def test_boleto_gerado_na_tmb_sem_data_na_janela_nao_aparece(self):
        # pedido antigo: a coleta só informa o dia de criação de quem nasceu na janela
        r = analisar(t=[tmb(status_id=10, criado_dia=None, doc="d5", nome="Pedido Antigo"),
                        tmb(status_id=10, criado_dia="2026-10-07", doc="d6", nome="Pedido Novo")])
        self.assertEqual([p["nome"] for p in r["pendentes"]], ["Pedido Novo"])

    def test_mensalidade_de_assinatura_em_aberto_nao_e_pendente(self):
        r = analisar([voomp(pago="2026-09-08 01:05", produto=200, contrato=77, doc="d1"),
                      voomp(criado="2026-10-08 01:08", status="waiting_payment", metodo="BOLETO",
                            produto=200, contrato=77, doc="d1")])
        self.assertEqual(r["pendentes"], [])
        self.assertEqual(r["mensalidades_abertas"], 1)

    def test_varios_boletos_da_mesma_pessoa_contam_uma_pessoa(self):
        linhas = [voomp(criado="2026-10-07 21:32", status="waiting_payment", metodo="BOLETO",
                        vencimento=v, doc="d5") for v in ("2026-10-10", "2026-10-11", "2026-10-12")]
        r = analisar(linhas)
        self.assertEqual(len(r["pendentes"]), 1)
        self.assertEqual(r["pendentes"][0]["vencimento"], dt.date(2026, 10, 12))

    def test_pendente_criado_antes_da_abertura_nao_aparece(self):
        r = analisar([voomp(criado="2026-10-07 12:02", status="waiting_payment", metodo="BOLETO",
                            doc="d5", nome="Antes da Abertura"),
                      voomp(criado="2026-10-07 21:33", status="waiting_payment", metodo="BOLETO",
                            doc="d6", nome="Depois da Abertura")])
        self.assertEqual([p["nome"] for p in r["pendentes"]], ["Depois da Abertura"])

    def test_pendente_de_oferta_de_outra_fase_nao_entra_na_meta(self):
        r = analisar([voomp(criado="2026-10-06 23:50", status="waiting_payment", metodo="BOLETO",
                            oferta=11, doc="d5")])
        self.assertEqual([p["fase"] for p in r["pendentes"]], ["F1"])
        self.assertEqual(da_meta(r), [])
        self.assertEqual(r["fases"]["F1"]["pendentes"], 1)


class Regua(unittest.TestCase):
    def feitas(self):
        ate_sexta = [voomp(pago="2026-10-08 10:%02d" % (i % 60), doc="a%d" % i) for i in range(58)]
        hoje = [voomp(pago="2026-10-10 11:%02d" % i, doc="b%d" % i) for i in range(4)]
        return ate_sexta + hoje

    def test_meta_do_dia_saldo_e_projecao(self):
        r = analisar(self.feitas(), config=cfg(meta={"total": 82, "acumulada": REGUA}))
        self.assertEqual(r["total"], 62)
        regua = r["regua"]
        self.assertEqual(regua["meta_dia"], 1)
        self.assertEqual(regua["feitas_hoje"], 4)
        self.assertEqual(regua["meta_acumulada"], 59)
        self.assertEqual(regua["saldo"], 3)
        self.assertEqual(regua["projecao"], 85)  # 62 + o que a régua pede de domingo a sexta (23)

    def test_dia_atrasado_entra_na_projecao(self):
        # sábado sem nenhuma venda: a projeção ainda conta com a meta de hoje
        r = analisar(self.feitas()[:58], config=cfg(meta={"total": 82, "acumulada": REGUA}))
        self.assertEqual(r["regua"]["saldo"], -1)
        self.assertEqual(r["regua"]["projecao"], 82)

    def test_sem_regua_mostra_ritmo_necessario(self):
        r = analisar(self.feitas())
        self.assertIsNone(r["regua"])
        self.assertEqual(r["ritmo"]["faltam"], 20)
        self.assertEqual(r["ritmo"]["dias"], 7)  # de sábado 10 a sexta 16

    def test_meta_batida_nao_fica_negativa(self):
        r = analisar(self.feitas(), config=cfg(meta={"total": 60}))
        self.assertEqual(r["faltam"], 0)


class Textos(unittest.TestCase):
    def leitura(self):
        return analisar([voomp(pago="2026-10-10 11:40", doc="d1"),
                         voomp(criado="2026-10-09 15:11", status="waiting_payment", metodo="BOLETO",
                               vencimento="2026-10-12", doc="d5", nome="Fulana Teste",
                               telefone="+5511999990000", email_claro="fulana@teste.com")])

    def test_resumo_do_canal_nao_leva_dados_pessoais(self):
        texto = vendas.resumo_canal(self.leitura(), cfg())
        self.assertIn("Aguardando pagamento: 1", texto)  # a pessoa entra na conta, sem ser identificada
        for dado in ("Fulana", "+5511999990000", "fulana@teste.com"):
            self.assertNotIn(dado, texto)

    def test_resumo_do_canal_traz_efetivadas_meta_e_pendentes(self):
        texto = vendas.resumo_canal(self.leitura(), cfg())
        self.assertIn("Black Teste", texto)
        self.assertIn("1 de 82", texto)
        self.assertIn("faltam 81", texto)
        self.assertIn("Aguardando pagamento: 1", texto)

    def test_relatorio_do_chat_lista_quem_esta_aguardando(self):
        texto = vendas.relatorio_chat(self.leitura(), cfg())
        self.assertIn("Fulana Teste", texto)
        self.assertIn("12/10", texto)

    def test_parcela_mensal_de_assinatura_nao_aparece_nos_textos(self):
        # o Cleber só quer as informações da campanha: mensalidade de quem já é aluna fica fora
        r = analisar([voomp(pago="2026-09-08 01:05", produto=200, contrato=77, doc="d1"),
                      voomp(criado="2026-10-08 01:08", status="waiting_payment", metodo="BOLETO",
                            produto=200, contrato=77, doc="d1", vencimento="2026-10-18")])
        self.assertEqual(r["mensalidades_abertas"], 1)
        for texto in (vendas.resumo_canal(r, cfg()), vendas.relatorio_chat(r, cfg())):
            for termo in ("ensalidade", "ssinatura", "ecorrência", "Parcelas mensais"):
                self.assertNotIn(termo, texto)

    def test_resumo_mostra_o_que_mudou_desde_a_leitura_anterior(self):
        anterior = {"lido_em": "2026-10-10T13:03:00-03:00", "total": 0}
        texto = vendas.resumo_canal(self.leitura(), cfg(), anterior=anterior)
        self.assertIn("+1 desde as 13h03", texto)


class PostarNoCanal(unittest.TestCase):
    """Só vai para o canal a leitura em que o número de efetivadas mudou."""

    def leitura(self, quantas):
        return analisar([voomp(pago="2026-10-08 10:%02d" % i, doc="d%d" % i) for i in range(quantas)])

    def anterior(self, total):
        return {"lido_em": "2026-10-10T07:03:00-03:00", "total": str(total)}

    def test_primeira_leitura_do_projeto_vai_para_o_canal(self):
        self.assertTrue(vendas.deve_postar(self.leitura(2), None))

    def test_mesmo_numero_de_efetivadas_nao_vai_para_o_canal(self):
        self.assertFalse(vendas.deve_postar(self.leitura(2), self.anterior(2)))

    def test_venda_nova_vai_para_o_canal(self):
        self.assertTrue(vendas.deve_postar(self.leitura(3), self.anterior(2)))

    def test_matricula_que_saiu_da_conta_tambem_vai_para_o_canal(self):
        self.assertTrue(vendas.deve_postar(self.leitura(1), self.anterior(2)))

    def test_mudanca_so_em_quem_esta_aguardando_nao_vai_para_o_canal(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1"),
                      voomp(criado="2026-10-09 15:11", status="waiting_payment", metodo="BOLETO", doc="d5")])
        self.assertEqual(len(r["pendentes"]), 1)
        self.assertFalse(vendas.deve_postar(r, self.anterior(1)))


class ResumoDoPlano(unittest.TestCase):
    """O resumo abre dizendo se o projeto está dentro do plano, com um placar por dia."""

    CALENDARIO = {"2026-10-11": "anúncio do sorteio, 19h", "2026-10-13": "live, 20h"}

    def config(self):
        return cfg(meta={"total": 82, "acumulada": REGUA}, calendario=self.CALENDARIO)

    def resumo(self, pagas_por_dia, agora):
        """pagas_por_dia: {"2026-10-08": 58, "2026-10-10": 4} vira uma aluna paga por unidade."""
        linhas = []
        for dia, quantas in pagas_por_dia.items():
            linhas += [voomp(pago="%s 08:%02d" % (dia, i % 60), doc="%s-%d" % (dia, i)) for i in range(quantas)]
        r = analisar(linhas, config=self.config(), agora=brt(agora))
        return vendas.resumo_canal(r, self.config())

    def test_titulos_das_secoes_saem_em_negrito(self):
        texto = self.resumo({"2026-10-08": 58, "2026-10-10": 4}, "2026-10-10 16:41")
        for titulo in ("**Vendas Black Teste · sáb 10/10, 16h41**", "**Estamos no plano?**",
                       "**Plano dia a dia**", "**Onde vendeu**", "**Aguardando pagamento: 0 pessoas**"):
            self.assertIn(titulo, texto)

    def test_a_posicao_no_plano_vem_antes_do_resto(self):
        texto = self.resumo({"2026-10-08": 58, "2026-10-10": 4}, "2026-10-10 16:41")
        self.assertLess(texto.index("**Estamos no plano?**"), texto.index("**Onde vendeu**"))

    def test_meta_de_hoje_batida_diz_sim_e_quanto_esta_a_frente(self):
        texto = self.resumo({"2026-10-08": 58, "2026-10-10": 4}, "2026-10-10 16:41")
        self.assertIn("Sim. A meta de hoje já está batida: 62 de 59, 3 à frente.", texto)

    def test_dia_em_andamento_dentro_do_plano_diz_quanto_falta_hoje(self):
        # terça de manhã com 63: o plano pedia 62 até segunda e pede 66 até o fim de hoje
        texto = self.resumo({"2026-10-08": 58, "2026-10-11": 5}, "2026-10-13 10:00")
        self.assertIn("Sim, até aqui. Faltam 3 hoje para fechar o dia na meta (63 de 66).", texto)

    def test_atras_do_que_o_plano_pedia_ate_ontem_diz_nao(self):
        texto = self.resumo({"2026-10-08": 58, "2026-10-11": 2}, "2026-10-13 10:00")
        self.assertIn("Não. Estamos 2 atrás do que o plano pedia até ontem (60 de 62).", texto)
        self.assertIn("Para fechar hoje na meta faltam 6.", texto)

    def test_cada_dia_do_plano_mostra_feitas_meta_e_acumulado(self):
        texto = self.resumo({"2026-10-08": 58, "2026-10-10": 4, "2026-10-12": 1}, "2026-10-12 22:03")
        self.assertIn("- sáb 10/10: 4 feitas (meta 1) · acumulado 62 de 59 ✅", texto)
        self.assertIn("- dom 11/10: 0 feitas (meta 1) · acumulado 62 de 60 ✅", texto)
        self.assertIn("- seg 12/10: 1 feita (meta 2) · acumulado 63 de 62 ✅", texto)

    def test_dia_que_fechou_abaixo_da_meta_acumulada_fica_marcado(self):
        texto = self.resumo({"2026-10-08": 58}, "2026-10-11 09:03")
        self.assertIn("- sáb 10/10: 0 feitas (meta 1) · acumulado 58 de 59 ⚠️", texto)

    def test_dia_de_hoje_ainda_abaixo_aparece_como_em_andamento(self):
        texto = self.resumo({"2026-10-08": 58}, "2026-10-11 09:03")
        self.assertIn("- dom 11/10: 0 feitas (meta 1) · acumulado 58 de 60 · em andamento", texto)

    def test_o_foco_do_dia_no_calendario_acompanha_a_linha_de_hoje(self):
        texto = self.resumo({"2026-10-08": 58, "2026-10-11": 5}, "2026-10-13 10:00")
        self.assertIn("· em andamento · live, 20h", texto)

    def test_amanha_mostra_a_meta_e_o_foco_do_dia(self):
        texto = self.resumo({"2026-10-08": 58, "2026-10-10": 4}, "2026-10-10 16:41")
        self.assertIn("- Amanhã, dom 11/10: meta 1 · anúncio do sorteio, 19h", texto)

    def test_projeto_sem_regua_mostra_a_meta_e_o_ritmo(self):
        r = analisar([voomp(pago="2026-10-10 11:40", doc="d1")])
        texto = vendas.resumo_canal(r, cfg())
        self.assertIn("**Meta**", texto)
        self.assertIn("- Efetivadas (Fase 2): 1 de 82, faltam 81", texto)
        self.assertIn("- Ritmo necessário: 11,6 por dia (81 em 7 dias)", texto)
        self.assertNotIn("Estamos no plano?", texto)

    def test_secoes_vem_separadas_por_linha_em_branco(self):
        texto = self.resumo({"2026-10-08": 58, "2026-10-10": 4}, "2026-10-10 16:41")
        self.assertIn("\n\n**Onde vendeu**\n- ", texto)


def pedido_api(pedido_id, efetivado="2026-10-08 10:00", criado="2026-10-07 21:30", status="Efetivado",
               produto=301, valor=4297, documento="111.222.333-44", email="Aluna@Teste.com"):
    """Pedido como a API oficial da TMB devolve em api/pedidos."""
    return {
        "pedido_id": pedido_id, "produto_id": produto, "lancamento": "Pós Teste S/Comercial",
        "status_pedido": status, "cliente": "Aluna Teste", "documento": documento, "email": email,
        "telefone": "+5511999990000", "valor_total": valor,
        "criado_em": brt(criado).strftime("%Y-%m-%dT%H:%M:%S.000000-03:00"),
        "data_efetivado": brt(efetivado).strftime("%Y-%m-%dT%H:%M:%S.000000"),
        "status_financeiro": "Adimplente",
    }


OFERTAS_API = {301: [{"titulo": "Oferta F1", "valor_principal": 3497},
                     {"titulo": "Oferta Black", "valor_principal": 4297},
                     {"titulo": "Oferta Antiga A", "valor_principal": 5997},
                     {"titulo": "Oferta Antiga B", "valor_principal": 5997}]}


class TmbPelaApi(unittest.TestCase):
    """A API oficial lê os efetivados sem login; o portal traz os boletos em aberto e a oferta."""

    def test_hash_e_o_mesmo_dos_coletores_do_navegador(self):
        # SHA-256("abc") começa com ba7816bf8f01; o coletor apara espaços e põe em minúsculas
        self.assertEqual(vendas.hash_id("  ABC "), "ba7816bf8f01")

    def test_hash_do_cpf_ignora_pontuacao(self):
        self.assertEqual(vendas.hash_doc("111.222.333-44"), vendas.hash_id("11122233344"))

    def test_campo_vazio_nao_gera_hash(self):
        self.assertIsNone(vendas.hash_doc(""))
        self.assertIsNone(vendas.hash_id(None))

    def test_pedido_da_api_nao_carrega_dado_pessoal(self):
        linha = vendas.normalizar_tmb_api([pedido_api(900)], OFERTAS_API)[0]
        for campo in ("nome", "telefone", "email"):
            self.assertIsNone(linha[campo])
        self.assertEqual(linha["h_doc"], vendas.hash_doc("111.222.333-44"))
        self.assertEqual(linha["h_email"], vendas.hash_id("aluna@teste.com"))

    def test_pedido_efetivado_so_na_api_entra_na_contagem(self):
        api = vendas.normalizar_tmb_api([pedido_api(900, efetivado="2026-10-10 17:30")], OFERTAS_API)
        r = analisar(t=vendas.juntar_tmb(api, []), agora=brt("2026-10-10 18:00"))
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["por_dia"], {"2026-10-10": 1})

    def test_boleto_do_portal_que_a_api_ja_mostra_efetivado_vira_matricula(self):
        portal = [tmb(status_id=10, criado_dia="2026-10-07", id=900, nome="Aluna Teste",
                      doc=vendas.hash_doc("111.222.333-44"))]
        api = vendas.normalizar_tmb_api([pedido_api(900, efetivado="2026-10-10 17:30")], OFERTAS_API)
        r = analisar(t=vendas.juntar_tmb(api, portal), agora=brt("2026-10-10 18:00"))
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["pendentes"], [])

    def test_boleto_que_so_o_portal_conhece_continua_pendente(self):
        portal = [tmb(status_id=10, criado_dia="2026-10-07", id=901, doc="outra", nome="Outra Aluna")]
        api = vendas.normalizar_tmb_api([pedido_api(900)], OFERTAS_API)
        r = analisar(t=vendas.juntar_tmb(api, portal))
        self.assertEqual([p["nome"] for p in r["pendentes"]], ["Outra Aluna"])

    def test_oferta_lida_no_portal_vale_mais_que_a_inferida(self):
        portal = [tmb(efetivado="2026-10-09 14:09", oferta="Oferta F1", id=900, valor=4297,
                      doc=vendas.hash_doc("111.222.333-44"))]
        api = vendas.normalizar_tmb_api([pedido_api(900, efetivado="2026-10-09 14:09", valor=4297)], OFERTAS_API)
        r = analisar(t=vendas.juntar_tmb(api, portal))
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["fases"]["F1"]["matriculas"], 1)

    def test_oferta_e_inferida_pelo_valor_quando_so_a_api_tem_o_pedido(self):
        api = vendas.normalizar_tmb_api([pedido_api(900, efetivado="2026-10-09 14:09", valor=3497)], OFERTAS_API)
        self.assertEqual(api[0]["oferta"], "Oferta F1")
        r = analisar(t=vendas.juntar_tmb(api, []))
        self.assertEqual(r["fases"]["F1"]["matriculas"], 1)

    def test_valor_que_casa_com_duas_ofertas_fica_sem_oferta(self):
        api = vendas.normalizar_tmb_api([pedido_api(900, valor=5997)], OFERTAS_API)
        self.assertIsNone(api[0]["oferta"])

    def test_pedido_cancelado_na_api_sai_da_conta(self):
        api = vendas.normalizar_tmb_api([pedido_api(900, status="Cancelado")], OFERTAS_API)
        r = analisar(t=vendas.juntar_tmb(api, []))
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["saidas"]["cancelamentos"], 1)

    def test_cancelamento_solicitado_na_api_tambem_sai_da_conta(self):
        api = vendas.normalizar_tmb_api([pedido_api(900, status="Cancelamento Solicitado")], OFERTAS_API)
        r = analisar(t=vendas.juntar_tmb(api, []))
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["saidas"]["cancelamentos"], 1)
        self.assertEqual(r["alertas"], [])

    def test_nota_da_leitura_aparece_no_resumo(self):
        r = analisar([voomp(pago="2026-10-08 10:00", doc="d1")])
        r["notas"] = ["Boletos da TMB lidos do portal em sáb 10/10, 16h41"]
        self.assertIn("Boletos da TMB lidos do portal em sáb 10/10, 16h41", vendas.resumo_canal(r, cfg()))


class Coleta(unittest.TestCase):
    def test_registro_que_a_plataforma_conta_e_nao_devolve_vira_aviso(self):
        coleta = {"plataforma": "tmb", "total_api": 5, "linhas": [tmb(), tmb()]}
        avisos = vendas.avisos_da_coleta(cfg(), "tmb", coleta)
        self.assertEqual(len(avisos), 1)
        self.assertIn("diferença de 3", avisos[0])

    def test_diferenca_ja_conhecida_no_config_nao_vira_aviso(self):
        config = cfg()
        config["plataformas"]["tmb"]["registros_ocultos"] = 1
        coleta = {"plataforma": "tmb", "total_api": 3, "linhas": [tmb(), tmb()]}
        self.assertEqual(vendas.avisos_da_coleta(config, "tmb", coleta), [])

    def test_diferenca_conhecida_do_portal_nao_vale_para_a_coleta_da_api(self):
        config = cfg()
        config["plataformas"]["tmb"]["registros_ocultos"] = 1
        completa = {"plataforma": "tmb", "fonte": "api", "total_api": 2, "linhas": [tmb(), tmb()]}
        self.assertEqual(vendas.avisos_da_coleta(config, "tmb", completa), [])

    def test_coleta_completa_nao_gera_aviso(self):
        coleta = {"plataforma": "voomp", "total_api": 2, "linhas": [voomp(pago="2026-10-08 10:00"), voomp(pago="2026-10-08 11:00")]}
        self.assertEqual(vendas.avisos_da_coleta(cfg(), "voomp", coleta), [])


class Coletor(unittest.TestCase):
    def test_coletor_da_voomp_leva_os_produtos_do_projeto(self):
        js = vendas.montar_coletor(cfg(), "voomp", agora=AGORA)
        self.assertTrue(js.lstrip().startswith("async"))
        self.assertNotIn("__CFG__", js)
        self.assertIn("[100, 200]", js)

    def test_coletor_da_tmb_pergunta_o_dia_de_criacao_de_cada_dia_da_janela(self):
        js = vendas.montar_coletor(cfg(), "tmb", agora=AGORA)
        self.assertNotIn("__CFG__", js)
        self.assertIn("[300, 301]", js)
        for dia in ("2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10"):
            self.assertIn(dia, js)
        self.assertNotIn("2026-10-11", js)


CARTEIRA = {
    "tipo": "carteira",
    "titulo": "Vendas semanais teste",
    "fuso": "America/Sao_Paulo",
    "plataformas": {
        "voomp": {"coletar_desde": "2025-01-01", "assinatura": [200],
                  "comercial": {"afiliados": [9], "produtos": [150]}},
        "tmb": {"comercial": {"produtos": [300]}},
    },
    "produtos": [
        {"nome": "Pós A", "expert": "Expert A",
         "voomp": {"100": "avulso", "150": "Comercial", "200": "recorrência"},
         "tmb": {"300": "C/Comercial", "301": "S/Comercial"}},
        {"nome": "Pós B", "expert": "Expert B", "voomp": {"400": "avulso"}},
        {"nome": "Curso C", "expert": "Expert B", "tmb": {"500": "S/Comercial"}},
    ],
}
SEGUNDA = dt.date(2026, 10, 19)  # semana fechada: seg 12/10 a dom 18/10


def carteira():
    return vendas.preparar_config(copy.deepcopy(CARTEIRA))


def semanal(v=(), t=(), hoje=SEGUNDA):
    return vendas.semanal(carteira(), list(v), list(t), hoje)


def produto(r, nome):
    return next(p for p in r["produtos"] if p["nome"] == nome)


class Semanal(unittest.TestCase):
    def test_segunda_fecha_a_semana_de_segunda_a_domingo_anteriores(self):
        self.assertEqual(vendas.semana_anterior(SEGUNDA), (dt.date(2026, 10, 12), dt.date(2026, 10, 18)))

    def test_no_meio_da_semana_vale_a_ultima_semana_fechada(self):
        self.assertEqual(vendas.semana_anterior(dt.date(2026, 10, 21)),
                         (dt.date(2026, 10, 12), dt.date(2026, 10, 18)))

    def test_semana_na_virada_do_mes_fecha_o_mes_anterior_e_abre_o_novo(self):
        self.assertEqual(vendas.meses_da_semana(dt.date(2026, 10, 26), dt.date(2026, 11, 1)),
                         [(dt.date(2026, 10, 1), dt.date(2026, 10, 31)), (dt.date(2026, 11, 1), dt.date(2026, 11, 1))])

    def test_mes_vai_do_dia_1_ate_o_domingo(self):
        self.assertEqual(vendas.meses_da_semana(dt.date(2026, 10, 12), dt.date(2026, 10, 18)),
                         [(dt.date(2026, 10, 1), dt.date(2026, 10, 18))])

    def test_config_da_carteira_monta_os_produtos_de_cada_plataforma(self):
        c = carteira()
        self.assertEqual(set(c["plataformas"]["voomp"]["produtos"]), {"100", "150", "200", "400"})
        self.assertEqual(set(c["plataformas"]["tmb"]["produtos"]), {"300", "301", "500"})

    def test_produto_em_duas_linhas_da_carteira_e_erro(self):
        c = copy.deepcopy(CARTEIRA)
        c["produtos"][1]["voomp"]["100"] = "repetido"
        with self.assertRaises(SystemExit):
            vendas.preparar_config(c)

    def test_separa_comercial_e_nao_comercial(self):
        r = semanal([voomp(pago="2026-10-13 10:00", doc="d1", afiliado=9, valor=3897),
                     voomp(pago="2026-10-13 11:00", doc="d2", produto=150, valor=3700),
                     voomp(pago="2026-10-14 10:00", doc="d3", valor=3897)],
                    [tmb(efetivado="2026-10-15 10:00", doc="d4", produto=300, valor=4297),
                     tmb(efetivado="2026-10-16 10:00", doc="d5", produto=301, valor=4297)])
        s = produto(r, "Pós A")["semana"]
        self.assertEqual((s["total"], s["comercial"], s["nao_comercial"]), (5, 3, 2))
        self.assertEqual(s["valor_comercial"], 3897 + 3700 + 4297)
        self.assertEqual(s["valor_nao_comercial"], 3897 + 4297)

    def test_venda_do_comeco_do_mes_entra_so_no_mes(self):
        r = semanal([voomp(pago="2026-10-02 10:00", doc="d1"), voomp(pago="2026-10-13 10:00", doc="d2")])
        p = produto(r, "Pós A")
        self.assertEqual(p["semana"]["total"], 1)
        self.assertEqual(p["meses"][0]["total"], 2)

    def test_venda_de_setembro_e_de_hoje_ficam_fora(self):
        r = semanal([voomp(pago="2026-09-30 10:00", doc="d1"), voomp(pago="2026-10-19 09:00", doc="d2")])
        p = produto(r, "Pós A")
        self.assertEqual((p["semana"]["total"], p["meses"][0]["total"]), (0, 0))

    def test_dia_e_o_do_pagamento_em_brasilia(self):
        r = semanal([voomp(pago="2026-10-18 23:30", doc="d1")])  # 02h30 de segunda em UTC
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 1)

    def test_renovacao_de_assinatura_nao_e_venda_nova(self):
        r = semanal([voomp(pago="2026-09-13 10:00", produto=200, contrato=7, doc="d1", valor=597),
                     voomp(pago="2026-10-13 10:00", produto=200, contrato=7, doc="d1", valor=597)])
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 0)

    def test_contrato_compartilhado_por_varias_alunas_conta_cada_uma(self):
        r = semanal([voomp(pago="2026-09-13 10:00", produto=200, contrato=5, doc="d1", valor=597),
                     voomp(pago="2026-10-13 10:00", produto=200, contrato=5, doc="d2", valor=597)])
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 1)

    def test_aluna_que_ganha_contrato_novo_nao_vira_venda_nova(self):
        r = semanal([voomp(pago="2026-09-13 10:00", produto=200, contrato=5, doc="d1", valor=597),
                     voomp(pago="2026-10-13 10:00", produto=200, contrato=6, doc="d1", valor=597)])
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 0)

    def test_primeira_mensalidade_de_assinatura_e_venda_nova(self):
        r = semanal([voomp(pago="2026-10-13 10:00", produto=200, contrato=8, doc="d1", valor=597)])
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 1)

    def test_aluna_nas_duas_plataformas_conta_uma_vez_no_produto(self):
        r = semanal([voomp(pago="2026-10-13 10:00", doc="d1")], [tmb(efetivado="2026-10-14 10:00", doc="d1")])
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 1)

    def test_mesma_aluna_em_dois_produtos_conta_nos_dois(self):
        r = semanal([voomp(pago="2026-10-13 10:00", doc="d1"), voomp(pago="2026-10-13 11:00", doc="d1", produto=400)])
        self.assertEqual((produto(r, "Pós A")["semana"]["total"], produto(r, "Pós B")["semana"]["total"]), (1, 1))

    def test_quem_comprou_em_outro_mes_e_compra_de_novo_conta_de_novo(self):
        r = semanal([voomp(pago="2026-10-15 12:52", doc="d1")], [tmb(efetivado="2026-09-02 18:57", doc="d1")])
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 1)

    def test_cobranca_em_dobro_no_mes_conta_uma(self):
        r = semanal([voomp(pago="2026-10-08 04:09", doc="d1"), voomp(pago="2026-10-13 04:11", doc="d1")])
        p = produto(r, "Pós A")
        self.assertEqual((p["semana"]["total"], p["meses"][0]["total"]), (0, 1))

    def test_reembolso_sai_da_conta_e_aparece_na_semana(self):
        v = voomp(pago="2026-10-13 10:00", doc="d1", status="refunded")
        v["reembolsado"] = utc_iso("2026-10-15 10:00")
        r = semanal([v])
        p = produto(r, "Pós A")
        self.assertEqual((p["semana"]["total"], p["reembolsos"]), (0, 1))

    def test_produto_fora_da_carteira_e_ignorado(self):
        r = semanal([voomp(pago="2026-10-13 10:00", doc="d1", produto=999)])
        self.assertEqual(r["total"]["semana"]["total"], 0)

    def test_total_soma_os_produtos(self):
        r = semanal([voomp(pago="2026-10-13 10:00", doc="d1"), voomp(pago="2026-10-13 11:00", doc="d2", produto=400)],
                    [tmb(efetivado="2026-10-14 10:00", doc="d3", produto=500, valor=1000)])
        self.assertEqual(r["total"]["semana"]["total"], 3)
        self.assertEqual(r["total"]["semana"]["valor"], 3897 * 2 + 1000)

    def test_resumo_traz_semana_e_mes_de_cada_produto_em_negrito(self):
        r = semanal([voomp(pago="2026-10-13 10:00", doc="d1", afiliado=9), voomp(pago="2026-10-02 10:00", doc="d2")])
        texto = vendas.resumo_semanal(r)
        self.assertIn("**Vendas da semana · seg 12/10 a dom 18/10**", texto)
        self.assertIn("**Pós A · Expert A**", texto)
        self.assertIn("- Semana: 1 venda, R$ 3.897 · comercial 1 (R$ 3.897) · não comercial 0", texto)
        self.assertIn("- Outubro até 18/10: 2 vendas, R$ 7.794 · comercial 1 (R$ 3.897) · não comercial 1 (R$ 3.897)", texto)
        self.assertIn("**Total**", texto)

    def test_produto_sem_venda_no_mes_vai_para_uma_linha_so(self):
        r = semanal([voomp(pago="2026-10-13 10:00", doc="d1")])
        texto = vendas.resumo_semanal(r)
        self.assertNotIn("**Pós B", texto)
        self.assertIn("Sem vendas no mês: Pós B (Expert B), Curso C (Expert B)", texto)

    def test_mes_que_fechou_na_semana_aparece_como_fechado(self):
        r = semanal([voomp(pago="2026-10-27 10:00", doc="d1")], hoje=dt.date(2026, 11, 2))
        texto = vendas.resumo_semanal(r)
        self.assertIn("- Outubro (fechado): 1 venda", texto)
        self.assertIn("- Novembro até 01/11: nenhuma venda", texto)

    def test_resumo_nao_leva_dado_pessoal(self):
        v = voomp(pago="2026-10-13 10:00", doc="d1", nome="Fulana de Tal", telefone="+5511999990000")
        texto = vendas.resumo_semanal(semanal([v]))
        self.assertNotIn("Fulana", texto)
        self.assertNotIn("99999", texto)

    def test_coletor_da_carteira_nao_traz_contato_de_ninguem(self):
        js = vendas.montar_coletor(carteira(), "voomp", agora=brt("2026-10-19 08:00"))
        self.assertIn("[100, 150, 200, 400]", js)
        self.assertIn('"contato_desde": "9999-12-31"', js)
        self.assertIn('"desde": "2025-01-01"', js)


class Anual(unittest.TestCase):
    def test_ano_vai_de_janeiro_ate_o_dia_pedido_mes_a_mes(self):
        r = vendas.anual(carteira(), [], [], 2026, dt.date(2026, 10, 18))
        self.assertEqual(len(r["meses"]), 10)
        self.assertEqual(r["meses"][-1], (dt.date(2026, 10, 1), dt.date(2026, 10, 18)))

    def test_cada_mes_conta_e_o_ano_soma(self):
        r = vendas.anual(carteira(), [voomp(pago="2026-01-10 10:00", doc="d1", afiliado=9),
                                      voomp(pago="2026-03-10 10:00", doc="d2"),
                                      voomp(pago="2026-03-11 10:00", doc="d3", produto=400),
                                      voomp(pago="2026-10-19 10:00", doc="d4")], [], 2026, dt.date(2026, 10, 18))
        p = produto(r, "Pós A")
        self.assertEqual([m["total"] for m in p["meses"]][:3], [1, 0, 1])
        self.assertEqual((p["ano"]["total"], p["ano"]["comercial"]), (2, 1))
        self.assertEqual(r["total"]["ano"]["total"], 3)

    def test_venda_de_2025_fica_fora_do_ano(self):
        r = vendas.anual(carteira(), [voomp(pago="2025-12-31 23:00", doc="d1")], [], 2026, dt.date(2026, 10, 18))
        self.assertEqual(r["total"]["ano"]["total"], 0)

    def test_tabela_do_ano_tem_uma_coluna_por_mes(self):
        r = vendas.anual(carteira(), [voomp(pago="2026-02-10 10:00", doc="d1")], [], 2026, dt.date(2026, 3, 15))
        texto = vendas.resumo_anual(r)
        self.assertIn("| Produto | jan | fev | mar | Ano | Comercial | Não comercial | Valor |", texto)
        self.assertIn("| Pós A · Expert A | 0 | 1 | 0 | 1 | 0 | 1 | R$ 3.897 |", texto)
        self.assertIn("Sem vendas no ano: Pós B, Curso C", texto)


CARTEIRA_H = {
    "tipo": "carteira",
    "fuso": "America/Sao_Paulo",
    "plataformas": {
        "voomp": {"comercial": {"afiliados": [9]}},
        "hotmart": {"comercial": {"afiliados": ["UC-VALMIR"]}},
    },
    "produtos": [
        {"nome": "Pós A", "expert": "Expert A", "voomp": {"100": "avulso"}, "hotmart": {"700": "Pós na Hotmart"}},
        {"nome": "Cursos B", "expert": "Expert B", "contar": "por_produto",
         "hotmart": {"801": "e-book 1", "802": "e-book 2"}},
    ],
}


def hm_venda(pago="2026-10-13 10:00", status="COMPLETE", produto=700, email="a@x.com", moeda="BRL", valor=247.0,
             transacao=None, criado=None):
    ms = lambda texto: int(brt(texto).timestamp() * 1000) if texto else None
    return {"product": {"id": produto, "name": "Produto %s" % produto},
            "buyer": {"name": "Fulana de Tal", "email": email, "ucode": "BUY-1"},
            "purchase": {"transaction": transacao or "HP%d" % next(_ids), "status": status,
                         "order_date": ms(criado or pago), "approved_date": ms(pago),
                         "price": {"value": valor, "currency_code": moeda}, "offer": {"code": "of1"},
                         "payment": {"type": "CREDIT_CARD", "installments_number": 1}}}


def hm_comissao(transacao, cambio=1, moeda_repasse="BRL", afiliado=None):
    cms = [{"source": "PRODUCER", "commission": {"value": 10, "currency_code": moeda_repasse},
            "user": {"ucode": "UC-PROD", "name": "Produtora"}}]
    if afiliado:
        cms.append({"source": "AFFILIATE", "commission": {"value": 5, "currency_code": moeda_repasse},
                    "user": {"ucode": afiliado, "name": "Valmir Teste"}})
    return {"transaction": transacao, "exchange_rate_currency_payout": cambio, "commissions": cms}


def hm(vendas_e_comissoes):
    vendas_hm = [v for v, _ in vendas_e_comissoes]
    comissoes = [c for _, c in vendas_e_comissoes if c]
    return vendas.normalizar_hotmart(vendas_hm, comissoes)


def hm_par(**kw):
    afiliado = kw.pop("afiliado", None)
    cambio = kw.pop("cambio", 1)
    repasse = kw.pop("repasse", "BRL")
    v = hm_venda(**kw)
    return v, hm_comissao(v["purchase"]["transaction"], cambio, repasse, afiliado)


def carteira_h():
    return vendas.preparar_config(copy.deepcopy(CARTEIRA_H))


class Hotmart(unittest.TestCase):
    def test_venda_vira_linha_sem_dado_pessoal(self):
        l = hm([hm_par()])[0]
        self.assertEqual((l["status"], l["moeda"], l["valor"]), ("COMPLETE", "BRL", 247.0))
        self.assertIsNone(l["nome"])
        self.assertEqual(l["h_email"], vendas.hash_id("a@x.com"))
        self.assertNotIn("Fulana", repr(l))

    def test_moeda_estrangeira_vai_para_a_moeda_de_repasse_pelo_cambio_da_hotmart(self):
        l = hm([hm_par(moeda="ARS", valor=83357, cambio=0.000572, repasse="USD")])[0]
        self.assertEqual(l["moeda"], "USD")
        self.assertAlmostEqual(l["valor"], 47.68, places=2)

    def test_afiliado_fica_na_linha(self):
        l = hm([hm_par(afiliado="UC-VALMIR")])[0]
        self.assertEqual(l["afiliados"], ["UC-VALMIR"])

    def test_aprovada_e_completa_contam_e_reembolso_nao(self):
        r = vendas.semanal(carteira_h(), [], [], SEGUNDA, hotmart=hm([
            hm_par(status="APPROVED", email="a1"), hm_par(status="COMPLETE", email="a2"),
            hm_par(status="REFUNDED", email="a3"), hm_par(status="CANCELLED", email="a4")]))
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 2)

    def test_afiliado_do_comercial_conta_como_comercial(self):
        r = vendas.semanal(carteira_h(), [], [], SEGUNDA, hotmart=hm([
            hm_par(email="a1", afiliado="UC-VALMIR"), hm_par(email="a2", afiliado="UC-OUTRO"), hm_par(email="a3")]))
        s = produto(r, "Pós A")["semana"]
        self.assertEqual((s["comercial"], s["nao_comercial"]), (1, 2))

    def test_mesma_aluna_na_voomp_e_na_hotmart_conta_uma_pelo_email(self):
        r = vendas.semanal(carteira_h(), [voomp(pago="2026-10-13 09:00", doc=None, email=vendas.hash_id("a@x.com"))], [],
                           SEGUNDA, hotmart=hm([hm_par(email="a@x.com")]))
        self.assertEqual(produto(r, "Pós A")["semana"]["total"], 1)

    def test_linha_por_produto_conta_cada_produto_da_mesma_aluna(self):
        r = vendas.semanal(carteira_h(), [], [], SEGUNDA, hotmart=hm([
            hm_par(produto=801, email="a1", valor=47), hm_par(produto=802, email="a1", valor=67),
            hm_par(produto=801, pago="2026-10-14 10:00", email="a1", valor=47)]))
        s = produto(r, "Cursos B")["semana"]
        self.assertEqual((s["total"], s["valor"]), (2, 114))

    def test_valor_em_dolar_fica_separado_do_real(self):
        r = vendas.semanal(carteira_h(), [], [], SEGUNDA, hotmart=hm([
            hm_par(email="a1", valor=247), hm_par(email="a2", moeda="USD", valor=17, repasse="USD")]))
        s = produto(r, "Pós A")["semana"]
        self.assertEqual((s["total"], s["valor"], s["moedas"]["USD"]["valor"]), (2, 247, 17))
        self.assertIn("2 vendas, R$ 247 + US$ 17", vendas.resumo_semanal(r))

    def test_produto_fora_da_carteira_vira_alerta(self):
        r = vendas.semanal(carteira_h(), [], [], SEGUNDA, hotmart=hm([hm_par(produto=999)]))
        self.assertTrue(any("999" in a and "fora da carteira" in a for a in r["alertas"]), r["alertas"])

    def test_venda_estrangeira_sem_cambio_vira_alerta(self):
        v = hm_venda(moeda="ARS", valor=30000)
        r = vendas.semanal(carteira_h(), [], [], SEGUNDA, hotmart=vendas.normalizar_hotmart([v], []))
        self.assertTrue(any("câmbio" in a for a in r["alertas"]), r["alertas"])

    def test_ano_tem_a_hotmart(self):
        r = vendas.anual(carteira_h(), [], [], 2026, dt.date(2026, 10, 18), hotmart=hm([hm_par(pago="2026-02-10 10:00")]))
        self.assertEqual(produto(r, "Pós A")["meses"][1]["total"], 1)


class Deck(unittest.TestCase):
    def dados(self, parcial=False, hoje=SEGUNDA):
        c = carteira_h()
        c["experts"] = {"Expert A": {"curto": "Ana"}}
        hm_l = hm([hm_par(email="a1", afiliado="UC-VALMIR"), hm_par(email="a2", moeda="USD", valor=17, repasse="USD"),
                   hm_par(produto=801, email="a3", valor=47, pago="2026-09-10 10:00")])
        v = [voomp(pago="2026-10-14 10:00", doc="d9", nome="Fulana de Tal", telefone="+5511999990000")]
        r = vendas.semanal(c, v, [], hoje, hotmart=hm_l, parcial=parcial)
        r_ant = vendas.semanal(c, v, [], r["inicio"], hotmart=hm_l)
        ra = vendas.anual(c, v, [], r["fim"].year, r["fim"], hotmart=hm_l)
        return vendas.dados_deck(c, r, r_ant, ra)

    def slides(self, **kw):
        import deck_vendas
        cons = kw.pop("consideracoes", None)
        return deck_vendas.montar_slides(self.dados(**kw), cons)

    def test_tem_um_slide_por_expert_com_venda_e_os_fixos(self):
        md = self.slides()
        for chave in ("chapter: Panorama", "chapter: Ana", "chapter: Expert", "chapter: Comercial VS2A",
                      "chapter: O ano", "chapter: Pontos de atenção"):
            self.assertIn(chave, md)

    def test_soma_por_expert_junta_os_produtos(self):
        d = self.dados()
        ana = next(e for e in d["experts"] if e["curto"] == "Ana")
        self.assertEqual((ana["semana"]["total"], ana["semana"]["comercial"]), (3, 1))
        self.assertEqual(ana["semana"]["moedas"]["USD"]["valor"], 17)

    def test_deck_nao_leva_dado_pessoal(self):
        md = self.slides()
        self.assertNotIn("Fulana", md)
        self.assertNotIn("99999", md)

    def test_dolar_aparece_em_dolar(self):
        self.assertIn("US$ 17", self.slides())

    def test_consideracoes_viram_cartoes(self):
        md = self.slides(consideracoes={"titulo": "VS2A", "cartoes": [{"t": "Repescagem", "d": "12 aguardando"}]})
        self.assertIn("chapter: Para discutir", md)
        self.assertIn("Repescagem", md)

    def test_avaliacao_no_meio_da_semana_diz_que_a_semana_esta_em_andamento(self):
        md = self.slides(parcial=True, hoje=dt.date(2026, 10, 21))
        self.assertIn("semana em andamento · seg 19/10 a qua 21/10", md)

    def test_html_dos_slides_nao_tem_linha_em_branco_no_meio_de_bloco(self):
        md = self.slides()
        for bloco in md.split("<PlStage>")[1:]:
            self.assertNotIn("\n\n", bloco.split("</PlStage>")[0])

    def test_semana_na_virada_usa_o_mes_que_fechou_e_cita_o_novo(self):
        import deck_vendas
        c = carteira_h()
        v = [voomp(pago="2026-10-20 10:00", doc="d1"), voomp(pago="2026-09-20 10:00", doc="d2"),
             voomp(pago="2026-10-27 10:00", doc="d3"), voomp(pago="2026-11-01 10:00", doc="d4")]
        hoje = dt.date(2026, 11, 2)
        r = vendas.semanal(c, v, [], hoje, hotmart=[])
        d = vendas.dados_deck(c, r, vendas.semanal(c, v, [], r["inicio"], hotmart=[]),
                              vendas.anual(c, v, [], 2026, r["fim"], hotmart=[]))
        self.assertEqual(d["mes"], (dt.date(2026, 10, 1), dt.date(2026, 10, 31)))
        self.assertEqual(d["total"]["mes"]["total"], 2)
        self.assertEqual(d["experts"][0]["produtos"][0]["mes_anterior"]["total"], 1)
        self.assertEqual(d["mes_novo"]["total"]["total"], 1)
        md = deck_vendas.montar_slides(d)
        self.assertIn("Novembro até 01/11: 1 venda", md)
        self.assertIn("outubro (fechado)", md)

    def test_semana_dentro_do_mes_nao_cita_mes_novo(self):
        self.assertIsNone(self.dados()["mes_novo"])

    def test_le_consideracoes_de_um_md(self):
        import deck_vendas, tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Comercial VS2A\n\n- **Repescagem** · 12 aguardando pagamento\n- Ponto sem título\n")
        try:
            c = deck_vendas.ler_consideracoes(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(c["titulo"], "Comercial VS2A")
        self.assertEqual(c["cartoes"][0], {"t": "Repescagem", "d": "12 aguardando pagamento"})
        self.assertEqual(c["cartoes"][1]["t"], "Ponto sem título")


class CallDeSocios(unittest.TestCase):
    def test_call_da_semana_passada_aberta_e_finalizada(self):
        self.assertTrue(vendas.precisa_finalizar(dt.date(2026, 10, 19), "para fazer", dt.date(2026, 10, 26)))

    def test_call_de_hoje_fica_aberta(self):
        self.assertFalse(vendas.precisa_finalizar(dt.date(2026, 10, 26), "para fazer", dt.date(2026, 10, 26)))

    def test_call_ja_finalizada_nao_mexe(self):
        self.assertFalse(vendas.precisa_finalizar(dt.date(2026, 10, 19), "finalizada", dt.date(2026, 10, 26)))


if __name__ == "__main__":
    unittest.main()
