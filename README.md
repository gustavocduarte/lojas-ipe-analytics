# Lojas Ipê — Análise Comercial e Financeira

> README provisório — a documentação completa vem na Fase 6.

Projeto de portfólio de Análise de Dados / BI sobre uma rede varejista **fictícia** com ~15 lojas no Brasil.
Responde a três perguntas: como as vendas estão contra as metas por loja e setor, como as despesas realizadas
se comparam ao orçado e à previsão por centro de custo, e quais lançamentos são suspeitos.

**Stack:** PostgreSQL 18 · Python 3.12+ · Excel/VBA · Power BI Desktop (Power Query/M e DAX).

## Fases
| Fase | Conteúdo | Situação |
|---|---|---|
| 0 | Setup do repositório | feita |
| 1 | Modelo dimensional + gerador de dados sintéticos | feita |
| 2 | ETL com validações de qualidade e carga via procedures | feita (aguarda revisão) |
| 3 | Regras de anomalia em SQL e tabela de alertas | feita (aguarda revisão) |
| 4 | Previsão de vendas, relatório Excel e macro VBA | feita (aguarda revisão) |
| 5 | Dashboard Power BI (4 páginas) | a fazer |
| 6 | Documentação final | a fazer |

## Como rodar
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # preencher com os dados do seu PostgreSQL
python -m src.gerador         # gera os CSVs em data/raw/
python -m src.banco           # cria as tabelas no banco do .env
pytest                        # testes (sem banco)
```

## ETL (Fase 2)
```
python -m src.banco --procedures                  # cria/atualiza as procedures de carga
python -m src.etl fontes                          # lista as fontes mapeadas (config/fontes/)
python -m src.etl carregar                        # lê, limpa, valida e carrega as fontes padrão
python -m src.etl carregar --fonte lojas_ipe_erp --entidade lojas   # só uma entidade
python -m src.etl carregar --completo             # relê também os arquivos que não mudaram
```
Cada execução é uma *carga* (tabela `etl.cargas`) e gera um relatório de qualidade em
`data/processed/relatorio_carga_NNNN.json` (e na tabela `etl.relatorios_qualidade`).
Por padrão a carga é **incremental**: arquivos com o mesmo conteúdo (hash) de uma carga já
concluída não são relidos. Códigos de saída: 0 ok · 1 validação estrutural reprovou (o dw não
muda) · 2 erro de uso · 3 erro de execução (banco, arquivo, memória, outra carga em andamento)
· 4 dados carregados, mas a geração dos alertas falhou (a carga fica `concluida`; reavalie com
`python -m src.etl alertas`).
Durante a carga uma vigia confere a memória livre; se ela ficar abaixo de 0,4 GB por mais de
alguns segundos seguidos (`src/config.py`), a consulta é cancelada, o dw volta ao que era e o
comando sai com 3.
O contrato de entrada está em `docs/contrato_de_entrada.md`.

### Fonte de "outra empresa" (prova de generalidade)
O gerador também cria `data/raw/outra_empresa/vendas_2024-03.xlsx`: uma planilha com colunas de
nomes diferentes ("Nº Cupom", "Dt. Emissão", "Vlr. Líquido"...), cabeçalho na linha 3, linha de
total no fim e uma aba extra ("Resumo") que deve ser ignorada. O mapeamento
`config/fontes/outra_empresa.yaml` a leva ao mesmo contrato de entrada; por isso o resultado no dw
é igual ao do CSV do ERP para o mesmo mês (há um teste para isso). Essa fonte só é carregada
quando pedida (`python -m src.etl carregar --fonte outra_empresa`), para não misturar empresas.

## Alertas (Fase 3)
```
python -m src.etl alertas                # reavalia as regras (ex.: depois de mudar um parâmetro)
python -m src.banco --views              # cria/atualiza as views para o Power BI
```
Os sinais da carga viram **alertas** persistentes em `dw.alertas`: tipo, severidade (baixa, média,
alta, crítica), data, loja, vendedor ou centro de custo, valor envolvido, regra que disparou,
explicação legível ("desconto de 32,0% acima do limite de 18%"), carga que o gerou e status
(`novo`, `em_analise`, `resolvido`, `falso_positivo`). As regras são SQL e todos os limites ficam em
`etl.parametros_negocio`. Rodar de novo não duplica nada e um alerta já tratado não volta como novo;
quem trata usa `CALL dw.tratar_alerta(sk_alerta, 'resolvido', 'usuario', 'observação')`, que guarda o
histórico. Um estouro de orçamento causado por outro alerta (valor atípico, documento repetido,
centro errado) é um alerta *derivado*, ligado à origem, e não entra na contagem do painel.
Views: `dw.vw_alertas_detalhe`, `vw_alertas_por_tipo`, `vw_alertas_por_loja`,
`vw_alertas_tendencia_mensal` e `vw_alertas_resumo`.

## Previsão de vendas (Fase 4)
```
python -m src.banco 15_previsao.sql 16_pesos_meta_diaria.sql 17_previsao_agregada.sql   # num banco que já tem os anteriores
python -m src.banco --procedures ; python -m src.banco --views
python -m src.previsao backtest                    # compara as abordagens (treino até 30/06/2025)
python -m src.previsao gerar --gravar              # 3 meses depois do último dia com venda
python -m src.previsao gerar --corte 2025-12-15 --ate 2025-12-31 --gravar   # corte simulado
```
**Modelos** (só numpy/pandas, leves): `ingenua` (mesmo dia da semana um ano antes), `decomposicao`
(nível recente x dia da semana x feriado x **janela pré-Natal (15 a 24/12)** x mês x tendência amortecida;
fatores aprendidos por setor nas lojas com histórico longo), `holt_winters` (semanal, aditivo, tendência amortecida, feito à mão) e
`holt_winters_mensal` (o anterior corrigido pelo fator do mês). Séries são a receita líquida diária de
vendas concluídas por loja e setor (90 séries).

**Backtest** treinando até 30/06/2025 e prevendo 01/07 a 31/12/2025. WAPE = soma dos erros absolutos /
soma do real; viés = soma do previsto / soma do real - 1. "L×S" junta os erros de todas as lojas e
setores; "rede" compara o total.

| Abordagem | WAPE mês L×S | WAPE dia L×S | WAPE mês rede | WAPE dia rede | Viés mês rede |
|---|---|---|---|---|---|
| **decomposicao** (escolhida) | **17,8%** | **71,1%** | **3,4%** | **20,0%** | -0,3% |
| ingenua | 19,6% | 90,2% | 5,7% | 21,5% | -5,5% |
| holt_winters_mensal | 26,8% | 71,7% | 14,8% | 21,9% | -14,8% |
| holt_winters | 34,4% | 73,4% | 21,8% | 29,9% | -20,9% |

O erro diário por loja e setor é alto porque a série é esparsa (vários dias sem venda de um setor numa
loja); o erro mensal e o da rede são os que servem para decidir. A escolha é pelo menor WAPE mensal por
loja e setor. **Ressalva:** como o modelo foi escolhido pelo próprio backtest e não há dados para um
período de validação separado (são 24 meses), o WAPE informado é levemente otimista. Com 18 meses de
treino a sazonalidade anual vem de um ano só para julho a dezembro; por isso o Holt-Winters semanal (sem
componente anual) perde, e a sazonalidade anual fica com a ingênua e com o fator mensal da decomposição.

**Faixa baixa/alta:** percentis 10 e 90 da razão real/previsto do backtest, por granularidade e setor
(alvo: ~80% dos valores reais dentro). A cobertura é medida fora da amostra (faixa calibrada num backtest
anterior, treino até 31/03/2025) e na amostra; está em `dw.previsao_backtest` e no relatório do comando.
A faixa da **rede** e a de cada **loja** (soma dos setores) não são a soma das faixas das séries, que seria
larga demais (os erros se compensam): são calibradas nos resíduos no próprio total
(`src/previsao/faixa_agregada.py`) e gravadas em `dw.previsao_vendas` com `nivel = 'rede'` (`sk_loja` e
`setor` nulos) e `nivel = 'loja'` (`setor` nulo); as séries são `nivel = 'loja_setor'`.

**Backtest de várias origens** (`src/previsao/rolling.py`): seis meses dão só 6 pontos mensais, pouco para
um percentil. Por isso as faixas (rede, loja e setor) são calibradas nos resíduos de **9 origens mensais**
(31/01/2025 a 30/09/2025), cada uma treinando só até o fim do mês e prevendo os 3 meses seguintes (o horizonte
da previsão de 2026). Cada ponto é fora da amostra do modelo. A cobertura "fora da amostra" usa, para cada
origem, uma faixa calibrada só com origens cujo período previsto não se sobrepõe ao dela; "na amostra" usa
todas (otimista). A escolha do modelo continua a do backtest original (treino até 30/06/2025).

| Cobertura da faixa (alvo 80%) | Fora da amostra | Pontos | Na amostra |
|---|---|---|---|
| Rede, dia | 79,0% | 823 | 79,8% |
| Rede, mês | 74,1% | 27 | 77,8% |
| Loja (total), dia: mín / mediana / máx | 64,9% / 82,3% / 88,0% | 642 a 823 por loja | 64,6% / 82,0% / 87,7% |
| Loja (total), mês: mín / mediana / máx | 48,1% / 85,2% / 96,3% | 21 a 27 por loja | 51,9% / 85,2% / 100% |
| Loja x setor, dia (média) | 83,2% | 72.620 | 83,3% |
| Loja x setor, mês (média) | 79,0% | 2.382 | 79,8% |

Antes (um só backtest) a faixa mensal da rede cobria 50% fora da amostra; a de loja x setor cobria 84,3% (dia)
e 88,1% (mês), larga demais, e passou a vir também das 9 origens. Os 27 pontos mensais da rede se sobrepõem
(a mesma data cai em até 3 origens), então a incerteza sobre a cobertura mensal continua grande; as lojas
novas têm menos pontos.

**Onde fica:** `dw.previsao_vendas` (dia e mês, por loja e setor, com faixa, `versao_modelo`,
`treino_ate`, `gerado_em` e o WAPE do backtest da série) e `dw.previsao_backtest`. Gravar duas vezes não
duplica (`CALL dw.gravar_previsao`/`gravar_backtest`). As datas previstas são `DATE` porque passam do
fim da `dim_tempo`.

**Fechamentos** (a data de referência é sempre um parâmetro; as views usam `dw.data_referencia()`, o
último dia com venda):
* `dw.fn_projecao_fechamento_mes(data)` / `dw.vw_projecao_fechamento_mes`: **projeção = realizado do mês
  até a data + previsão dos dias restantes** (previsão gerada com `treino_ate` igual à data). Cobertura
  projetada = projeção / meta do mês. No último dia do mês a projeção é o realizado.
* `dw.fn_projecao_despesas_ano(data)` / `dw.vw_projecao_despesas_ano`: **projeção do ano = realizado até a
  data + orçado do que falta x fator**, com fator = realizado / orçado do período já passado, limitado a
  [0,7; 1,3] (`projecao_fator_min/max` em `etl.parametros_negocio`). O orçado do mês da data é repartido
  pela fração dos dias. O fator **não conta** os lançamentos de alertas vigentes de documento repetido (a
  cópia), valor atípico ou centro incompatível, salvo os marcados como falso positivo; esses lançamentos
  continuam no realizado somado à projeção. Com o corte em 30/06/2025, nenhum centro ficou no teto (antes,
  L02-PES e L02-TER ficavam em 1,30) e o desvio total da projeção contra o realizado de 2025 caiu de +1,9% para +0,6%.
* `dw.vw_meta_vendas_diaria` e `dw.vw_meta_vendedor_diaria`: meta do mês repartida pelos dias com o peso
  do dia da semana e do feriado (os mesmos de `src/config.py`); a soma dos dias bate com a meta do mês (o
  último dia absorve o resto do arredondamento).
* **Evolução** (relatório) = acumulado do mês / acumulado do mesmo período do ano anterior - 1.

## Relatório Excel e macros (Fase 4)
```
python -m src.relatorios fechamento                                 # mês/dia da referência
python -m src.relatorios fechamento --mes 2025-12 --dia 2025-12-15
```
Gera `data/processed/fechamento_AAAA-MM.xlsx` com cinco abas: **Resumo da rede** (indicadores, gráfico de
venda por dia contra a meta do dia), **Lojas** (venda e meta do dia, acumulado, cobertura, evolução contra
o ano anterior, projeção), **Vendedores** (ranking, meta, cobertura), **Alertas abertos** (só
independentes, do mais grave ao menos) e **Previsão** (por loja, com faixa, erro do backtest e gráfico).
Formatos brasileiros, cabeçalho fixo, filtros e verde/vermelho na cobertura e na evolução. Os números
são conferidos contra consultas independentes ao dw nos testes.

Com `vba/modelo_fechamento.xlsm` presente a saída é `.xlsm` com duas macros (`GerarAbaDaLoja`,
`ExportarResumoPDF`, atalhos `Ctrl+Shift+L` e `Ctrl+Shift+P`). O modelo é criado uma vez, à mão, no Excel
(passo a passo, segurança de macros e roteiro de teste em `docs/macro_vba.md`); sem ele o relatório sai
como `.xlsx`.
