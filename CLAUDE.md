# Lojas Ipê — Análise Comercial e Financeira

Projeto de portfólio para vagas de Analista de Dados / Analista de BI. Responder sempre em português.

## Cenário
Rede varejista brasileira **fictícia** (dados 100% sintéticos, nomes via Faker pt_BR, sem CPF/telefone/e-mail), ~15 lojas em vários estados (SP, RJ, MG, BA, PE, PR, RS, GO, SC, CE, DF), vendendo em setores (Alimentos, Bebidas, Limpeza, Casa, Eletro, Cuidados Pessoais). Moeda: BRL. A empresa quer: acompanhar vendas vs. metas por loja/setor, comparar despesas orçadas vs. realizadas vs. previsão por centro de custo e detectar anomalias (lançamentos suspeitos) automaticamente.

## Stack
PostgreSQL 18 (local) + Python 3.12+ (pandas, sqlalchemy, psycopg 3, python-dotenv, openpyxl, pytest, ruff) + Excel/VBA + Power BI Desktop (feito depois, manualmente, com Power Query/M e DAX).

**Decisão (Fase 0):** o plano original previa SQL Server, mas ele não está instalado neste computador (nem o ODBC Driver 18). Decidimos usar o PostgreSQL 18 que já existe. Por isso: DDL em SQL do PostgreSQL (`GENERATED ALWAYS AS IDENTITY`, `NUMERIC`, `DATE`), procedures/funções em PL/pgSQL (`CREATE PROCEDURE` nas cargas da Fase 2) e conexão SQLAlchemy `postgresql+psycopg://`.

## CUIDADO: este PostgreSQL é compartilhado com o projeto Dindify
- **Nunca** tocar, alterar ou apagar banco, schema, usuário ou tabela que já exista.
- Deste projeto existem **apenas** o banco `lojas_ipe_dw`, o usuário `lojas_ipe` (com permissão só nesse banco) e o usuário `lojas_ipe_teste` (só para os testes de banco).
- Antes de criar qualquer coisa no servidor: mostrar os comandos e a lista de bancos existentes e esperar autorização.
- Não mudar nenhuma configuração do servidor (`shared_buffers` fica em 128 MB). Não existe mais o limite de 512 MB do SQL Server.
- A senha do superusuário `postgres` só é pedida ao usuário quando necessário e **nunca** vai para arquivo versionado.
- `psql` não está no PATH: usar `C:\Program Files\PostgreSQL\18\bin\psql.exe`.
- **Só o usuário roda o script `sql/ddl/00_criar_banco_e_usuario.sql`**: ele pede a senha do `postgres`, que o Claude não recebe. O script mostra os bancos existentes (`\l`), aborta se algum nome do projeto já existir e cria apenas `lojas_ipe` (dono do `lojas_ipe_dw`) e `lojas_ipe_teste`. As senhas entram como variáveis do `psql` (`-v`), nunca no arquivo.
- **Testes de banco usam só o usuário `lojas_ipe_teste`** (LOGIN + CREATEDB, sem SUPERUSER e sem CREATEROLE), via `BD_TESTE_USUARIO`/`BD_TESTE_SENHA`, nunca o `postgres`. Como no PostgreSQL só o dono apaga um banco, ele só consegue apagar os bancos temporários que ele mesmo criou, nunca os do Dindify.

## Restrição de memória
O computador tem 3,9 GB de RAM e costuma ter ~0,5 GB livres.
- Antes de qualquer etapa pesada (gerar dados, carga no banco), conferir a memória livre. **Abaixo de 0,4 GB não rodar**: avisar o usuário e esperar. O gerador já faz essa checagem (`src/memoria.py`).
- Volumes moderados; processar em partes (o gerador escreve um mês por vez), nunca carregar tudo na memória.

## Plano de fases
- **Fase 0:** setup do repositório.
- **Fase 1:** modelo do data warehouse (esquema estrela) + gerador de dados sintéticos.
- **Fase 2:** ETL em Python com validações de qualidade; carga no DW via stored procedures.
- **Fase 3:** regras de anomalia em SQL + tabela de alertas. Entra aqui (ou na Fase 5) a view `dw.vw_meta_vendas_diaria`: reparte a meta mensal (por loja e setor, e também por vendedor) pelos dias do mês, usando o peso de cada dia da semana e dos feriados que o gerador já usa (`FATOR_DIA_SEMANA`, `FATOR_FERIADO_NACIONAL`, em `src/config.py`), de forma que a soma dos dias bata exatamente com a meta do mês (o último dia absorve o resto do arredondamento). Com teste.
- **Fase 4:** previsão simples de vendas + relatório Excel automático (openpyxl) + macro VBA simples.
- **Fase 5:** dashboard Power BI (4 páginas: Resumo Executivo, Vendas vs Meta, Orçado vs Realizado vs Previsão, Alertas), com parte das transformações em Power Query/M. Acrescenta-se a página **Acompanhamento Diário**, inspirada em painéis de sell-out:
  - tabela por loja e por UF com venda do dia, meta do dia, cobertura do dia %, acumulado do mês, meta do mês e cobertura do mês % (formatação condicional verde/vermelho);
  - cartões com mês anterior, mês atual, projeção de fechamento e evolução % contra o mesmo período do ano anterior;
  - gráfico de barras com a venda por dia;
  - rankings de lojas, setores, produtos e vendedores contra o ano anterior;
  - medidas DAX com `TOTALMTD`, `SAMEPERIODLASTYEAR`/`DATEADD` e uma projeção ponderada pelos pesos dos dias (usa `dw.vw_meta_vendas_diaria`).
- **Fase 6:** documentação (README, dicionário de dados, diagrama de linhagem). O README explica as fórmulas de cobertura, projeção e evolução.

Fases 3 a 6 acima são plano: nada disso está implementado ainda.

Não começar uma fase sem a revisão do usuário da anterior.

## Convenções
- **Tudo em português:** código (funções, variáveis, módulos), tabelas e colunas do banco, README, documentação, mensagens de commit e textos do dashboard. Nomes **sem acento** e em `snake_case` no código e no banco (valores de dados, como "São Paulo", podem ter acento).
- **Formatos brasileiros na apresentação** (R$, vírgula decimal, datas dd/mm/aaaa). No banco, tipos corretos (`DATE`, `NUMERIC`), nunca texto (exceto o schema `stg`, que é cru de propósito).
- **Credenciais sempre em `.env`** (nunca no código); `.env.example` só com os nomes das variáveis.
- **Constantes e parâmetros em `src/config.py`**; nada de número mágico no código. Cadastros fictícios (lojas, produtos) ficam em `src/gerador/catalogo.py`.
- **Testes** nunca acessam a rede, o banco real (`lojas_ipe_dw`) nem gravam em `data/`: usar `tmp_path` e fixtures. Testes que precisam de PostgreSQL levam `@pytest.mark.banco`, criam e apagam um banco de teste próprio e usam as variáveis `BD_TESTE_*`. Localmente ficam fora da execução padrão (`pytest -m banco` para rodá-los); no CI rodam os dois grupos (`pytest -m "banco or not banco"`).
- **Antes de cada commit:** rodar `pytest` e `ruff check .` (e `ruff format .`) e informar a contagem de testes pela diferença real.
- **Git:** mostrar o diff e esperar a aprovação do usuário antes de cada commit. Um commit por assunto, mensagens em português. Nunca `--amend`, nunca `git stash`, **sem trailer de atribuição** (nada de `Co-Authored-By`).
- Confirmar no código antes de corrigir qualquer coisa; nunca mudar o valor esperado de um teste existente sem perguntar.
- Arquivos temporários em `%TEMP%`, fora do repositório.

## Estrutura
```
data/raw/          CSVs gerados (ignorados pelo git)
sql/ddl/           DDL do PostgreSQL (00 = administrativo; 01..05 = schemas, dimensões, fatos, staging, índices; 06.. = ETL)
sql/procedures/    cargas em PL/pgSQL (Fase 2)
sql/views/         views (Fases 3 e 5)
src/gerador/       gerador de dados sintéticos
src/etl/           ETL (Fase 2): contrato de entrada, mapeamentos, leitura, limpeza, cargas
config/fontes/     um YAML por fonte de dados (coluna da fonte -> coluna do sistema)
src/relatorios/    relatório Excel (Fase 4)
tests/ docs/ powerbi/
docs/contrato_de_entrada.md   gerado por `python -m src.etl.contrato`; não editar à mão
```

## Comandos
```
.venv\Scripts\activate
python -m src.gerador                # gera data/raw/ (confere a memória antes)
python -m src.banco                  # aplica todo o DDL 01.. num banco novo (usuário lojas_ipe do .env)
python -m src.banco 06_controle_etl.sql   # aplica só scripts novos num banco que já tem os anteriores
pytest                               # testes sem banco
pytest -m banco                      # só os testes de banco (BD_TESTE_* no .env, usuário lojas_ipe_teste)
ruff check . ; ruff format .
```
