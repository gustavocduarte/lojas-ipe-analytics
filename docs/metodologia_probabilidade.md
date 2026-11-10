# Probabilidade de bater a meta do mês

Estimativa da chance de a receita do mês fechar **maior ou igual à meta do mês**, por loja e para a
rede, em cada dia do mês. É sempre uma **estimativa**: o painel diz isso e mostra a calibração.

Comando: `python -m src.previsao probabilidade [--gravar]` (código em `src/previsao/probabilidade*.py`).
Tabelas: `dw.previsao_probabilidade_meta`, `dw.previsao_probabilidade_calibracao`,
`dw.previsao_erro_resto`. Views para o Power BI em `sql/views/23_probabilidade.sql`.

## 1. Método

Em cada **corte** `d` (a receita até o fim do dia `d` já é conhecida), o que falta do mês é a parte
incerta:

```
receita do mês = realizado até d + (previsto do resto do mês) × R
R = real do resto / previsto do resto            (R = 1: a previsão acertou)
P = P(R ≥ (meta − realizado até d) / previsto do resto)
```

- **Previsto do resto:** o modelo de decomposição (o que venceu o backtest) é **reajustado em cada
  corte**, só com o painel até `d` (nada do futuro), e prevê os dias de `d + 1` ao fim do mês. A loja
  é a soma dos seus setores; a rede é a soma das lojas.
- **Erro do resto:** `ln R` por faixa de **dias que faltam** (1–5, 6–10, 11–15, 16–22, 23–31;
  `PROB_FAIXAS_DIAS`). O erro com 25 dias a vencer é maior que com 3, e a probabilidade herda isso.
  Medir o erro só no que falta (e não no total) faz a incerteza **encolher sozinha** ao longo do mês.
- **Janela:** o erro (`mu`, `sigma` e forma) usa só os **últimos 6 meses fechados** antes do mês
  avaliado (`PROB_JANELA_MESES`, mínimo de 3). O viés do resto do mês muda de nível ao longo do ano e
  a média de todo o passado ficava presa aos primeiros meses (escolha da V2; ver seção 6).
- **Viés e dispersão (`mu`, `sigma`)** por loja e faixa, **encolhidos** para o conjunto das lojas com
  peso `n / (n + K)`, `K = 4`: `mu = w·mu_loja + (1−w)·mu_conjunto` e
  `sigma² = w·sigma_loja² + (1−w)·sigma_conjunto²`. O `n` é o número de **meses distintos** observados
  da loja naquela faixa, não de cortes: os cortes de um mesmo mês têm o mesmo desfecho e não são
  evidência independente (30 cortes de um mês contam como 1 mês).
- **Rede:** tem a **dispersão própria**, estimada do erro do total. Não é a soma das lojas: os erros
  das lojas se compensam em parte, então a rede é menos dispersa que uma loja.
- **Forma da distribuição:** empírica, dos resíduos padronizados `z = (ln R − mu) / sigma`, juntos de
  todas as lojas e faixas (a distribuição acumulada é interpolada; fora da amostra vale o último
  passo, então nunca sai 0% ou 100% por extrapolação).
- **Casos exatos:** no **último dia do mês** não há o que prever, e `P` é exatamente 0 ou 1. Meta já
  batida (`realizado ≥ meta`): `P = 1`.

> **Desvio do plano aprovado.** O plano falava em encolher a loja "para a rede". Encolho para o
> **conjunto das lojas** (todas as amostras de loja juntas), e a rede tem dispersão própria. O motivo
> é o mesmo da regra "rede não é soma das lojas": o total é menos disperso que uma loja, então
> encolher uma loja para a dispersão do total a deixaria otimista demais.

## 2. Sem vazamento do futuro

O desfecho de um corte (o real do resto) só é conhecido no **fim do mês** daquele corte. Por isso há
dois esquemas, e o código os separa pelo parâmetro `esquema`:

| Esquema | O que entra no ajuste do erro para avaliar o mês M | Para que serve |
|---|---|---|
| `so_passado` | só meses **fechados e anteriores a M**, os **últimos 6** (`PROB_JANELA_MESES`; mínimo de 3 na janela) | é a probabilidade que vai **para o painel**; é a que se teria tido naquele dia |
| `leave_one_month_out` | todos os meses fechados **exceto M**, **inclusive meses posteriores a M** | só mede a calibração com mais meses; **é otimista** e nunca vai para o painel |

Em `so_passado`, para qualquer data de referência `d` só entram meses que terminaram **antes** de
`d`: nem o mês corrente, porque o desfecho dele ainda não existe. Consequências:

- Os primeiros meses (janeiro a março de 2025) **não têm base** (menos de `PROB_MESES_MINIMOS = 3`
  meses fechados): a probabilidade fica vazia (`motivo_sem_base = 'sem_amostra_erro'`), nunca 50%.
  O último dia do mês continua exato (0 ou 1), porque não depende do modelo de erro.
- Mudar o desfecho de um mês **não altera** nenhuma probabilidade do próprio mês nem dos anteriores
  (teste `test_so_passado_nao_usa_o_mes_avaliado_nem_os_posteriores`).

A **calibração** usa os dois esquemas e os separa nas tabelas (`esquema`). A de `leave_one_month_out`
usa meses posteriores ao avaliado; quem decide se a probabilidade é honesta é a de `so_passado`.

## 3. Quem fica sem probabilidade ("sem base")

A probabilidade fica **vazia (NULL), nunca 50%**, quando:

| `motivo_sem_base` | Quando |
|---|---|
| `loja_nova` | a loja tem alguma série com menos de 28 dias de venda no corte (`PREVISAO_DIAS_MINIMOS_SERIE`); o modelo não prevê essa série |
| `sem_meta` | o mês não tem meta para a loja |
| `sem_amostra_erro` | há menos de 3 meses fechados para estimar o erro daquela faixa |
| `sem_previsao` | o previsto do resto é zero |

O Power BI mostra **"sem base"** nesses casos (mesmo padrão do diagnóstico).

**Rede.** A rede soma **só as lojas com base e meta** naquele corte: realizado, previsto e meta são
sempre das mesmas lojas, e `lojas_incluidas` × `lojas_total` mostra quantas ficaram de fora (loja
nova entra na rede depois de 28 dias de venda). A rede não fica vazia por causa de uma loja nova.

*(Contagem de lojas e cortes sem base em 2025: ver a seção 6, preenchida na geração.)*

## 4. Calibração

Nos cortes avaliáveis (com probabilidade, desfecho do mês conhecido, falta algo para vender e a
meta **ainda não batida**; com a meta já batida `P = 1` por construção e não informa nada):

- **Curva de confiabilidade:** faixas de 10 pontos percentuais; previsto médio × frequência observada
  de meta batida × `n` (cortes) × `n_unidades` (pares loja-mês distintos, o **n efetivo**, porque todos
  os cortes de um mesmo loja-mês têm o mesmo desfecho). Intervalo de Wilson de 90% calculado com o
  `n_unidades`.
- **Brier score**, comparado com duas referências: 50% constante (Brier = 0,25) e a frequência
  histórica (Brier = f·(1−f)). **ECE** (erro de calibração esperado) = média, ponderada por `n`, de
  |observado − previsto| por faixa.
- Por nível (loja, rede) e por faixa de dias que faltam.

**Limites honestos.** O primeiro corte sem usar o futuro é janeiro de 2025 (12 meses de histórico),
então são no máximo 12 meses por loja (e menos em `so_passado`, que precisa de 3 meses de passado).
Na rede são ~12 desfechos independentes. A calibração prova coerência, não precisão fina; por isso a
probabilidade é sempre exibida como estimativa.

## 5. Tabelas

- `dw.previsao_probabilidade_meta`: uma linha por loja (ou rede) e dia de referência
  (`so_passado`); `probabilidade` NULL = sem base e `motivo_sem_base` diz por quê. Rede com
  `sk_loja` NULL e `lojas_incluidas`/`lojas_total`.
- `dw.previsao_probabilidade_calibracao`: curva (tipo `faixa`) e Brier/ECE (tipo `resumo`) por
  esquema, nível e faixa de dias.
- `dw.previsao_erro_resto`: `mu`/`sigma`/peso por loja, conjunto e rede e faixa de dias, e a forma
  dos resíduos (101 quantis), de cada ajuste mensal (`meses_ate`).
- Limites de cor no Power BI em `etl.parametros_negocio`: `prob_verde_min = 0,70` (a partir daqui,
  verde) e `prob_ambar_min = 0,30` (abaixo, vermelho; entre os dois, âmbar).

A gravação é idempotente: cada procedure (`dw.gravar_probabilidade_*`, `dw.gravar_erro_resto`)
substitui o que é seu (as probabilidades, no intervalo de datas pedido).

## 6. Resultados (esquema `so_passado`, o do painel)

Modelo de previsão: decomposição com **Black Friday** (efeito inteiro do ano anterior, K = 0; ver
`docs/metodologia_previsao_eventos.md`). Probabilidade: a **V2** (erro nos últimos 6 meses fechados,
mínimo de 3, encolhimento mantido). A escolha da V2 foi decidida antes de repetir a medição final
(diagnóstico em ABR a DEZ/2025, só 9 meses); a calibração documentada é a de `so_passado`.
`leave_one_month_out` usa meses posteriores e nunca é a calibração do painel.

**Sem base em 2025.** Só a Ipê Brasília (loja nova): 29 de 5.414 cortes de loja, de 03/03 a
31/03/2025 (`loja_nova`); nesses cortes a rede fica sem a Brasília na conta (29 de 365 cortes).
Em `so_passado`, jan a mar/2025 não têm 3 meses fechados de passado: 1.130 cortes de loja e 85 da
rede (`sem_amostra_erro`). Nunca 50%.

**Curva de confiabilidade, lojas** (3.732 cortes avaliáveis; 135 pares loja-mês; IC de Wilson de 90%
com o n de pares loja-mês).

| Faixa | Previsto médio | Observado | n cortes | n loja-mês | IC 90% |
|---|---|---|---|---|---|
| 0–10% | 2,8% | 3,4% | 1027 | 67 | 1,2–9,2 |
| 10–20% | 14,3% | 12,8% | 374 | 74 | 7,7–20,6 |
| 20–30% | 24,9% | 19,6% | 250 | 67 | 12,9–28,7 |
| 30–40% | 34,9% | 47,9% | 263 | 64 | 37,9–58,1 |
| 40–50% | 44,9% | 55,1% | 234 | 61 | 44,7–65,2 |
| 50–60% | 54,8% | 66,7% | 198 | 59 | 56,0–75,8 |
| 60–70% | 64,9% | 78,2% | 211 | 61 | 68,4–85,6 |
| 70–80% | 75,5% | 84,5% | 232 | 59 | 75,2–90,7 |
| 80–90% | 85,1% | 87,4% | 254 | 59 | 78,6–92,9 |
| 90–100% | 97,8% | 99,3% | 689 | 68 | 94,9–99,9 |

**Resumo.**

| Nível | Cortes | Loja-mês | Brier | 50% constante | Frequência histórica | ECE | Previsto médio | Observado |
|---|---|---|---|---|---|---|---|---|
| Lojas | 3.732 | 135 | 0,1059 | 0,2500 | 0,2495 | 0,0460 | 44,3% | 47,9% |
| Rede | 264 | 9 | 0,1663 | 0,2500 | 0,2468 | 0,1235 | 44,8% | 55,7% |

Brier das lojas por dias que faltam: 0,069 (1–5), 0,075 (6–10), 0,089 (11–15), 0,115 (16–22), 0,145
(23–31), sempre melhor que o 50% (0,25); ECE de 0,048 a 0,085. A rede tem só 9 desfechos
independentes (IC de 30 a 50 pontos por faixa): o Brier dela não permite concluir nada fino.

**Viés por mês** (`dif` = ln R realizado − `mu` usado; positivo = o resto do mês foi subestimado).

| Mês | Lojas: previsto | observado | mu usado | ln R real | dif | Rede: dif |
|---|---|---|---|---|---|---|
| 04/2025 | 37,4% | 41,0% | −0,073 | +0,029 | +0,102 | +0,101 |
| 05/2025 | 47,6% | 49,8% | −0,045 | −0,057 | −0,012 | −0,058 |
| 06/2025 | 42,2% | 43,8% | −0,049 | −0,064 | −0,016 | −0,027 |
| 07/2025 | 53,8% | 62,2% | −0,050 | +0,018 | +0,069 | +0,043 |
| 08/2025 | 44,5% | 50,1% | −0,028 | −0,003 | +0,025 | +0,048 |
| 09/2025 | 43,8% | 37,7% | −0,020 | +0,034 | +0,054 | +0,018 |
| 10/2025 | 39,7% | 36,3% | −0,007 | +0,022 | +0,029 | +0,018 |
| 11/2025 | 35,6% | 39,3% | −0,008 | −0,025 | −0,017 | −0,014 |
| 12/2025 | 54,1% | 71,2% | −0,003 | +0,098 | +0,101 | +0,109 |

**Limitação conhecida: viés conservador remanescente.** Mesmo com a janela de 6 meses, as lojas
batem a meta mais do que a probabilidade indica: previsto médio 44,3% contra 47,9% observado, e nas
faixas de 30 a 80% o observado fica 9 a 13 pontos acima do previsto (a faixa de 20–30% fica abaixo).
Na rede a diferença é maior (44,8% contra 55,7%), mas sobre 9 meses. A causa são os meses em que o
resto do mês é subestimado (abril, julho, dezembro: `dif` ≈ +0,07 a +0,10; em dezembro, o pré-Natal e
a semana de 25 a 31/12, ver `docs/metodologia_previsao_eventos.md`). A probabilidade é
**estimativa conservadora**: o painel diz "estimativa" e não corrige esse viés.

**Validação 1 a 15/12/2025.** Todas bateram a meta no fim do mês. Probabilidade em 01/12, 08/12 e
15/12:

| | Probabilidade | Desfecho |
|---|---|---|
| Rede | 22% / 59% / 50% | 107,0% da meta |
| Ipê Brasília | 10% / 9% / 10% | 107,2% da meta |
| Ipê Niterói | 90% / 96% / 100% | 127,0% da meta |
| Ipê Porto Alegre | 61% / 93% / 93% | 131,9% da meta |
| Ipê Recife | 76% / 40% / 31% | 122,3% da meta |

A Brasília (loja nova, ~9 meses de histórico) e a Recife tiveram probabilidade baixa em meses que
bateram a meta: coerente com o viés conservador acima, e dois casos não provam nada isoladamente.
