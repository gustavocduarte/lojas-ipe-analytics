-- ADMINISTRATIVO: roda uma única vez, como superusuário, num terminal, pelo próprio dono do servidor.
-- Cria só o que é deste projeto e NÃO toca em nenhum banco, schema, usuário ou tabela existente
-- (o servidor também é usado pelo projeto Dindify). Se qualquer item já existir, o script aborta
-- antes de criar qualquer coisa.
--
-- As senhas NUNCA ficam neste arquivo: entram como variáveis do psql (-v), por exemplo:
--   psql -U postgres -h localhost -v senha_lojas_ipe="..." -v senha_teste="..." -f 00_criar_banco_e_usuario.sql
-- Evite aspas e barras invertidas nas senhas.

\set ON_ERROR_STOP on

\echo
\echo '=== Bancos que já existem no servidor (nada deles será alterado) ==='
\l

\echo
\echo '=== Papéis (usuários) que já existem ==='
\du

-- Exige as duas senhas.
\if :{?senha_lojas_ipe}
\else
    \echo 'ABORTADO: faltou -v senha_lojas_ipe="..."'
    \quit
\endif
\if :{?senha_teste}
\else
    \echo 'ABORTADO: faltou -v senha_teste="..."'
    \quit
\endif

-- Aborta se qualquer nome já estiver em uso (evita tocar em algo que não é deste projeto).
SELECT
    EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('lojas_ipe', 'lojas_ipe_teste'))
    OR EXISTS (SELECT 1 FROM pg_database WHERE datname = 'lojas_ipe_dw') AS ja_existe
\gset
\if :ja_existe
    \echo 'ABORTADO: lojas_ipe, lojas_ipe_teste ou lojas_ipe_dw já existe. Nada foi criado.'
    \quit
\endif

-- Usuário do projeto: dono do banco lojas_ipe_dw e nada além disso.
CREATE ROLE lojas_ipe LOGIN PASSWORD :'senha_lojas_ipe'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

-- Usuário só para os testes marcados como "banco": pode criar bancos (que passam a ser dele)
-- e, como no PostgreSQL só o dono apaga um banco, não consegue apagar os bancos de outros
-- projetos. Não é superusuário e não cria papéis.
CREATE ROLE lojas_ipe_teste LOGIN PASSWORD :'senha_teste'
    NOSUPERUSER CREATEDB NOCREATEROLE NOREPLICATION;

CREATE DATABASE lojas_ipe_dw OWNER lojas_ipe;

-- Só o usuário do projeto (e superusuários) conseguem conectar neste banco.
REVOKE ALL ON DATABASE lojas_ipe_dw FROM PUBLIC;
GRANT CONNECT ON DATABASE lojas_ipe_dw TO lojas_ipe;

\echo
\echo '=== Criado ==='
\du lojas_ipe*
\l lojas_ipe_dw
