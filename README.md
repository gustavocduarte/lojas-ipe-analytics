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
| 4 | Previsão de vendas, relatório Excel e macro VBA | a fazer |
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
