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
| 2 | ETL com validações de qualidade e carga via procedures | a fazer |
| 3 | Regras de anomalia em SQL e tabela de alertas | a fazer |
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
