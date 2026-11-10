# Previsão: Black Friday e Natal (modelo de decomposição)

A decomposição (Fase 4) tinha fator de feriado e um fator único de **pré-Natal** (15 a 24/12), mas não
conhecia a **Black Friday**. O diagnóstico da probabilidade de bater a meta mostrou o motivo: em
novembro/2025 o resto do mês era subestimado (ln R de +0,31 nas lojas), com o pico no fim do mês.
Esta página registra o que foi feito, o que foi tentado e o que foi revertido.

**Regra do modelo.** O modelo só conhece a **data** do evento (`src/calendario.black_friday`, que se
sabe com antecedência) e **estima o efeito pelo histórico**. Nenhum parâmetro do gerador entra
(`BLACK_FRIDAY_FATORES`, `MULT_SETOR_*`, `FATOR_*`...). O teste
`test_o_modulo_de_previsao_nao_usa_parametros_do_gerador` varre `src/previsao/*.py` e falha se algum
deles for importado ou usado.

## 1. Black Friday (adotada, K = 0)

- **Janela:** de 7 dias antes a 7 dias depois da sexta-feira (`PREVISAO_BLACK_FRIDAY_JANELA`), genérica,
  definida antes de ver erros.
- **Efeito por dia:** razão do dia (sem dia da semana e feriado) pela média dos 14 dias logo antes da
  janela, em cada ano com a janela inteira nos dados. Cada setor aprende o seu.
- **Encolhimento:** `PREVISAO_BLACK_FRIDAY_K = 0`, ou seja, o efeito **inteiro** do ano anterior, como o
  fator de pré-Natal. Com K = 1 (a primeira tentativa), 1 ano de histórico valia metade do efeito em
  log e o pico ficava subestimado.
- **Fora das estimativas:** a janela sai do fator do dia da semana, do fator do mês, da referência do
  Natal e do nível dos últimos 56 dias.
- **Sem histórico** (nenhum ano com a janela inteira) o fator é 1.

**Critério de adoção (definido antes da medição):** rolling-origin, rede, geral: WAPE do mês <= 4,4%
(o "sem BF") **e** WAPE do dia < 19,1%. Resultado com K = 0: **4,1% e 16,2%: adotada.**

Rolling-origin (origens fim de mês de jan a nov/2025, até 3 meses à frente), em %:

| Recorte | Versão | Rede dia | Rede mês | Viés mês | Loja dia | Loja mês |
|---|---|---|---|---|---|---|
| Geral | sem BF | 19,1 | 4,4 | −0,4 | 46,9 | 11,6 |
| | BF K=1 | 17,3 | 5,0 | −1,1 | 45,6 | 11,8 |
| | **BF K=0** | **16,2** | **4,1** | +0,2 | 45,1 | 11,6 |
| Novembro | sem BF | 31,0 | 4,3 | −4,3 | 56,2 | 9,3 |
| | BF K=1 | 21,6 | 6,2 | −6,2 | 49,4 | 9,9 |
| | **BF K=0** | **14,6** | **1,6** | +1,2 | 46,6 | 8,7 |
| Dezembro | sem BF | 16,3 | 5,6 | −5,6 | 40,6 | 9,4 |
| | BF K=1 | 14,6 | 8,0 | −8,0 | 39,1 | 10,4 |
| | **BF K=0** | **14,6** | 7,0 | −7,0 | 38,9 | 9,9 |
| 25–31/12 | sem BF | 18,3 | 7,8 | −7,8 | 44,6 | 19,4 |
| | BF K=1 | 20,0 | 14,1 | −14,1 | 44,1 | 21,3 |
| | **BF K=0** | 20,2 | 14,4 | −14,4 | 44,1 | 21,5 |

(O viés do mês é o mesmo para a rede e para as lojas: é a soma. "Mês" é o total do recorte por
origem; em 25–31/12 é a soma desses 7 dias.)

Backtest oficial (`python -m src.previsao backtest`, treino até 30/06/2025, teste de jul a dez):

| | WAPE mês loja×setor | WAPE dia loja×setor | WAPE mês rede | WAPE dia rede | Viés mês rede |
|---|---|---|---|---|---|
| Antes (sem BF) | 17,8% | 71,1% | 3,4% | 20,0% | −0,3% |
| BF K=0 | 17,9% | 69,4% | 3,1% | 15,4% | +0,6% |

Mesmo backtest, por recorte (rede dia / rede mês / viés / loja dia / loja mês), sem BF → BF K=0:
jul–dez 20,0 / 0,3 / −0,3 / 47,3 / 9,7 → 15,4 / 0,6 / +0,6 / 44,9 / 9,7; novembro 31,2 / 3,9 / −3,9 /
56,5 / 12,1 → 14,6 / 1,6 / +1,6 / 47,4 / 12,6; dezembro 16,3 / 4,2 / −4,2 / 41,7 / 12,1 → 14,2 / 5,6 /
−5,6 / 40,4 / 12,3; 25–31/12 18,1 / 6,6 / −6,6 / 45,6 / 19,5 → 19,5 / 13,5 / −13,5 / 44,7 / 21,5.

**Limitações conhecidas**
- Com K = 0 o pico de 2025 vem de **um único ano** (2024) de histórico; se aquele ano for atípico, o
  erro se repete no seguinte.
- A janela cruza o limite de mês (final de novembro e começo de dezembro): parte do degrau
  sazonal de dezembro entra no "efeito" dos últimos dias da janela.
- A Black Friday não resolve dezembro (ver abaixo).

## 2. Natal por dia com K = 1 (tentado e **revertido**)

Hipótese: substituir o fator único de pré-Natal por um efeito estimado **dia a dia** na janela de 15 a
31/12 (pré-Natal, o próprio 25/12 sem o fator de feriado comum, e a semana pós-Natal), com o mesmo
método e o mesmo K (= `PREVISAO_SUAVIZACAO_FERIADO_K` = 1) da primeira Black Friday. Motivo: com a
origem em 30/11 a razão real/previsto era de 1,2 a 1,4 em 19–23/12, de 0,6 em 25/12 e de 1,3 a 1,4 em
29–31/12.

Resultado (rolling, rede, viés do mês; BF K=1 com o Natal antigo → com o Natal por dia):

| Recorte | Viés do mês | WAPE mês rede | WAPE dia rede |
|---|---|---|---|
| Geral | −1,0% → −1,3% | 5,0% → 5,3% | 17,4% → 17,4% |
| Dezembro | −8,1% → −10,0% | 8,1% → 10,0% | 14,8% → 15,2% |
| 15–24/12 | −10,3% → −16,1% | 10,3% → 16,1% | 16,0% → 16,1% |
| 25–31/12 | −12,4% → −13,7% | 12,4% → 13,7% | 19,2% → 20,1% |

No backtest com treino até 30/06 o resultado foi o mesmo: dezembro de −6,7% para −8,5% e 25–31/12 de
−11,4% para −12,3%; o backtest oficial subiu de 4,3% para 4,7% (WAPE do mês da rede).

**Por que foi revertido.** O fator único anterior não tem encolhimento; o efeito por dia com K = 1 e
**um** ano de histórico entra pela metade em log. O pré-Natal ficou ainda mais subestimado, e o dia a
dia não trouxe ganho de erro por dia. Critério da decisão: não piorar dezembro. O código e os testes
da janela de Natal foram removidos; o modelo voltou ao **fator único de pré-Natal e ao feriado do
25/12** como estavam.

## 3. O que continua errado (limitação conhecida)

Dezembro segue subestimado: viés do mês de −7,0% na rede (rolling), −14,4% em 25–31/12. A semana
pós-Natal não tem fator, o 25/12 usa o fator de feriado comum e o pré-Natal tem um fator único. Isso
alimenta o viés conservador remanescente da probabilidade (`docs/metodologia_probabilidade.md`,
seção 6). Qualquer correção futura precisa de mais de um ano de histórico de Natal ou de um critério de
encolhimento escolhido **antes** da medição.
