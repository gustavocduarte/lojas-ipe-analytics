-- Simulador v2: o conservador oficial passa do percentil 5% para o 10%. Depois do ajuste de
-- diluição o p10 fica perto de 75% de cobertura semanal nas trocas, com viés menos extremo.
-- Migração para bancos que já têm o 20 (o 20 insere 0,05; em banco novo este script vem depois).

UPDATE etl.parametros_negocio
SET valor = 0.10,
    descricao = 'Simulador v2: percentil da distribuição das fatias semanais usado como projeção conservadora (p10: perto de 75% de cobertura semanal nas trocas depois da diluição).'
WHERE chave = 'simulador_percentil_fatia';
