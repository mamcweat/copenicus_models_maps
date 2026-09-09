import argparse
import calendar
import os
from datetime import datetime
from dateutil.relativedelta import relativedelta
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import cartopy.crs as ccrs
import cartopy.feature as cfeature

def parse_args():
    parser = argparse.ArgumentParser(description="Geração de Mapas de Previsão Climática Sazonal (6 Meses)")
    parser.add_argument("--f_previsao", type=str, required=True, help="Caminho do arquivo data_0 (Previsão BOM)")
    parser.add_argument("--f_hindcast", type=str, required=True, help="Caminho do arquivo data_1 (Climatologia BOM)")
    parser.add_argument("--modelo", type=str, default="BOM", help="Nome do modelo meteorológico")
    parser.add_argument("--mes", type=int, required=True, help="Mês da rodada inicial (1-12)")
    parser.add_argument("--ano", type=int, required=True, help="Ano da rodada inicial (ex: 2026)")
    parser.add_argument("--dir_saida", type=str, default="saida_mapas", help="Diretório base de saída dos mapas")
    return parser.parse_args()

def get_days_in_month(year, month):
    return calendar.monthrange(year, month)[1]

def extrai_matriz_2d(da_slice):
    """
    Garante a extração de uma matriz 2D (lat, lon) a partir da fatia de tempo selecionada.
    """
    da_squeezed = da_slice.squeeze()
    while da_squeezed.ndim > 2:
        da_squeezed = da_squeezed.isel({da_squeezed.dims[0]: 0})
    return da_squeezed.values

def processa_variaveis_mes(ds_prev, ds_hind, lead_idx, target_date):
    days = get_days_in_month(target_date.year, target_date.month)
    sec_in_month = days * 86400

    # Seleção do leadtime/mês específico na dimensão de tempo
    # Funciona se a dimensão primária de tempo for a primeira
    pr_p_raw = ds_prev['tprate'].isel({ds_prev['tprate'].dims[0]: lead_idx})
    pr_h_raw = ds_hind['tprate'].isel({ds_hind['tprate'].dims[0]: lead_idx})
    
    tmin_p_raw = ds_prev['mn2t24'].isel({ds_prev['mn2t24'].dims[0]: lead_idx})
    tmin_h_raw = ds_hind['mn2t24'].isel({ds_hind['mn2t24'].dims[0]: lead_idx})
    
    tmax_p_raw = ds_prev['mx2t24'].isel({ds_prev['mx2t24'].dims[0]: lead_idx})
    tmax_h_raw = ds_hind['mx2t24'].isel({ds_hind['mx2t24'].dims[0]: lead_idx})

    # Conversões e extração de matriz 2D
    pr_prev = extrai_matriz_2d(pr_p_raw) * sec_in_month * 1000.0
    pr_hind = extrai_matriz_2d(pr_h_raw) * sec_in_month * 1000.0
    pr_anom = pr_prev - pr_hind

    tmin_prev = extrai_matriz_2d(tmin_p_raw) - 273.15
    tmin_hind = extrai_matriz_2d(tmin_h_raw) - 273.15
    tmin_anom = tmin_prev - tmin_hind

    tmax_prev = extrai_matriz_2d(tmax_p_raw) - 273.15
    tmax_hind = extrai_matriz_2d(tmax_h_raw) - 273.15
    tmax_anom = tmax_prev - tmax_hind

    return {
        'PR': (pr_prev, pr_anom, 'Precipitação Acumulada', 'mm/mês', 'YlGnBu', 'BrBG', np.arange(0, 501, 50), np.arange(-200, 201, 20)),
        'TMIN': (tmin_prev, tmin_anom, 'Temperatura Mínima', '°C', 'jet', 'RdBu_r', np.arange(0, 33, 2), np.arange(-5, 5.5, 0.5)),
        'TMAX': (tmax_prev, tmax_anom, 'Temperatura Máxima', '°C', 'jet', 'RdBu_r', np.arange(10, 43, 2), np.arange(-5, 5.5, 0.5))
    }

def plota_mapa(lons, lats, data, title, cbar_label, cmap, levels, output_path):
    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={'projection': ccrs.PlateCarree()})
    
    ax.add_feature(cfeature.LAND, facecolor='lightgray', alpha=0.3)
    ax.add_feature(cfeature.OCEAN, facecolor='lightblue', alpha=0.3)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
    ax.add_feature(cfeature.BORDERS, linestyle=':', linewidth=0.8, edgecolor='black')
    
    states = cfeature.NaturalEarthFeature(
        category='cultural',
        name='admin_1_states_provinces_lines',
        scale='50m',
        facecolor='none'
    )
    ax.add_feature(states, edgecolor='gray', linewidth=0.5)

    ax.set_extent([lons.min(), lons.max(), lats.min(), lats.max()], crs=ccrs.PlateCarree())

    cf = ax.contourf(lons, lats, data, levels=levels, cmap=cmap, extend='both', transform=ccrs.PlateCarree())
    
    cbar = plt.colorbar(cf, ax=ax, orientation='horizontal', pad=0.04, shrink=0.75)
    cbar.set_label(cbar_label, fontsize=10, fontweight='bold')
    
    gl = ax.gridlines(draw_labels=True, linestyle='--', color='gray', alpha=0.5)
    gl.top_labels = False
    gl.right_labels = False

    plt.title(title, fontsize=11, fontweight='bold', pad=10)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()

def main():
    args = parse_args()

    # Criação do diretório específico para a rodada atual
    # Estrutura: saida_mapas/BOM_202608/
    pasta_rodada = f"{args.modelo}_{args.ano}{args.mes:02d}"
    caminho_saida = os.path.join(args.dir_saida, pasta_rodada)
    os.makedirs(caminho_saida, exist_ok=True)

    ds_prev = xr.open_dataset(args.f_previsao)
    ds_hind = xr.open_dataset(args.f_hindcast)

    lats = ds_prev['latitude'].values
    lons = ds_prev['longitude'].values

    run_date = datetime(args.ano, args.mes, 1)

    # Iteração pelos 6 meses de previsão (leadtime 0 a 5 -> Mês 1 a 6)
    for lead_idx in range(6):
        target_date = run_date + relativedelta(months=lead_idx)
        str_data = target_date.strftime('%B/%Y').capitalize()
        num_mês_prev = lead_idx + 1

        vars_dict = processa_variaveis_mes(ds_prev, ds_hind, lead_idx, target_date)

        for key, (val_abs, val_anom, nome_var, unit, cmap_abs, cmap_anom, lev_abs, lev_anom) in vars_dict.items():
            # Nome do arquivo inclui o mês de previsão (M1 a M6) e o mês de validade
            sufixo_arquivo = f"M{num_mês_prev}_{target_date.strftime('%Y%m')}.png"

            # 1. Mapa Absoluto
            title_abs = f"Previsão ({args.modelo}) - {nome_var}\nValidade: {str_data} (Mês {num_mês_prev})"
            fn_abs = os.path.join(caminho_saida, f"mapa_{args.modelo}_{key}_abs_{sufixo_arquivo}")
            plota_mapa(lons, lats, val_abs, title_abs, f"{nome_var} ({unit})", cmap_abs, lev_abs, fn_abs)

            # 2. Mapa de Anomalia
            title_anom = f"Anomalia de Previsão ({args.modelo}) - {nome_var}\nValidade: {str_data} (Mês {num_mês_prev})"
            fn_anom = os.path.join(caminho_saida, f"mapa_{args.modelo}_{key}_anom_{sufixo_arquivo}")
            plota_mapa(lons, lats, val_anom, title_anom, f"Anomalia ({unit})", cmap_anom, lev_anom, fn_anom)

        print(f"-> Mapas do Mês {num_mês_prev} ({str_data}) gerados com sucesso.")

    print(f"\nTodos os 6 meses foram processados e salvos em: {caminho_saida}")

if __name__ == "__main__":
    main()