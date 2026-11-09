-- Limites do painel de diagnóstico da loja (Power BI). Ficam em etl.parametros_negocio (nada fixo no
-- DAX) e saem para o relatório pela view dw.vw_parametros_diagnostico. Reaplicável: só atualiza a descrição,
-- nunca um valor que alguém já tenha mudado.
INSERT INTO etl.parametros_negocio (chave, valor, descricao) VALUES
    ('diag_cupons_queda', 0.05, 'Diagnóstico: queda de cupons vs mesmo período do ano anterior, a partir da qual é atenção (e alta igual é ponto forte).'),
    ('diag_ticket_minimo', 0.90, 'Diagnóstico: ticket médio abaixo desta fração do ticket médio da rede é atenção.'),
    ('diag_ticket_forte', 1.10, 'Diagnóstico: ticket médio acima desta fração do ticket médio da rede é ponto forte.'),
    ('diag_desconto_pp', 0.005, 'Diagnóstico: desconto médio acima (atenção) ou abaixo (ponto forte) da média da rede por esta diferença, em fração do bruto.'),
    ('diag_setor_fraco', 0.70, 'Diagnóstico: setor com cobertura da meta abaixo desta fração é fraco.'),
    ('diag_setor_forte', 1.30, 'Diagnóstico: setor com cobertura da meta acima desta fração é forte.'),
    ('diag_equipe_abaixo', 0.50, 'Diagnóstico: fração de vendedores abaixo da meta a partir da qual a equipe é atenção.'),
    ('diag_equipe_acima', 0.75, 'Diagnóstico: fração de vendedores acima da meta a partir da qual a equipe é ponto forte.'),
    ('diag_meta_folga', 0.10, 'Diagnóstico: meta até o dia abaixo (folgada) ou acima (apertada) da venda do ano anterior por esta fração.')
ON CONFLICT (chave) DO UPDATE SET descricao = EXCLUDED.descricao;
