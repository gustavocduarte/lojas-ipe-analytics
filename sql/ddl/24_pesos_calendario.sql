-- Meta diária: peso do calendário comercial por data e setor (feriados, Natal, Black Friday, Dia das
-- Mães, Carnaval, volta às aulas, dia da semana e multiplicador do setor), conhecido com antecedência.
-- É carregada por `python -m src.banco --calendario` (src/calendario_comercial.py) e usada por
-- dw.vw_meta_vendas_diaria; sem linha para a data, a view cai nos pesos simples de
-- etl.parametros_negocio (dia da semana x feriado).

CREATE TABLE IF NOT EXISTS etl.pesos_calendario (
    data   DATE          NOT NULL,
    setor  VARCHAR(30)   NOT NULL,
    peso   NUMERIC(12,6) NOT NULL CHECK (peso >= 0),
    PRIMARY KEY (data, setor)
);

COMMENT ON TABLE etl.pesos_calendario IS 'Peso de cada dia e setor para repartir a meta mensal (calendário comercial, sem venda realizada).';
