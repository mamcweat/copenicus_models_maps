#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import zipfile
from pathlib import Path
import cdsapi

# Caminhos absolutos garantindo execução via CRONTAB
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "saida_modelos"

# Mapeamento: originating_centre -> system
MODEL_SYSTEM_MAP = {
    "bom": "2",
    "dwd": "22",
    "cmcc": "4",
    "ecmwf": "51",
    "meteo_france": "8",
    "ukmo": "610",
    "ncep": "2",
    "eccc": "3",
    "meteo_france": "9",
    "jma": "4"
}

def baixar_e_processar_modelo(modelo: str, month: str, year: str) -> bool:
    """Baixa o ZIP do Copernicus, extrai data_1.nc e data_2.nc, renomeia e gera os mapas."""
    modelo_lower = modelo.lower()
    modelo_upper = modelo.upper()

    if modelo_lower not in MODEL_SYSTEM_MAP:
        print(f"[-] Erro: Modelo '{modelo}' não cadastrado na biblioteca.")
        return False

    system_id = MODEL_SYSTEM_MAP[modelo_lower]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    month_str = f"{int(month):02d}"
    year_str = str(year)

    # Definir caminho do arquivo zip temporário
    temp_zip = BASE_DIR / f"temp_{modelo_lower}_{year_str}{month_str}.zip"

    request = {
        "originating_centre": modelo_lower,
        "system": system_id,
        "variable": [
            "maximum_2m_temperature_in_the_last_24_hours",
            "minimum_2m_temperature_in_the_last_24_hours",
            "total_precipitation"
        ],
        "product_type": [
            "ensemble_mean",
            "hindcast_climate_mean"
        ],
        "year": [year_str],
        "month": [month_str],
        "leadtime_month": ["1", "2", "3", "4", "5", "6"],
        "data_format": "netcdf",
        "area": [20, -110, -60, -20]
    }

    print(f"\n[+] Baixando dados do Copernicus para {modelo_upper} (Sistema {system_id})...")
    try:
        client = cdsapi.Client()
        # Forçar o salvamento do download no caminho específico fornecendo 'target'
        result = client.retrieve("seasonal-monthly-single-levels", request)
        result.download(target=str(temp_zip))
    except Exception as e:
        print(f"[-] Erro ao realizar o download no Copernicus: {e}")
        return False

    f_prev = OUTPUT_DIR / f"{modelo_upper}_0.nc"
    f_hind = OUTPUT_DIR / f"{modelo_upper}_1.nc"

    # Processamento e descompactação do ZIP
    try:
        if not temp_zip.exists():
            print(f"[-] Erro: Arquivo descarregado não foi encontrado em {temp_zip}")
            return False

        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            arquivos_no_zip = zip_ref.namelist()
            print(f"[+] Arquivos encontrados no ZIP: {arquivos_no_zip}")
            
            extracted_count = 0
            for file_name in arquivos_no_zip:
                if file_name == "data_0.nc":
                    zip_ref.extract(file_name, OUTPUT_DIR)
                    os.replace(OUTPUT_DIR / "data_0.nc", f_prev)
                    extracted_count += 1
                elif file_name == "data_1.nc":
                    zip_ref.extract(file_name, OUTPUT_DIR)
                    os.replace(OUTPUT_DIR / "data_1.nc", f_hind)
                    extracted_count += 1

            if extracted_count < 2:
                print("[-] Aviso: Nem todos os arquivos esperados (data_0.nc, data_1.nc) estavam no ZIP.")
                return False

    except Exception as e:
        print(f"[-] Erro ao descompactar ou renomear arquivos: {e}")
        return False
    finally:
        if temp_zip.exists():
            temp_zip.unlink()

    print(f"[+] Arquivos extraídos e salvos: {f_prev.name} e {f_hind.name}")

    # Execução do script de geração de mapas
    script_mapas = BASE_DIR / "gera_mapas_previsao.py"
    cmd = [
        sys.executable, str(script_mapas),
        "--f_previsao", str(f_prev),
        "--f_hindcast", str(f_hind),
        "--modelo", modelo_upper,
        "--mes", month_str,
        "--ano", year_str
    ]

    print(f"[+] Gerando mapas: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode == 0:
        print(f"[+] Mapas gerados com sucesso para {modelo_upper}.")
        if res.stdout:
            print(f"[Log gera_mapas]:\n{res.stdout}")
        return True
    else:
        print(f"[-] Erro ao executar gera_mapas_previsao.py:\n{res.stderr}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Automação de download e geração de mapas operacionais do CDS Copernicus.")
    parser.add_argument("--modelo", type=str, choices=list(MODEL_SYSTEM_MAP.keys()) + ["ALL", "all"], help="Origem do modelo ou 'ALL' para rodar todos.")
    parser.add_argument("--month", type=str, help="Mês da previsão (01 a 12).")
    parser.add_argument("--year", type=str, help="Ano da previsão (ex: 2026).")
    parser.add_argument("--all", action="store_true", help="Executa para todos os modelos cadastrados.")

    args = parser.parse_args()

    if not args.month or not args.year:
        parser.error("Os argumentos --month e --year são obrigatórios.")

    if args.all or (args.modelo and args.modelo.upper() == "ALL"):
        modelos_para_rodar = list(MODEL_SYSTEM_MAP.keys())
    elif args.modelo:
        modelos_para_rodar = [args.modelo]
    else:
        parser.error("Informe um modelo com --modelo <NOME> ou utilize a opção --all.")

    for mod in modelos_para_rodar:
        baixar_e_processar_modelo(mod, args.month, args.year)

if __name__ == "__main__":
    main()