#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
plot_seasonal_forecast.py

Geração de mapas de previsão sazonal a partir de arquivos NetCDF
provenientes do Copernicus / Climate Data Store (CDS).

Principais recursos
-------------------

Variáveis:

    mx2t24
        Temperatura máxima a 2 metros.
        Unidade original esperada: Kelvin.
        Convertida para °C.

    mn2t24
        Temperatura mínima a 2 metros.
        Unidade original esperada: Kelvin.
        Convertida para °C.

    tprate
        Taxa média de precipitação.
        Unidade original esperada: m/s.
        Convertida para precipitação acumulada mensal em mm.

Calendário:

    --year e --month definem o mês correspondente ao
    forecastMonth = 1.

Ensemble:

    Quando existir a dimensão "number", é calculada a média
    de todos os membros do ensemble.

Mapas mensais:

    Um mapa para cada forecastMonth disponível.

Mapas trimestrais:

    São calculadas janelas móveis de três meses.

    Temperatura:
        média ponderada pelo número de dias de cada mês.

    Precipitação:
        soma dos acumulados mensais.

Melhorias cartográficas:

    - Países da América do Sul;
    - Fronteiras internacionais;
    - Divisões administrativas de primeiro nível;
    - Estados brasileiros;
    - Linha de costa;
    - Destaque do contorno do Brasil;
    - Campo interpolado para visualização mais suave;
    - Uso de contourf, evitando aspecto pixelizado.

A interpolação espacial é utilizada SOMENTE na apresentação gráfica.
Os cálculos meteorológicos permanecem nos dados originais.

Exemplo:

    python3 plot_seasonal_forecast.py \
        --input data_2.nc \
        --output saida_mapas \
        --year 2026 \
        --month 9

Opcionalmente, processar apenas uma variável:

    python3 plot_seasonal_forecast.py \
        --input data_2.nc \
        --output saida_mapas \
        --year 2026 \
        --month 9 \
        --variable tprate
"""


import os
import argparse
import calendar
import warnings

import numpy as np
import pandas as pd
import xarray as xr

import matplotlib.pyplot as plt

from matplotlib.colors import (
    ListedColormap,
    BoundaryNorm,
)

from matplotlib.ticker import MultipleLocator

import cartopy.crs as ccrs
import cartopy.feature as cfeature

from cartopy.io import shapereader

from cartopy.mpl.ticker import (
    LongitudeFormatter,
    LatitudeFormatter,
)


# ============================================================
# CONFIGURAÇÃO GERAL
# ============================================================

# Resolução cartográfica.
#
# 50m oferece bom equilíbrio entre qualidade visual e velocidade.
MAP_RESOLUTION = "50m"


# Área principal de interesse: América do Sul.
#
# west, east, south, north
DEFAULT_MAP_EXTENT = [
    -85.0,
    -30.0,
    -60.0,
    15.0,
]


# Número aproximado de pontos desejados para a maior dimensão
# da grade interpolada.
#
# Aumentar este valor deixa as transições mais suaves, mas também
# aumenta o tempo de processamento.
DISPLAY_MAX_GRID_POINTS = 500


# Número mínimo de pontos desejado para cada dimensão.
DISPLAY_MIN_GRID_POINTS = 100


# DPI das figuras.
FIGURE_DPI = 180


# Tamanho padrão da figura.
FIGURE_SIZE = (
    12,
    9,
)


# ============================================================
# CONFIGURAÇÃO DAS VARIÁVEIS
# ============================================================

VARIABLES = {
    "mx2t24": {
        "nome": "Temperatura Máxima a 2 m",
        "unidade": "°C",
        "tipo": "temperatura",
        "descricao_mensal": "Temperatura Máxima Mensal",
        "descricao_trimestral": "Temperatura Máxima Média Trimestral",
    },

    "mn2t24": {
        "nome": "Temperatura Mínima a 2 m",
        "unidade": "°C",
        "tipo": "temperatura",
        "descricao_mensal": "Temperatura Mínima Mensal",
        "descricao_trimestral": "Temperatura Mínima Média Trimestral",
    },

    "tprate": {
        "nome": "Precipitação",
        "unidade": "mm",
        "tipo": "precipitacao",
        "descricao_mensal": "Precipitação Acumulada Mensal",
        "descricao_trimestral": "Precipitação Acumulada Trimestral",
    },
}


# ============================================================
# NOMES DOS MESES
# ============================================================

MESES_PT = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


# ============================================================
# ESCALA FIXA DE PRECIPITAÇÃO
# ============================================================

PRECIPITATION_LEVELS = [
    0,
    10,
    25,
    50,
    75,
    100,
    150,
    200,
    250,
    300,
    350,
    400,
    450,
    500,
    600,
]


PRECIPITATION_COLORS = [
    "#F2F2F2",  #   0 -  10 mm
    "#00E000",  #  10 -  25 mm
    "#009900",  #  25 -  50 mm
    "#006400",  #  50 -  75 mm
    "#FFF200",  #  75 - 100 mm
    "#FFC000",  # 100 - 150 mm
    "#FF9900",  # 150 - 200 mm
    "#FF6600",  # 200 - 250 mm
    "#F00000",  # 250 - 300 mm
    "#C00000",  # 300 - 350 mm
    "#800000",  # 350 - 400 mm
    "#B00070",  # 400 - 450 mm
    "#C99ABA",  # 450 - 500 mm
    "#D8C8D8",  # 500 - 600 mm
]


PRECIPITATION_CMAP = ListedColormap(
    PRECIPITATION_COLORS,
    name="precipitacao_faixas",
)


PRECIPITATION_NORM = BoundaryNorm(
    PRECIPITATION_LEVELS,
    ncolors=PRECIPITATION_CMAP.N,
    clip=False,
)


PRECIPITATION_CMAP.set_under(
    "#FFFFFF"
)


PRECIPITATION_CMAP.set_over(
    "#E6DCE6"
)


# ============================================================
# ABERTURA DO DATASET
# ============================================================

def abrir_dataset(arquivo):
    """
    Abre o arquivo NetCDF utilizando o backend netcdf4.
    """

    print()
    print("=" * 78)
    print(f"Abrindo arquivo: {arquivo}")
    print("=" * 78)

    ds = xr.open_dataset(
        arquivo,
        engine="netcdf4",
    )

    print("Arquivo aberto com sucesso.")
    print("Backend utilizado: netcdf4")

    return ds


# ============================================================
# INSPEÇÃO DO DATASET
# ============================================================

def mostrar_estrutura(ds):
    """
    Exibe dimensões, coordenadas e variáveis.
    """

    print()
    print("=" * 78)
    print("ESTRUTURA DO DATASET")
    print("=" * 78)

    print()
    print("DIMENSÕES:")

    for nome, tamanho in ds.sizes.items():

        print(
            f"  {nome}: {tamanho}"
        )

    print()
    print("COORDENADAS:")

    for coord in ds.coords:

        valores = ds[coord].values

        print()
        print(f"  {coord}")
        print(
            f"    Dimensões: {ds[coord].dims}"
        )
        print(
            f"    Shape: {ds[coord].shape}"
        )

        if (
            valores.ndim == 1
            and valores.size <= 20
        ):

            print(
                f"    Valores: {valores}"
            )

        else:

            try:

                print(
                    f"    Mínimo: {np.nanmin(valores)}"
                )

                print(
                    f"    Máximo: {np.nanmax(valores)}"
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

    print()
    print("VARIÁVEIS METEOROLÓGICAS:")

    for var in ds.data_vars:

        attrs = ds[var].attrs

        print()
        print(f"  {var}")
        print(
            f"    Shape: {ds[var].shape}"
        )
        print(
            f"    Dimensões: {ds[var].dims}"
        )
        print(
            "    Descrição: "
            f"{attrs.get('long_name', 'N/A')}"
        )
        print(
            "    Unidade: "
            f"{attrs.get('units', 'N/A')}"
        )

    print()
    print("=" * 78)


# ============================================================
# CALENDÁRIO DOS FORECAST MONTHS
# ============================================================

def criar_calendario_forecast(
    forecast_months,
    year,
    month,
):
    """
    Cria a correspondência entre forecastMonth e mês-calendário.

    forecastMonth = 1 corresponde ao --year e --month
    informados pelo usuário.
    """

    if month < 1 or month > 12:

        raise ValueError(
            "--month deve estar entre 1 e 12."
        )

    registros = []

    data_inicial = pd.Timestamp(
        year=year,
        month=month,
        day=1,
    )

    for forecast_month in forecast_months:

        deslocamento = (
            int(forecast_month) - 1
        )

        data_mes = (
            data_inicial
            + pd.DateOffset(
                months=deslocamento
            )
        )

        numero_dias = calendar.monthrange(
            data_mes.year,
            data_mes.month,
        )[1]

        registros.append(
            {
                "forecastMonth": int(
                    forecast_month
                ),

                "year": int(
                    data_mes.year
                ),

                "month": int(
                    data_mes.month
                ),

                "month_name": MESES_PT[
                    data_mes.month
                ],

                "year_month": (
                    f"{data_mes.year:04d}-"
                    f"{data_mes.month:02d}"
                ),

                "days": int(
                    numero_dias
                ),
            }
        )

    calendario = pd.DataFrame(
        registros
    )

    return calendario


def mostrar_calendario(calendario):
    """
    Mostra o calendário calculado.
    """

    print()
    print("=" * 78)
    print("CALENDÁRIO DA PREVISÃO")
    print("=" * 78)

    for _, linha in calendario.iterrows():

        print(
            f"  Forecast Month "
            f"{int(linha['forecastMonth'])}: "
            f"{linha['month_name']}/"
            f"{int(linha['year'])} "
            f"({int(linha['days'])} dias)"
        )

    print("=" * 78)


def criar_dataarray_dias(
    calendario,
    forecast_month_coord,
):
    """
    Cria DataArray contendo o número de dias de cada
    forecastMonth.
    """

    return xr.DataArray(
        calendario["days"].values.astype(
            float
        ),

        dims=[
            "forecastMonth"
        ],

        coords={
            "forecastMonth":
                forecast_month_coord
        },

        name="days_in_forecast_month",
    )


# ============================================================
# MÉDIA DO ENSEMBLE
# ============================================================

def calcular_media_ensemble(dados):
    """
    Calcula a média dos membros do ensemble quando existir
    a dimensão "number".
    """

    if "number" in dados.dims:

        numero_membros = dados.sizes[
            "number"
        ]

        print(
            "Calculando média do ensemble: "
            f"{numero_membros} membros"
        )

        dados = dados.mean(
            dim="number",
            skipna=True,
        )

    return dados


# ============================================================
# INDEXING TIME
# ============================================================

def remover_indexing_time(dados):
    """
    Remove indexing_time quando possuir apenas um ciclo.

    O processamento é interrompido se houver mais de um ciclo,
    evitando mistura involuntária entre diferentes rodadas.
    """

    if "indexing_time" not in dados.dims:

        return dados

    tamanho = dados.sizes[
        "indexing_time"
    ]

    if tamanho == 1:

        print(
            "Removendo dimensão indexing_time "
            "(apenas um ciclo disponível)."
        )

        return dados.isel(
            indexing_time=0
        )

    raise ValueError(
        "Foram encontrados "
        f"{tamanho} valores em indexing_time. "
        "O script está configurado para processar "
        "um único ciclo por arquivo."
    )


# ============================================================
# CONVERSÃO DE TEMPERATURA
# ============================================================

def converter_temperatura_para_celsius(dados):
    """
    Converte Kelvin para Celsius.

        °C = K - 273.15
    """

    print(
        "Convertendo temperatura: Kelvin -> °C"
    )

    resultado = (
        dados - 273.15
    )

    resultado.attrs = dados.attrs.copy()

    resultado.attrs["units"] = "°C"

    return resultado


# ============================================================
# CONVERSÃO DE PRECIPITAÇÃO
# ============================================================

def converter_tprate_para_mm_mensal(
    dados,
    dias_por_mes,
):
    """
    Converte taxa de precipitação de m/s para acumulado
    mensal em mm.

        mm = m/s
             * 1000 mm/m
             * 86400 s/dia
             * número de dias do mês
    """

    print(
        "Convertendo precipitação:"
    )

    print(
        "  m/s -> mm acumulados no mês"
    )

    resultado = (
        dados
        * 1000.0
        * 86400.0
        * dias_por_mes
    )

    resultado.attrs = dados.attrs.copy()

    resultado.attrs["units"] = "mm"

    resultado.attrs["long_name"] = (
        "Precipitação total acumulada mensal"
    )

    return resultado


# ============================================================
# PREPARAÇÃO DOS DADOS
# ============================================================

def preparar_dados(
    ds,
    variavel,
    dias_por_mes,
):
    """
    Processa uma variável:

    1. Média do ensemble;
    2. Remove indexing_time unitário;
    3. Converte temperatura para Celsius;
    4. Converte precipitação para acumulado mensal.
    """

    print()
    print(
        f"Preparando variável: {variavel}"
    )

    dados = ds[variavel]

    dados = calcular_media_ensemble(
        dados
    )

    dados = remover_indexing_time(
        dados
    )

    if variavel in (
        "mx2t24",
        "mn2t24",
    ):

        dados = (
            converter_temperatura_para_celsius(
                dados
            )
        )

    elif variavel == "tprate":

        dados = (
            converter_tprate_para_mm_mensal(
                dados,
                dias_por_mes,
            )
        )

    return dados


# ============================================================
# NORMALIZAÇÃO DAS COORDENADAS
# ============================================================

def normalizar_coordenadas(dados):
    """
    Normaliza as coordenadas para facilitar a plotagem.

    Longitude:
        Se estiver entre 0 e 360, converte para -180 a 180.

    Latitude:
        Ordena de sul para norte.

    Longitude:
        Ordena de oeste para leste.
    """

    resultado = dados

    # --------------------------------------------------------
    # LONGITUDE
    # --------------------------------------------------------

    if "longitude" not in resultado.coords:

        raise ValueError(
            "A coordenada 'longitude' não foi encontrada."
        )

    if "latitude" not in resultado.coords:

        raise ValueError(
            "A coordenada 'latitude' não foi encontrada."
        )

    lon = resultado["longitude"]

    if float(lon.max()) > 180.0:

        print(
            "Normalizando longitude: "
            "0-360 -> -180-180"
        )

        nova_longitude = (
            (
                lon + 180.0
            )
            % 360.0
        ) - 180.0

        resultado = resultado.assign_coords(
            longitude=nova_longitude
        )

    # --------------------------------------------------------
    # ORDENAÇÃO
    # --------------------------------------------------------

    resultado = resultado.sortby(
        "longitude"
    )

    resultado = resultado.sortby(
        "latitude"
    )

    return resultado


# ============================================================
# SUAVIZAÇÃO PARA VISUALIZAÇÃO
# ============================================================

def suavizar_para_visualizacao(dados):
    """
    Cria uma grade espacial mais densa para melhorar a
    aparência visual dos mapas.

    IMPORTANTE:
        Esta interpolação é utilizada somente para plotagem.
        Não altera os cálculos meteorológicos.

    É utilizada interpolação linear sobre latitude e longitude.
    """

    dados = normalizar_coordenadas(
        dados
    )

    n_lat_original = dados.sizes[
        "latitude"
    ]

    n_lon_original = dados.sizes[
        "longitude"
    ]

    # --------------------------------------------------------
    # DEFINIÇÃO DA NOVA RESOLUÇÃO
    # --------------------------------------------------------

    maior_dimensao = max(
        n_lat_original,
        n_lon_original,
    )

    if maior_dimensao >= DISPLAY_MAX_GRID_POINTS:

        # O campo já possui resolução suficiente.
        return dados

    fator = (
        DISPLAY_MAX_GRID_POINTS
        / maior_dimensao
    )

    n_lat_novo = max(
        DISPLAY_MIN_GRID_POINTS,
        int(
            np.ceil(
                n_lat_original * fator
            )
        ),
    )

    n_lon_novo = max(
        DISPLAY_MIN_GRID_POINTS,
        int(
            np.ceil(
                n_lon_original * fator
            )
        ),
    )

    n_lat_novo = min(
        n_lat_novo,
        DISPLAY_MAX_GRID_POINTS,
    )

    n_lon_novo = min(
        n_lon_novo,
        DISPLAY_MAX_GRID_POINTS,
    )

    print(
        "  Suavização visual:"
    )

    print(
        f"    Grade original: "
        f"{n_lat_original} x {n_lon_original}"
    )

    print(
        f"    Grade para plotagem: "
        f"{n_lat_novo} x {n_lon_novo}"
    )

    nova_latitude = np.linspace(
        float(
            dados["latitude"].min()
        ),

        float(
            dados["latitude"].max()
        ),

        n_lat_novo,
    )

    nova_longitude = np.linspace(
        float(
            dados["longitude"].min()
        ),

        float(
            dados["longitude"].max()
        ),

        n_lon_novo,
    )

    try:

        resultado = dados.interp(
            latitude=nova_latitude,
            longitude=nova_longitude,
            method="linear",
        )

    except Exception as erro:

        warnings.warn(
            "Não foi possível interpolar a grade "
            f"para suavização: {erro}. "
            "Será utilizada a grade original."
        )

        resultado = dados

    return resultado


# ============================================================
# DEFINIÇÃO DA ÁREA DO MAPA
# ============================================================

def obter_extent_mapa(dados):
    """
    Define a extensão do mapa.

    Para previsões sobre a América do Sul, limita o mapa
    à região principal.

    Caso os dados não tenham cobertura suficiente nessa área,
    utiliza a extensão dos próprios dados com uma pequena margem.
    """

    dados = normalizar_coordenadas(
        dados
    )

    lon_min = float(
        dados["longitude"].min()
    )

    lon_max = float(
        dados["longitude"].max()
    )

    lat_min = float(
        dados["latitude"].min()
    )

    lat_max = float(
        dados["latitude"].max()
    )

    # Verifica interseção razoável com a América do Sul.
    intersecta_america_sul = (
        lon_max >= DEFAULT_MAP_EXTENT[0]
        and lon_min <= DEFAULT_MAP_EXTENT[1]
        and lat_max >= DEFAULT_MAP_EXTENT[2]
        and lat_min <= DEFAULT_MAP_EXTENT[3]
    )

    if intersecta_america_sul:

        return DEFAULT_MAP_EXTENT

    margem_lon = (
        lon_max - lon_min
    ) * 0.03

    margem_lat = (
        lat_max - lat_min
    ) * 0.03

    return [
        lon_min - margem_lon,
        lon_max + margem_lon,
        lat_min - margem_lat,
        lat_max + margem_lat,
    ]


# ============================================================
# CARREGAMENTO DO CONTORNO DO BRASIL
# ============================================================

def obter_geometria_brasil():
    """
    Obtém a geometria do Brasil da base Natural Earth.

    Retorna None caso a geometria não possa ser carregada.
    """

    try:

        caminho = (
            shapereader.natural_earth(
                resolution=MAP_RESOLUTION,
                category="cultural",
                name="admin_0_countries",
            )
        )

        leitor = shapereader.Reader(
            caminho
        )

        for registro in leitor.records():

            atributos = registro.attributes

            nome = atributos.get(
                "NAME_LONG",
                ""
            )

            nome_adm = atributos.get(
                "ADMIN",
                ""
            )

            if (
                nome == "Brazil"
                or nome_adm == "Brazil"
            ):

                return registro.geometry

    except Exception as erro:

        warnings.warn(
            "Não foi possível carregar a geometria "
            f"do Brasil: {erro}"
        )

    return None


# ============================================================
# CAMADAS CARTOGRÁFICAS
# ============================================================

def adicionar_divisao_politica(ax):
    """
    Adiciona:

    - oceano;
    - costa;
    - fronteiras internacionais;
    - divisões administrativas de primeiro nível;
    - contorno destacado do Brasil.
    """

    # --------------------------------------------------------
    # OCEANO
    # --------------------------------------------------------

    ax.add_feature(
        cfeature.OCEAN.with_scale(
            MAP_RESOLUTION
        ),

        facecolor="#F3F5F7",
        zorder=0,
    )

    # --------------------------------------------------------
    # PAÍSES
    # --------------------------------------------------------

    ax.add_feature(
        cfeature.BORDERS.with_scale(
            MAP_RESOLUTION
        ),

        edgecolor="black",
        linewidth=0.65,
        zorder=8,
    )

    # --------------------------------------------------------
    # COSTA
    # --------------------------------------------------------

    ax.add_feature(
        cfeature.COASTLINE.with_scale(
            MAP_RESOLUTION
        ),

        edgecolor="black",
        linewidth=0.8,
        zorder=9,
    )

    # --------------------------------------------------------
    # DIVISÕES ADMINISTRATIVAS
    #
    # Esta camada inclui estados/províncias de primeiro nível.
    # Assim, os estados brasileiros aparecem quando disponíveis
    # na base Natural Earth.
    # --------------------------------------------------------

    try:

        caminho_admin_1 = (
            shapereader.natural_earth(
                resolution=MAP_RESOLUTION,
                category="cultural",
                name=(
                    "admin_1_states_provinces_lines"
                ),
            )
        )

        reader = shapereader.Reader(
            caminho_admin_1
        )

        geometries = list(
            reader.geometries()
        )

        ax.add_geometries(
            geometries,
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor="#202020",
            linewidth=0.35,
            alpha=0.85,
            zorder=7,
        )

    except Exception as erro:

        warnings.warn(
            "Não foi possível carregar as divisões "
            f"administrativas: {erro}"
        )

    # --------------------------------------------------------
    # DESTAQUE DO BRASIL
    # --------------------------------------------------------

    geometria_brasil = (
        obter_geometria_brasil()
    )

    if geometria_brasil is not None:

        ax.add_geometries(
            [geometria_brasil],
            crs=ccrs.PlateCarree(),
            facecolor="none",
            edgecolor="black",
            linewidth=1.05,
            zorder=10,
        )


# ============================================================
# GRADE E EIXOS
# ============================================================

def configurar_eixos_geograficos(
    ax,
    extent,
):
    """
    Configura extensão, grade e formatação geográfica.
    """

    ax.set_extent(
        extent,
        crs=ccrs.PlateCarree(),
    )

    # --------------------------------------------------------
    # GRADE
    # --------------------------------------------------------

    gl = ax.gridlines(
        crs=ccrs.PlateCarree(),
        draw_labels=False,
        linewidth=0.35,
        color="gray",
        alpha=0.5,
        linestyle="--",
        zorder=2,
    )

    gl.xlocator = plt.MultipleLocator(
        5
    )

    gl.ylocator = plt.MultipleLocator(
        5
    )

    # --------------------------------------------------------
    # TICKS
    # --------------------------------------------------------

    lon_ticks = np.arange(
        -90,
        -25,
        10,
    )

    lat_ticks = np.arange(
        -60,
        20,
        10,
    )

    ax.set_xticks(
        lon_ticks,
        crs=ccrs.PlateCarree(),
    )

    ax.set_yticks(
        lat_ticks,
        crs=ccrs.PlateCarree(),
    )

    ax.xaxis.set_major_formatter(
        LongitudeFormatter(
            zero_direction_label=False
        )
    )

    ax.yaxis.set_major_formatter(
        LatitudeFormatter()
    )

    ax.tick_params(
        labelsize=10
    )


# ============================================================
# ESCALAS DOS MAPAS
# ============================================================

def obter_escala(
    variavel,
    dados,
):
    """
    Retorna a configuração visual da variável.

    Precipitação:
        escala fixa e discreta.

    Temperatura:
        escala contínua baseada nos percentis 2 e 98.
    """

    # --------------------------------------------------------
    # PRECIPITAÇÃO
    # --------------------------------------------------------

    if variavel == "tprate":

        return {
            "cmap": PRECIPITATION_CMAP,
            "norm": PRECIPITATION_NORM,
            "vmin": None,
            "vmax": None,
            "levels": PRECIPITATION_LEVELS,
            "colorbar_levels":
                PRECIPITATION_LEVELS,
            "extend": "max",
            "discreta": True,
        }

    # --------------------------------------------------------
    # TEMPERATURA
    # --------------------------------------------------------

    valores = dados.values

    p2 = np.nanpercentile(
        valores,
        2,
    )

    p98 = np.nanpercentile(
        valores,
        98,
    )

    vmin = np.floor(
        p2
    )

    vmax = np.ceil(
        p98
    )

    # Garante que a escala tenha intervalo.
    if vmax <= vmin:

        vmax = vmin + 1.0

    # Mais níveis produzem transições suaves.
    levels = np.linspace(
        vmin,
        vmax,
        25,
    )

    return {
        "cmap": "RdYlBu_r",
        "norm": None,
        "vmin": vmin,
        "vmax": vmax,
        "levels": levels,
        "colorbar_levels": None,
        "extend": "both",
        "discreta": False,
    }


# ============================================================
# PLOTAGEM DO MAPA
# ============================================================

def plotar_mapa(
    dados,
    titulo,
    arquivo_saida,
    unidade,
    escala,
):
    """
    Gera um mapa geográfico suavizado.

    Etapas:

    1. Normaliza latitude/longitude;
    2. Interpola para uma grade mais densa;
    3. Usa contourf;
    4. Adiciona divisão política;
    5. Adiciona barra de cores.
    """

    # --------------------------------------------------------
    # PREPARAÇÃO DAS COORDENADAS
    # --------------------------------------------------------

    dados_plot = normalizar_coordenadas(
        dados
    )

    # --------------------------------------------------------
    # EXTENSÃO
    # --------------------------------------------------------

    extent = obter_extent_mapa(
        dados_plot
    )

    # --------------------------------------------------------
    # SUAVIZAÇÃO VISUAL
    # --------------------------------------------------------

    dados_plot = suavizar_para_visualizacao(
        dados_plot
    )

    # --------------------------------------------------------
    # FIGURA
    # --------------------------------------------------------

    fig = plt.figure(
        figsize=FIGURE_SIZE
    )

    ax = plt.axes(
        projection=ccrs.PlateCarree()
    )

    # --------------------------------------------------------
    # EXTENSÃO E OCEANO
    # --------------------------------------------------------

    configurar_eixos_geograficos(
        ax,
        extent,
    )

    # --------------------------------------------------------
    # CAMPO METEOROLÓGICO
    #
    # contourf produz transições muito mais suaves que
    # pcolormesh para grades de modelos sazonais.
    # --------------------------------------------------------

    if escala["discreta"]:

        im = ax.contourf(
            dados_plot["longitude"],
            dados_plot["latitude"],
            dados_plot.values,

            levels=escala["levels"],

            cmap=escala["cmap"],

            norm=escala["norm"],

            extend=escala["extend"],

            transform=ccrs.PlateCarree(),

            antialiased=True,

            zorder=3,
        )

    else:

        im = ax.contourf(
            dados_plot["longitude"],
            dados_plot["latitude"],
            dados_plot.values,

            levels=escala["levels"],

            cmap=escala["cmap"],

            vmin=escala["vmin"],

            vmax=escala["vmax"],

            extend=escala["extend"],

            transform=ccrs.PlateCarree(),

            antialiased=True,

            zorder=3,
        )

    # --------------------------------------------------------
    # DIVISÃO POLÍTICA
    #
    # Colocada após o campo para garantir visibilidade
    # sobre os valores meteorológicos.
    # --------------------------------------------------------

    adicionar_divisao_politica(
        ax
    )

    # --------------------------------------------------------
    # TÍTULO
    # --------------------------------------------------------

    ax.set_title(
        titulo,
        fontsize=15,
        fontweight="bold",
        pad=12,
    )

    # --------------------------------------------------------
    # BARRA DE CORES
    # --------------------------------------------------------

    if escala["colorbar_levels"] is not None:

        cbar = fig.colorbar(
            im,

            ax=ax,

            orientation="vertical",

            shrink=0.86,

            pad=0.025,

            ticks=escala[
                "colorbar_levels"
            ],

            boundaries=escala[
                "levels"
            ],

            spacing="proportional",

            extend=escala["extend"],
        )

    else:

        cbar = fig.colorbar(
            im,

            ax=ax,

            orientation="vertical",

            shrink=0.86,

            pad=0.025,

            extend=escala["extend"],
        )

    cbar.set_label(
        unidade,
        fontsize=11,
        labelpad=10,
    )

    cbar.ax.tick_params(
        labelsize=9
    )

    # --------------------------------------------------------
    # AJUSTE FINAL
    # --------------------------------------------------------

    plt.tight_layout()

    plt.savefig(
        arquivo_saida,
        dpi=FIGURE_DPI,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(
        fig
    )

    print(
        f"  Mapa salvo: {arquivo_saida}"
    )


# ============================================================
# MAPAS MENSAIS
# ============================================================

def gerar_mapas_mensais(
    dados,
    variavel,
    calendario,
    diretorio_saida,
):
    """
    Gera um mapa para cada forecastMonth.
    """

    config = VARIABLES[
        variavel
    ]

    escala = obter_escala(
        variavel,
        dados,
    )

    print()
    print(
        f"Gerando mapas mensais: {variavel}"
    )

    for _, linha in calendario.iterrows():

        forecast_month = int(
            linha["forecastMonth"]
        )

        year = int(
            linha["year"]
        )

        month_name = linha[
            "month_name"
        ]

        year_month = linha[
            "year_month"
        ]

        # ----------------------------------------------------
        # SELEÇÃO DO MÊS
        # ----------------------------------------------------

        campo = dados.sel(
            forecastMonth=forecast_month
        )

        # ----------------------------------------------------
        # TÍTULO
        # ----------------------------------------------------

        titulo = (
            f"{config['nome']}\n"
            f"{config['descricao_mensal']} - "
            f"{month_name}/{year}\n"
            f"Forecast Month {forecast_month} | "
            f"Média do Ensemble"
        )

        # ----------------------------------------------------
        # ARQUIVO
        # ----------------------------------------------------

        nome_arquivo = (
            f"{variavel}_"
            f"{year_month}.png"
        )

        arquivo_saida = os.path.join(
            diretorio_saida,
            nome_arquivo,
        )

        # ----------------------------------------------------
        # MAPA
        # ----------------------------------------------------

        plotar_mapa(
            dados=campo,

            titulo=titulo,

            arquivo_saida=arquivo_saida,

            unidade=config["unidade"],

            escala=escala,
        )


# ============================================================
# MÉDIA DE TEMPERATURA PONDERADA
# ============================================================

def calcular_media_temperatura_ponderada(
    dados_janela,
    dias_janela,
):
    """
    Calcula:

             soma(T_i * dias_i)
        T = ---------------------
                 soma(dias_i)
    """

    numerador = (
        dados_janela
        * dias_janela
    ).sum(
        dim="forecastMonth",
        skipna=True,
    )

    denominador = dias_janela.sum(
        dim="forecastMonth",
        skipna=True,
    )

    return (
        numerador
        / denominador
    )


# ============================================================
# MAPAS TRIMESTRAIS
# ============================================================

def gerar_mapas_trimestrais(
    dados,
    variavel,
    calendario,
    dias_por_mes,
    diretorio_saida,
):
    """
    Gera mapas para janelas móveis de três meses.

    Exemplos:

        M1-M3
        M2-M4
        M3-M5
        M4-M6
    """

    config = VARIABLES[
        variavel
    ]

    escala = obter_escala(
        variavel,
        dados,
    )

    print()
    print(
        f"Gerando mapas trimestrais: {variavel}"
    )

    forecast_months = list(
        dados["forecastMonth"].values
    )

    if len(forecast_months) < 3:

        print(
            "  Menos de três forecastMonths disponíveis."
        )

        print(
            "  Mapas trimestrais não serão gerados."
        )

        return

    # --------------------------------------------------------
    # JANELAS MÓVEIS
    # --------------------------------------------------------

    for inicio in range(
        len(forecast_months) - 2
    ):

        janela = forecast_months[
            inicio:inicio + 3
        ]

        print(
            "  Processando trimestre: "
            f"M{int(janela[0])}-"
            f"M{int(janela[-1])}"
        )

        dados_janela = dados.sel(
            forecastMonth=janela
        )

        dias_janela = dias_por_mes.sel(
            forecastMonth=janela
        )

        # ----------------------------------------------------
        # PRECIPITAÇÃO
        # ----------------------------------------------------

        if variavel == "tprate":

            # Os valores mensais já estão em mm acumulados.
            # Portanto, para o trimestre basta somar.
            campo = dados_janela.sum(
                dim="forecastMonth",
                skipna=True,
            )

        # ----------------------------------------------------
        # TEMPERATURA
        # ----------------------------------------------------

        else:

            campo = (
                calcular_media_temperatura_ponderada(
                    dados_janela,
                    dias_janela,
                )
            )

        # ----------------------------------------------------
        # PERÍODO
        # ----------------------------------------------------

        linha_inicio = calendario[
            calendario["forecastMonth"]
            == int(janela[0])
        ].iloc[0]

        linha_fim = calendario[
            calendario["forecastMonth"]
            == int(janela[-1])
        ].iloc[0]

        inicio_label = (
            f"{linha_inicio['month_name']}/"
            f"{int(linha_inicio['year'])}"
        )

        fim_label = (
            f"{linha_fim['month_name']}/"
            f"{int(linha_fim['year'])}"
        )

        inicio_arquivo = (
            f"{int(linha_inicio['year']):04d}-"
            f"{int(linha_inicio['month']):02d}"
        )

        fim_arquivo = (
            f"{int(linha_fim['year']):04d}-"
            f"{int(linha_fim['month']):02d}"
        )

        # ----------------------------------------------------
        # TÍTULO
        # ----------------------------------------------------

        titulo = (
            f"{config['nome']}\n"
            f"{config['descricao_trimestral']}\n"
            f"{inicio_label} a {fim_label}\n"
            f"Forecast Month "
            f"{int(janela[0])}-{int(janela[-1])} | "
            f"Média do Ensemble"
        )

        # ----------------------------------------------------
        # ARQUIVO
        # ----------------------------------------------------

        nome_arquivo = (
            f"{variavel}_"
            f"{inicio_arquivo}_"
            f"a_"
            f"{fim_arquivo}.png"
        )

        arquivo_saida = os.path.join(
            diretorio_saida,
            nome_arquivo,
        )

        # ----------------------------------------------------
        # MAPA
        # ----------------------------------------------------

        plotar_mapa(
            dados=campo,

            titulo=titulo,

            arquivo_saida=arquivo_saida,

            unidade=config["unidade"],

            escala=escala,
        )


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Geração de mapas de previsão sazonal "
            "a partir de dados do Copernicus/CDS."
        ),

        formatter_class=(
            argparse.ArgumentDefaultsHelpFormatter
        ),
    )

    # --------------------------------------------------------
    # INPUT
    # --------------------------------------------------------

    parser.add_argument(
        "--input",

        required=True,

        help=(
            "Arquivo NetCDF de entrada."
        ),
    )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    parser.add_argument(
        "--output",

        default="saida_mapas",

        help=(
            "Diretório para salvar os mapas."
        ),
    )

    # --------------------------------------------------------
    # YEAR
    # --------------------------------------------------------

    parser.add_argument(
        "--year",

        required=True,

        type=int,

        help=(
            "Ano correspondente ao forecastMonth=1."
        ),
    )

    # --------------------------------------------------------
    # MONTH
    # --------------------------------------------------------

    parser.add_argument(
        "--month",

        required=True,

        type=int,

        choices=range(1, 13),

        metavar="{1..12}",

        help=(
            "Mês correspondente ao forecastMonth=1. "
            "1=Janeiro, ..., 12=Dezembro."
        ),
    )

    # --------------------------------------------------------
    # VARIABLE
    # --------------------------------------------------------

    parser.add_argument(
        "--variable",

        default=None,

        choices=list(
            VARIABLES.keys()
        ),

        help=(
            "Processa apenas uma variável. "
            "Se omitido, processa todas as variáveis "
            "disponíveis."
        ),
    )

    args = parser.parse_args()

    # ========================================================
    # DIRETÓRIO PRINCIPAL
    # ========================================================

    os.makedirs(
        args.output,
        exist_ok=True,
    )

    # ========================================================
    # ABERTURA DO DATASET
    # ========================================================

    ds = abrir_dataset(
        args.input
    )

    try:

        # ====================================================
        # ESTRUTURA
        # ====================================================

        mostrar_estrutura(
            ds
        )

        # ====================================================
        # FORECAST MONTH
        # ====================================================

        if "forecastMonth" not in ds.coords:

            raise ValueError(
                "A coordenada 'forecastMonth' "
                "não foi encontrada no arquivo."
            )

        forecast_months = ds[
            "forecastMonth"
        ].values

        if len(forecast_months) == 0:

            raise ValueError(
                "Nenhum forecastMonth foi encontrado."
            )

        print()
        print(
            "Forecast Months encontrados: "
            f"{forecast_months}"
        )

        # ====================================================
        # CALENDÁRIO
        # ====================================================

        calendario = (
            criar_calendario_forecast(
                forecast_months=forecast_months,

                year=args.year,

                month=args.month,
            )
        )

        mostrar_calendario(
            calendario
        )

        # ====================================================
        # DIAS POR MÊS
        # ====================================================

        dias_por_mes = (
            criar_dataarray_dias(
                calendario=calendario,

                forecast_month_coord=
                    forecast_months,
            )
        )

        # ====================================================
        # SELEÇÃO DAS VARIÁVEIS
        # ====================================================

        if args.variable is not None:

            if args.variable not in ds.data_vars:

                raise ValueError(
                    f"A variável '{args.variable}' "
                    "não existe no arquivo."
                )

            variaveis = [
                args.variable
            ]

        else:

            variaveis = [
                variavel

                for variavel in VARIABLES

                if variavel in ds.data_vars
            ]

        if not variaveis:

            raise ValueError(
                "Nenhuma das variáveis configuradas "
                "(mx2t24, mn2t24, tprate) foi encontrada "
                "no arquivo."
            )

        print()
        print(
            "Variáveis selecionadas:"
        )

        for variavel in variaveis:

            print(
                f"  - {variavel}"
            )

        # ====================================================
        # PROCESSAMENTO
        # ====================================================

        for variavel in variaveis:

            print()
            print("=" * 78)
            print(
                f"PROCESSANDO: {variavel}"
            )
            print("=" * 78)

            # ------------------------------------------------
            # DIRETÓRIO DA VARIÁVEL
            # ------------------------------------------------

            diretorio_variavel = os.path.join(
                args.output,
                variavel,
            )

            os.makedirs(
                diretorio_variavel,
                exist_ok=True,
            )

            # ------------------------------------------------
            # PREPARAÇÃO
            # ------------------------------------------------

            dados = preparar_dados(
                ds=ds,

                variavel=variavel,

                dias_por_mes=dias_por_mes,
            )

            # ------------------------------------------------
            # VERIFICAÇÃO DAS DIMENSÕES
            # ------------------------------------------------

            dimensoes_esperadas = {
                "forecastMonth",
                "latitude",
                "longitude",
            }

            dimensoes_extras = (
                set(dados.dims)
                - dimensoes_esperadas
            )

            if dimensoes_extras:

                print()
                print(
                    "ATENÇÃO: dimensões adicionais "
                    "encontradas:"
                )

                for dim in dimensoes_extras:

                    print(
                        f"  - {dim}: "
                        f"{dados.sizes[dim]}"
                    )

                raise ValueError(
                    "Existem dimensões não tratadas "
                    f"na variável {variavel}: "
                    f"{sorted(dimensoes_extras)}"
                )

            # ------------------------------------------------
            # NORMALIZAÇÃO DAS COORDENADAS
            # ------------------------------------------------

            dados = normalizar_coordenadas(
                dados
            )

            # ------------------------------------------------
            # MAPAS MENSAIS
            # ------------------------------------------------

            gerar_mapas_mensais(
                dados=dados,

                variavel=variavel,

                calendario=calendario,

                diretorio_saida=
                    diretorio_variavel,
            )

            # ------------------------------------------------
            # MAPAS TRIMESTRAIS
            # ------------------------------------------------

            gerar_mapas_trimestrais(
                dados=dados,

                variavel=variavel,

                calendario=calendario,

                dias_por_mes=dias_por_mes,

                diretorio_saida=
                    diretorio_variavel,
            )

        # ====================================================
        # FINALIZAÇÃO
        # ====================================================

        print()
        print("=" * 78)
        print(
            "PROCESSAMENTO CONCLUÍDO COM SUCESSO"
        )
        print("=" * 78)

        print()
        print(
            f"Mapas salvos em: {args.output}"
        )

    finally:

        ds.close()

        print()
        print(
            "Dataset NetCDF fechado."
        )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()