# copenicus_models_maps
Script que pega dados mensais do Copernicus, do seguinte site:
https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels?tab=download#leadtime_month
https://cds.climate.copernicus.eu/datasets/seasonal-original-single-levels?tab=overview

python3 automacao_copernicus.py --help
usage: automacao_copernicus.py [-h] [--modelo {bom,dwd,cmcc,ecmwf,meteo_france,ukmo,ncep,eccc,jma,ALL,all}] [--month MONTH] [--year YEAR] [--all]

Automação de download e geração de mapas operacionais do CDS Copernicus.

options:
  -h, --help            show this help message and exit
  --modelo {bom,dwd,cmcc,ecmwf,meteo_france,ukmo,ncep,eccc,jma,ALL,all}
                        Origem do modelo ou 'ALL' para rodar todos.
  --month MONTH         Mês da previsão (01 a 12).
  --year YEAR           Ano da previsão (ex: 2026).
  --all                 Executa para todos os modelos cadastrados.
marcio-Latitude-3440:/home/marcio/scripts/modelos/copernicus>python3 automacao_copernicus.py --modelo jma --month 08 --year 2026

python gera_mapas_previsao.py --f_previsao saida_modelos/DWD_0.nc --f_hindcast saida_modelos/DWD_1.nc --modelo DWD --mes 08 --ano 2026
