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
| `so_passado` | só meses **fechados e anteriores a M** | é a probabilidade que vai **para o painel**; é a que se teria tido naquele dia |
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

## 6. Resultados

*(Preenchido na geração: lojas e cortes sem base, curva de confiabilidade, Brier, ECE e a validação
de 1 a 15/12/2025.)*
