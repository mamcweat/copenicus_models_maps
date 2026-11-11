#!/usr/bin/env python3
"""Monta as pastas de verificação de um mês-alvo para o valida_previsoes.py.

Para cada prazo k (M1..M6), procura a rodada AAAAMM = alvo - (k-1) meses em
saida_mapas/<MODELO>_<rodada>/ e copia os mapas de anomalia de chuva
mapa_<MODELO>_PR_anom_M<k>_<alvo>.png para a pasta de verificação:

    M1 -> Verificação/OUT26
    M2 -> Verificação/SET26-OUT26     (rodada de setembro, alvo outubro)
    M3 -> Verificação/AGO26-OUT26 ...

Com --obs, o mapa observado (anomalia CPTEC-MERGE) é copiado para cada pasta
como OBS_<MES><AA>.png. Arquivos existentes não são sobrescritos sem --force.

Uso:
    python prepara_verificacao.py --alvo 202610
    python prepara_verificacao.py --alvo 202610 --obs ~/Downloads/anomalia_chuva.png
"""
import argparse
import glob
import os
import re
import shutil

MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def rotulo(aaaamm):
    return f"{MESES[int(aaaamm[4:]) - 1]}{aaaamm[2:4]}"


def menos_meses(aaaamm, n):
    a, m = int(aaaamm[:4]), int(aaaamm[4:]) - 1 - n
    a += m // 12
    return f"{a:04d}{m % 12 + 1:02d}"


def copia(orig, dest, force):
    if os.path.exists(dest) and not force:
        return False
    shutil.copy2(orig, dest)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alvo", required=True, help="Mês verificado, AAAAMM")
    ap.add_argument("--mapas", default="saida_mapas", help="Diretório com <MODELO>_<rodada>/")
    ap.add_argument("--dir", default="saida_mapas/Verificação", help="Diretório das pastas de verificação")
    ap.add_argument("--obs", help="PNG da anomalia observada (CPTEC-MERGE) a copiar para as pastas")
    ap.add_argument("--max-lead", type=int, default=6)
    ap.add_argument("--force", action="store_true", help="Sobrescreve arquivos existentes")
    args = ap.parse_args()

    if not re.fullmatch(r"\d{4}(0[1-9]|1[0-2])", args.alvo):
        ap.error("--alvo deve ser AAAAMM")
    if args.obs and not os.path.isfile(args.obs):
        ap.error(f"arquivo --obs não encontrado: {args.obs}")

    alvo = args.alvo
    criadas = []
    for k in range(1, args.max_lead + 1):
        rodada = menos_meses(alvo, k - 1)
        arqs = sorted(glob.glob(os.path.join(args.mapas, f"*_{rodada}", f"mapa_*_PR_anom_M{k}_{alvo}.png")))
        if not arqs:
            continue
        nome = rotulo(alvo) if k == 1 else f"{rotulo(rodada)}-{rotulo(alvo)}"
        pasta = os.path.join(args.dir, nome)
        os.makedirs(pasta, exist_ok=True)
        n = sum(copia(a, os.path.join(pasta, os.path.basename(a)), args.force) for a in arqs)
        modelos = [re.match(r"mapa_(.+)_PR_anom", os.path.basename(a)).group(1) for a in arqs]
        msg = f"M{k} rodada {rodada} -> {nome}: {len(arqs)} modelos ({n} copiados)"
        if args.obs:
            dest = os.path.join(pasta, f"OBS_{rotulo(alvo)}.png")
            msg += "; OBS copiado" if copia(args.obs, dest, args.force) else "; OBS já existia"
        elif not glob.glob(os.path.join(pasta, "OBS*.png")):
            msg += "; SEM OBS*.png"
        print(msg)
        print("    " + ", ".join(modelos))
        criadas.append(nome)

    if not criadas:
        print(f"Nenhum mapa de previsão encontrado para {alvo}.")
    else:
        print("\nValidar com:\n    python valida_previsoes.py --pasta " + " ".join(criadas))


if __name__ == "__main__":
    main()
