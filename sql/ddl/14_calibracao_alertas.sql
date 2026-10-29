-- Calibração das faixas de severidade com a distribuição dos dados reais (carga de 2024-2025).
-- Os valores iniciais de 11_ e 12_ eram palpites e ficavam acima de tudo que existe nos dados
-- (nenhum alerta chegava a "alta"). "Alta" passa a significar "no topo 10% dos valores reais":
--   * total de cupom: p50 = R$ 85, p90 = R$ 254, p95 = R$ 353, p99 = R$ 1.000;
--   * lançamento de despesa: p50 = R$ 430, p90 = R$ 1.633, p99 = R$ 3.248.
-- As demais faixas (desconto, margem, valor atípico, cancelamento, orçado) já separavam bem os
-- casos reais e ficam como estavam.

UPDATE etl.parametros_negocio SET valor = 250,
    descricao = 'Venda fora do horário: total do cupom (R$) a partir do qual a severidade é alta (~p90 dos cupons).'
WHERE chave = 'fora_horario_valor_alto';

UPDATE etl.parametros_negocio SET valor = 250,
    descricao = 'Cupom duplicado: valor repetido (R$) a partir do qual a severidade é alta (~p90 dos cupons).'
WHERE chave = 'cupom_duplicado_valor_alto';

UPDATE etl.parametros_negocio SET valor = 1600,
    descricao = 'Documento repetido: valor repetido (R$) a partir do qual a severidade é alta (~p90 das despesas).'
WHERE chave = 'documento_repetido_valor_alto';
