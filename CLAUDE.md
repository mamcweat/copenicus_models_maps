# Memória do projeto — Previsões sazonais Copernicus

Pipeline que baixa previsões sazonais mensais do Copernicus CDS (centros europeus e outros),
gera mapas de previsão para a América do Sul e valida as previsões de anomalia de chuva contra o
observado (CPTEC-MERGE). Idioma do projeto: português.

## Fluxo

1. `automacao_copernicus.py --modelo <m|ALL> --month MM --year AAAA`
   Baixa do CDS (`cdsapi`) para `saida_modelos/<MODELO>_0.nc` (previsão) e `<MODELO>_1.nc`
   (hindcast/climatologia) e chama `gera_mapas_previsao.py`. Esses .nc são **sobrescritos** a
   cada rodada, por isso a validação usa os PNGs, não os .nc. Pode rodar via crontab.
   Modelos: bom, dwd, cmcc, ecmwf, meteo_france, ukmo, ncep, eccc, jma (`MODEL_SYSTEM_MAP`).
   Antes de baixar, consulta o catálogo do CDS (endpoint de constraints, via `ecmwf.datastores`,
   sem gerar pedido na fila) e pula modelos cuja rodada ainda não foi publicada (costuma sair no
   meio do mês). `--verificar` só consulta; `--pendentes` pula modelos com mapas já gerados;
   `--month/--year` têm como padrão o mês atual. Termina com código 0 só se todos ficaram prontos,
   o que permite rodar diariamente pelo crontab na 2ª quinzena.
2. `gera_mapas_previsao.py` gera 6 meses (M1..M6) de PR, TMAX e TMIN, absoluto e anomalia, em
   `saida_mapas/<MODELO>_<AAAAMM da rodada>/mapa_<MODELO>_<VAR>_<abs|anom>_M<k>_<AAAAMM alvo>.png`.
   Domínio: lon −109,5..−20,5, lat −59,5..19,5, grade de 1°. A anomalia é previsão − hindcast.
   A paleta de anomalia de chuva está em `get_cmap_anomalia_chuva()`
   (níveis −300,−200,−150,−100,−50,−20,20,50,100,150,200,300; branco de −20 a 20).
3. `gera_multimodelo.py --rodada AAAAMM` gera o consenso `saida_mapas/MULTIMODELO_<AAAAMM>/`
   (mesmos nomes de arquivo dos modelos). A anomalia é a média, com peso igual, das anomalias de
   cada modelo (previsão − hindcast próprio), o que é igual à média das previsões menos a média dos
   hindcasts. O absoluto é a média das previsões. Nos mapas de anomalia, o pontilhado (cinza
   #7a7a7a, claro para não confundir o georreferenciamento do validador) marca onde menos de
   ⌈7N/9⌉ modelos concordam com o sinal. O JMA (1,25°) é interpolado para 1°. Só entram os
   modelos cujo `saida_modelos/<MODELO>.rodada` (gravado pelo automacao) é a rodada pedida, porque
   os .nc são sobrescritos. Grava `multimodelo.json` (modelos usados e limiar).
4. `gera_pdf_comparativo.py` monta o PDF comparativo (`Comparativo_Modelos_<AAAAMM>.pdf`) com a
   grade de todos os modelos por variável/tipo/mês. O MULTIMODELO fica no último painel (10º do
   5x2), e o rodapé de cada página explica como ele é calculado.
5. `prepara_verificacao.py --alvo AAAAMM [--obs PNG]` monta as pastas de verificação do mês-alvo
   (M1 → `OUT26`, M2 → `SET26-OUT26`, M3 → `AGO26-OUT26`, ...) copiando os mapas PR_anom de cada
   rodada existente; com `--obs` copia a anomalia MERGE como `OBS_<MES><AA>.png`. Não sobrescreve
   sem `--force`.
6. `valida_previsoes.py` faz a validação espacial da previsão contra o observado (detalhes abaixo).
7. `gera_relatorio_validacao.py --alvo AAAAMM` gera `Verificação/Relatorio_Validacao_<MES><AA>.pdf`
   (resumo, comparação entre rodadas e uma seção por rodada), a partir dos CSV/PNG de
   `<PASTA>/validacao/`; rodar depois do `valida_previsoes.py`. HTML de apoio em
   `Verificação/relatorio_<MES><AA>/`.
8. `clima_mswep.py` (preparado, ainda não usado): baixa via rclone os mensais MSWEP 1993–2016 e
   gera `~/scripts/MSWEP/clima/mswep_clima_1993-2016.nc`, para no futuro validar contra o MSWEP.

## Validação (`valida_previsoes.py`)

Entrada: `saida_mapas/Verificação/<PASTA>/`. Cada pasta corresponde a um mês verificado, por
exemplo `SET26` (M1 da rodada 202609) ou `AGO26-SET26` (M2 da rodada 202608 para setembro).
Cada pasta contém:
- `mapa_<MODELO>_PR_anom_M<k>_<AAAAMM>.png` (copiados de `saida_mapas/<MODELO>_<rodada>/`)
- `OBS*.png`: mapa de anomalia "CPTEC - MERGE" (layout Rural Clima, estilo GrADS)

```
python valida_previsoes.py                     # todas as pastas + ranking consolidado
python valida_previsoes.py --pasta SET26 --debug
python valida_previsoes.py --res 0.5
```

Método:
- **Georreferenciamento automático**: detecta o quadro do mapa e ajusta (chamfer matching) a
  costa, as fronteiras e os estados do Natural Earth 50m às linhas pretas da imagem. Faz uma busca
  em grade dentro de `BUSCA_EXTENSAO` e refina com Nelder-Mead. Isso é necessário porque os PNGs
  do observado variam de tamanho e de extensão entre meses (ex.: AGO lon −85..−30, SET lon
  −82..−33). Um erro de ajuste acima de 3 px gera aviso; com `--debug` o script salva sobreposições
  em `validacao/calibracao/`.
- **Decodificação de cores**: o pixel recebe o valor central da classe. `PALETA_PREVISAO` vem do
  gera_mapas. `PALETA_OBS` são as cores do MERGE, com classes de 20 mm e branco de −10 a 10;
  acima de 120 mm o observado usa a mesma cor do triângulo, logo satura em ±120. Se o CPTEC mudar
  a legenda, atualizar `PALETA_OBS`.
- **Grade comum** (1° por padrão): média dos pixels por célula, com saturação comum de ±140 mm,
  apenas continente, ponderada por cos(lat).
- **Métricas**: quantitativas (corr, ACC não centrado, RMSE, MAE, viés) e qualitativas
  (3 categorias com limiar ±20 mm, comum às duas escalas: % de acerto, HSS e acerto de sinal).
- **Ranking**: média das posições por métrica (quantitativo e qualitativo); o geral é a média dos
  dois. Calculado por região em `REGIOES` (América do Sul geral, Brasil, N, NE, CO, SE, S, MATOPIBA;
  regiões definidas por listas de UFs).

Saídas em `<PASTA>/validacao/`: `Validacao_<PASTA>.pdf`, `metricas_ranking_<PASTA>.csv`,
`ranking_<PASTA>.png` e `campos_<PASTA>.png`. Saída geral: `Verificação/ranking_consolidado.csv`.

Cuidados de interpretação:
- Nordeste em AGO/SET (estação seca) cai quase todo em "normal", então HSS ≈ 0 e o ranking da
  região pesa pouco.
- O MERGE é ruidoso nos Andes e na Colômbia, o que reduz a correlação "geral"; o recorte Brasil
  é mais confiável.

## Ambiente

- Máquina de desenvolvimento (notebook): Python do miniconda (`/home/marcio/miniconda3/bin/python3`),
  shell tcsh.
- Produção: o repositório é clonado numa VM, onde roda o crontab (`cron_copernicus.sh`, ver
  README). Dependências em `environment.yml` (conda-forge + pip: cdsapi, ecmwf-datastores-client).
  Credenciais em `~/.cdsapirc`; o `ecmwf.datastores` lê a mesma url/key desse arquivo.
- Todos os caminhos são relativos ao diretório do script (`BASE_DIR`). O `automacao` passa
  `--dir_saida` ao `gera_mapas_previsao.py`, porque sem isso o cron gravava os mapas relativos ao
  diretório corrente. Não reintroduzir caminhos absolutos de /home/marcio.
- `saida_modelos/`, `saida_mapas/`, `logs/` e os PDFs comparativos não são versionados.
- A validação mensal roda no **notebook**, onde fica o histórico (`saida_mapas/Verificação/`).
  Antes do `prepara_verificacao.py`, traga da VM os mapas novos (sem `--delete`):
  `rsync -av --exclude 'Verificação/' <vm>:<clone>/saida_mapas/ saida_mapas/`.
- Bibliotecas: xarray, cartopy 0.24, geopandas, shapely 2, scipy, matplotlib, PIL, cdsapi.
  OpenCV e tesseract **não** estão instalados.
- Shapefiles Natural Earth em cache: `~/.local/share/cartopy/shapefiles/natural_earth/`.
  O admin_1 50m inclui as UFs do Brasil (coluna `postal`).

## Resultados registrados

| Pasta | Ranking geral (América do Sul) |
|---|---|
| AGO26 (M1) | ECMWF, BOM, JMA, DWD, UKMO, CMCC, METEO_FRANCE, NCEP |
| SET26 (M1) | ECMWF, JMA, NCEP, UKMO, CMCC, METEO_FRANCE, BOM, DWD |
| AGO26-SET26 (M2) | DWD, UKMO, CMCC, ECMWF, METEO_FRANCE, BOM, JMA, NCEP |
| OUT26 (M1) | UKMO, ECMWF, BOM, CMCC, NCEP, JMA, METEO_FRANCE, DWD |
| SET26-OUT26 (M2) | UKMO, DWD, METEO_FRANCE, ECMWF, BOM, JMA, NCEP, CMCC |
| AGO26-OUT26 (M3) | ECMWF, UKMO, JMA, BOM, METEO_FRANCE, CMCC, DWD, NCEP |

Consolidado (6 pastas, até OUT26): América do Sul → ECMWF, UKMO, BOM, JMA; Brasil → UKMO, ECMWF,
BOM, JMA. NCEP e METEO_FRANCE ficam no fim. Out/2026 teve anomalia positiva no CO/SE/PR e seca no
RS/Norte; quase todos os modelos subestimaram (viés negativo no Brasil, exceto NCEP, que superestima).

## Pendências conhecidas

- MULTIMODELO criado em 11/11/2026, a partir da rodada 202611. Ele entra sozinho no
  `prepara_verificacao.py`/`valida_previsoes.py` como mais um "modelo"; a primeira validação
  possível é a de NOV26 (M1). Comparar o desempenho dele com o dos modelos individuais.

- ECCC: trocado em 11/11/2026 do sistema 3 (sem rodadas desde 2024; por isso o ECCC nunca gerou
  mapas) para o 5. O CDS também tem o 4 (outro modelo do CanSIPS, mesma data de início). Ainda
  não há mapas nem validação do ECCC; conferir a primeira rodada no gera_mapas_previsao.py.
- A chave `meteo_france` duplicada no `MODEL_SYSTEM_MAP` foi corrigida em 11/11/2026 (sistema 9).
