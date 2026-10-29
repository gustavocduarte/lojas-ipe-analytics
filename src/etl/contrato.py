"""Contrato de entrada: as colunas que o sistema precisa de cada entidade, com tipo e significado.

É a fonte única do que o ETL espera. O documento docs/contrato_de_entrada.md é gerado daqui
(`python -m src.etl.contrato`) e os mapeamentos de config/fontes/ são validados contra ele.
"""

from dataclasses import dataclass

TEXTO = "texto"
INTEIRO = "inteiro"
DECIMAL = "decimal"
DATA = "data"
HORA = "hora"
TIPOS = (TEXTO, INTEIRO, DECIMAL, DATA, HORA)

REJEITAR = "rejeita a linha"
OPCIONAL = "aceita vazio"


@dataclass(frozen=True)
class ColunaContrato:
    nome: str
    tipo: str
    obrigatoria: bool
    descricao: str
    se_ausente: str = ""  # o que o ETL faz quando vem vazio

    @property
    def regra_se_ausente(self) -> str:
        return self.se_ausente or (REJEITAR if self.obrigatoria else OPCIONAL)


@dataclass(frozen=True)
class EntidadeContrato:
    nome: str
    descricao: str
    chave_natural: tuple[str, ...]
    colunas: tuple[ColunaContrato, ...]

    @property
    def nomes_das_colunas(self) -> tuple[str, ...]:
        return tuple(c.nome for c in self.colunas)

    @property
    def obrigatorias(self) -> tuple[str, ...]:
        return tuple(c.nome for c in self.colunas if c.obrigatoria)

    def coluna(self, nome: str) -> ColunaContrato:
        return next(c for c in self.colunas if c.nome == nome)


def _c(nome, tipo, obrigatoria, descricao, se_ausente=""):
    return ColunaContrato(nome, tipo, obrigatoria, descricao, se_ausente)


_ENTIDADES = (
    EntidadeContrato(
        "lojas",
        "Cadastro das lojas da rede.",
        ("cod_loja",),
        (
            _c("cod_loja", TEXTO, True, "Código da loja (chave)."),
            _c("nome_loja", TEXTO, True, "Nome da loja."),
            _c("uf", TEXTO, True, "Sigla do estado, 2 letras."),
            _c(
                "regiao",
                TEXTO,
                True,
                "Região do país (Sudeste, Nordeste, Sul, Centro-Oeste, Norte).",
            ),
            _c("cidade", TEXTO, True, "Cidade da loja."),
            _c("formato", TEXTO, True, "Formato da loja (Hipermercado, Supermercado, Express)."),
            _c("data_abertura", DATA, True, "Data de inauguração da loja."),
        ),
    ),
    EntidadeContrato(
        "horarios_loja",
        "Horário de funcionamento de cada loja por dia da semana.",
        ("cod_loja", "dia_semana"),
        (
            _c("cod_loja", TEXTO, True, "Código da loja."),
            _c("dia_semana", INTEIRO, True, "Dia da semana, de 1 (segunda) a 7 (domingo)."),
            _c("hora_abertura", HORA, True, "Hora de abertura."),
            _c("hora_fechamento", HORA, True, "Hora de fechamento (depois da abertura)."),
        ),
    ),
    EntidadeContrato(
        "produtos",
        "Cadastro de produtos (SKU).",
        ("sku",),
        (
            _c("sku", TEXTO, True, "Código do produto (chave). Espaços e caixa são normalizados."),
            _c("nome_produto", TEXTO, True, "Descrição do produto."),
            _c("marca", TEXTO, True, "Marca do produto."),
            _c("setor", TEXTO, True, "Setor (Alimentos, Bebidas, Limpeza, Casa, Eletro, ...)."),
            _c("categoria", TEXTO, True, "Categoria dentro do setor."),
            _c("custo_unitario", DECIMAL, True, "Custo unitário em R$ (não negativo)."),
            _c("preco_lista", DECIMAL, True, "Preço de lista em R$ (não negativo)."),
        ),
    ),
    EntidadeContrato(
        "centros_custo",
        "Centros de custo das despesas (de loja ou corporativos).",
        ("cod_centro_custo",),
        (
            _c("cod_centro_custo", TEXTO, True, "Código do centro de custo (chave)."),
            _c("nome_centro_custo", TEXTO, True, "Nome do centro de custo."),
            _c("tipo_despesa", TEXTO, True, "Pessoal, Terceiros ou Discricionárias."),
            _c("cod_loja", TEXTO, False, "Loja do centro; vazio = centro corporativo."),
        ),
    ),
    EntidadeContrato(
        "feriados",
        "Feriados nacionais.",
        ("data",),
        (
            _c("data", DATA, True, "Data do feriado (chave)."),
            _c("nome_feriado", TEXTO, True, "Nome do feriado."),
        ),
    ),
    EntidadeContrato(
        "formas_pagamento",
        "Formas de pagamento aceitas.",
        ("cod_forma_pagamento",),
        (
            _c("cod_forma_pagamento", TEXTO, True, "Código da forma de pagamento (chave)."),
            _c("nome_forma_pagamento", TEXTO, True, "Nome (Pix, Débito, Crédito à vista, ...)."),
        ),
    ),
    EntidadeContrato(
        "campanhas",
        "Campanhas promocionais.",
        ("cod_campanha",),
        (
            _c("cod_campanha", TEXTO, True, "Código da campanha (chave)."),
            _c("nome_campanha", TEXTO, True, "Nome da campanha."),
            _c("data_inicio", DATA, True, "Primeiro dia da campanha."),
            _c("data_fim", DATA, True, "Último dia da campanha (não anterior ao início)."),
            _c("desconto_medio_pct", DECIMAL, True, "Desconto médio da campanha, em % (5 = 5%)."),
        ),
    ),
    EntidadeContrato(
        "vendedores",
        "Cadastro de vendedores, com admissão e desligamento.",
        ("cod_vendedor",),
        (
            _c("cod_vendedor", TEXTO, True, "Código do vendedor (chave)."),
            _c("nome_vendedor", TEXTO, True, "Nome; espaços extras e caixa são normalizados."),
            _c("cod_loja", TEXTO, True, "Loja do vendedor."),
            _c("cargo", TEXTO, True, "Cargo."),
            _c("turno", TEXTO, True, "Manhã, Tarde ou Integral."),
            _c("data_admissao", DATA, True, "Data de admissão."),
            _c("data_desligamento", DATA, False, "Data de desligamento; vazio = ainda ativo."),
            _c("percentual_comissao", DECIMAL, True, "Comissão em % (2 = 2%)."),
        ),
    ),
    EntidadeContrato(
        "clientes",
        "Clientes do programa de fidelidade (sem dados pessoais identificáveis).",
        ("cod_cliente",),
        (
            _c("cod_cliente", TEXTO, True, "Código do cliente (chave)."),
            _c("cidade", TEXTO, True, "Cidade de residência."),
            _c("uf", TEXTO, True, "Sigla do estado, 2 letras."),
            _c("faixa_etaria", TEXTO, True, "Faixa etária (ex.: 25-34)."),
            _c("data_cadastro_fidelidade", DATA, True, "Data de entrada no programa."),
        ),
    ),
    EntidadeContrato(
        "vendas",
        "Itens de cupom de venda (uma linha por item).",
        ("id_venda_erp",),
        (
            _c("id_venda_erp", TEXTO, True, "Identificador do item no ERP (chave)."),
            _c("numero_cupom", TEXTO, True, "Número do cupom."),
            _c("numero_item", INTEIRO, True, "Posição do item no cupom (1, 2, ...)."),
            _c("data_venda", DATA, True, "Data da venda."),
            _c("hora_venda", HORA, True, "Hora da venda."),
            _c("cod_loja", TEXTO, True, "Loja da venda."),
            _c("caixa", INTEIRO, True, "Número do caixa (PDV)."),
            _c("cod_vendedor", TEXTO, True, "Vendedor do cupom."),
            _c("cod_cliente", TEXTO, False, "Cliente identificado; vazio = não identificado."),
            _c("cod_forma_pagamento", TEXTO, True, "Forma de pagamento."),
            _c("numero_parcelas", INTEIRO, True, "Parcelas (1 = à vista)."),
            _c("cod_campanha", TEXTO, False, "Campanha aplicada; vazio = sem campanha."),
            _c("sku", TEXTO, True, "Produto vendido. Espaços e caixa são normalizados."),
            _c("quantidade", INTEIRO, True, "Quantidade (maior que zero)."),
            _c("preco_unitario", DECIMAL, True, "Preço unitário praticado em R$."),
            _c(
                "desconto",
                DECIMAL,
                True,
                "Desconto do item em R$.",
                "recalcula: quantidade * preco_unitario - receita_liquida",
            ),
            _c("receita_liquida", DECIMAL, True, "Valor líquido do item em R$ (bruto - desconto)."),
            _c("custo_total", DECIMAL, True, "Custo do item em R$ (quantidade * custo unitário)."),
            _c("total_cupom", DECIMAL, True, "Valor total do cupom (soma dos itens), em R$."),
            _c("status", TEXTO, True, "Concluída, Cancelada ou Devolvida."),
            _c(
                "motivo_cancelamento_devolucao",
                TEXTO,
                False,
                "Motivo; obrigatório quando o status não é Concluída.",
            ),
        ),
    ),
    EntidadeContrato(
        "metas_vendas",
        "Meta mensal de vendas por loja e setor.",
        ("competencia", "cod_loja", "setor"),
        (
            _c("competencia", DATA, True, "Mês da meta (primeiro dia do mês)."),
            _c("cod_loja", TEXTO, True, "Loja."),
            _c("setor", TEXTO, True, "Setor."),
            _c("valor_meta", DECIMAL, True, "Meta em R$ (não negativa)."),
        ),
    ),
    EntidadeContrato(
        "metas_vendedor",
        "Meta mensal de vendas por vendedor.",
        ("competencia", "cod_vendedor"),
        (
            _c("competencia", DATA, True, "Mês da meta (primeiro dia do mês)."),
            _c("cod_vendedor", TEXTO, True, "Vendedor."),
            _c("valor_meta", DECIMAL, True, "Meta em R$ (não negativa)."),
        ),
    ),
    EntidadeContrato(
        "despesas",
        "Lançamentos de despesa.",
        (),  # sem chave natural: a linha é identificada por arquivo_origem + linha_origem
        (
            _c("numero_documento", TEXTO, True, "Número do documento do lançamento."),
            _c("data_lancamento", DATA, True, "Data do lançamento."),
            _c("cod_centro_custo", TEXTO, True, "Centro de custo."),
            _c("valor", DECIMAL, True, "Valor em R$."),
            _c(
                "descricao",
                TEXTO,
                False,
                "Descrição do lançamento.",
                "preenche com 'NAO INFORMADO'",
            ),
            _c("fornecedor", TEXTO, False, "Fornecedor."),
        ),
    ),
    EntidadeContrato(
        "orcamento_despesas",
        "Orçamento mensal de despesa por centro de custo.",
        ("competencia", "cod_centro_custo"),
        (
            _c("competencia", DATA, True, "Mês do orçamento (primeiro dia do mês)."),
            _c("cod_centro_custo", TEXTO, True, "Centro de custo."),
            _c("valor_orcado", DECIMAL, True, "Valor orçado em R$ (não negativo)."),
        ),
    ),
)

CONTRATO: dict[str, EntidadeContrato] = {e.nome: e for e in _ENTIDADES}
ORDEM_DE_CARGA = tuple(CONTRATO)  # dimensões antes dos fatos


def gerar_markdown() -> str:
    """Texto de docs/contrato_de_entrada.md."""
    linhas = [
        "# Contrato de entrada",
        "",
        "Este documento lista, para cada entidade, as colunas que o sistema precisa receber.",
        "Cada fonte de dados (o ERP da Lojas Ipê, uma planilha de outra empresa etc.) é ligada a",
        "este contrato por um arquivo de mapeamento em `config/fontes/`, que diz qual coluna da",
        "fonte corresponde a cada coluna abaixo.",
        "",
        "Este arquivo é gerado por `python -m src.etl.contrato`; não edite à mão.",
        "",
        "Tipos: `texto`, `inteiro`, `decimal`, `data`, `hora`. Todos chegam ao staging como texto",
        "cru; a conversão e a limpeza acontecem na carga para o data warehouse.",
        "",
        "`linha_origem` é a posição da linha de dados no arquivo, contada a partir de 1 na",
        "primeira linha depois do cabeçalho (sem contar linhas ignoradas).",
    ]
    for entidade in CONTRATO.values():
        chave = ", ".join(f"`{c}`" for c in entidade.chave_natural) or (
            "nenhuma (a linha é identificada pelo arquivo e pela posição nele)"
        )
        linhas += ["", f"## {entidade.nome}", "", entidade.descricao, "", f"Chave natural: {chave}"]
        linhas += [
            "",
            "| Coluna | Tipo | Obrigatória | Significado | Se vier vazia |",
            "|---|---|---|---|---|",
        ]
        for c in entidade.colunas:
            obrigatoria = "sim" if c.obrigatoria else "não"
            linhas.append(
                f"| `{c.nome}` | {c.tipo} | {obrigatoria} | {c.descricao} | {c.regra_se_ausente} |"
            )
    return "\n".join(linhas) + "\n"


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(gerar_markdown())
