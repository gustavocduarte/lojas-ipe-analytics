"""Mapeamento de uma fonte de dados para o contrato de entrada (config/fontes/*.yaml).

Um arquivo de mapeamento descreve, por entidade, onde estão os dados (arquivo, formato,
separador, codificação, aba, cabeçalho, linhas a ignorar) e qual coluna da fonte corresponde a
cada coluna do sistema. Nada aqui lê dados: só carrega e valida a configuração.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src import config
from src.etl.contrato import CONTRATO, DATA

PADROES_INICIAIS = {
    "formato": "csv",
    "separador": config.SEPARADOR_CSV,
    "codificacao": config.CODIFICACAO_CSV,
    "linha_cabecalho": 1,
}
CHAVES_ENTIDADE = {
    "arquivo",
    "formato",
    "separador",
    "codificacao",
    "aba",
    "linha_cabecalho",
    "ignorar_linhas",
    "colunas",
    "formato_data",
    "separador_decimal",
    "separador_milhar",
}


class MapeamentoInvalido(ValueError):
    """O arquivo de mapeamento está incompleto ou contradiz o contrato de entrada."""


@dataclass(frozen=True)
class RegraIgnorar:
    """Ignora a linha cuja célula da coluna indicada (nome na fonte) casa com a regra."""

    coluna: str
    igual_a: str | None = None
    comeca_com: str | None = None

    def casa(self, valor: str) -> bool:
        texto = valor.strip().casefold()
        if self.igual_a is not None and texto == self.igual_a.casefold():
            return True
        return self.comeca_com is not None and texto.startswith(self.comeca_com.casefold())


@dataclass(frozen=True)
class MapeamentoEntidade:
    entidade: str
    arquivo: str  # nome ou padrão glob (ex.: vendas_*.csv)
    formato: str
    separador: str
    codificacao: str
    aba: str | None
    linha_cabecalho: int  # 1 = primeira linha do arquivo
    ignorar_linhas: tuple[RegraIgnorar, ...]
    colunas: dict[str, str]  # coluna da fonte -> coluna do sistema
    formato_data: str | None  # strptime; vazio = copiar o texto como vem
    separador_decimal: str  # "." ou ","; só "," altera o texto (vira ponto)
    separador_milhar: str


@dataclass(frozen=True)
class Fonte:
    nome: str
    descricao: str
    pasta: Path  # onde ficam os arquivos (relativa à raiz do projeto, se não for absoluta)
    entidades: dict[str, MapeamentoEntidade] = field(default_factory=dict)


def carregar_fonte(caminho: Path, raiz: Path = config.RAIZ_PROJETO) -> Fonte:
    """Lê e valida um arquivo de mapeamento. Levanta MapeamentoInvalido se algo estiver errado."""
    try:
        bruto = yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))
    except yaml.YAMLError as erro:
        raise MapeamentoInvalido(f"{caminho}: YAML inválido ({erro})") from erro
    if not isinstance(bruto, dict):
        raise MapeamentoInvalido(f"{caminho}: o arquivo precisa ser um mapa YAML")
    for chave in ("fonte", "pasta", "entidades"):
        if chave not in bruto:
            raise MapeamentoInvalido(f"{caminho}: falta a chave '{chave}'")

    padroes = {**PADROES_INICIAIS, **(bruto.get("padroes") or {})}
    pasta = Path(bruto["pasta"])
    entidades = {}
    nome = str(bruto["fonte"])
    for entidade, bloco in (bruto["entidades"] or {}).items():
        entidades[entidade] = _montar_entidade(nome, entidade, bloco, padroes)
    if not entidades:
        raise MapeamentoInvalido(f"fonte '{nome}': nenhuma entidade mapeada")
    return Fonte(
        nome=nome,
        descricao=str(bruto.get("descricao", "")),
        pasta=pasta if pasta.is_absolute() else raiz / pasta,
        entidades=entidades,
    )


def carregar_fontes(pasta: Path = config.DIR_MAPEAMENTOS) -> dict[str, Fonte]:
    fontes = {}
    for caminho in sorted(Path(pasta).glob("*.yaml")):
        fonte = carregar_fonte(caminho)
        if fonte.nome in fontes:
            raise MapeamentoInvalido(f"fonte '{fonte.nome}' definida em mais de um arquivo")
        fontes[fonte.nome] = fonte
    return fontes


def _montar_entidade(fonte: str, entidade: str, bloco: dict, padroes: dict) -> MapeamentoEntidade:
    onde = f"fonte '{fonte}', entidade '{entidade}'"
    if entidade not in CONTRATO:
        raise MapeamentoInvalido(f"{onde}: entidade fora do contrato ({', '.join(CONTRATO)})")
    if not isinstance(bloco, dict):
        raise MapeamentoInvalido(f"{onde}: esperado um mapa de configurações")
    desconhecidas = set(bloco) - CHAVES_ENTIDADE
    if desconhecidas:
        raise MapeamentoInvalido(f"{onde}: chaves desconhecidas {sorted(desconhecidas)}")
    dados = {**padroes, **bloco}

    if not dados.get("arquivo"):
        raise MapeamentoInvalido(f"{onde}: falta 'arquivo'")
    formato = str(dados["formato"]).lower()
    if formato not in config.FORMATOS_ARQUIVO_FONTE:
        raise MapeamentoInvalido(f"{onde}: formato '{formato}' não suportado")
    if formato == "xlsx" and not dados.get("aba"):
        raise MapeamentoInvalido(f"{onde}: arquivo Excel precisa informar a 'aba'")
    linha_cabecalho = dados["linha_cabecalho"]
    if not isinstance(linha_cabecalho, int) or linha_cabecalho < 1:
        raise MapeamentoInvalido(f"{onde}: 'linha_cabecalho' deve ser um inteiro >= 1")
    if formato == "csv" and len(str(dados["separador"])) != 1:
        raise MapeamentoInvalido(f"{onde}: 'separador' deve ter um caractere")

    colunas = bloco.get("colunas")
    if not isinstance(colunas, dict) or not colunas:
        raise MapeamentoInvalido(f"{onde}: falta o mapa 'colunas' (coluna da fonte: do sistema)")
    colunas = {str(origem): str(destino) for origem, destino in colunas.items()}
    contrato = CONTRATO[entidade]
    destinos = list(colunas.values())
    repetidas = {d for d in destinos if destinos.count(d) > 1}
    if repetidas:
        raise MapeamentoInvalido(f"{onde}: coluna do sistema repetida {sorted(repetidas)}")
    fora = set(destinos) - set(contrato.nomes_das_colunas)
    if fora:
        raise MapeamentoInvalido(f"{onde}: colunas fora do contrato {sorted(fora)}")
    faltam = set(contrato.obrigatorias) - set(destinos)
    if faltam:
        raise MapeamentoInvalido(f"{onde}: colunas obrigatórias sem mapeamento {sorted(faltam)}")

    regras = tuple(_montar_regra(onde, r) for r in dados.get("ignorar_linhas") or [])
    for regra in regras:
        if regra.coluna not in colunas:
            raise MapeamentoInvalido(
                f"{onde}: 'ignorar_linhas' cita coluna não mapeada: {regra.coluna}"
            )
    decimal = str(dados.get("separador_decimal") or ".")
    if decimal not in (".", ","):
        raise MapeamentoInvalido(f"{onde}: 'separador_decimal' deve ser '.' ou ','")
    formato_data = dados.get("formato_data")
    if formato_data and not any(contrato.coluna(d).tipo == DATA for d in destinos):
        raise MapeamentoInvalido(f"{onde}: 'formato_data' informado, mas não há colunas de data")
    return MapeamentoEntidade(
        entidade=entidade,
        arquivo=str(dados["arquivo"]),
        formato=formato,
        separador=str(dados["separador"]),
        codificacao=str(dados["codificacao"]),
        aba=dados.get("aba"),
        linha_cabecalho=linha_cabecalho,
        ignorar_linhas=regras,
        colunas=colunas,
        formato_data=formato_data or None,
        separador_decimal=decimal,
        separador_milhar=str(dados.get("separador_milhar") or ""),
    )


def _montar_regra(onde: str, bruto: dict) -> RegraIgnorar:
    if not isinstance(bruto, dict) or "coluna" not in bruto:
        raise MapeamentoInvalido(f"{onde}: cada regra de 'ignorar_linhas' precisa de 'coluna'")
    igual_a, comeca_com = bruto.get("igual_a"), bruto.get("comeca_com")
    if igual_a is None and comeca_com is None:
        raise MapeamentoInvalido(
            f"{onde}: regra de 'ignorar_linhas' sem 'igual_a' nem 'comeca_com'"
        )
    return RegraIgnorar(str(bruto["coluna"]), igual_a, comeca_com)
