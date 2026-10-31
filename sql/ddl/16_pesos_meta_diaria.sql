-- Fase 4: pesos para repartir a meta mensal pelos dias do mês (usados em dw.vw_meta_vendas_diaria).
--
-- Os valores são os mesmos de FATOR_DIA_SEMANA e FATOR_FERIADO_NACIONAL em src/config.py (um teste
-- confere). peso_dia_semana_N: N = dia ISO da semana (1 = segunda ... 7 = domingo).

INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('peso_dia_semana_1', 0.90, 'Meta diária: peso da segunda-feira.'),
    ('peso_dia_semana_2', 0.88, 'Meta diária: peso da terça-feira.'),
    ('peso_dia_semana_3', 0.92, 'Meta diária: peso da quarta-feira.'),
    ('peso_dia_semana_4', 0.95, 'Meta diária: peso da quinta-feira.'),
    ('peso_dia_semana_5', 1.10, 'Meta diária: peso da sexta-feira.'),
    ('peso_dia_semana_6', 1.25, 'Meta diária: peso do sábado.'),
    ('peso_dia_semana_7', 0.70, 'Meta diária: peso do domingo.'),
    ('peso_feriado', 0.85, 'Meta diária: multiplicador do peso nos feriados nacionais.');
