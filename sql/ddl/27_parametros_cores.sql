-- Cores do relatório Power BI (verde, vermelho, âmbar...). Ficam no banco (nada de "#RRGGBB" espalhado
-- pelas medidas) e saem para o relatório pela view dw.vw_parametros_cores (sql/views/24_cores.sql).
-- Reaplicável: cria só o que falta e atualiza a descrição, nunca uma cor que alguém já tenha mudado.
CREATE TABLE IF NOT EXISTS etl.parametros_cores (
    chave     TEXT PRIMARY KEY,
    cor       TEXT NOT NULL CHECK (cor ~ '^#[0-9A-Fa-f]{6}$'),
    descricao TEXT NOT NULL
);

INSERT INTO etl.parametros_cores (chave, cor, descricao) VALUES
    ('verde', '#2E7D32', 'Meta batida, evolução positiva, ponto forte.'),
    ('vermelho', '#C62828', 'Abaixo da meta, queda, atenção.'),
    ('vermelho_claro', '#E57373', 'Falta para a meta quando a cobertura está entre 80% e 100%.'),
    ('ambar', '#B26A00', 'Contexto ou alerta intermediário que não é mérito nem falha (meta folgada/apertada, setor abaixo da meta sem ser fraco, probabilidade intermediária).'),
    ('laranja_quadrante', '#EF8A17', 'Quadrante: cresce receita e perde margem.'),
    ('azul_quadrante', '#1F6FB5', 'Quadrante: perde receita e ganha margem.'),
    ('cinza', '#6B7280', 'Neutro ou sem base.'),
    ('cinza_texto', '#374151', 'Neutro em texto (sinal igual a zero).')
ON CONFLICT (chave) DO UPDATE SET descricao = EXCLUDED.descricao;
