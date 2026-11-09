"""Diagnóstico da loja: por que ela está acima ou abaixo da meta.

Referência em Python do painel "Diagnóstico da loja" do Power BI, que faz estas contas em DAX: as
mesmas regras, para testar os limites e conferir o que o painel mostra
(`scripts/diagnostico_loja.py`). Nada daqui lê os gabaritos do gerador. Os limites vêm de
`etl.parametros_negocio` (chaves `diag_*`, pela view `dw.vw_parametros_diagnostico`) e as médias da
rede, de `dw.vw_referencia_rede_dia`.

Período: o mês até o dia (como a "cobertura da meta até o dia" do relatório): do dia 1 do mês de
`ate` até `ate`. As comparações com o ano anterior usam as mesmas datas um ano antes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import psycopg

PREFIXO_PARAMETROS = "diag_"
MESES_MATURACAO = 12  # loja aberta há menos que isso (antes da posição) ainda não tem ano anterior
MAX_ATENCOES = 2
MAX_FORTES = 2
# Ordem em que as causas e os pontos fortes aparecem no veredito (a mais importante primeiro).
ORDEM_ATENCAO = ("setor_fraco", "equipe", "fluxo", "ticket", "desconto")
ORDEM_FORTE = ("setor_forte", "ticket", "fluxo", "equipe", "desconto")


@dataclass
class Indicadores:
    """Números da loja no período, já comparados com a rede e com o ano anterior."""

    nome_loja: str
    aberta_em: date
    ate: date
    receita: float
    meta: float
    cupons: int
    cupons_ano_anterior: int | None  # None = sem base
    ticket: float | None
    ticket_rede: float | None
    desconto: float | None  # fração do valor bruto
    desconto_rede: float | None
    venda_ano_anterior: float | None
    setores: dict[str, tuple[float, float]] = field(
        default_factory=dict
    )  # setor -> (receita, meta)
    vendedores: list[tuple[float, float]] = field(
        default_factory=list
    )  # (receita, meta) com meta > 0

    @property
    def cobertura(self) -> float | None:
        return self.receita / self.meta if self.meta > 0 else None

    @property
    def em_maturacao(self) -> bool:
        return self.aberta_em > _um_ano_antes(self.ate, MESES_MATURACAO // 12)


@dataclass
class Sinal:
    """Uma conclusão do diagnóstico. `valor` é +1 (ponto forte), -1 (atenção) ou 0 (neutro)."""

    codigo: str
    valor: int
    texto: str = ""


@dataclass
class Diagnostico:
    sinais: dict[str, Sinal]
    atencoes: list[str]
    fortes: list[str]
    veredito: str


def _um_ano_antes(dia: date, anos: int = 1) -> date:
    try:
        return dia.replace(year=dia.year - anos)
    except ValueError:  # 29/02
        return dia.replace(year=dia.year - anos, day=28)


def _pct(valor: float, casas: int = 1) -> str:
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def _pp(valor: float) -> str:
    return f"{abs(valor) * 100:.1f}".replace(".", ",") + " p.p."


def _limite(valor: float) -> str:
    return f"{valor * 100:.0f}%"


def _lista(itens: list[str]) -> str:
    return ", ".join(itens)


def diagnosticar(ind: Indicadores, par: dict[str, float]) -> Diagnostico:
    """Aplica as regras e monta o veredito. `par` são os limites sem o prefixo `diag_`."""
    sinais: dict[str, Sinal] = {}

    if ind.cupons_ano_anterior:  # fluxo de cupons vs mesmo período do ano anterior
        var = ind.cupons / ind.cupons_ano_anterior - 1
        if var <= -par["cupons_queda"]:
            sinais["fluxo"] = Sinal("fluxo", -1, f"o fluxo de cupons caiu {_pct(-var)}")
        elif var >= par["cupons_queda"]:
            sinais["fluxo"] = Sinal("fluxo", 1, f"o fluxo de cupons cresceu {_pct(var)}")
        else:
            sinais["fluxo"] = Sinal("fluxo", 0)

    if ind.ticket and ind.ticket_rede:  # ticket médio vs rede
        razao = ind.ticket / ind.ticket_rede
        if razao < par["ticket_minimo"]:
            sinais["ticket"] = Sinal(
                "ticket", -1, f"o ticket médio está {_pct(1 - razao)} abaixo da rede"
            )
        elif razao >= par["ticket_forte"]:
            sinais["ticket"] = Sinal(
                "ticket", 1, f"o ticket médio está {_pct(razao - 1)} acima da rede"
            )
        else:
            sinais["ticket"] = Sinal("ticket", 0)

    if ind.desconto is not None and ind.desconto_rede is not None:  # desconto médio vs rede
        dif = ind.desconto - ind.desconto_rede
        if dif >= par["desconto_pp"]:
            sinais["desconto"] = Sinal(
                "desconto", -1, f"o desconto médio está {_pp(dif)} acima da rede"
            )
        elif dif <= -par["desconto_pp"]:
            sinais["desconto"] = Sinal(
                "desconto", 1, f"o desconto médio está {_pp(dif)} abaixo da rede"
            )
        else:
            sinais["desconto"] = Sinal("desconto", 0)

    cob_setor = sorted(
        (r / m, s) for s, (r, m) in ind.setores.items() if m > 0
    )  # (cobertura, setor), do mais fraco ao mais forte
    fracos = [f"{s} ({_pct(c, 0)})" for c, s in cob_setor if c < par["setor_fraco"]]
    fortes = [f"{s} ({_pct(c, 0)})" for c, s in reversed(cob_setor) if c >= par["setor_forte"]]
    limite_fraco, limite_forte = _limite(par["setor_fraco"]), _limite(par["setor_forte"])
    sinais["setor_fraco"] = (
        Sinal("setor_fraco", -1, f"{_lista(fracos)} abaixo de {limite_fraco} da meta")
        if fracos
        else Sinal("setor_fraco", 0)
    )
    sinais["setor_forte"] = (
        Sinal("setor_forte", 1, f"{_lista(fortes)} acima de {limite_forte} da meta")
        if fortes
        else Sinal("setor_forte", 0)
    )

    n = len(ind.vendedores)
    if n:
        abaixo = sum(1 for r, m in ind.vendedores if r < m)
        if abaixo / n >= par["equipe_abaixo"]:
            sinais["equipe"] = Sinal("equipe", -1, f"{abaixo} de {n} vendedores abaixo da meta")
        elif (n - abaixo) / n >= par["equipe_acima"]:
            sinais["equipe"] = Sinal("equipe", 1, f"{n - abaixo} de {n} vendedores acima da meta")
        else:
            sinais["equipe"] = Sinal("equipe", 0)

    if ind.venda_ano_anterior:  # a meta em relação à venda do ano anterior (contexto)
        var = ind.meta / ind.venda_ano_anterior - 1
        if var <= -par["meta_folga"]:
            texto = f"meta {_pct(-var)} abaixo da venda do ano anterior (folgada)"
            sinais["meta"] = Sinal("meta", 1, texto)
        elif var >= par["meta_folga"]:
            texto = f"meta {_pct(var)} acima da venda do ano anterior (apertada)"
            sinais["meta"] = Sinal("meta", -1, texto)
        else:
            sinais["meta"] = Sinal("meta", 0)

    atencoes = [sinais[c].texto for c in ORDEM_ATENCAO if c in sinais and sinais[c].valor < 0]
    pontos_fortes = [sinais[c].texto for c in ORDEM_FORTE if c in sinais and sinais[c].valor > 0]
    return Diagnostico(
        sinais, atencoes, pontos_fortes, _veredito(ind, sinais, atencoes, pontos_fortes)
    )


def _veredito(
    ind: Indicadores, sinais: dict[str, Sinal], atencoes: list[str], fortes: list[str]
) -> str:
    cob = ind.cobertura
    if cob is None:
        return "Sem meta no período."
    partes = [f"{'Acima' if cob >= 1 else 'Abaixo'} da meta ({_pct(cob)})."]
    if ind.em_maturacao:
        partes.append(
            f"Loja em maturação: aberta em {ind.aberta_em:%d/%m/%Y}, sem ano anterior; "
            "meta estimada com o histórico curto da loja e de lojas de formato semelhante."
        )
    if atencoes:
        partes.append(f"Atenção: {'; '.join(atencoes[:MAX_ATENCOES])}.")
    elif cob < 1:
        partes.append("Sem causa clara nos indicadores (variação do período).")
    if fortes:
        rotulo = "Ponto forte" if len(fortes[:MAX_FORTES]) == 1 else "Pontos fortes"
        partes.append(f"{rotulo}: {'; '.join(fortes[:MAX_FORTES])}.")
    meta = sinais.get("meta")
    if meta is not None and meta.valor != 0:
        partes.append(f"Contexto: {meta.texto}.")
    return " ".join(partes)


# --- leitura do dw (somente SELECT) ---------------------------------------------------------------


def ler_parametros(con: psycopg.Connection) -> dict[str, float]:
    linhas = con.execute("SELECT chave, valor FROM dw.vw_parametros_diagnostico").fetchall()
    return {chave.removeprefix(PREFIXO_PARAMETROS): float(valor) for chave, valor in linhas}


def calcular_indicadores(con: psycopg.Connection, cod_loja: str, ate: date) -> Indicadores:
    """Indicadores da loja no mês até `ate`, lidos do dw (só concluídas, como as medidas)."""
    inicio = ate.replace(day=1)
    inicio_ant, ate_ant = _um_ano_antes(inicio), _um_ano_antes(ate)
    nome, aberta_em = con.execute(
        "SELECT nome_loja, data_abertura FROM dw.dim_loja WHERE cod_loja = %s", (cod_loja,)
    ).fetchone()

    def vendas(de: date, ate_: date):
        return con.execute(
            """SELECT coalesce(sum(f.receita_liquida), 0)::float8,
                      count(DISTINCT f.numero_cupom),
                      coalesce(sum(f.desconto), 0)::float8,
                      coalesce(sum(f.preco_unitario * f.quantidade), 0)::float8
               FROM dw.fato_vendas f JOIN dw.dim_tempo t USING (sk_tempo)
               JOIN dw.dim_loja l ON l.sk_loja = f.sk_loja
               WHERE f.status = 'Concluída' AND l.cod_loja = %s AND t.data BETWEEN %s AND %s""",
            (cod_loja, de, ate_),
        ).fetchone()

    receita, cupons, desconto, bruto = vendas(inicio, ate)
    receita_ant, cupons_ant, _, _ = vendas(inicio_ant, ate_ant)
    meta = con.execute(
        """SELECT coalesce(sum(m.valor_meta_dia), 0)::float8 FROM dw.vw_meta_vendas_diaria m
           JOIN dw.dim_loja l USING (sk_loja) WHERE l.cod_loja = %s AND m.data BETWEEN %s AND %s""",
        (cod_loja, inicio, ate),
    ).fetchone()[0]
    rede = con.execute(
        """SELECT sum(receita)::float8, sum(cupons)::float8, sum(desconto)::float8,
                  sum(receita_bruta)::float8
           FROM dw.vw_referencia_rede_dia WHERE data BETWEEN %s AND %s""",
        (inicio, ate),
    ).fetchone()
    por_setor = con.execute(
        """SELECT p.setor, sum(f.receita_liquida)::float8
           FROM dw.fato_vendas f JOIN dw.dim_tempo t USING (sk_tempo)
           JOIN dw.dim_loja l ON l.sk_loja = f.sk_loja JOIN dw.dim_produto p USING (sk_produto)
           WHERE f.status = 'Concluída' AND l.cod_loja = %s AND t.data BETWEEN %s AND %s
           GROUP BY 1""",
        (cod_loja, inicio, ate),
    ).fetchall()
    meta_setor = con.execute(
        """SELECT m.setor, sum(m.valor_meta_dia)::float8 FROM dw.vw_meta_vendas_diaria m
           JOIN dw.dim_loja l USING (sk_loja) WHERE l.cod_loja = %s AND m.data BETWEEN %s AND %s
           GROUP BY 1""",
        (cod_loja, inicio, ate),
    ).fetchall()
    receita_setor = dict(por_setor)
    setores = {s: (receita_setor.get(s, 0.0), m) for s, m in meta_setor}
    vendedores = con.execute(
        """SELECT coalesce(r.receita, 0)::float8, m.meta
           FROM (SELECT mv.sk_vendedor, sum(mv.valor_meta_dia)::float8 AS meta
                 FROM dw.vw_meta_vendedor_diaria mv WHERE mv.data BETWEEN %s AND %s
                 GROUP BY 1) m
           JOIN dw.dim_vendedor v ON v.sk_vendedor = m.sk_vendedor
           JOIN dw.dim_loja l ON l.sk_loja = v.sk_loja
           LEFT JOIN (SELECT f.sk_vendedor, sum(f.receita_liquida) AS receita
                      FROM dw.fato_vendas f JOIN dw.dim_tempo t USING (sk_tempo)
                      WHERE f.status = 'Concluída' AND t.data BETWEEN %s AND %s
                      GROUP BY 1) r ON r.sk_vendedor = m.sk_vendedor
           WHERE l.cod_loja = %s AND m.meta > 0""",
        (inicio, ate, inicio, ate, cod_loja),
    ).fetchall()
    return Indicadores(
        nome_loja=nome,
        aberta_em=aberta_em,
        ate=ate,
        receita=receita,
        meta=meta,
        cupons=cupons,
        cupons_ano_anterior=cupons_ant if receita_ant > 0 else None,
        ticket=receita / cupons if cupons else None,
        ticket_rede=rede[0] / rede[1] if rede[1] else None,
        desconto=desconto / bruto if bruto else None,
        desconto_rede=rede[2] / rede[3] if rede[3] else None,
        venda_ano_anterior=receita_ant if receita_ant > 0 else None,
        setores=setores,
        vendedores=[(r, m) for r, m in vendedores],
    )
