"""Diagnóstico de uma loja no mês até o dia (SOMENTE LEITURA no dw: só SELECT).

Mostra os indicadores, os sinais e o veredito que o painel "Diagnóstico da loja" do Power BI deve
exibir, usando a referência em Python (`src/diagnostico.py`). Serve para conferir o painel.

  python scripts/diagnostico_loja.py --ate 2025-12-15 "Ipê Brasília" "Ipê Niterói"
  python scripts/diagnostico_loja.py --ate 2025-12-15          # todas as lojas, só o veredito

Sem `--ate`, usa o último dia com venda (`dw.data_referencia()`). Os nomes aceitam parte do texto.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src import banco, diagnostico  # noqa: E402


def mostrar(con, cod_loja: str, ate: date, par: dict[str, float], detalhe: bool) -> None:
    ind = diagnostico.calcular_indicadores(con, cod_loja, ate)
    res = diagnostico.diagnosticar(ind, par)
    print(f"\n=== {ind.nome_loja} (até {ate:%d/%m/%Y}) ===")
    if detalhe:
        ant = ind.cupons_ano_anterior
        print(f"receita {ind.receita:,.2f} | meta {ind.meta:,.2f} | cobertura {ind.cobertura:.1%}")
        print(f"cupons {ind.cupons} (ano anterior: {ant if ant is not None else 'sem base'})")
        print(f"ticket {ind.ticket:,.2f} | rede {ind.ticket_rede:,.2f}")
        print(f"desconto {ind.desconto:.2%} | rede {ind.desconto_rede:.2%}")
        for setor, (r, m) in sorted(ind.setores.items(), key=lambda x: x[1][0] / x[1][1]):
            print(f"  setor {setor:<18} {r / m:7.1%}")
        abaixo = sum(1 for r, m in ind.vendedores if r < m)
        print(f"vendedores abaixo da meta: {abaixo} de {len(ind.vendedores)}")
        print("sinais:", {c: s.valor for c, s in res.sinais.items()})
    print(res.veredito)


def principal() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("lojas", nargs="*", help="nome (ou parte) das lojas; vazio = todas")
    parser.add_argument(
        "--ate", type=date.fromisoformat, help="AAAA-MM-DD (padrão: último dia com venda)"
    )
    args = parser.parse_args()
    with banco.conectar() as con:
        con.read_only = True
        ate = args.ate or con.execute("SELECT dw.data_referencia()").fetchone()[0]
        par = diagnostico.ler_parametros(con)
        lojas = con.execute(
            "SELECT cod_loja, nome_loja FROM dw.dim_loja ORDER BY nome_loja"
        ).fetchall()
        for cod, nome in lojas:
            if not args.lojas or any(t.lower() in nome.lower() for t in args.lojas):
                mostrar(con, cod, ate, par, detalhe=bool(args.lojas))


if __name__ == "__main__":
    principal()
