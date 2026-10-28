"""Cadastros fictícios da rede: lojas, produtos e centros de custo."""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from faker import Faker

from src import calendario, config
from src.gerador.parametros import rng_para

SETORES = ("Alimentos", "Bebidas", "Limpeza", "Casa", "Eletro", "Cuidados Pessoais")
PREFIXO_SKU = {
    "Alimentos": "ALI",
    "Bebidas": "BEB",
    "Limpeza": "LIM",
    "Casa": "CAS",
    "Eletro": "ELE",
    "Cuidados Pessoais": "CUI",
}
# Faixa do custo como fração do preço de lista (teto 0,72, ver DESCONTO_MAXIMO em config)
FAIXA_CUSTO_POR_SETOR = {
    "Alimentos": (0.66, 0.72),
    "Bebidas": (0.62, 0.70),
    "Limpeza": (0.55, 0.66),
    "Casa": (0.55, 0.68),
    "Eletro": (0.70, 0.72),
    "Cuidados Pessoais": (0.52, 0.64),
}
# Mix de linhas de venda por setor em cada região (ordem de SETORES; normalizado no uso)
MIX_SETOR_POR_REGIAO = {
    "Sudeste": (0.36, 0.20, 0.13, 0.09, 0.030, 0.15),
    "Nordeste": (0.40, 0.23, 0.12, 0.07, 0.025, 0.13),
    "Sul": (0.35, 0.19, 0.12, 0.11, 0.030, 0.15),
    "Centro-Oeste": (0.37, 0.21, 0.12, 0.08, 0.040, 0.12),
}
# Marcas fictícias de cada setor; cada produto-base é vendido em algumas delas
MARCAS_POR_SETOR = {
    "Alimentos": (
        "Campo Verde", "Sabor da Terra", "Mesa Farta", "Bom Grão",
        "Fazenda Dourada", "Casa Nobre", "Nutri Vida", "Colheita Feliz",
    ),
    "Bebidas": (
        "Fonte Clara", "Vale Dourado", "Gole Real", "Serra Azul",
        "Fruta Viva", "Brisa Gelada", "Barril do Sul", "Uva Nobre",
    ),
    "Limpeza": (
        "Brilho Real", "Lar Limpo", "Espuma Nova", "Pura Casa",
        "Cheiro Bom", "Limpa Tudo", "Azul Brilhante", "Flor de Lavanda",
    ),
    "Casa": (
        "Doce Lar", "Casa Viva", "Ninho", "Lar e Arte",
        "Toque Suave", "Madeira Nobre", "Vida Prática", "Conforto Real",
    ),
    "Eletro": (
        "Eletrolar", "Tecnoval", "Voltmax", "Climatiza",
        "Domus", "Nova Era", "Lumina", "Prisma",
    ),
    "Cuidados Pessoais": (
        "Bela Pele", "Viva Bem", "Aurora", "Fio de Seda",
        "Sol Maior", "Pura Pele", "Cuida Mais", "Essência",
    ),
}  # fmt: skip
CIDADES_VIZINHAS = {
    "SP": ("Santos", "Sorocaba", "Jundiaí", "Guarulhos"),
    "RJ": ("Duque de Caxias", "Petrópolis", "Nova Iguaçu"),
    "MG": ("Contagem", "Betim", "Uberaba"),
    "BA": ("Lauro de Freitas", "Feira de Santana"),
    "PE": ("Olinda", "Jaboatão dos Guararapes"),
    "PR": ("São José dos Pinhais", "Londrina"),
    "RS": ("Canoas", "Novo Hamburgo"),
    "GO": ("Aparecida de Goiânia", "Anápolis"),
    "SC": ("São José", "Palhoça"),
    "CE": ("Caucaia", "Maracanaú"),
    "DF": ("Taguatinga", "Ceilândia"),
}
SUFIXO_CC = {
    config.TIPO_PESSOAL: "PES",
    config.TIPO_TERCEIROS: "TER",
    config.TIPO_DISCRICIONARIAS: "DIS",
}
# Descrições típicas de lançamento por tipo de despesa (um lançamento fora do seu tipo = erro)
DESCRICOES_POR_TIPO = {
    config.TIPO_PESSOAL: (
        "Folha de pagamento",
        "Encargos sociais (INSS/FGTS)",
        "Vale-transporte e refeição",
        "Horas extras",
        "Provisão de férias",
    ),
    config.TIPO_TERCEIROS: (
        "Serviço de limpeza terceirizado",
        "Vigilância e segurança",
        "Manutenção predial",
        "Transporte e fretes",
        "Assessoria contábil",
        "Licença de software",
    ),
    config.TIPO_DISCRICIONARIAS: (
        "Material de marketing",
        "Material de escritório",
        "Viagens e hospedagem",
        "Confraternização",
        "Brindes e eventos",
        "Treinamentos",
    ),
}


@dataclass(frozen=True)
class Loja:
    cod_loja: str
    nome_loja: str
    uf: str
    regiao: str
    cidade: str
    formato: str
    data_abertura: date
    porte: float  # peso no volume de vendas e nos orçamentos
    atingimento_meta: float  # realizado / meta típico da loja
    fator_preco: float  # variação regional de preço


@dataclass(frozen=True)
class Produto:
    sku: str
    nome_produto: str
    setor: str
    categoria: str
    marca: str
    custo_unitario: float
    preco_lista: float
    popularidade: float  # peso dentro do setor


@dataclass(frozen=True)
class CentroCusto:
    cod_centro_custo: str
    nome_centro_custo: str
    tipo_despesa: str
    cod_loja: str | None  # None = corporativo
    percentual_receita: float  # fração da receita líquida (da loja ou da rede) orçada


@dataclass(frozen=True)
class Vendedor:
    cod_vendedor: str
    nome_vendedor: str
    cod_loja: str
    cargo: str
    turno: str
    data_admissao: date
    data_desligamento: date | None
    percentual_comissao: float
    desempenho: float  # peso na escolha do vendedor de cada cupom


@dataclass(frozen=True)
class Cliente:
    cod_cliente: str
    cod_loja: str  # loja onde costuma comprar
    cidade: str
    uf: str
    faixa_etaria: str
    data_cadastro: date
    peso_recorrencia: float


@dataclass(frozen=True)
class Campanha:
    cod_campanha: str
    nome_campanha: str
    data_inicio: date
    data_fim: date
    desconto_medio: float  # fração (0,12 = 12%)


@dataclass(frozen=True)
class Catalogo:
    lojas: tuple[Loja, ...]
    produtos: tuple[Produto, ...]
    centros_custo: tuple[CentroCusto, ...]
    vendedores: tuple[Vendedor, ...]
    clientes: tuple[Cliente, ...]
    campanhas: tuple[Campanha, ...]
    fornecedores_por_tipo: dict[str, tuple[str, ...]]

    def mix_setor_por_loja(self) -> np.ndarray:
        """Matriz (lojas x setores) com a probabilidade de cada setor por loja."""
        mix = np.array([MIX_SETOR_POR_REGIAO[loja.regiao] for loja in self.lojas], dtype=float)
        return mix / mix.sum(axis=1, keepdims=True)


_LOJAS = (
    Loja("L01", "Ipê São Paulo", "SP", "Sudeste", "São Paulo", "Hipermercado", date(2010, 3, 12), 1.6, 1.06, 1.03),
    Loja("L02", "Ipê Campinas", "SP", "Sudeste", "Campinas", "Supermercado", date(2013, 8, 20), 1.1, 0.97, 1.00),
    Loja("L03", "Ipê Ribeirão Preto", "SP", "Sudeste", "Ribeirão Preto", "Supermercado", date(2015, 5, 5), 0.9, 1.02, 0.99),
    Loja("L04", "Ipê Rio de Janeiro", "RJ", "Sudeste", "Rio de Janeiro", "Hipermercado", date(2011, 10, 1), 1.5, 0.92, 1.04),
    Loja("L05", "Ipê Niterói", "RJ", "Sudeste", "Niterói", "Supermercado", date(2016, 2, 15), 0.8, 0.89, 1.02),
    Loja("L06", "Ipê Belo Horizonte", "MG", "Sudeste", "Belo Horizonte", "Hipermercado", date(2012, 6, 30), 1.3, 1.04, 1.00),
    Loja("L07", "Ipê Uberlândia", "MG", "Sudeste", "Uberlândia", "Supermercado", date(2017, 9, 10), 0.8, 1.08, 0.98),
    Loja("L08", "Ipê Salvador", "BA", "Nordeste", "Salvador", "Hipermercado", date(2014, 11, 22), 1.2, 0.94, 0.99),
    Loja("L09", "Ipê Recife", "PE", "Nordeste", "Recife", "Supermercado", date(2018, 4, 18), 0.9, 0.87, 0.98),
    Loja("L10", "Ipê Curitiba", "PR", "Sul", "Curitiba", "Hipermercado", date(2013, 3, 9), 1.2, 1.10, 1.01),
    Loja("L11", "Ipê Porto Alegre", "RS", "Sul", "Porto Alegre", "Supermercado", date(2015, 10, 25), 1.0, 0.98, 1.00),
    Loja("L12", "Ipê Goiânia", "GO", "Centro-Oeste", "Goiânia", "Supermercado", date(2016, 7, 14), 0.9, 1.01, 0.98),
    Loja("L13", "Ipê Florianópolis", "SC", "Sul", "Florianópolis", "Express", date(2019, 1, 12), 0.5, 0.95, 1.03),
    Loja("L14", "Ipê Fortaleza", "CE", "Nordeste", "Fortaleza", "Supermercado", date(2024, 6, 15), 0.7, 0.91, 0.97),
    Loja("L15", "Ipê Brasília", "DF", "Centro-Oeste", "Brasília", "Express", date(2025, 3, 3), 0.5, 1.03, 1.02),
)  # fmt: skip

# Produtos-base por setor (nome, categoria, preço de lista), do mais para o menos vendido.
# Cada um vira vários SKUs, um por marca (ver _montar_produtos).
_PRODUTOS = {
    "Alimentos": (
        ("Arroz Tipo 1 5kg", "Mercearia", 28.90),
        ("Feijão Carioca 1kg", "Mercearia", 8.49),
        ("Leite Integral 1L", "Laticínios", 5.49),
        ("Café Torrado 500g", "Matinais", 18.90),
        ("Açúcar Refinado 1kg", "Mercearia", 4.69),
        ("Óleo de Soja 900ml", "Mercearia", 7.79),
        ("Macarrão Espaguete 500g", "Massas", 4.99),
        ("Biscoito Recheado 140g", "Biscoitos", 3.79),
        ("Pão de Forma 500g", "Padaria", 8.90),
        ("Farinha de Trigo 1kg", "Mercearia", 5.99),
        ("Molho de Tomate 340g", "Molhos", 3.29),
        ("Frango Congelado 1kg", "Congelados", 12.90),
        ("Ovos Dúzia", "Ovos", 11.90),
        ("Margarina 500g", "Laticínios", 7.90),
        ("Sal Refinado 1kg", "Mercearia", 3.49),
        ("Iogurte Natural 170g", "Laticínios", 3.20),
        ("Queijo Mussarela kg", "Frios", 42.90),
        ("Presunto Fatiado 200g", "Frios", 11.90),
        ("Cereal Matinal 300g", "Matinais", 14.90),
        ("Atum em Lata 170g", "Enlatados", 9.90),
        ("Milho em Conserva 200g", "Enlatados", 3.99),
        ("Achocolatado 400g", "Matinais", 9.50),
        ("Salgadinho 100g", "Snacks", 7.50),
        ("Sorvete 2L", "Congelados", 24.90),
    ),
    "Bebidas": (
        ("Refrigerante Cola 2L", "Refrigerantes", 9.49),
        ("Água Mineral 1,5L", "Águas", 2.99),
        ("Cerveja Pilsen Lata 350ml", "Cervejas", 3.99),
        ("Refrigerante Guaraná 2L", "Refrigerantes", 8.99),
        ("Suco de Laranja 1L", "Sucos", 8.90),
        ("Cerveja Pilsen Pack 12un", "Cervejas", 42.90),
        ("Energético 473ml", "Energéticos", 8.99),
        ("Chá Gelado 1,5L", "Chás", 7.49),
        ("Água de Coco 1L", "Águas", 11.90),
        ("Isotônico 500ml", "Energéticos", 5.99),
        ("Refrigerante Laranja 2L", "Refrigerantes", 8.49),
        ("Água com Gás 500ml", "Águas", 2.79),
        ("Cerveja Long Neck 330ml", "Cervejas", 5.49),
        ("Néctar de Uva 1L", "Sucos", 9.90),
        ("Vinho Tinto Suave 750ml", "Vinhos", 32.90),
        ("Cachaça Prata 700ml", "Destilados", 24.90),
        ("Vinho Branco Seco 750ml", "Vinhos", 36.90),
        ("Whisky 1L", "Destilados", 89.90),
    ),
    "Limpeza": (
        ("Detergente Líquido 500ml", "Cozinha", 2.79),
        ("Sabão em Pó 1,6kg", "Roupas", 24.90),
        ("Papel Higiênico 12 rolos", "Papéis", 21.90),
        ("Água Sanitária 2L", "Banheiro", 6.49),
        ("Amaciante 2L", "Roupas", 15.90),
        ("Desinfetante 1L", "Banheiro", 6.99),
        ("Esponja Multiuso 3un", "Cozinha", 4.99),
        ("Limpador Multiuso 500ml", "Geral", 5.49),
        ("Saco de Lixo 30L 10un", "Geral", 7.90),
        ("Papel Toalha 2 rolos", "Papéis", 8.90),
        ("Sabão em Barra 5un", "Roupas", 9.90),
        ("Álcool 70% 1L", "Geral", 8.90),
        ("Vassoura", "Utensílios", 14.90),
        ("Rodo", "Utensílios", 19.90),
        ("Pano de Chão", "Utensílios", 6.90),
        ("Limpa Vidros 500ml", "Geral", 8.50),
        ("Inseticida Aerossol 300ml", "Geral", 16.90),
    ),
    "Casa": (
        ("Jogo de Toalhas de Banho", "Cama e Banho", 69.90),
        ("Organizador Plástico", "Organização", 29.90),
        ("Jarra de Vidro 1,5L", "Cozinha", 24.90),
        ("Travesseiro", "Cama e Banho", 34.90),
        ("Lençol Casal", "Cama e Banho", 79.90),
        ("Cesto de Roupa", "Organização", 39.90),
        ("Conjunto de Pratos 12 peças", "Cozinha", 99.90),
        ("Luminária de Mesa", "Decoração", 59.90),
        ("Conjunto de Copos 6un", "Cozinha", 32.90),
        ("Jogo de Panelas 5 peças", "Cozinha", 189.90),
        ("Pote Hermético Kit 5un", "Organização", 44.90),
        ("Jogo de Facas 6 peças", "Cozinha", 54.90),
        ("Cobertor Casal", "Cama e Banho", 119.90),
        ("Tapete de Sala", "Decoração", 89.90),
        ("Cortina 2,2m", "Decoração", 74.90),
        ("Edredom Casal", "Cama e Banho", 159.90),
    ),
    "Eletro": (
        ("Sanduicheira", "Pequenos Eletros", 99.90),
        ("Liquidificador 700W", "Pequenos Eletros", 149.90),
        ("Ventilador de Mesa 40cm", "Climatização", 189.90),
        ("Ferro a Vapor", "Pequenos Eletros", 139.90),
        ("Panela Elétrica de Arroz", "Pequenos Eletros", 159.90),
        ("Cafeteira Elétrica", "Pequenos Eletros", 159.90),
        ("Aspirador de Pó", "Pequenos Eletros", 299.90),
        ("Fritadeira Elétrica 4L", "Pequenos Eletros", 349.90),
        ("Batedeira Planetária", "Pequenos Eletros", 399.90),
        ("Micro-ondas 20L", "Linha Branca", 549.00),
        ("Fogão 4 Bocas", "Linha Branca", 899.00),
        ("Smart TV 43 polegadas", "Imagem e Som", 1899.00),
        ("Máquina de Lavar 11kg", "Linha Branca", 1899.00),
        ("Geladeira Frost Free 370L", "Linha Branca", 3299.00),
    ),
    "Cuidados Pessoais": (
        ("Sabonete 90g", "Banho", 2.49),
        ("Creme Dental 90g", "Higiene Bucal", 4.29),
        ("Shampoo 350ml", "Cabelos", 14.90),
        ("Condicionador 350ml", "Cabelos", 14.90),
        ("Desodorante Aerosol 150ml", "Banho", 12.90),
        ("Escova Dental", "Higiene Bucal", 6.90),
        ("Absorvente 8un", "Higiene Feminina", 6.49),
        ("Hidratante Corporal 400ml", "Pele", 19.90),
        ("Fralda Descartável M 30un", "Infantil", 39.90),
        ("Protetor Solar FPS 50 200ml", "Pele", 39.90),
        ("Barbeador Descartável 4un", "Barba", 12.90),
        ("Enxaguante Bucal 500ml", "Higiene Bucal", 14.90),
        ("Lenço Umedecido 50un", "Infantil", 9.90),
        ("Cotonete 75un", "Banho", 4.50),
        ("Creme para Pentear 300ml", "Cabelos", 16.90),
        ("Perfume Feminino 100ml", "Perfumaria", 119.90),
        ("Perfume Masculino 100ml", "Perfumaria", 109.90),
        ("Aparelho de Barbear Elétrico", "Barba", 79.90),
    ),
}

_CENTROS_CORPORATIVOS = (
    ("COR-RH", "Recursos Humanos", config.TIPO_PESSOAL),
    ("COR-FIN", "Financeiro", config.TIPO_PESSOAL),
    ("COR-TI", "Tecnologia da Informação", config.TIPO_TERCEIROS),
    ("COR-LOG", "Logística Central", config.TIPO_TERCEIROS),
    ("COR-MKT", "Marketing", config.TIPO_DISCRICIONARIAS),
    ("COR-DIR", "Diretoria", config.TIPO_DISCRICIONARIAS),
)


def _preco_de_vitrine(preco: float) -> float:
    """Termina em ,x9 (preço psicológico), sem deixar o preço chegar a zero."""
    return round(max(round(preco, 1) - 0.01, 0.99), config.CASAS_DECIMAIS_DINHEIRO)


def _montar_produtos(semente: int) -> tuple[Produto, ...]:
    """Um SKU por produto-base e marca. A popularidade é desigual: poucos SKUs vendem muito."""
    rng = rng_para(semente, config.FLUXO_CATALOGO)
    produtos = []
    for setor in SETORES:
        marcas = MARCAS_POR_SETOR[setor]
        posicao = 0
        for ranking, (nome, categoria, preco) in enumerate(_PRODUTOS[setor], start=1):
            peso_base = 1.0 / ranking**config.EXPOENTE_POPULARIDADE_SKU
            n_marcas = config.MARCAS_POR_PRODUTO[setor]
            escolhidas = rng.choice(len(marcas), size=n_marcas, replace=False)
            for (peso_marca, mult_preco), indice_marca in zip(
                config.PERFIL_MARCAS, escolhidas, strict=False
            ):
                posicao += 1
                preco_sku = _preco_de_vitrine(preco * mult_preco)
                fracao_custo = rng.uniform(*FAIXA_CUSTO_POR_SETOR[setor])
                ruido = rng.lognormal(0.0, config.DESVIO_RUIDO_POPULARIDADE)
                produtos.append(
                    Produto(
                        sku=f"{PREFIXO_SKU[setor]}-{posicao:04d}",
                        nome_produto=f"{nome} {marcas[indice_marca]}",
                        setor=setor,
                        categoria=categoria,
                        marca=marcas[indice_marca],
                        custo_unitario=round(
                            preco_sku * fracao_custo, config.CASAS_DECIMAIS_DINHEIRO
                        ),
                        preco_lista=preco_sku,
                        popularidade=float(peso_base * peso_marca * ruido),
                    )
                )
    return tuple(produtos)


def _montar_centros_custo() -> tuple[CentroCusto, ...]:
    centros = []
    for loja in _LOJAS:
        for tipo, percentual in config.PERCENTUAL_DESPESA_LOJA.items():
            centros.append(
                CentroCusto(
                    cod_centro_custo=f"{loja.cod_loja}-{SUFIXO_CC[tipo]}",
                    nome_centro_custo=f"{loja.nome_loja} - {tipo}",
                    tipo_despesa=tipo,
                    cod_loja=loja.cod_loja,
                    percentual_receita=percentual,
                )
            )
    for cod, nome, tipo in _CENTROS_CORPORATIVOS:
        percentual = config.PERCENTUAL_DESPESA_CORPORATIVO[cod]
        centros.append(CentroCusto(cod, nome, tipo, None, percentual))
    return tuple(centros)


def horario_funcionamento(formato: str, dia_semana: int) -> tuple[int, int]:
    """(hora de abertura, hora de fechamento exclusiva) do formato num dia da semana (seg = 0)."""
    horarios = config.HORARIOS_POR_FORMATO[formato]
    return horarios["domingo"] if dia_semana == config.DIA_SEMANA_DOMINGO else horarios["semana"]


def _dia_aleatorio(rng: np.random.Generator, inicio: date, fim: date) -> date:
    return inicio + timedelta(days=int(rng.integers(0, (fim - inicio).days + 1)))


def _montar_vendedores(
    fake: Faker, rng: np.random.Generator, data_inicio: date, data_fim: date
) -> tuple[Vendedor, ...]:
    portes = [lj.porte for lj in _LOJAS]
    minimo, maximo = config.VENDEDORES_POR_LOJA
    vendedores: list[Vendedor] = []

    def novo(loja, cargo, turno, admissao, desligamento, veterano=False) -> None:
        desempenho = float(np.exp(rng.normal(0, config.DESVIO_DESEMPENHO_VENDEDOR)))
        if veterano:
            desempenho *= config.BONUS_DESEMPENHO_VETERANO
        vendedores.append(
            Vendedor(
                cod_vendedor=f"V{len(vendedores) + 1:04d}",
                nome_vendedor=f"{fake.first_name()} {fake.last_name()}",
                cod_loja=loja.cod_loja,
                cargo=cargo,
                turno=turno,
                data_admissao=admissao,
                data_desligamento=desligamento,
                percentual_comissao=config.CARGOS_COMISSAO[cargo],
                desempenho=desempenho,
            )
        )

    for loja in _LOJAS:
        quantidade = round(
            minimo + (loja.porte - min(portes)) * (maximo - minimo) / (max(portes) - min(portes))
        )
        loja_nova = loja.data_abertura >= data_inicio
        for k in range(quantidade):
            if loja_nova:
                dias = int(rng.integers(*config.DIAS_ANTES_ABERTURA_ADMISSAO))
                admissao_inicial = loja.data_abertura - timedelta(days=dias)
            else:
                dias = int(rng.integers(*config.DIAS_ADMISSAO_VETERANO))
                admissao_inicial = max(
                    loja.data_abertura - timedelta(days=15), data_inicio - timedelta(days=dias)
                )
            if k < config.VENDEDORES_VETERANOS_FIXOS:
                cargo = "Líder de Vendas" if k == 0 else "Vendedor Sênior"
                novo(loja, cargo, config.TURNO_INTEGRAL, admissao_inicial, None, veterano=True)
                continue
            turno = config.TURNO_MANHA if rng.random() < 0.5 else config.TURNO_TARDE
            cargo = "Vendedor Sênior" if rng.random() < 0.2 else "Vendedor"
            sorteio = rng.random()
            if sorteio < config.PROB_VENDEDOR_DESLIGADO:
                primeiro = max(data_inicio, loja.data_abertura) + timedelta(
                    days=config.DIAS_MINIMOS_ANTES_DESLIGAMENTO
                )
                ultimo = data_fim - timedelta(days=config.DIAS_MINIMOS_ANTES_DESLIGAMENTO)
                desligamento = _dia_aleatorio(rng, primeiro, ultimo)
                novo(loja, cargo, turno, admissao_inicial, desligamento)
                dias_reposicao = int(rng.integers(*config.DIAS_REPOSICAO_VENDEDOR))
                reposicao = desligamento + timedelta(days=dias_reposicao)
                if reposicao <= data_fim:
                    novo(loja, "Vendedor", turno, reposicao, None)
            elif (
                sorteio < config.PROB_VENDEDOR_DESLIGADO + config.PROB_VENDEDOR_ADMITIDO_NO_PERIODO
            ):
                admissao = _dia_aleatorio(
                    rng, max(data_inicio, loja.data_abertura), data_fim - timedelta(days=90)
                )
                novo(loja, cargo, turno, admissao, None)
            else:
                novo(loja, cargo, turno, admissao_inicial, None)
    return tuple(vendedores)


def _montar_clientes(
    rng: np.random.Generator, data_inicio: date, data_fim: date
) -> tuple[Cliente, ...]:
    portes = np.array([lj.porte for lj in _LOJAS])
    por_loja = rng.multinomial(config.TOTAL_CLIENTES, portes / portes.sum())
    faixas, pesos_faixas = zip(*config.FAIXAS_ETARIAS, strict=True)
    clientes: list[Cliente] = []
    for loja, quantidade in zip(_LOJAS, por_loja, strict=True):
        cidades = CIDADES_VIZINHAS[loja.uf]
        for _ in range(int(quantidade)):
            if rng.random() < config.FRACAO_CLIENTES_CADASTRADOS_NO_PERIODO:
                cadastro = _dia_aleatorio(rng, data_inicio, data_fim)
            else:
                cadastro = _dia_aleatorio(
                    rng, config.CADASTRO_FIDELIDADE_INICIO, data_inicio - timedelta(days=1)
                )
            cadastro = max(cadastro, loja.data_abertura)
            vizinha = rng.random() < config.PROB_CIDADE_VIZINHA
            clientes.append(
                Cliente(
                    cod_cliente=f"C{len(clientes) + 1:05d}",
                    cod_loja=loja.cod_loja,
                    cidade=cidades[int(rng.integers(0, len(cidades)))] if vizinha else loja.cidade,
                    uf=loja.uf,
                    faixa_etaria=str(rng.choice(faixas, p=pesos_faixas)),
                    data_cadastro=cadastro,
                    peso_recorrencia=float(rng.gamma(config.FORMA_GAMMA_FIDELIDADE)) + 0.01,
                )
            )
    return tuple(clientes)


def _montar_campanhas(data_inicio: date, data_fim: date) -> tuple[Campanha, ...]:
    campanhas = []
    for ano in range(data_inicio.year, data_fim.year + 1):
        for posicao, (nome, inicio, fim) in enumerate(calendario.campanhas_do_ano(ano), start=1):
            campanhas.append(
                Campanha(
                    cod_campanha=f"CMP{ano}{posicao:02d}",
                    nome_campanha=nome,
                    data_inicio=inicio,
                    data_fim=fim,
                    desconto_medio=config.DESCONTO_MEDIO_CAMPANHA[nome],
                )
            )
    return tuple(campanhas)


def montar_catalogo(
    semente: int = config.SEMENTE_ALEATORIA,
    data_inicio: date = config.DATA_INICIO,
    data_fim: date = config.DATA_FIM,
) -> Catalogo:
    fake = Faker("pt_BR")
    fake.seed_instance(semente)
    rng = rng_para(semente, config.FLUXO_CATALOGO, 1)
    fornecedores = {
        tipo: tuple(fake.company() for _ in range(config.FORNECEDORES_POR_TIPO))
        for tipo in config.PERCENTUAL_DESPESA_LOJA
    }
    return Catalogo(
        lojas=_LOJAS,
        produtos=_montar_produtos(semente),
        centros_custo=_montar_centros_custo(),
        vendedores=_montar_vendedores(fake, rng, data_inicio, data_fim),
        clientes=_montar_clientes(rng, data_inicio, data_fim),
        campanhas=_montar_campanhas(data_inicio, data_fim),
        fornecedores_por_tipo=fornecedores,
    )
