# copenicus_models_maps

Previsões sazonais mensais do Copernicus C3S (CDS) para a América do Sul: download,
mapas de previsão (chuva, Tmax e Tmin; absoluto e anomalia; meses M1 a M6), PDF
comparativo entre modelos e validação da anomalia de chuva contra o CPTEC-MERGE.

Fontes:
- https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels
- https://cds.climate.copernicus.eu/datasets/seasonal-original-single-levels (diário)

Modelos: BOM, CMCC, DWD, ECCC, ECMWF, JMA, METEO_FRANCE, NCEP, UKMO
(sistemas em `MODEL_SYSTEM_MAP`, no `automacao_copernicus.py`).

## Instalação (VM nova)

```bash
git clone https://github.com/mamcweat/copenicus_models_maps.git copernicus
cd copernicus

# 1. Ambiente Python
conda env create -f environment.yml          # cria o ambiente "copernicus"

# 2. Pacotes do sistema
sudo apt install fonts-dejavu-core           # fontes do PDF comparativo
# opcional, só para gera_relatorio_validacao.py: google-chrome ou chromium

# 3. Credenciais do CDS (https://cds.climate.copernicus.eu/profile)
cat > ~/.cdsapirc <<EOF
url: https://cds.climate.copernicus.eu/api
key: <SUA-CHAVE>
EOF
chmod 600 ~/.cdsapirc
```

A licença do dataset "seasonal-monthly-single-levels" precisa estar aceita na conta
do CDS. Os shapefiles do Natural Earth são baixados pelo cartopy na primeira execução,
então a VM precisa de acesso à internet.

Teste rápido, que só consulta o catálogo e não baixa nada:

```bash
conda activate copernicus
python automacao_copernicus.py --all --verificar
```

## Rotina mensal automática (crontab)

As rodadas costumam ser publicadas no CDS por volta do meio do mês. O
`cron_copernicus.sh` pode rodar várias vezes por dia nessa janela:
- consulta o catálogo do CDS e baixa só os modelos já publicados;
- pula os modelos cujos mapas do mês já existem;
- quando os 9 estão prontos, gera o consenso MULTIMODELO (`gera_multimodelo.py`) e
  `Comparativo_Modelos_<AAAAMM>.pdf`, uma única vez;
- usa uma trava (`flock`) para não rodar duas vezes ao mesmo tempo e grava o log em
  `logs/automacao_<AAAAMM>.log`.

```bash
chmod +x cron_copernicus.sh
crontab -e
```
```
# Copernicus: 3x ao dia, do dia 5 ao 25
0 8,14,20 5-25 * * PYTHON=$HOME/miniconda3/envs/copernicus/bin/python $HOME/copernicus/cron_copernicus.sh
```

Ajuste os caminhos ao local do clone e do conda na VM.

## Uso manual

```bash
python automacao_copernicus.py --all                          # mês atual
python automacao_copernicus.py --modelo ecmwf --month 10 --year 2026
python automacao_copernicus.py --all --pendentes              # só o que falta
python automacao_copernicus.py --all --verificar              # só consulta a publicação
python gera_multimodelo.py --rodada 202611                    # consenso (média dos modelos)
python gera_pdf_comparativo.py --rodada 202611                # ~17 MB (800 px, JPEG 60)
python gera_pdf_comparativo.py --rodada 202611 --largura 1100 --qualidade 75 \
       --saida-pdf Comparativo_Modelos_202611_alta.pdf         # alta resolução (~33 MB)
```

## Validação mensal (contra o CPTEC-MERGE)

A validação roda na máquina que guarda o histórico (`saida_mapas/Verificação/`), não na VM.
Depois que o mês termina, traga da VM as rodadas novas e, com o PNG de anomalia do MERGE
(layout Rural Clima) em mãos, rode:

```bash
# mapas da VM (sem --delete, para não apagar rodadas antigas e o histórico local)
rsync -av --exclude 'Verificação/' <vm>:copernicus/saida_mapas/ saida_mapas/
rsync -av '<vm>:copernicus/Comparativo_Modelos_*.pdf' .          # opcional

python prepara_verificacao.py --alvo 202610 --obs OBS_OUT26.png   # monta as pastas M1..M6
python valida_previsoes.py                                        # métricas + ranking consolidado
python gera_relatorio_validacao.py --alvo 202610                  # relatório PDF por rodada
```

## Estrutura de saída (não versionada)

```
saida_modelos/<MODELO>_0.nc, _1.nc     previsão e hindcast da última rodada (sobrescritos)
saida_mapas/<MODELO>_<AAAAMM>/         36 PNGs por modelo e rodada
saida_mapas/Verificação/<PASTA>/       pastas de validação, OBS*.png e resultados
Comparativo_Modelos_<AAAAMM>.pdf
logs/
```

Nada disso vem no `git clone`. A VM produz os mapas e os comparativos. A máquina de
validação recebe os mapas por `rsync` (ver acima) e guarda o histórico `saida_mapas/Verificação/`.

Detalhes do método e dos resultados estão em `CLAUDE.md`.
