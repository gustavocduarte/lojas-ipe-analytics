"""Base mínima do dw para testar as regras de alerta com dados escritos à mão (sem ETL).

`montar_base(con)` cria carga 1, calendário de 2024, horas, 2 lojas (L01 abre 08:00-20:00 todos os
dias; L02 sem horário), 2 vendedores, 1 produto, 1 forma de pagamento e 4 centros de custo.
`item(...)` e `despesa(...)` inserem fatos; os valores padrão não disparam nenhuma regra.
"""

from datetime import date, timedelta

MESES = (
    "Janeiro Fevereiro Março Abril Maio Junho Julho Agosto Setembro Outubro Novembro Dezembro"
).split()
DIAS = "Segunda-feira Terça-feira Quarta-feira Quinta-feira Sexta-feira Sábado Domingo".split()
CENTROS = (
    ("L01-PES", "Loja 1 - Pessoal", "Pessoal", "L01"),
    ("L01-TER", "Loja 1 - Terceiros", "Terceiros", "L01"),
    ("L01-DIS", "Loja 1 - Discricionárias", "Discricionárias", "L01"),
    ("COR-TI", "Tecnologia da Informação", "Terceiros", None),
)


def montar_base(con, ano: int = 2024, feriados: dict[date, str] | None = None) -> int:
    """Cria a base e devolve o id da carga (1)."""
    con.execute(
        "INSERT INTO etl.cargas (fonte, modo, status) VALUES ('teste', 'completo', 'concluida')"
    )
    id_carga = con.execute("SELECT max(id_carga) FROM etl.cargas").fetchone()[0]
    con.execute("CALL etl.carregar_horas()")
    dia = date(ano, 1, 1)
    linhas = []
    while dia.year == ano:
        nome = (feriados or {}).get(dia)
        linhas.append(
            (
                int(dia.strftime("%Y%m%d")), dia, dia.day, dia.isocalendar()[1], dia.month,
                (dia.month - 1) // 3 + 1, dia.year, MESES[dia.month - 1], DIAS[dia.weekday()],
                nome is not None, nome,
            )
        )  # fmt: skip
        dia += timedelta(days=1)
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO dw.dim_tempo (sk_tempo, data, dia, semana, mes, trimestre, ano, nome_mes,"
            " nome_dia_semana, feriado_nacional, nome_feriado)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            linhas,
        )
    for cod in ("L01", "L02"):
        con.execute(
            "INSERT INTO dw.dim_loja (cod_loja, nome_loja, uf, regiao, cidade, formato,"
            " data_abertura)"
            " VALUES (%s, %s, 'SP', 'Sudeste', 'São Paulo', 'Supermercado', '2010-01-01')",
            (cod, f"Ipê {cod}"),
        )
    for dia_semana in range(1, 8):
        con.execute(
            "INSERT INTO dw.dim_loja_horario SELECT sk_loja, %s, '08:00', '20:00'"
            " FROM dw.dim_loja WHERE cod_loja = 'L01'",
            (dia_semana,),
        )
    for cod, loja in (("V1", "L01"), ("V2", "L02")):
        con.execute(
            "INSERT INTO dw.dim_vendedor (cod_vendedor, nome_vendedor, sk_loja, cargo, turno,"
            " data_admissao, percentual_comissao) SELECT %s, %s, sk_loja, 'Vendedor', 'Integral',"
            " '2020-01-01', 1 FROM dw.dim_loja WHERE cod_loja = %s",
            (cod, f"Vendedor {cod}", loja),
        )
    con.execute(
        "INSERT INTO dw.dim_produto (sku, nome_produto, marca, setor, categoria, custo_unitario,"
        " preco_lista) VALUES ('P1', 'Produto 1', 'Marca', 'Alimentos', 'Mercearia', 60, 100)"
    )
    con.execute(
        "INSERT INTO dw.dim_forma_pagamento (cod_forma_pagamento, nome_forma_pagamento)"
        " VALUES ('PIX', 'Pix')"
    )
    for cod, nome, tipo, loja in CENTROS:
        con.execute(
            "INSERT INTO dw.dim_centro_custo (cod_centro_custo, nome_centro_custo, tipo_despesa,"
            " sk_loja) VALUES (%s, %s, %s, (SELECT sk_loja FROM dw.dim_loja WHERE cod_loja = %s))",
            (cod, nome, tipo, loja),
        )
    con.commit()
    return id_carga


def item(
    con,
    id_venda: str,
    cupom: str = "C1",
    numero_item: int = 1,
    data: str = "2024-03-05",
    hora: str = "10:00:00",
    loja: str = "L01",
    vendedor: str = "V1",
    quantidade: int = 1,
    preco: float = 100.0,
    desconto: float = 0.0,
    receita: float | None = None,
    custo: float = 60.0,
    status: str = "Concluída",
) -> None:
    """Insere um item de venda. Receita padrão = bruto - desconto."""
    receita = quantidade * preco - desconto if receita is None else receita
    motivo = None if status == "Concluída" else "Desistência do cliente"
    con.execute(
        "INSERT INTO dw.fato_vendas (id_venda_erp, numero_cupom, numero_item, sk_tempo, sk_hora,"
        " data_hora_venda, sk_loja, caixa, sk_vendedor, sk_forma_pagamento, numero_parcelas,"
        " sk_produto, quantidade, preco_unitario, desconto, receita_liquida, custo, status,"
        " motivo_cancelamento_devolucao)"
        " SELECT %(id)s, %(cupom)s, %(item)s, to_char(%(data)s::DATE, 'YYYYMMDD')::INT,"
        " extract(hour FROM %(hora)s::TIME)::INT, %(data)s::DATE + %(hora)s::TIME, l.sk_loja, 1,"
        " v.sk_vendedor, f.sk_forma_pagamento, 1, p.sk_produto, %(qtd)s, %(preco)s, %(desc)s,"
        " %(rec)s, %(custo)s, %(status)s, %(motivo)s"
        " FROM dw.dim_loja l, dw.dim_vendedor v, dw.dim_forma_pagamento f, dw.dim_produto p"
        " WHERE l.cod_loja = %(loja)s AND v.cod_vendedor = %(vend)s AND p.sku = 'P1'",
        {
            "id": id_venda, "cupom": cupom, "item": numero_item, "data": data, "hora": hora,
            "qtd": quantidade, "preco": preco, "desc": desconto, "rec": receita, "custo": custo,
            "status": status, "motivo": motivo, "loja": loja, "vend": vendedor,
        },
    )  # fmt: skip


def despesa(
    con,
    documento: str,
    valor: float,
    centro: str = "L01-TER",
    data: str = "2024-03-05",
    descricao: str = "Manutenção predial",
    linha: int | None = None,
    arquivo: str = "despesas.csv",
) -> int:
    """Insere um lançamento de despesa e devolve a linha de origem usada."""
    if linha is None:
        linha = con.execute(
            "SELECT coalesce(max(linha_origem), 0) + 1 FROM dw.fato_despesas"
            " WHERE arquivo_origem = %s",
            (arquivo,),
        ).fetchone()[0]
    con.execute(
        "INSERT INTO dw.fato_despesas (numero_documento, sk_tempo, sk_centro_custo, valor,"
        " descricao,"
        " arquivo_origem, linha_origem)"
        " SELECT %s, to_char(%s::DATE, 'YYYYMMDD')::INT, sk_centro_custo, %s, %s, %s, %s"
        " FROM dw.dim_centro_custo WHERE cod_centro_custo = %s",
        (documento, data, valor, descricao, arquivo, linha, centro),
    )
    return linha


def orcamento(con, centro: str, mes: int, valor: float, ano: int = 2024) -> None:
    con.execute(
        "INSERT INTO dw.fato_orcamento_despesas (sk_tempo, sk_centro_custo, valor_orcado)"
        " SELECT to_char(make_date(%s, %s, 1), 'YYYYMMDD')::INT, sk_centro_custo, %s"
        " FROM dw.dim_centro_custo WHERE cod_centro_custo = %s",
        (ano, mes, valor, centro),
    )


def gerar(con, id_carga: int | None = None) -> int:
    """Roda as regras numa NOVA carga (ou na indicada) e devolve o id usado."""
    if id_carga is None:
        con.execute("INSERT INTO etl.cargas (fonte, modo) VALUES ('alertas', 'completo')")
        id_carga = con.execute("SELECT max(id_carga) FROM etl.cargas").fetchone()[0]
    con.execute("CALL etl.gerar_alertas(%s)", (id_carga,))
    con.commit()
    return id_carga


def alertas(con, tipo: str | None = None, vigentes: bool | None = None) -> list[dict]:
    """Alertas como dicionários, ordenados pela chave."""
    filtros, parametros = [], []
    if tipo:
        filtros.append("tipo_alerta = %s")
        parametros.append(tipo)
    if vigentes is not None:
        filtros.append("vigente = %s")
        parametros.append(vigentes)
    cursor = con.execute(
        "SELECT * FROM dw.alertas" + (" WHERE " + " AND ".join(filtros) if filtros else "")
        + " ORDER BY chave_alerta",
        parametros,
    )  # fmt: skip
    nomes = [c.name for c in cursor.description]
    return [dict(zip(nomes, linha, strict=True)) for linha in cursor.fetchall()]
