#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import zipfile
from datetime import date, datetime
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
    "meteo_france": "9",
    "ukmo": "610",
    "ncep": "2",
    "eccc": "5",
    "jma": "4"
}

DATASET = "seasonal-monthly-single-levels"
VARIAVEIS = [
    "maximum_2m_temperature_in_the_last_24_hours",
    "minimum_2m_temperature_in_the_last_24_hours",
    "total_precipitation"
]
PRODUTOS = ["ensemble_mean", "hindcast_climate_mean"]
MAPAS_DIR = BASE_DIR / "saida_mapas"


def _cliente_constraints():
    """Cliente leve do CDS para consultar o catálogo (não cria pedidos na fila)."""
    from ecmwf.datastores import Client
    cfg = {}
    rc = Path.home() / ".cdsapirc"
    if rc.exists():
        for linha in rc.read_text().splitlines():
            if ":" in linha:
                k, v = linha.split(":", 1)
                cfg[k.strip()] = v.strip()
    url = os.getenv("CDSAPI_URL") or cfg.get("url")
    key = os.getenv("CDSAPI_KEY") or cfg.get("key")
    return Client(url=url, key=key)


def verificar_disponibilidade(modelos, month: str, year: str) -> dict:
    """Consulta o catálogo do CDS (endpoint de constraints) para saber se a rodada
    AAAAMM de cada modelo já foi publicada, com previsão e hindcast das 3 variáveis.

    Retorna {modelo: True | False | None}; None = não foi possível consultar
    (nesse caso o download é tentado mesmo assim).
    """
    month_str = f"{int(month):02d}"
    try:
        client = _cliente_constraints()
    except Exception as e:
        print(f"[!] Não foi possível consultar o catálogo do CDS ({e}); seguindo sem verificação.")
        return {m: None for m in modelos}

    status = {}
    for modelo in modelos:
        m = modelo.lower()
        ok = True
        try:
            for produto in PRODUTOS:
                r = client.apply_constraints(DATASET, {
                    "originating_centre": m,
                    "system": MODEL_SYSTEM_MAP[m],
                    "year": [str(year)],
                    "product_type": [produto],
                    "variable": VARIAVEIS,
                })
                meses = r.get("month", [])
                if month_str not in meses:
                    ok = False
                    if not meses:
                        print(f"[!] {m.upper()}: o sistema {MODEL_SYSTEM_MAP[m]} não tem nenhuma rodada em "
                              f"{year} no CDS — provavelmente foi descontinuado; revise MODEL_SYSTEM_MAP.")
                    break
            status[m] = ok
        except Exception as e:
            print(f"[!] {m.upper()}: falha na consulta ao catálogo ({e}).")
            status[m] = None
    return status


def mapas_ja_gerados(modelo: str, month: str, year: str) -> bool:
    pasta = MAPAS_DIR / f"{modelo.upper()}_{year}{int(month):02d}"
    return pasta.is_dir() and any(pasta.glob("mapa_*_PR_anom_M1_*.png"))


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
        "variable": VARIAVEIS,
        "product_type": PRODUTOS,
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
        result = client.retrieve(DATASET, request)
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

    # marca a rodada dos .nc (são sobrescritos a cada mês); usada pelo gera_multimodelo.py
    (OUTPUT_DIR / f"{modelo_upper}.rodada").write_text(f"{year_str}{month_str}\n")
    print(f"[+] Arquivos extraídos e salvos: {f_prev.name} e {f_hind.name}")

    # Execução do script de geração de mapas
    script_mapas = BASE_DIR / "gera_mapas_previsao.py"
    cmd = [
        sys.executable, str(script_mapas),
        "--f_previsao", str(f_prev),
        "--f_hindcast", str(f_hind),
        "--modelo", modelo_upper,
        "--mes", month_str,
        "--ano", year_str,
        "--dir_saida", str(MAPAS_DIR)
    ]

    print(f"[+] Gerando mapas: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR)

    if res.returncode == 0:
        print(f"[+] Mapas gerados com sucesso para {modelo_upper}.")
        if res.stdout:
            print(f"[Log gera_mapas]:\n{res.stdout}")
        return True
    else:
        print(f"[-] Erro ao executar gera_mapas_previsao.py:\n{res.stderr}")
        return False

def main():
    hoje = date.today()
    parser = argparse.ArgumentParser(
        description="Automação de download e geração de mapas operacionais do CDS Copernicus.",
        epilog="As rodadas costumam ser publicadas no CDS por volta do meio do mês. Antes de baixar, "
               "o script consulta o catálogo e pula os modelos ainda não publicados. Para o crontab, "
               "rode diariamente na 2ª quinzena com --pendentes: só baixa o que falta e termina com "
               "código 0 quando todos os modelos do mês estão prontos.")
    parser.add_argument("--modelo", type=str, choices=list(MODEL_SYSTEM_MAP.keys()) + ["ALL", "all"], help="Origem do modelo ou 'ALL' para rodar todos.")
    parser.add_argument("--month", type=str, default=f"{hoje.month:02d}", help="Mês da previsão (01 a 12; padrão: mês atual).")
    parser.add_argument("--year", type=str, default=str(hoje.year), help="Ano da previsão (padrão: ano atual).")
    parser.add_argument("--all", action="store_true", help="Executa para todos os modelos cadastrados.")
    parser.add_argument("--verificar", action="store_true", help="Só verifica a publicação no CDS, sem baixar.")
    parser.add_argument("--pendentes", action="store_true", help="Pula modelos cujos mapas do mês já foram gerados.")
    parser.add_argument("--sem-verificacao", action="store_true", help="Baixa sem consultar o catálogo antes.")

    args = parser.parse_args()

    if args.all or (args.modelo and args.modelo.upper() == "ALL"):
        modelos_para_rodar = list(MODEL_SYSTEM_MAP.keys())
    elif args.modelo:
        modelos_para_rodar = [args.modelo.lower()]
    else:
        parser.error("Informe um modelo com --modelo <NOME> ou utilize a opção --all.")

    rodada = f"{args.year}{int(args.month):02d}"
    print(f"[i] Rodada {rodada} — {datetime.now():%d/%m/%Y %H:%M}")

    prontos = []
    if args.pendentes:
        prontos = [m for m in modelos_para_rodar if mapas_ja_gerados(m, args.month, args.year)]
        for m in prontos:
            print(f"[=] {m.upper()}: mapas de {rodada} já gerados, pulando.")
        modelos_para_rodar = [m for m in modelos_para_rodar if m not in prontos]

    if args.sem_verificacao:
        status = {m: None for m in modelos_para_rodar}
    else:
        status = verificar_disponibilidade(modelos_para_rodar, args.month, args.year)
        print(f"\n[i] Publicação no CDS ({DATASET}), rodada {rodada}:")
        for m in modelos_para_rodar:
            s = status[m]
            txt = "disponível" if s else ("AINDA NÃO PUBLICADO" if s is False else "não verificado")
            print(f"    {m.upper():<13} sistema {MODEL_SYSTEM_MAP[m]:<4} {txt}")

    if args.verificar:
        faltam = [m for m, s in status.items() if not s]
        sys.exit(1 if faltam else 0)

    sucesso, falha, indisponivel = [], [], []
    for mod in modelos_para_rodar:
        if status[mod] is False:
            indisponivel.append(mod)
            continue
        (sucesso if baixar_e_processar_modelo(mod, args.month, args.year) else falha).append(mod)

    print(f"\n[i] Resumo da rodada {rodada}:")
    for rot, lst in [("já prontos", prontos), ("processados", sucesso),
                     ("não publicados", indisponivel), ("com erro", falha)]:
        if lst:
            print(f"    {rot:<15} {', '.join(m.upper() for m in lst)}")
    sys.exit(1 if (falha or indisponivel) else 0)

if __name__ == "__main__":
    main()