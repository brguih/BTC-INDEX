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

## Indicadores

| Indicador | O que é | Histórico | Parâmetros |
|---|---|---|---|
| **Fear & Greed** | índice de sentimento 0–100 da alternative.me | 2018-02 → hoje | banda ± pontos |
| **M2 global (USD)** | M2 de EUA + Zona do Euro + China + Japão + Reino Unido convertido a dólar | 1999 → hoje | janela de variação (semanas), *lead* em dias, países no agregado, banda ± p.p. |
| **Net Liquidity do Fed** | balanço do Fed − conta do Tesouro − reverse repo | 2003 → hoje | idem |
| **Ciclo do BTC** | dias decorridos desde a âncora do ciclo | 2012-11 → hoje | âncora (halving/topo/fundo), comprimento do ciclo, banda ± dias |

### Sobre o ciclo

Os halvings **não** são de 1460 dias. Intervalos observados: **1319**, **1402** e **1435** dias.
O default do projeto é **1435** e a âncora default é o halving, a única conhecida em tempo real
(topos e fundos só se conhecem depois do fato). O próximo halving é projetado para março/2028.

### Sobre o lead da liquidez

O valor do indicador de liquidez no dia `t` é a variação percentual da liquidez em `N` semanas
medida `lead` dias **antes** de `t`. Com o default de 70 dias (10 semanas), o sinal de hoje usa
M2 de ~10 semanas atrás — que é dado já publicado, o que resolve de quebra a defasagem de
publicação das fontes oficiais.

## Estrutura

```
app.py                  interface Streamlit
update_data.py          atualização por linha de comando
btcindex/
  cache.py              HTTP com retry + cache CSV + reamostragem para diário
  sources/              uma fonte por arquivo (btc_price, fear_greed, fred, global_m2, net_liquidity)
  cycle.py              halvings, topos, fundos, distância circular
  indicators.py         definição dos indicadores e regra de comparação
  matcher.py            casamento por banda, "E" composto, relaxamento automático
  stats.py              estatísticas das janelas + episódios independentes
  engine.py             amarra tudo
tests/                  testes do motor, sem rede
```

### Adicionar um indicador novo

1. Crie a fonte em `btcindex/sources/`, devolvendo uma `pd.Series` diária.
2. Em `engine.build_indicators`, monte um `Indicator` com `band_mode` `abs`, `rel` ou `circular`.
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
| Net Liquidity | FRED `WALCL`, `WTREGEN`, `RRPONTSYD` | não |

As séries de M2 estrangeiro **do FRED** (`MYAGM2EZM196N`, `MYAGM2JPM189N`, `MABMM301*`) foram
descontinuadas entre 2017 e 2023 e não servem para atualização diária — por isso cada país vem
da fonte oficial viva.
