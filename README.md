# BTC INDEX

Responde a uma pergunta: **como o preço do bitcoin variou em 1, 3, 6 e 12 meses a partir dos
dias do passado em que os indicadores estavam como estão hoje?** Individualmente e em conjunto
(interseção estrita, o "E" matemático).

## Rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

Atualizar as fontes pela linha de comando:

```bash
python update_data.py
```

Os dados ficam em `data/cache/*.csv`. A interface tem um botão **Atualizar dados agora**.

## Deploy no Streamlit Cloud

O container do Cloud sobe vazio e **hiberna sem tráfego**, então cold start é a regra, não a
exceção — e sem cuidado cada visita paga a busca inteira nas fontes. Três coisas evitam isso:

- **As 12 fontes são buscadas em paralelo** (`engine.prefetch`). Medido: 36,3s em fila → 4,6s.
- **`data/cache/*.csv` é versionado de propósito** (1,4 MB). Com os CSVs no repo o cold start
  lê disco em vez de rede: **0,18s**. O TTL de cada fonte continua valendo, então o que
  vencer é rebuscado — em paralelo, no primeiro acesso.
- **`.github/workflows/atualizar-dados.yml`** roda todo dia às 11:00 UTC, atualiza os CSVs e
  commita. O push dispara o redeploy do Streamlit Cloud, que é como o dado novo chega ao app.
  Dá para rodar na mão pela aba Actions (*workflow_dispatch*).

A Action precisa de permissão de escrita: **Settings → Actions → General → Workflow
permissions → Read and write permissions**.

O preço do BTC é buscado de forma incremental: havendo cache, só o trecho que falta desde a
última data (1 requisição em vez das 6 páginas do histórico completo).

## Indicadores

| Indicador | O que é | Histórico | Banda |
|---|---|---|---|
| **Fear & Greed** | índice de sentimento 0–100 da alternative.me | 2018-02 → hoje | ± pontos ou ± percentil |
| **MVRV Z-score** | lucro não realizado do mercado inteiro, normalizado | 2011 → hoje | ± z ou ± percentil |
| **Ciclo do BTC** | dias decorridos desde a âncora do ciclo | 2012-11 → hoje | ± dias (distância circular) |

O **M2 global** não é um indicador: ele não entra em nenhuma análise. Tem aba própria, onde é
desenhado sobre o preço com o deslocamento em dias que você escolher.

### O benchmark "holder"

Toda tabela de resultado traz, ao lado dos números do indicador, a estatística de **comprar num
dia qualquer do período e segurar** — mesma janela, mesmo recorte de datas. A coluna
**Vantagem p.p.** é a diferença entre as duas medianas.

É a pergunta que importa: o indicador ajuda, ou é só o bitcoin tendo subido? Uma mediana de
+34% em 12 meses parece ótima até você ver que o holder fez +79% no mesmo período — vantagem
de −45 p.p.

### MVRV Z-score

    Z = (valor de mercado − valor realizado) / desvio-padrão expansivo do valor de mercado

O valor realizado precifica cada moeda pela última vez que ela se moveu, então a diferença mede
o lucro não realizado do mercado. O Z-score normaliza pela escala do próprio ciclo, o que
permite comparar 2013 com 2025.

Dois detalhes de implementação:

- O desvio-padrão é **expansivo** (só o passado até cada data). Usar o da série inteira
  embutiria informação do futuro em toda a série histórica e inflaria o backtest.
- A Coin Metrics não libera `CapRealUSD` no tier gratuito, então o valor realizado é derivado:
  `valor de mercado ÷ MVRV`. O resultado bate com referências externas dentro de ~0,03 z.

Cuidado ao combinar com o ciclo: **MVRV é parcialmente colinear com o dia do ciclo**, então os
dois juntos na composta cortam menos amostra do que parece. O funil mostra isso.

### Sobre o fator das bandas

A interseção estrita de três indicadores costuma devolver quase nenhum dia. O **fator**
multiplica todas as bandas ao mesmo tempo, e você escolhe como ele se comporta em
**Fator das bandas**, na barra lateral:

| Modo | O que faz |
|---|---|
| **Automático até um teto** | Sobe pelos degraus 1; 1,25; 1,5; 2; 2,5; 3; 4; 5; 7; 10 e para no primeiro que alcança o N mínimo, sem passar do teto que você definir. Se bater no teto sem chegar lá, avisa. |
| **Fator fixo** | Aplica exatamente o fator escolhido e ignora o N mínimo. Abaixo de 1 aperta as bandas em vez de alargar. |
| **Sem relaxamento** | Vale a banda configurada, doa a quem doer. |

A aba Composto traz a **tabela de sensibilidade**: quantos dias cada fator entrega e quais as
bandas resultantes, com o fator em uso destacado. Cada degrau compra amostra vendendo
semelhança com hoje — a tabela mostra o preço antes de você pagar.

### Sobre o ciclo

Os halvings **não** são de 1460 dias. Intervalos observados: **1319**, **1402** e **1435** dias.
O default do projeto é **1435** e a âncora default é o halving, a única conhecida em tempo real
(topos e fundos só se conhecem depois do fato). O próximo halving é projetado para março/2028.

## Estrutura

```
app.py                  interface Streamlit
update_data.py          atualização por linha de comando
btcindex/
  cache.py              HTTP com retry + cache CSV + reamostragem para diário
  sources/              uma fonte por arquivo (btc_price, fear_greed, fred, global_m2, mvrv)
  cycle.py              halvings, topos, fundos, distância circular
  indicators.py         definição dos indicadores e regra de comparação
  matcher.py            casamento por banda, "E" composto, relaxamento automático
  stats.py              estatísticas das janelas + episódios independentes
  engine.py             amarra tudo
tests/                  testes do motor, sem rede
```

### Adicionar um indicador novo

1. Crie a fonte em `btcindex/sources/`, devolvendo uma `pd.Series` diária.
2. Em `engine.build_indicators`, monte um `Indicator` com `band_mode` `abs`, `pct`, `rel` ou
   `circular`. Se ele tiver lead, use `_indicador_de_variacao`, que já deixa o shift reancorável.
3. Adicione o controle no `app.py`.

Nada em `matcher.py`, `stats.py` ou na aba de resultados precisa mudar.

## Limitações (leia antes de decidir qualquer coisa com isso)

- **N inflado por sobreposição.** 300 dias casados consecutivos são quase uma única observação.
  Use a coluna **Episódios** — é ela que diz quantas situações independentes existem.
- **Fear & Greed só existe desde fevereiro de 2018**, cerca de um ciclo e meio.
- **Regimes não são comparáveis.** Um retorno de 12 meses de 2013 e um de 2023 são coisas
  diferentes. O filtro de data inicial existe por isso (default 2015).
- **M2 é publicado com defasagem** de 1 a 3 meses conforme o país. O Japão (IMF/IFS) é o mais
  atrasado; o agregado é encadeado (*chain-linked*), então um componente que entra ou sai da
  amostra não cria degrau artificial no nível.
- Isto é estatística descritiva do passado, não previsão.

## Fontes

| Série | Fonte | Chave de API |
|---|---|---|
| BTC/USD diário | Bitstamp OHLC (fallback Yahoo Finance) | não |
| Fear & Greed | alternative.me | não |
| M2 EUA | FRED `WM2NS` | não |
| M2 Zona do Euro | ECB Data Portal, série `BSI.M.U2.Y.V.M20.X.1.U2.2300.Z01.E` | não |
| M2 China | PBoC via chinadata.live, emendado com FRED `MYAGM2CNM189N` para 1999–2014 | não |
| M2 Japão | IMF IFS `M.JP.FMB_XDC` via DBnomics | não |
| M4 Reino Unido | Bank of England `LPMAUYM` | não |
| Câmbio | FRED `DEXUSEU`, `DEXCHUS`, `DEXJPUS`, `DEXUSUK` | não |
| MVRV Z-score | Coin Metrics community API (`CapMVRVCur`, `CapMrktCurUSD`) | não |

As séries de M2 estrangeiro **do FRED** (`MYAGM2EZM196N`, `MYAGM2JPM189N`, `MABMM301*`) foram
descontinuadas entre 2017 e 2023 e não servem para atualização diária — por isso cada país vem
da fonte oficial viva.
