#!/usr/bin/env python3
"""Previsão MULTIMODELO (consenso) a partir dos modelos já baixados em saida_modelos/.

Para cada modelo: anomalia = previsão (ensemble_mean) − hindcast do próprio modelo,
na grade de 1° (o JMA, em 1,25°, é interpolado). O MULTIMODELO é a média simples,
com peso igual, dessas anomalias. Isso é o mesmo que a média das previsões menos a
média dos hindcasts. O mapa absoluto é a média das previsões.

Nos mapas de anomalia, o pontilhado marca os pontos em que menos de LIMIAR dos N
modelos concordam com o sinal da média (padrão: 7 de 9, proporcional se N ≠ 9).

Os .nc de saida_modelos/ são sobrescritos a cada rodada, por isso só entram os
modelos cujo <MODELO>.rodada (gravado pelo automacao_copernicus.py) é a rodada pedida.

Saída: saida_mapas/MULTIMODELO_<AAAAMM>/, com os mesmos nomes de arquivo dos modelos,
e multimodelo.json (modelos usados e limiar), lido pelo gera_pdf_comparativo.py.

Uso:
    python gera_multimodelo.py --rodada 202611
"""
import argparse
import json
import math
import os
from datetime import datetime

import numpy as np
import xarray as xr
from dateutil.relativedelta import relativedelta

from gera_mapas_previsao import plota_mapa, processa_variaveis_mes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NOME = "MULTIMODELO"
MIN_MODELOS = 5


def modelos_da_rodada(dir_modelos, rodada):
    usados, ignorados = [], []
    for arq in sorted(os.listdir(dir_modelos)):
        if not arq.endswith("_0.nc"):
            continue
        m = arq[:-5]
        f_rod = os.path.join(dir_modelos, f"{m}.rodada")
        f_hind = os.path.join(dir_modelos, f"{m}_1.nc")
        rod = open(f_rod).read().strip() if os.path.exists(f_rod) else None
        if rod == rodada and os.path.exists(f_hind):
            usados.append(m)
        else:
            ignorados.append((m, rod))
    return usados, ignorados


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rodada", required=True, help="AAAAMM da rodada")
    ap.add_argument("--dir-modelos", default=os.path.join(BASE_DIR, "saida_modelos"))
    ap.add_argument("--dir-saida", default=os.path.join(BASE_DIR, "saida_mapas"))
    ap.add_argument("--min-modelos", type=int, default=MIN_MODELOS)
    args = ap.parse_args()

    modelos, ignorados = modelos_da_rodada(args.dir_modelos, args.rodada)
    for m, rod in ignorados:
        print(f"  ignorado: {m} (rodada dos .nc: {rod or 'desconhecida'})")
    n = len(modelos)
    if n < args.min_modelos:
        raise SystemExit(f"Só {n} modelos da rodada {args.rodada} ({modelos}); mínimo {args.min_modelos}.")
    limiar = math.ceil(n * 7 / 9)
    print(f"{NOME} {args.rodada}: {n} modelos {modelos}; pontilhado onde < {limiar}/{n} concordam no sinal")

    # grade de referência: a de 1° usada pela maioria dos modelos
    grade = None
    dados = {}
    for m in modelos:
        p = xr.open_dataset(os.path.join(args.dir_modelos, f"{m}_0.nc"))
        h = xr.open_dataset(os.path.join(args.dir_modelos, f"{m}_1.nc"))
        dados[m] = (p, h)
        if grade is None and p.sizes["latitude"] == 80:
            grade = (p["latitude"], p["longitude"])
    if grade is None:
        raise SystemExit("Nenhum modelo na grade de 1° para servir de referência.")
    lat_ref, lon_ref = grade
    for m, (p, h) in dados.items():
        if p.sizes["latitude"] != lat_ref.size or not np.allclose(p["latitude"], lat_ref) \
                or not np.allclose(p["longitude"], lon_ref):
            print(f"  {m}: interpolado para a grade de 1°")
            dados[m] = (p.interp(latitude=lat_ref, longitude=lon_ref),
                        h.interp(latitude=lat_ref, longitude=lon_ref))

    lats, lons = lat_ref.values, lon_ref.values
    ano, mes = int(args.rodada[:4]), int(args.rodada[4:])
    run_date = datetime(ano, mes, 1)
    pasta = os.path.join(args.dir_saida, f"{NOME}_{args.rodada}")
    os.makedirs(pasta, exist_ok=True)

    for lead in range(6):
        alvo = run_date + relativedelta(months=lead)
        str_data = alvo.strftime("%m/%Y")
        por_modelo = [processa_variaveis_mes(p, h, lead, alvo) for p, h in dados.values()]
        for key in ("PR", "TMIN", "TMAX"):
            _, _, nome_var, unit, cmap_abs, norm_abs, lev_abs, cmap_anom, norm_anom, lev_anom = por_modelo[0][key]
            absol = np.stack([d[key][0] for d in por_modelo])
            anom = np.stack([d[key][1] for d in por_modelo])
            media_abs = np.nanmean(absol, axis=0)
            media_anom = np.nanmean(anom, axis=0)
            concordam = (np.sign(anom) == np.sign(media_anom)).sum(axis=0)
            fraco = concordam < limiar

            sufixo = f"M{lead + 1}_{alvo.strftime('%Y%m')}.png"
            hdr_dir = f"Rodada: {ano}-{mes:02d}\nMensal {str_data}"
            plota_mapa(lons, lats, media_abs,
                       f"{NOME} (média de {n} modelos)\n{nome_var} ({unit})", hdr_dir,
                       f"{nome_var} ({unit})", cmap_abs, lev_abs, norm_abs,
                       os.path.join(pasta, f"mapa_{NOME}_{key}_abs_{sufixo}"))
            plota_mapa(lons, lats, media_anom,
                       f"{NOME} vs CLIM ({n} modelos)\nAnomalia de {nome_var} ({unit})",
                       f"Rodada: {ano}-{mes:02d}\nMensal (anomalia) {str_data}",
                       f"Anomalia ({unit})  ·  pontilhado: < {limiar}/{n} concordam no sinal",
                       cmap_anom, lev_anom, norm_anom,
                       os.path.join(pasta, f"mapa_{NOME}_{key}_anom_{sufixo}"),
                       pontilhado=fraco)
        print(f"-> M{lead + 1} ({str_data})")

    with open(os.path.join(pasta, "multimodelo.json"), "w") as f:
        json.dump({"rodada": args.rodada, "modelos": modelos, "limiar_concordancia": limiar}, f, indent=1)
    print(f"Mapas em {pasta}")


if __name__ == "__main__":
    main()
