#!/usr/bin/env python3
"""Climatologia mensal do MSWEP para a validação (valida_previsoes.py --obs mswep).

O período padrão é 1993–2016, igual ao dos hindcasts do Copernicus, de modo que a
anomalia observada e a prevista (previsão − hindcast) tenham a mesma referência.

Etapas:
  1. (opcional, --remote) baixa com rclone os mensais AAAAMM.nc do Drive da GloH2O
     para <dir-mensal>. Requer um remote do rclone com acesso à pasta do MSWEP
     (acesso pedido pelo formulário em gloh2o.org/mswep).
  2. Recorta a América do Sul e calcula a média de cada mês do ano com todos os anos
     disponíveis. Um mês só entra se tiver todos os anos do período (ou --min-anos).
  3. Grava <saida> com precipitation(month, lat, lon) em mm/mês.

Uso:
    python clima_mswep.py --remote mswep:MSWEP_V280/Past/Monthly --meses 10
    python clima_mswep.py                     # só recalcula com os arquivos já baixados
"""
import argparse
import os
import subprocess

import numpy as np
import xarray as xr

DIR_MSWEP = "/home/marcio/scripts/MSWEP"
# domínio com folga em relação ao dos mapas (lon -109,5..-20,5, lat -59,5..19,5)
LON = (-115.0, -15.0)
LAT = (25.0, -65.0)


def baixa(remote, destino, anos, meses):
    os.makedirs(destino, exist_ok=True)
    for a in anos:
        for m in meses:
            nome = f"{a}{m:02d}.nc"
            if os.path.exists(os.path.join(destino, nome)):
                continue
            print(f"  rclone copy {remote}/{nome}")
            r = subprocess.run(["rclone", "copy", f"{remote}/{nome}", destino])
            if r.returncode != 0:
                print(f"  falhou: {nome}")


def recorta(arq):
    ds = xr.open_dataset(arq)
    p = ds["precipitation"].sel(lon=slice(*LON), lat=slice(*LAT))
    return p.isel(time=0, drop=True).load() if "time" in p.dims else p.load()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir-mensal", default=os.path.join(DIR_MSWEP, "Past_Monthly"),
                    help="Diretório com os AAAAMM.nc do período da climatologia")
    ap.add_argument("--saida", default=os.path.join(DIR_MSWEP, "clima", "mswep_clima_1993-2016.nc"))
    ap.add_argument("--ini", type=int, default=1993)
    ap.add_argument("--fim", type=int, default=2016)
    ap.add_argument("--meses", type=int, nargs="*", default=list(range(1, 13)))
    ap.add_argument("--remote", help="Caminho rclone da pasta mensal (ex.: mswep:MSWEP_V280/Past/Monthly)")
    ap.add_argument("--min-anos", type=int, help="Mínimo de anos por mês (padrão: todos do período)")
    args = ap.parse_args()

    anos = list(range(args.ini, args.fim + 1))
    min_anos = args.min_anos or len(anos)
    if args.remote:
        baixa(args.remote, args.dir_mensal, anos, args.meses)

    # mantém meses já calculados numa execução anterior
    clima = {}
    if os.path.exists(args.saida):
        with xr.open_dataset(args.saida) as old:
            for m in old.month.values:
                clima[int(m)] = old["precipitation"].sel(month=m).load()

    for m in args.meses:
        arqs = [os.path.join(args.dir_mensal, f"{a}{m:02d}.nc") for a in anos]
        arqs = [a for a in arqs if os.path.exists(a)]
        if len(arqs) < min_anos:
            print(f"  mês {m:02d}: {len(arqs)}/{len(anos)} anos — não calculado")
            continue
        soma = None
        for a in arqs:
            p = recorta(a)
            soma = p if soma is None else soma + p
        clima[m] = (soma / len(arqs)).assign_attrs(units="mm month-1", n_anos=len(arqs))
        print(f"  mês {m:02d}: média de {len(arqs)} anos")

    if not clima:
        print("Nenhum mês calculado.")
        return
    meses = sorted(clima)
    out = xr.concat([clima[m] for m in meses], dim=xr.DataArray(meses, dims="month", name="month"))
    ds = out.to_dataset(name="precipitation")
    ds.attrs.update(fonte="MSWEP mensal", periodo=f"{args.ini}-{args.fim}",
                    dir_origem=os.path.abspath(args.dir_mensal))
    os.makedirs(os.path.dirname(args.saida), exist_ok=True)
    tmp = args.saida + ".tmp"
    ds.to_netcdf(tmp, encoding={"precipitation": {"zlib": True, "complevel": 4, "dtype": "float32"}})
    os.replace(tmp, args.saida)
    print(f"-> {args.saida} (meses {meses})")


if __name__ == "__main__":
    main()
