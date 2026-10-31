"""Constantes e parâmetros do projeto Lojas Ipê. Nenhum número mágico fora deste arquivo."""

from datetime import date
from pathlib import Path

# --- Caminhos ---------------------------------------------------------------------------------
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DIR_DADOS_BRUTOS = RAIZ_PROJETO / "data" / "raw"
DIR_DDL = RAIZ_PROJETO / "sql" / "ddl"
DIR_PROCEDURES = RAIZ_PROJETO / "sql" / "procedures"
DIR_VIEWS = RAIZ_PROJETO / "sql" / "views"

# --- Banco de dados ---------------------------------------------------------------------------
NOME_BANCO_DW = "lojas_ipe_dw"
SCHEMA_STAGING = "stg"
SCHEMA_DW = "dw"
DRIVER_SQLALCHEMY = "postgresql+psycopg"
PORTA_PADRAO_BANCO = 5432
SERVIDOR_PADRAO_BANCO = "localhost"
# Scripts de DDL aplicados em ordem; o 00 (criação de banco/usuário) é administrativo e fica fora.
PREFIXO_SCRIPT_ADMIN = "00_"

# Variáveis de ambiente (valores vêm do .env)
VAR_BD_SERVIDOR = "BD_SERVIDOR"
VAR_BD_PORTA = "BD_PORTA"
VAR_BD_NOME = "BD_NOME"
VAR_BD_USUARIO = "BD_USUARIO"
VAR_BD_SENHA = "BD_SENHA"
VAR_BD_TESTE_SERVIDOR = "BD_TESTE_SERVIDOR"
VAR_BD_TESTE_PORTA = "BD_TESTE_PORTA"
VAR_BD_TESTE_USUARIO = "BD_TESTE_USUARIO"
VAR_BD_TESTE_SENHA = "BD_TESTE_SENHA"

# --- Memória (computador com ~3,9 GB de RAM) --------------------------------------------------
MEMORIA_LIVRE_MINIMA_GB = 0.4
INTERVALO_VIGIA_MEMORIA_S = 2.0  # de quanto em quanto tempo a carga confere a memória livre
TOLERANCIA_PISO_MEMORIA_S = 6.0  # abaixo do piso por mais que isso, seguido: aborta a carga
BYTES_POR_GB = 1024**3

# --- Gerador: parâmetros gerais ---------------------------------------------------------------
SEMENTE_ALEATORIA = 20240101
DATA_INICIO = date(2024, 1, 1)
DATA_FIM = date(2025, 12, 31)
TOTAL_LINHAS_VENDA = 300_000
SEPARADOR_CSV = ";"
CODIFICACAO_CSV = "utf-8"
FORMATO_DATA_BR = "%d/%m/%Y"
FORMATO_DATA_ISO = "%Y-%m-%d"

# Identificadores dos fluxos aleatórios (cada parte do gerador tem o seu, para ser independente)
FLUXO_CATALOGO = 1
FLUXO_VENDAS = 2
FLUXO_DESPESAS = 3
FLUXO_PLANO_ANOMALIAS = 4
FLUXO_METAS = 5
FLUXO_QUALIDADE_VENDAS = 6
FLUXO_QUALIDADE_DESPESAS = 7

# Nomes dos arquivos gerados em data/raw/
ARQ_LOJAS = "lojas.csv"
ARQ_PRODUTOS = "produtos.csv"
ARQ_CENTROS_CUSTO = "centros_custo.csv"
ARQ_FERIADOS = "feriados.csv"
ARQ_HORARIOS = "horarios_loja.csv"
ARQ_FORMAS_PAGAMENTO = "formas_pagamento.csv"
ARQ_CAMPANHAS = "campanhas.csv"
ARQ_VENDEDORES = "vendedores.csv"
ARQ_CLIENTES = "clientes.csv"
ARQ_METAS_VENDEDOR = "metas_vendedor.csv"
ARQ_METAS = "metas_vendas.csv"
ARQ_DESPESAS = "despesas.csv"
ARQ_ORCAMENTO = "orcamento_despesas.csv"
ARQ_ANOMALIAS = "_anomalias_injetadas.csv"
ARQ_PROBLEMAS = "_problemas_qualidade.csv"
MODELO_ARQ_VENDAS = "vendas_{ano}-{mes:02d}.csv"
# Exemplo de fonte de "outra empresa": planilha Excel com as vendas de um mês
PASTA_OUTRA_EMPRESA = "outra_empresa"
MODELO_ARQ_OUTRA_EMPRESA = "vendas_{ano}-{mes:02d}.xlsx"
MES_EXEMPLO_OUTRA_EMPRESA = (2024, 3)

# --- Calendário e sazonalidade brasileira -----------------------------------------------------
FERIADOS_FIXOS = (
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (12, 25, "Natal"),
)
FERIADO_CONSCIENCIA_NEGRA = (11, 20, "Dia Nacional de Zumbi e da Consciência Negra")
ANO_INICIO_CONSCIENCIA_NEGRA = 2024  # feriado nacional a partir da Lei 14.759/2023
DIAS_SEXTA_SANTA_ANTES_PASCOA = 2
DIAS_CARNAVAL_ANTES_PASCOA = 47  # terça-feira de carnaval

NOMES_MESES = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)
NOMES_DIAS_SEMANA = (
    "Segunda-feira",
    "Terça-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sábado",
    "Domingo",
)
DIA_SEMANA_FIM_DE_SEMANA_INICIO = 5  # sábado (segunda = 0)

CRESCIMENTO_ANUAL_VENDAS = 0.06
DIAS_POR_ANO = 365
FATOR_SAZONAL_MES = {
    1: 0.92,
    2: 0.95,
    3: 0.93,
    4: 0.97,
    5: 1.08,
    6: 0.96,
    7: 0.98,
    8: 0.97,
    9: 0.96,
    10: 1.00,
    11: 1.18,
    12: 1.40,
}
FATOR_DIA_SEMANA = {
    0: 0.90,
    1: 0.88,
    2: 0.92,
    3: 0.95,
    4: 1.10,
    5: 1.25,
    6: 0.70,
}  # domingo reduzido

# Fatores por dia, relativos a uma data âncora do evento
BLACK_FRIDAY_FATORES = {-1: 1.5, 0: 2.6, 1: 1.8, 2: 1.3, 3: 1.4}  # âncora: sexta-feira
DIA_DAS_MAES_FATORES = {-7: 1.1, -6: 1.1, -5: 1.15, -4: 1.2, -3: 1.3, -2: 1.5, -1: 1.9, 0: 1.4}
CARNAVAL_FATORES = {-3: 0.70, -2: 0.60, -1: 0.55, 0: 0.55, 1: 0.80}  # âncora: terça de carnaval
NATAL_JANELA_DIAS = (18, 24)
NATAL_FATOR_JANELA = 1.5
NATAL_FATOR_DIA = 0.25
ANO_NOVO_FATOR_DIA = 0.35
VESPERA_ANO_NOVO_FATOR = 1.2
VOLTA_AS_AULAS_DIAS = (1, 14)  # dias de fevereiro
VOLTA_AS_AULAS_FATOR = 1.12
FATOR_FERIADO_NACIONAL = 0.85

# Multiplicadores do mix de setores
MULT_SETOR_MES = {
    2: {"Casa": 1.35, "Limpeza": 1.10, "Cuidados Pessoais": 1.10},
    5: {"Eletro": 1.50, "Casa": 1.25, "Cuidados Pessoais": 1.40},
    11: {"Eletro": 1.90, "Casa": 1.20},
    12: {"Alimentos": 1.35, "Bebidas": 1.50, "Eletro": 1.30},
}
MULT_SETOR_BLACK_FRIDAY = {"Eletro": 2.5, "Casa": 1.5}

# --- Gerador: vendas --------------------------------------------------------------------------
QUANTIDADE_MEDIA_EXTRA_POR_SETOR = {  # lambda da Poisson somada a 1 unidade
    "Alimentos": 1.0,
    "Bebidas": 1.5,
    "Limpeza": 0.7,
    "Casa": 0.3,
    "Eletro": 0.05,
    "Cuidados Pessoais": 0.6,
}
# Catálogo: cada produto-base é vendido em algumas marcas (peso de venda, multiplicador de preço)
MARCAS_POR_PRODUTO = {
    "Alimentos": 4,
    "Bebidas": 4,
    "Limpeza": 4,
    "Casa": 3,
    "Eletro": 3,
    "Cuidados Pessoais": 4,
}
PERFIL_MARCAS = ((0.45, 1.00), (0.28, 0.86), (0.17, 1.22), (0.10, 1.45))
EXPOENTE_POPULARIDADE_SKU = 1.0  # Zipf entre os produtos-base de um setor
DESVIO_RUIDO_POPULARIDADE = 0.35  # variação lognormal da popularidade de cada SKU
PROB_DESCONTO_NORMAL = 0.30
FAIXA_DESCONTO_NORMAL = (0.03, 0.12)
DESCONTO_MAXIMO = (
    0.18  # limite permitido; com custo <= 72% do preço a margem natural nunca fica negativa
)
CASAS_DECIMAIS_DINHEIRO = 2

# --- Gerador: despesas e orçamento ------------------------------------------------------------
TIPO_PESSOAL = "Pessoal"
TIPO_TERCEIROS = "Terceiros"
TIPO_DISCRICIONARIAS = "Discricionárias"
# O orçamento é derivado da receita líquida (média mensal do ano): cada centro recebe um
# percentual dela. Lojas: percentual da receita da própria loja; centros corporativos:
# percentual da receita da rede. Total esperado: ~22% da receita líquida, pessoal o maior bloco.
PERCENTUAL_DESPESA_LOJA = {
    TIPO_PESSOAL: 0.095,
    TIPO_TERCEIROS: 0.045,
    TIPO_DISCRICIONARIAS: 0.025,
}
PERCENTUAL_DESPESA_CORPORATIVO = {
    "COR-RH": 0.013,
    "COR-FIN": 0.012,
    "COR-TI": 0.010,
    "COR-LOG": 0.010,
    "COR-MKT": 0.009,
    "COR-DIR": 0.006,
}
ORCAMENTO_MINIMO_CENTRO = 50.0  # piso mensal por centro (evita orçamento zero em loja sem venda)
FATOR_ORCAMENTO_PESSOAL_MES = {12: 1.5}  # 13º salário
FAIXA_REALIZACAO_ORCAMENTO = (0.93, 1.03)
LANCAMENTOS_POR_TIPO = {TIPO_PESSOAL: 3, TIPO_TERCEIROS: 4, TIPO_DISCRICIONARIAS: 4}
ALFA_DIRICHLET_LANCAMENTOS = 4.0
PREFIXO_DOCUMENTO = "DOC"
DIGITOS_DOCUMENTO = 7
PREFIXO_ID_VENDA = "VD"
DIGITOS_ID_VENDA = 6

# --- Gerador: anomalias propositais (gabarito da Fase 3) --------------------------------------
ANOMALIA_DESPESA_DUPLICADA = "despesa_duplicada"
ANOMALIA_VALOR_ATIPICO = "despesa_valor_atipico"
ANOMALIA_CENTRO_CUSTO_ERRADO = "centro_custo_errado"
ANOMALIA_FIM_SEMANA_FERIADO = "lancamento_fim_semana_feriado"
ANOMALIA_MARGEM_NEGATIVA = "venda_margem_negativa"
ANOMALIA_ACIMA_ORCADO = "despesa_acima_orcado"
ANOMALIA_FORA_HORARIO = "venda_fora_horario"
ANOMALIA_DESCONTO_ACIMA_LIMITE = "desconto_acima_limite"
ANOMALIA_VENDEDOR_CANCELAMENTO = "vendedor_cancelamento_alto"
ANOMALIA_CUPOM_DUPLICADO = "cupom_duplicado"
QUANTIDADE_ANOMALIAS = {
    ANOMALIA_DESPESA_DUPLICADA: 12,
    ANOMALIA_VALOR_ATIPICO: 10,
    ANOMALIA_CENTRO_CUSTO_ERRADO: 12,
    ANOMALIA_FIM_SEMANA_FERIADO: 15,
    ANOMALIA_MARGEM_NEGATIVA: 30,
    ANOMALIA_ACIMA_ORCADO: 8,
    ANOMALIA_FORA_HORARIO: 10,
    ANOMALIA_DESCONTO_ACIMA_LIMITE: 15,
    ANOMALIA_VENDEDOR_CANCELAMENTO: 2,
    ANOMALIA_CUPOM_DUPLICADO: 8,
}
FAIXA_FATOR_VALOR_ATIPICO = (8.0, 15.0)
FAIXA_FATOR_ACIMA_ORCADO = (1.6, 2.4)
FAIXA_CUSTO_SOBRE_RECEITA_NEGATIVA = (1.15, 1.6)

# --- Gerador: problemas de qualidade para o ETL da Fase 2 -------------------------------------
PROBLEMA_DATA_FORMATO_MISTO = "data_formato_misto"
PROBLEMA_SKU_SUJO = "sku_espacos_maiusculas"
PROBLEMA_VALOR_TEXTO_BR = "valor_texto_formato_br"
PROBLEMA_VALOR_NULO = "valor_nulo"
# Fração das linhas de cada arquivo com algum problema (cada linha recebe um único problema)
TAXA_LINHAS_COM_PROBLEMA = 0.035
PESO_PROBLEMA = {  # chance relativa de cada tipo entre os aplicáveis ao arquivo
    "data": 0.25,
    "hora": 0.20,
    "sku": 0.20,
    "valor": 0.25,
    "nulo": 0.07,
    "nome": 1.00,
}
VARIANTES_SKU_SUJO = 4

# --- Metas de vendas --------------------------------------------------------------------------
DESVIO_ATINGIMENTO_MENSAL = 0.06
ATINGIMENTO_MINIMO = 0.70

# --- Gerador: cupons, horários, vendedores, clientes ------------------------------------------
FLUXO_QUALIDADE_CADASTROS = 8
LAMBDA_ITENS_EXTRA_POR_CUPOM = 2.0  # itens por cupom = 1 + Poisson(2) -> média 3
LIMITE_ITENS_REPARTIDOS = 0.8  # cupons duplicados saem dos primeiros 80% do mês
PROB_CUPOM_EM_CAMPANHA = 0.70
PROB_DESCONTO_CAMPANHA = 0.85
DESVIO_DESCONTO_CAMPANHA = 0.02
FAIXA_DESCONTO_ACIMA_LIMITE = (0.20, 0.25)  # mantém a margem positiva (custo <= 72% do preço)
HORAS_FORA_DO_HORARIO_MAX = 24

# Horário de funcionamento (hora de abertura, hora de fechamento exclusiva) por formato
HORARIOS_POR_FORMATO = {
    "Hipermercado": {"semana": (7, 22), "domingo": (8, 20)},
    "Supermercado": {"semana": (8, 21), "domingo": (9, 18)},
    "Express": {"semana": (7, 22), "domingo": (8, 14)},
}
DIA_SEMANA_DOMINGO = 6
# Peso de cada hora do dia nas vendas: picos no almoço (11-13) e no fim da tarde (17-19)
PESO_POR_HORA = (
    0, 0, 0, 0, 0, 0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.4,
    1.9, 1.6, 1.0, 0.9, 1.1, 1.7, 2.0, 1.5, 0.9, 0.5, 0.2, 0.05,
)  # fmt: skip
HORA_CORTE_TURNO = 14  # antes: turno da manhã; a partir daqui: turno da tarde
FAIXAS_DO_DIA = (
    ("Madrugada", 0, 5),
    ("Manhã", 6, 10),
    ("Almoço", 11, 13),
    ("Tarde", 14, 17),
    ("Noite", 18, 23),
)
CAIXAS_MINIMO = 3
CAIXAS_POR_PORTE = 4.0

TURNO_MANHA = "Manhã"
TURNO_TARDE = "Tarde"
TURNO_INTEGRAL = "Integral"
CARGOS_COMISSAO = {"Vendedor": 1.0, "Vendedor Sênior": 1.5, "Líder de Vendas": 2.0}
VENDEDORES_POR_LOJA = (6, 15)  # lojas menores e maiores
VENDEDORES_VETERANOS_FIXOS = 2  # integrais, nunca desligados (garantem cobertura de turno)
PROB_VENDEDOR_DESLIGADO = 0.25
PROB_VENDEDOR_ADMITIDO_NO_PERIODO = 0.15
DIAS_ANTES_ABERTURA_ADMISSAO = (15, 45)
DIAS_ADMISSAO_VETERANO = (100, 2500)
DIAS_MINIMOS_ANTES_DESLIGAMENTO = 60
DIAS_REPOSICAO_VENDEDOR = (3, 30)
DESVIO_DESEMPENHO_VENDEDOR = 0.35
BONUS_DESEMPENHO_VETERANO = 1.3
ATINGIMENTO_META_VENDEDOR = (0.80, 1.20)

TOTAL_CLIENTES = 5000
PROB_CLIENTE_IDENTIFICADO = 0.30
CADASTRO_FIDELIDADE_INICIO = date(2022, 1, 1)
FRACAO_CLIENTES_CADASTRADOS_NO_PERIODO = 0.30
FORMA_GAMMA_FIDELIDADE = 0.7  # cauda pesada: poucos clientes compram muito
PROB_CIDADE_VIZINHA = 0.20
FAIXAS_ETARIAS = (
    ("18-24", 0.12),
    ("25-34", 0.27),
    ("35-44", 0.25),
    ("45-54", 0.18),
    ("55-64", 0.11),
    ("65+", 0.07),
)

FORMAS_PAGAMENTO = (
    ("PIX", "Pix"),
    ("DEB", "Débito"),
    ("CRV", "Crédito à vista"),
    ("CRP", "Crédito parcelado"),
    ("DIN", "Dinheiro"),
)
# Participação (início, fim do período) de cada forma; Pix cresce e dinheiro cai.
PARTICIPACAO_PAGAMENTO = {
    "PIX": (0.22, 0.50),
    "DEB": (0.25, 0.18),
    "CRV": (0.15, 0.12),
    "CRP": (0.20, 0.14),
    "DIN": (0.18, 0.06),
}
MULT_PARCELADO_ELETRO = 4.0
MULT_DINHEIRO_ELETRO = 0.3
PARCELAS_COMUM = (2, 6)
PARCELAS_ELETRO = (3, 12)

PROB_CANCELAMENTO = 0.018
PROB_DEVOLUCAO = 0.012
PROB_CANCELAMENTO_VENDEDOR_ALTO = 0.35
STATUS_CONCLUIDA = "Concluída"
STATUS_CANCELADA = "Cancelada"
STATUS_DEVOLVIDA = "Devolvida"
MOTIVOS_CANCELAMENTO = (
    "Desistência do cliente",
    "Erro de digitação no PDV",
    "Produto sem estoque",
    "Falha no pagamento",
)
MOTIVOS_DEVOLUCAO = ("Produto com defeito", "Arrependimento", "Produto errado", "Validade próxima")

DESCONTO_MEDIO_CAMPANHA = {
    "Volta às Aulas": 0.05,
    "Semana do Consumidor": 0.08,
    "Dia das Mães": 0.07,
    "Liquidação de Inverno": 0.10,
    "Black Friday": 0.12,
    "Natal": 0.06,
}
CAMPANHAS_FIXAS = (  # nome, (mês, dia) de início, (mês, dia) de fim
    ("Volta às Aulas", (1, 15), (2, 15)),
    ("Semana do Consumidor", (3, 10), (3, 16)),
    ("Liquidação de Inverno", (7, 1), (7, 14)),
    ("Natal", (12, 1), (12, 24)),
)
DIAS_CAMPANHA_DIA_DAS_MAES = 10
FORNECEDORES_POR_TIPO = 8
PREFIXO_CUPOM = "CP"
DIGITOS_CUPOM = 6

# --- Problemas de qualidade novos ---------------------------------------------------------------
PROBLEMA_HORA_FORMATO_MISTO = "hora_formato_misto"
PROBLEMA_NOME_SUJO = "nome_espacos_caixa"
FORMATOS_HORA_ALTERNATIVOS = ("%H:%M", "%Hh%M", "%I:%M %p")
FORMATO_HORA = "%H:%M:%S"

# --- ETL (Fase 2) -------------------------------------------------------------------------------
DIR_MAPEAMENTOS = RAIZ_PROJETO / "config" / "fontes"
DIR_PROCESSADOS = RAIZ_PROJETO / "data" / "processed"
FORMATOS_ARQUIVO_FONTE = ("csv", "xlsx")
TAMANHO_LOTE_CARGA = 20_000  # linhas por lote no COPY
CODIGO_SAIDA_OK = 0
CODIGO_SAIDA_VALIDACAO_REPROVADA = 1
CODIGO_SAIDA_ERRO_DE_USO = 2
CODIGO_SAIDA_ERRO_DE_EXECUCAO = 3  # banco fora do ar, arquivo ilegível, memória insuficiente...
CODIGO_SAIDA_ALERTAS_FALHARAM = 4  # dados carregados (carga concluída), mas os alertas falharam
CHAVE_TRAVA_ETL = 20240601  # advisory lock do PostgreSQL: uma carga por vez
FORMATO_LOG = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
FORMATO_DATA_LOG = "%Y-%m-%d %H:%M:%S"

# --- Previsão de vendas (Fase 4) ----------------------------------------------------------------
DIR_RELATORIOS_EXCEL = RAIZ_PROJETO / "data" / "processed"
STATUS_VENDA_VALIDA = "Concluída"  # só estas vendas entram na série de receita
PREVISAO_TREINO_ATE_BACKTEST = date(2025, 6, 30)
PREVISAO_TESTE_INICIO_BACKTEST = date(2025, 7, 1)
PREVISAO_TESTE_FIM_BACKTEST = date(2025, 12, 31)
PREVISAO_ORIGEM_CALIBRACAO = date(
    2025, 3, 31
)  # backtest anterior, só para medir a faixa fora da amostra
PREVISAO_HORIZONTE_MESES = 3  # 01/2026 a 03/2026
PREVISAO_DIAS_ANO_ANTERIOR = 364  # 52 semanas: mesmo dia da semana um ano antes
PREVISAO_DIAS_MINIMOS_SERIE = 28  # série com menos dias de venda no treino não é prevista
PREVISAO_DIAS_MINIMOS_HISTORICO_FATORES = 365  # só lojas com tanto histórico ensinam os fatores
PREVISAO_JANELA_NIVEL_DIAS = 56  # dias finais do treino que definem o nível atual da série
PREVISAO_DIAS_MES_COMPLETO = (
    25  # mês do treino com menos dias de dado não entra nos fatores mensais
)
# peso do fator mensal = n / (n + K), com n = anos observados do mês
PREVISAO_SUAVIZACAO_MENSAL_K = 0.1
PREVISAO_SUAVIZACAO_FERIADO_K = 1.0  # idem para o fator de cada feriado
PREVISAO_AMORTECIMENTO_MENSAL = 0.9  # a tendência perde 10% do ritmo a cada mês à frente
PREVISAO_HW_PERIODO = 7
PREVISAO_HW_ALFAS = (0.05, 0.15, 0.3)
PREVISAO_HW_BETAS = (0.0, 0.02)
PREVISAO_HW_GAMAS = (0.05, 0.2)
PREVISAO_HW_AMORTECIMENTO = 0.98  # por dia
PREVISAO_QUANTIL_BAIXO = 0.10
PREVISAO_QUANTIL_ALTO = 0.90
PREVISAO_COBERTURA_ALVO = 0.80
PREVISAO_NIVEIS = ("rede", "loja", "setor", "loja_setor")
PREVISAO_MODELO_BASE = "ingenua"
PREVISAO_VERSAO_MODELO = 1
CASAS_PREVISAO = 2

# --- Relatório Excel (Fase 4) -------------------------------------------------------------------
DIR_VBA = RAIZ_PROJETO / "vba"
ARQ_MODELO_XLSM = (
    DIR_VBA / "modelo_fechamento.xlsm"
)  # criado à mão no Excel (veja docs/macro_vba.md)
MODELO_ARQ_FECHAMENTO = "fechamento_{ano}-{mes:02d}"  # sem extensão: .xlsx, ou .xlsm com o modelo
