import argparse
import calendar
import os
from datetime import datetime
from dateutil.relativedelta import relativedelta
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from mpl_toolkits.axes_grid1 import make_axes_locatable
import numpy as np
import xarray as xr
import cartopy.crs as ccrs
import cartopy.feature as cfeature

def parse_args():
    parser = argparse.ArgumentParser(description="Geração de Mapas de Previsão Climática Sazonal (6 Meses)")
    parser.add_argument("--f_previsao", type=str, required=True, help="Caminho do arquivo data_0")
    parser.add_argument("--f_hindcast", type=str, required=True, help="Caminho do arquivo data_1")
    parser.add_argument("--modelo", type=str, default="BOM", help="Nome do modelo meteorológico")
    parser.add_argument("--mes", type=int, required=True, help="Mês da rodada inicial (1-12)")
    parser.add_argument("--ano", type=int, required=True, help="Ano da rodada inicial (ex: 2026)")
    parser.add_argument("--dir_saida", type=str, default="saida_mapas", help="Diretório base de saída")
    return parser.parse_args()

def get_days_in_month(year, month):
    return calendar.monthrange(year, month)[1]

def extrai_matriz_2d(da_slice):
    da_squeezed = da_slice.squeeze()
    while da_squeezed.ndim > 2:
        da_squeezed = da_squeezed.isel({da_squeezed.dims[0]: 0})
    return da_squeezed.values

def get_cmap_chuva():
    levels = [10, 25, 50, 75, 100, 150, 200, 250, 300, 350, 400, 450, 500, 600]
    colors = [
        '#00FF00', '#00A800', '#006400', '#FFFF00', '#FFC800', 
        '#FF9600', '#FF0000', '#CC0000', '#800000', '#4A0000', 
        '#990099', '#E6B8E6', '#DDA0DD'
    ]
    cmap = ListedColormap(colors)
    cmap.set_under('#FFFFFF')
    cmap.set_over('#DDA0DD')
    norm = BoundaryNorm(levels, ncolors=cmap.N)
    return cmap, norm, levels

def get_cmap_anomalia_chuva():
    levels = [-300, -200, -150, -100, -50, -20, 20, 50, 100, 150, 200, 300]
    colors = [
        '#8B2500', '#C84B31', '#D98880', '#E6B0AA', '#FADBD8', 
        '#FFFFFF', 
        '#B2C6D5', '#7FA0B5', '#4A7C9D', '#1A5B8C', '#0D3B66'
    ]
    cmap = ListedColormap(colors)
    cmap.set_under('#5B0000')
    cmap.set_over('#051C3B')
    norm = BoundaryNorm(levels, ncolors=cmap.N)
    return cmap, norm, levels

def processa_variaveis_mes(ds_prev, ds_hind, lead_idx, target_date):
    days = get_days_in_month(target_date.year, target_date.month)
    sec_in_month = days * 86400

    pr_p_raw = ds_prev['tprate'].isel({ds_prev['tprate'].dims[0]: lead_idx})
    pr_h_raw = ds_hind['tprate'].isel({ds_hind['tprate'].dims[0]: lead_idx})
    
    tmin_p_raw = ds_prev['mn2t24'].isel({ds_prev['mn2t24'].dims[0]: lead_idx})
    tmin_h_raw = ds_hind['mn2t24'].isel({ds_hind['mn2t24'].dims[0]: lead_idx})
    
    tmax_p_raw = ds_prev['mx2t24'].isel({ds_prev['mx2t24'].dims[0]: lead_idx})
    tmax_h_raw = ds_hind['mx2t24'].isel({ds_hind['mx2t24'].dims[0]: lead_idx})

    pr_prev = extrai_matriz_2d(pr_p_raw) * sec_in_month * 1000.0
    pr_hind = extrai_matriz_2d(pr_h_raw) * sec_in_month * 1000.0
    pr_anom = pr_prev - pr_hind

    tmin_prev = extrai_matriz_2d(tmin_p_raw) - 273.15
    tmin_hind = extrai_matriz_2d(tmin_h_raw) - 273.15
    tmin_anom = tmin_prev - tmin_hind

    tmax_prev = extrai_matriz_2d(tmax_p_raw) - 273.15
    tmax_hind = extrai_matriz_2d(tmax_h_raw) - 273.15
    tmax_anom = tmax_prev - tmax_hind

    cmap_pr, norm_pr, lev_pr = get_cmap_chuva()
    cmap_anom_pr, norm_anom_pr, lev_anom_pr = get_cmap_anomalia_chuva()

    return {
        'PR': (pr_prev, pr_anom, 'Chuva Acumulada', 'mm', cmap_pr, norm_pr, lev_pr, cmap_anom_pr, norm_anom_pr, lev_anom_pr),
        'TMIN': (tmin_prev, tmin_anom, 'Temperatura Mínima', '°C', 'jet', None, np.arange(0, 33, 2), 'RdBu_r', None, np.arange(-5, 5.5, 0.5)),
        'TMAX': (tmax_prev, tmax_anom, 'Temperatura Máxima', '°C', 'jet', None, np.arange(10, 43, 2), 'RdBu_r', None, np.arange(-5, 5.5, 0.5))
    }

def plota_mapa(lons, lats, data, header_esq, header_dir, cbar_label, cmap, levels, norm, output_path,
               pontilhado=None):
    """pontilhado: máscara 2D opcional (True = pontilhar), usada no MULTIMODELO para
    marcar onde os modelos não concordam no sinal da anomalia.
    O cinza #7a7a7a é claro o bastante para o valida_previsoes.py não confundir os
    pontos com as linhas pretas (limiar 110) usadas no georreferenciamento."""
    fig = plt.figure(figsize=(10, 10))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    
    # Limites territoriais
    ax.add_feature(cfeature.LAND, facecolor='none', edgecolor='none')
    ax.add_feature(cfeature.OCEAN, facecolor='none', edgecolor='none')
    ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
    ax.add_feature(cfeature.BORDERS, linestyle='-', linewidth=0.6, edgecolor='black')
    
    states = cfeature.NaturalEarthFeature(
        category='cultural',
        name='admin_1_states_provinces_lines',
        scale='50m',
        facecolor='none'
    )
    ax.add_feature(states, edgecolor='black', linewidth=0.4)

    ax.set_extent([lons.min(), lons.max(), lats.min(), lats.max()], crs=ccrs.PlateCarree())

    # Plotagem dos dados
    if norm is not None:
        cf = ax.contourf(lons, lats, data, levels=levels, cmap=cmap, norm=norm, extend='both', transform=ccrs.PlateCarree())
    else:
        cf = ax.contourf(lons, lats, data, levels=levels, cmap=cmap, extend='both', transform=ccrs.PlateCarree())
    
    if pontilhado is not None and np.any(pontilhado):
        with plt.rc_context({"hatch.color": "#7a7a7a", "hatch.linewidth": 0.7}):
            ax.contourf(lons, lats, np.asarray(pontilhado, dtype=float), levels=[0.5, 1.5],
                        colors="none", hatches=[".."], transform=ccrs.PlateCarree())

    # Grade e rótulos
    gl = ax.gridlines(draw_labels=True, linestyle='--', color='gray', alpha=0.5)
    gl.top_labels = False
    gl.right_labels = False

    # Títulos sem sobreposição (Separados em Esquerda e Direita)
    plt.title(header_esq, fontsize=10, fontweight='bold', loc='left', pad=12)
    plt.title(header_dir, fontsize=10, fontweight='bold', loc='right', pad=12)

    # Inserção da Barra de Cores Proporcional para evitar sobreposição
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="4%", pad=0.15, axes_class=plt.Axes)
    
    cbar = fig.colorbar(cf, cax=cax, orientation='vertical', ticks=levels)
    cbar.set_label(cbar_label, fontsize=10, fontweight='bold')
    cbar.ax.tick_params(labelsize=9)

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

def main():
    args = parse_args()

    pasta_rodada = f"{args.modelo}_{args.ano}{args.mes:02d}"
    caminho_saida = os.path.join(args.dir_saida, pasta_rodada)
    os.makedirs(caminho_saida, exist_ok=True)

    ds_prev = xr.open_dataset(args.f_previsao)
    ds_hind = xr.open_dataset(args.f_hindcast)

    lats = ds_prev['latitude'].values
    lons = ds_prev['longitude'].values

    run_date = datetime(args.ano, args.mes, 1)

    for lead_idx in range(6):
        target_date = run_date + relativedelta(months=lead_idx)
        str_data = target_date.strftime('%m/%Y')
        num_mes_prev = lead_idx + 1

        vars_dict = processa_variaveis_mes(ds_prev, ds_hind, lead_idx, target_date)

        for key, tuple_var in vars_dict.items():
            val_abs, val_anom, nome_var, unit, cmap_abs, norm_abs, lev_abs, cmap_anom, norm_anom, lev_anom = tuple_var
            sufixo_arquivo = f"M{num_mes_prev}_{target_date.strftime('%Y%m')}.png"

            # 1. Mapa Absoluto
            hdr_esq_abs = f"{args.modelo}\n{nome_var} ({unit})"
            hdr_dir_abs = f"Rodada: {args.ano}-{args.mes:02d}\nMensal {str_data}"
            fn_abs = os.path.join(caminho_saida, f"mapa_{args.modelo}_{key}_abs_{sufixo_arquivo}")
            plota_mapa(lons, lats, val_abs, hdr_esq_abs, hdr_dir_abs, f"{nome_var} ({unit})", cmap_abs, lev_abs, norm_abs, fn_abs)

            # 2. Mapa de Anomalia
            hdr_esq_anom = f"{args.modelo} vs CLIM\nAnomalia de {nome_var} ({unit})"
            hdr_dir_anom = f"Rodada: {args.ano}-{args.mes:02d}\nMensal (anomalia) {str_data}"
            fn_anom = os.path.join(caminho_saida, f"mapa_{args.modelo}_{key}_anom_{sufixo_arquivo}")
            plota_mapa(lons, lats, val_anom, hdr_esq_anom, hdr_dir_anom, f"Anomalia ({unit})", cmap_anom, lev_anom, norm_anom, fn_anom)

        print(f"-> Mapas do Mês {num_mes_prev} ({str_data}) gerados com sucesso.")

    print(f"\nTodos os mapas foram salvos em: {caminho_saida}")

if __name__ == "__main__":
    main()