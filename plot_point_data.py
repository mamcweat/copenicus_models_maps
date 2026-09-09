#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
plot_point_data.py

Plota previsão pontual de temperatura e precipitação a partir
de um arquivo NetCDF de ensemble.

Compatível com diferentes modelos do Copernicus/C3S/DWD/etc.,
mesmo quando a numeração dos membros do ensemble varia.

REGRAS DO ENSEMBLE
------------------

O script lê automaticamente a dimensão "number" do NetCDF.

Exemplos:

    number = 0 ... 49
        -> membro default = 0

    number = 1 ... 11
        -> membro default = 1

    number = 10 ... 20
        -> membro default = 10

O membro default é SEMPRE o primeiro membro encontrado no
arquivo após ordenação numérica.

MODO DEFAULT
------------

Sem utilizar --member:

    Temperatura máxima:
        membro default + P5 + P90

    Temperatura mínima:
        membro default + P5 + P90

    Precipitação:
        membro default + P5 + P90

MODO --member
-------------

Permite selecionar um ou mais membros e/ou P5/P90.

Exemplos:

    --member 1

    --member 1 2 3

    --member P5 P90

    --member 1 P5 P90

    --member 1 5 10 P5 P90


ARGUMENTO --model
-----------------

O nome do modelo é informado pelo usuário e utilizado
na identificação dos gráficos e da tabela.

Exemplo:

    --model "BOM"

    --model "DWD"

    --model "ECMWF"

    --model "NCEP"


USO
---

python3 plot_point_data.py \
    --input BOM-Aug26.nc \
    --output forecast_sp.png \
    --latitude -23.55 \
    --longitude -46.63 \
    --local "São Paulo - SP" \
    --model "BOM" \
    --init-year 2026 \
    --init-month 8 \
    --init-day 1


NOTAS
-----

1. Temperatura:
       Kelvin -> Celsius

2. Precipitação:
       metros -> milímetros

3. A precipitação do arquivo é considerada acumulada.
   O script calcula a precipitação diária por diferença
   entre passos consecutivos.

4. A seleção espacial usa o ponto de grade mais próximo.

5. forecast_period é interpretado em horas a partir da
   data inicial fornecida pelo usuário.

6. decode_cf=False é utilizado devido à incompatibilidade
   encontrada no atributo dtype de forecast_period em
   determinados arquivos.

"""


import argparse
import os
import sys

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import xarray as xr

import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# ============================================================
# ARGUMENTOS
# ============================================================

def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "Plota previsão pontual de temperatura e "
            "precipitação a partir de um ensemble NetCDF."
        )
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Arquivo NetCDF de entrada."
    )

    parser.add_argument(
        "--output",
        required=True,
        help="Nome do arquivo PNG de saída."
    )

    parser.add_argument(
        "--latitude",
        type=float,
        required=True,
        help="Latitude do ponto desejado."
    )

    parser.add_argument(
        "--longitude",
        type=float,
        required=True,
        help="Longitude do ponto desejado."
    )

    parser.add_argument(
        "--local",
        type=str,
        default=None,
        help=(
            "Nome da localidade para exibição no gráfico "
            'e na tabela. Exemplo: --local "São Paulo - SP"'
        )
    )

    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help=(
            "Nome do modelo meteorológico. "
            'Exemplo: --model "BOM"'
        )
    )

    parser.add_argument(
        "--init-year",
        type=int,
        required=True,
        help="Ano da data inicial da previsão."
    )

    parser.add_argument(
        "--init-month",
        type=int,
        required=True,
        help="Mês da data inicial da previsão."
    )

    parser.add_argument(
        "--init-day",
        type=int,
        required=True,
        help="Dia da data inicial da previsão."
    )

    parser.add_argument(
        "--member",
        nargs="+",
        default=None,
        help=(
            "Seleciona um ou mais membros do ensemble "
            "e/ou P5/P90. "
            "Exemplo: --member 1 2 3 P5 P90"
        )
    )

    return parser.parse_args()


# ============================================================
# ABERTURA DO DATASET
# ============================================================

def open_dataset(filename):

    print("\n" + "=" * 80)
    print("ABRINDO ARQUIVO")
    print("=" * 80)

    print(
        f"Arquivo: {filename}"
    )

    if not os.path.exists(filename):

        raise FileNotFoundError(
            f"Arquivo não encontrado: {filename}"
        )

    # Necessário para determinados arquivos em que
    # forecast_period possui atributo dtype incompatível
    # com a decodificação automática do xarray.
    ds = xr.open_dataset(
        filename,
        decode_cf=False
    )

    return ds


# ============================================================
# INFORMAÇÕES DO DATASET
# ============================================================

def print_dataset_information(ds):

    print("\n" + "=" * 80)
    print("INFORMAÇÕES DO DATASET")
    print("=" * 80)

    print("\nDimensões:")

    for dim, size in ds.sizes.items():

        print(
            f"  {dim:25s}: {size}"
        )

    print("\nVariáveis:")

    for var in ds.data_vars:

        da = ds[var]

        units = da.attrs.get(
            "units",
            "não informado"
        )

        print(
            f"  {var:12s} "
            f"dims={str(da.dims):45s} "
            f"units={units}"
        )


# ============================================================
# MEMBROS DISPONÍVEIS
# ============================================================

def get_available_members(ds):

    if "number" not in ds.dims:

        raise ValueError(
            "O arquivo NetCDF não possui a dimensão "
            "'number'."
        )

    if "number" not in ds:

        raise ValueError(
            "A dimensão 'number' não possui variável "
            "correspondente no dataset."
        )

    values = np.asarray(
        ds["number"].values
    )

    if values.size == 0:

        raise ValueError(
            "A dimensão 'number' está vazia."
        )

    members = []

    for value in values:

        try:

            members.append(
                int(value)
            )

        except (TypeError, ValueError):

            raise ValueError(
                "Os valores da dimensão 'number' "
                "não puderam ser convertidos para "
                "números inteiros."
            )

    # Remove duplicações e ordena
    members = sorted(
        list(set(members))
    )

    return members


# ============================================================
# MEMBRO DEFAULT
# ============================================================

def determine_default_member(
    available_members
):

    if not available_members:

        raise ValueError(
            "Nenhum membro do ensemble foi encontrado."
        )

    # O primeiro membro existente no arquivo,
    # após ordenação numérica, é o membro default.
    #
    # Exemplos:
    #
    # 0 ... 49  -> M0
    # 1 ... 11  -> M1
    # 10 ... 20 -> M10

    return available_members[0]


# ============================================================
# INFORMAÇÕES DO ENSEMBLE
# ============================================================

def print_ensemble_information(
    available_members,
    default_member
):

    print("\n" + "=" * 80)
    print("ENSEMBLE")
    print("=" * 80)

    print(
        f"Número de membros: "
        f"{len(available_members)}"
    )

    print(
        "Membros disponíveis: "
        + ", ".join(
            str(member)
            for member in available_members
        )
    )

    print(
        f"\nMembro default: "
        f"M{default_member}"
    )

    print(
        "Regra: primeiro membro encontrado "
        "no arquivo."
    )


# ============================================================
# SELEÇÃO DOS MEMBROS
# ============================================================

def parse_member_selection(
    selection,
    available_members
):

    if selection is None:

        return None

    result = []

    for item in selection:

        item_str = str(item)

        item_upper = item_str.upper()

        # ----------------------------------------------------
        # PERCENTIS
        # ----------------------------------------------------

        if item_upper in [
            "P5",
            "P90"
        ]:

            if item_upper not in result:

                result.append(
                    item_upper
                )

            continue

        # ----------------------------------------------------
        # MEMBRO NUMÉRICO
        # ----------------------------------------------------

        try:

            member = int(
                item_str
            )

        except ValueError:

            raise ValueError(
                f"Seleção inválida: '{item_str}'. "
                "Use o número do membro, P5 ou P90."
            )

        # ----------------------------------------------------
        # VERIFICAÇÃO
        # ----------------------------------------------------

        if member not in available_members:

            raise ValueError(
                f"Membro {member} não existe no arquivo.\n"
                f"Membros disponíveis: "
                f"{available_members}"
            )

        if member not in result:

            result.append(
                member
            )

    if not result:

        raise ValueError(
            "Nenhuma seleção válida foi informada."
        )

    return result


# ============================================================
# NORMALIZAÇÃO DAS VARIÁVEIS
# ============================================================

def normalize_forecast_variable(
    ds_point,
    variable
):

    if variable not in ds_point:

        raise ValueError(
            f"Variável '{variable}' "
            "não encontrada no dataset."
        )

    da = ds_point[variable]

    # Remove dimensões de tamanho 1,
    # por exemplo forecast_reference_time.
    da = da.squeeze(
        drop=True
    )

    return da


# ============================================================
# CONVERSÃO DE TEMPERATURA
# ============================================================

def convert_temperature_to_celsius(
    temperature
):

    units = temperature.attrs.get(
        "units"
    )

    if units is None:

        raise ValueError(
            "Unidade de temperatura não encontrada."
        )

    units_lower = str(
        units
    ).lower()

    if units_lower in [
        "k",
        "kelvin"
    ]:

        values = (
            temperature.values -
            273.15
        )

    elif units_lower in [
        "c",
        "degc",
        "°c",
        "celsius"
    ]:

        values = temperature.values

    else:

        raise ValueError(
            "Unidade de temperatura não reconhecida: "
            f"'{units}'"
        )

    return xr.DataArray(
        values,
        dims=temperature.dims,
        coords={
            dim: temperature.coords[dim]
            for dim in temperature.dims
        },
        attrs={
            "units": "°C"
        },
        name=temperature.name
    )


# ============================================================
# CONVERSÃO DE PRECIPITAÇÃO
# ============================================================

def convert_precipitation_to_mm(
    precipitation
):

    units = precipitation.attrs.get(
        "units"
    )

    if units is None:

        raise ValueError(
            "Unidade de precipitação não encontrada."
        )

    units_lower = str(
        units
    ).lower()

    if units_lower in [
        "m",
        "meter",
        "meters"
    ]:

        values = (
            precipitation.values *
            1000.0
        )

    elif units_lower in [
        "mm",
        "millimeter",
        "millimeters"
    ]:

        values = precipitation.values

    else:

        raise ValueError(
            "Unidade de precipitação não reconhecida: "
            f"'{units}'"
        )

    return xr.DataArray(
        values,
        dims=precipitation.dims,
        coords={
            dim: precipitation.coords[dim]
            for dim in precipitation.dims
        },
        attrs={
            "units": "mm"
        },
        name=precipitation.name
    )


# ============================================================
# PRECIPITAÇÃO ACUMULADA -> DIÁRIA
# ============================================================

def accumulated_to_daily(
    accumulated_precip
):

    values = np.asarray(
        accumulated_precip.values,
        dtype=float
    )

    # ========================================================
    # CASO 1D
    # ========================================================

    if values.ndim == 1:

        daily_values = np.empty_like(
            values,
            dtype=float
        )

        daily_values[0] = values[0]

        if len(values) > 1:

            daily_values[1:] = (
                values[1:] -
                values[:-1]
            )

    # ========================================================
    # CASO 2D: NUMBER X FORECAST_PERIOD
    # ========================================================

    elif values.ndim == 2:

        if "number" not in accumulated_precip.dims:

            raise ValueError(
                "A dimensão 'number' não foi encontrada "
                "na precipitação."
            )

        number_axis = (
            accumulated_precip.dims.index(
                "number"
            )
        )

        if number_axis != 0:

            raise ValueError(
                "A dimensão 'number' deve ser a primeira "
                "dimensão da precipitação."
            )

        daily_values = np.empty_like(
            values,
            dtype=float
        )

        daily_values[:, 0] = values[:, 0]

        if values.shape[1] > 1:

            daily_values[:, 1:] = (
                values[:, 1:] -
                values[:, :-1]
            )

    else:

        raise ValueError(
            "Número inesperado de dimensões "
            f"na precipitação: {values.ndim}"
        )

    # ========================================================
    # VALORES NEGATIVOS
    # ========================================================

    small_negative = np.logical_and(
        daily_values < 0,
        daily_values > -1e-10
    )

    daily_values[
        small_negative
    ] = 0.0

    negative_values = (
        daily_values < -1e-8
    )

    if np.any(
        negative_values
    ):

        print(
            "\nAVISO: foram encontrados valores "
            "negativos na precipitação diária."
        )

        print(
            "Eles serão ajustados para zero."
        )

        daily_values = np.maximum(
            daily_values,
            0.0
        )

    return xr.DataArray(
        daily_values,
        dims=accumulated_precip.dims,
        coords={
            dim: accumulated_precip.coords[dim]
            for dim in accumulated_precip.dims
        },
        attrs={
            "units": "mm/day"
        },
        name="tp_daily"
    )


# ============================================================
# ESTATÍSTICAS DO ENSEMBLE
# ============================================================

def calculate_ensemble_statistics(
    data
):

    if "number" not in data.dims:

        raise ValueError(
            "A variável não possui dimensão "
            "'number'."
        )

    return {

        "min": data.min(
            dim="number",
            keep_attrs=True
        ),

        "mean": data.mean(
            dim="number",
            keep_attrs=True
        ),

        "max": data.max(
            dim="number",
            keep_attrs=True
        ),

        "p5": data.quantile(
            0.05,
            dim="number",
            keep_attrs=True
        ),

        "p90": data.quantile(
            0.90,
            dim="number",
            keep_attrs=True
        )
    }


# ============================================================
# CONSTRUÇÃO DAS DATAS
# ============================================================

def build_forecast_dates(
    ds,
    init_date
):

    if "forecast_period" not in ds:

        raise ValueError(
            "A variável forecast_period "
            "não foi encontrada."
        )

    forecast_period = ds[
        "forecast_period"
    ]

    hours = np.asarray(
        forecast_period.values,
        dtype=float
    )

    dates = []

    for hour in hours:

        dates.append(
            init_date +
            timedelta(
                hours=float(hour)
            )
        )

    return pd.DatetimeIndex(
        dates
    )


# ============================================================
# PREPARAÇÃO DOS DADOS
# ============================================================

def prepare_data(
    ds,
    latitude,
    longitude
):

    # --------------------------------------------------------
    # Seleção do ponto de grade mais próximo
    # --------------------------------------------------------

    ds_point = ds.sel(
        latitude=latitude,
        longitude=longitude,
        method="nearest"
    )

    selected_lat = float(
        ds_point["latitude"].values
    )

    selected_lon = float(
        ds_point["longitude"].values
    )

    print("\n" + "=" * 80)
    print("LOCALIZAÇÃO")
    print("=" * 80)

    print(
        f"Solicitado : "
        f"lat={latitude:.3f}, "
        f"lon={longitude:.3f}"
    )

    print(
        f"Grade usada: "
        f"lat={selected_lat:.3f}, "
        f"lon={selected_lon:.3f}"
    )

    # --------------------------------------------------------
    # Tmax
    # --------------------------------------------------------

    tmax = normalize_forecast_variable(
        ds_point,
        "mx2t24"
    )

    tmax = convert_temperature_to_celsius(
        tmax
    )

    # --------------------------------------------------------
    # Tmin
    # --------------------------------------------------------

    tmin = normalize_forecast_variable(
        ds_point,
        "mn2t24"
    )

    tmin = convert_temperature_to_celsius(
        tmin
    )

    # --------------------------------------------------------
    # Precipitação
    # --------------------------------------------------------

    precipitation = normalize_forecast_variable(
        ds_point,
        "tp"
    )

    precipitation = convert_precipitation_to_mm(
        precipitation
    )

    precipitation = accumulated_to_daily(
        precipitation
    )

    # --------------------------------------------------------
    # Estatísticas
    # --------------------------------------------------------

    tmax_stats = calculate_ensemble_statistics(
        tmax
    )

    tmin_stats = calculate_ensemble_statistics(
        tmin
    )

    precip_stats = calculate_ensemble_statistics(
        precipitation
    )

    return {

        "tmax": tmax,

        "tmin": tmin,

        "precip": precipitation,

        "tmax_stats": tmax_stats,

        "tmin_stats": tmin_stats,

        "precip_stats": precip_stats,

        "latitude": selected_lat,

        "longitude": selected_lon
    }


# ============================================================
# FORMATAÇÃO DOS VALORES
# ============================================================

def format_temperature(
    value
):

    if pd.isna(value):

        return "---"

    return f"{float(value):6.1f}"


def format_precipitation(
    value
):

    if pd.isna(value):

        return "---"

    return f"{float(value):6.1f}"


# ============================================================
# TABELA DEFAULT
# ============================================================

def print_default_table(
    dates,
    data,
    default_member,
    model,
    local
):

    print("\n")

    print(
        "=" * 118
    )

    print(
        f"MODELO: {model}"
    )

    if local:

        print(
            f"LOCALIDADE: {local}"
        )

    print(
        f"TABELA DA PREVISÃO — "
        f"M{default_member} + P5 + P90"
    )

    print(
        "=" * 118
    )

    print(
        f"{'Data':^12} | "
        f"{'Tmax M'+str(default_member):>10} "
        f"{'Tmax P5':>9} "
        f"{'Tmax P90':>9} | "
        f"{'Tmin M'+str(default_member):>10} "
        f"{'Tmin P5':>9} "
        f"{'Tmin P90':>9} | "
        f"{'Prec M'+str(default_member):>10} "
        f"{'Prec P5':>9} "
        f"{'Prec P90':>9}"
    )

    print(
        "-" * 118
    )

    tmax_member = data[
        "tmax"
    ].sel(
        number=default_member
    ).values

    tmax_p5 = data[
        "tmax_stats"
    ]["p5"].values

    tmax_p90 = data[
        "tmax_stats"
    ]["p90"].values

    tmin_member = data[
        "tmin"
    ].sel(
        number=default_member
    ).values

    tmin_p5 = data[
        "tmin_stats"
    ]["p5"].values

    tmin_p90 = data[
        "tmin_stats"
    ]["p90"].values

    precip_member = data[
        "precip"
    ].sel(
        number=default_member
    ).values

    precip_p5 = data[
        "precip_stats"
    ]["p5"].values

    precip_p90 = data[
        "precip_stats"
    ]["p90"].values

    for i, date in enumerate(dates):

        print(
            f"{date.strftime('%d/%m/%Y'):^12} | "
            f"{format_temperature(tmax_member[i]):>10} "
            f"{format_temperature(tmax_p5[i]):>9} "
            f"{format_temperature(tmax_p90[i]):>9} | "
            f"{format_temperature(tmin_member[i]):>10} "
            f"{format_temperature(tmin_p5[i]):>9} "
            f"{format_temperature(tmin_p90[i]):>9} | "
            f"{format_precipitation(precip_member[i]):>10} "
            f"{format_precipitation(precip_p5[i]):>9} "
            f"{format_precipitation(precip_p90[i]):>9}"
        )

    print(
        "=" * 118
    )

    print(
        "\nTemperaturas: °C"
        "    |    Precipitação: mm/dia"
    )

    print(
        f"M{default_member} = membro default"
        "    |    P5 = percentil 5"
        "    |    P90 = percentil 90"
    )

    print(
        "=" * 118
    )


# ============================================================
# TABELA --MEMBER
# ============================================================

def print_selected_table(
    dates,
    data,
    selection,
    model,
    local
):

    print("\n")

    print(
        "=" * 110
    )

    print(
        f"MODELO: {model}"
    )

    if local:

        print(
            f"LOCALIDADE: {local}"
        )

    print(
        "TABELA DA PREVISÃO — "
        "SELEÇÃO DO ENSEMBLE"
    )

    print(
        "=" * 110
    )

    # --------------------------------------------------------
    # Cabeçalho
    # --------------------------------------------------------

    header = (
        f"{'Data':^12} |"
    )

    for item in selection:

        if isinstance(
            item,
            int
        ):

            label = f"M{item}"

        else:

            label = item

        header += (
            f" Tmax {label:>4} |"
            f" Tmin {label:>4} |"
            f" Prec {label:>4} |"
        )

    print(
        header
    )

    print(
        "-" * 110
    )

    # --------------------------------------------------------
    # Linhas
    # --------------------------------------------------------

    for i, date in enumerate(dates):

        line = (
            f"{date.strftime('%d/%m/%Y'):^12} |"
        )

        for item in selection:

            # ----------------------------------------------
            # Membro
            # ----------------------------------------------

            if isinstance(
                item,
                int
            ):

                tmax = data[
                    "tmax"
                ].sel(
                    number=item
                ).values[i]

                tmin = data[
                    "tmin"
                ].sel(
                    number=item
                ).values[i]

                precip = data[
                    "precip"
                ].sel(
                    number=item
                ).values[i]

            # ----------------------------------------------
            # P5
            # ----------------------------------------------

            elif item == "P5":

                tmax = data[
                    "tmax_stats"
                ]["p5"].values[i]

                tmin = data[
                    "tmin_stats"
                ]["p5"].values[i]

                precip = data[
                    "precip_stats"
                ]["p5"].values[i]

            # ----------------------------------------------
            # P90
            # ----------------------------------------------

            elif item == "P90":

                tmax = data[
                    "tmax_stats"
                ]["p90"].values[i]

                tmin = data[
                    "tmin_stats"
                ]["p90"].values[i]

                precip = data[
                    "precip_stats"
                ]["p90"].values[i]

            else:

                raise ValueError(
                    f"Seleção inválida: {item}"
                )

            line += (
                f" {format_temperature(tmax)} |"
                f" {format_temperature(tmin)} |"
                f" {format_precipitation(precip)} |"
            )

        print(
            line
        )

    print(
        "=" * 110
    )

    print(
        "\nTemperaturas: °C"
        "    |    Precipitação: mm/dia"
    )

    print(
        "=" * 110
    )


# ============================================================
# EIXO TEMPORAL
# ============================================================

def configure_date_axis(
    ax
):

    ax.xaxis.set_major_locator(
        mdates.AutoDateLocator(
            minticks=8,
            maxticks=15
        )
    )

    ax.xaxis.set_major_formatter(
        mdates.DateFormatter(
            "%d/%m"
        )
    )

    ax.grid(
        True,
        linestyle="--",
        alpha=0.30
    )


# ============================================================
# TÍTULO DOS PAINÉIS
# ============================================================

def make_title(
    variable,
    model,
    local,
    latitude,
    longitude
):

    if variable == "tmax":

        title_variable = (
            "Temperatura Máxima"
        )

    elif variable == "tmin":

        title_variable = (
            "Temperatura Mínima"
        )

    else:

        title_variable = (
            "Precipitação"
        )

    title = (
        f"{title_variable} — {model}"
    )

    if local:

        title += (
            f" — {local}"
        )

    title += (
        f"\nLat: {latitude:.2f}° | "
        f"Lon: {longitude:.2f}°"
    )

    return title


# ============================================================
# GRÁFICO DEFAULT
# ============================================================

def plot_default(
    dates,
    data,
    default_member,
    model,
    output,
    local
):

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(15, 12),
        sharex=True
    )

    # ========================================================
    # TEMPERATURA MÁXIMA
    # ========================================================

    ax = axes[0]

    member_values = data[
        "tmax"
    ].sel(
        number=default_member
    ).values

    p5 = data[
        "tmax_stats"
    ]["p5"].values

    p90 = data[
        "tmax_stats"
    ]["p90"].values

    ax.fill_between(
        dates,
        p5,
        p90,
        alpha=0.18,
        label="P5–P90"
    )

    ax.plot(
        dates,
        member_values,
        linewidth=2.2,
        label=f"Membro {default_member}"
    )

    ax.plot(
        dates,
        p5,
        linestyle="--",
        linewidth=1.3,
        label="P5"
    )

    ax.plot(
        dates,
        p90,
        linestyle="--",
        linewidth=1.3,
        label="P90"
    )

    ax.set_ylabel(
        "°C"
    )

    ax.set_title(
        make_title(
            "tmax",
            model,
            local,
            data["latitude"],
            data["longitude"]
        ),
        fontsize=13,
        fontweight="bold"
    )

    ax.legend(
        loc="upper left",
        ncol=4
    )

    configure_date_axis(
        ax
    )

    # ========================================================
    # TEMPERATURA MÍNIMA
    # ========================================================

    ax = axes[1]

    member_values = data[
        "tmin"
    ].sel(
        number=default_member
    ).values

    p5 = data[
        "tmin_stats"
    ]["p5"].values

    p90 = data[
        "tmin_stats"
    ]["p90"].values

    ax.fill_between(
        dates,
        p5,
        p90,
        alpha=0.18,
        label="P5–P90"
    )

    ax.plot(
        dates,
        member_values,
        linewidth=2.2,
        label=f"Membro {default_member}"
    )

    ax.plot(
        dates,
        p5,
        linestyle="--",
        linewidth=1.3,
        label="P5"
    )

    ax.plot(
        dates,
        p90,
        linestyle="--",
        linewidth=1.3,
        label="P90"
    )

    ax.set_ylabel(
        "°C"
    )

    ax.set_title(
        make_title(
            "tmin",
            model,
            local,
            data["latitude"],
            data["longitude"]
        ),
        fontsize=13,
        fontweight="bold"
    )

    ax.legend(
        loc="upper left",
        ncol=4
    )

    configure_date_axis(
        ax
    )

    # ========================================================
    # PRECIPITAÇÃO
    # ========================================================

    ax = axes[2]

    member_values = data[
        "precip"
    ].sel(
        number=default_member
    ).values

    p5 = data[
        "precip_stats"
    ]["p5"].values

    p90 = data[
        "precip_stats"
    ]["p90"].values

    ax.fill_between(
        dates,
        p5,
        p90,
        alpha=0.18,
        label="P5–P90"
    )

    ax.plot(
        dates,
        member_values,
        linewidth=2.2,
        label=f"Membro {default_member}"
    )

    ax.plot(
        dates,
        p5,
        linestyle="--",
        linewidth=1.3,
        label="P5"
    )

    ax.plot(
        dates,
        p90,
        linestyle="--",
        linewidth=1.3,
        label="P90"
    )

    ax.set_ylabel(
        "mm/dia"
    )

    ax.set_title(
        make_title(
            "precip",
            model,
            local,
            data["latitude"],
            data["longitude"]
        ),
        fontsize=13,
        fontweight="bold"
    )

    ax.legend(
        loc="upper left",
        ncol=4
    )

    configure_date_axis(
        ax
    )

    ax.set_xlabel(
        "Data de validade da previsão"
    )

    # ========================================================
    # TÍTULO GERAL
    # ========================================================

    title = (
        f"Previsão Pontual — {model}\n"
        f"Membro {default_member} + P5 + P90"
    )

    if local:

        title += (
            f"\n{local}"
        )

    fig.suptitle(
        title,
        fontsize=16,
        fontweight="bold",
        y=0.995
    )

    plt.tight_layout(
        rect=[
            0,
            0,
            1,
            0.955
        ]
    )

    plt.savefig(
        output,
        dpi=150,
        bbox_inches="tight"
    )

    plt.close(
        fig
    )


# ============================================================
# GRÁFICO COM MEMBROS SELECIONADOS
# ============================================================

def plot_selected_members(
    dates,
    data,
    selection,
    model,
    output,
    local
):

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(15, 12),
        sharex=True
    )

    # ========================================================
    # FUNÇÕES AUXILIARES
    # ========================================================

    def get_values(
        variable,
        item
    ):

        if isinstance(
            item,
            int
        ):

            return data[
                variable
            ].sel(
                number=item
            ).values

        if item == "P5":

            return data[
                f"{variable}_stats"
            ]["p5"].values

        if item == "P90":

            return data[
                f"{variable}_stats"
            ]["p90"].values

        raise ValueError(
            f"Seleção inválida: {item}"
        )

    def get_label(
        item
    ):

        if isinstance(
            item,
            int
        ):

            return f"Membro {item}"

        return item

    # ========================================================
    # TEMPERATURA MÁXIMA
    # ========================================================

    ax = axes[0]

    for item in selection:

        if isinstance(
            item,
            int
        ):

            linewidth = 2.0
            linestyle = "-"

        else:

            linewidth = 1.5
            linestyle = "--"

        ax.plot(
            dates,
            get_values(
                "tmax",
                item
            ),
            linewidth=linewidth,
            linestyle=linestyle,
            label=get_label(
                item
            )
        )

    ax.set_ylabel(
        "°C"
    )

    ax.set_title(
        make_title(
            "tmax",
            model,
            local,
            data["latitude"],
            data["longitude"]
        ),
        fontsize=13,
        fontweight="bold"
    )

    ax.legend(
        loc="upper left",
        ncol=min(
            len(selection),
            5
        )
    )

    configure_date_axis(
        ax
    )

    # ========================================================
    # TEMPERATURA MÍNIMA
    # ========================================================

    ax = axes[1]

    for item in selection:

        if isinstance(
            item,
            int
        ):

            linewidth = 2.0
            linestyle = "-"

        else:

            linewidth = 1.5
            linestyle = "--"

        ax.plot(
            dates,
            get_values(
                "tmin",
                item
            ),
            linewidth=linewidth,
            linestyle=linestyle,
            label=get_label(
                item
            )
        )

    ax.set_ylabel(
        "°C"
    )

    ax.set_title(
        make_title(
            "tmin",
            model,
            local,
            data["latitude"],
            data["longitude"]
        ),
        fontsize=13,
        fontweight="bold"
    )

    ax.legend(
        loc="upper left",
        ncol=min(
            len(selection),
            5
        )
    )

    configure_date_axis(
        ax
    )

    # ========================================================
    # PRECIPITAÇÃO
    # ========================================================

    ax = axes[2]

    for item in selection:

        if isinstance(
            item,
            int
        ):

            linewidth = 2.0
            linestyle = "-"

        else:

            linewidth = 1.5
            linestyle = "--"

        ax.plot(
            dates,
            get_values(
                "precip",
                item
            ),
            linewidth=linewidth,
            linestyle=linestyle,
            label=get_label(
                item
            )
        )

    ax.set_ylabel(
        "mm/dia"
    )

    ax.set_title(
        make_title(
            "precip",
            model,
            local,
            data["latitude"],
            data["longitude"]
        ),
        fontsize=13,
        fontweight="bold"
    )

    ax.legend(
        loc="upper left",
        ncol=min(
            len(selection),
            5
        )
    )

    configure_date_axis(
        ax
    )

    ax.set_xlabel(
        "Data de validade da previsão"
    )

    # ========================================================
    # TÍTULO GERAL
    # ========================================================

    selected_text = ", ".join(
        [
            (
                f"M{x}"
                if isinstance(
                    x,
                    int
                )
                else x
            )
            for x in selection
        ]
    )

    title = (
        f"Previsão Pontual — {model}\n"
        f"{selected_text}"
    )

    if local:

        title += (
            f"\n{local}"
        )

    fig.suptitle(
        title,
        fontsize=16,
        fontweight="bold",
        y=0.995
    )

    plt.tight_layout(
        rect=[
            0,
            0,
            1,
            0.955
        ]
    )

    plt.savefig(
        output,
        dpi=150,
        bbox_inches="tight"
    )

    plt.close(
        fig
    )


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    args = parse_arguments()

    # ========================================================
    # DATA INICIAL
    # ========================================================

    try:

        init_date = datetime(
            args.init_year,
            args.init_month,
            args.init_day
        )

    except ValueError as exc:

        raise ValueError(
            f"Data inicial inválida: {exc}"
        )

    # ========================================================
    # DATASET
    # ========================================================

    ds = open_dataset(
        args.input
    )

    try:

        # ----------------------------------------------------
        # Informações
        # ----------------------------------------------------

        print_dataset_information(
            ds
        )

        # ----------------------------------------------------
        # Ensemble
        # ----------------------------------------------------

        available_members = (
            get_available_members(
                ds
            )
        )

        default_member = (
            determine_default_member(
                available_members
            )
        )

        print_ensemble_information(
            available_members,
            default_member
        )

        # ----------------------------------------------------
        # Seleção do usuário
        # ----------------------------------------------------

        selection = (
            parse_member_selection(
                args.member,
                available_members
            )
        )

        if selection is None:

            print(
                "\nModo DEFAULT:"
            )

            print(
                f"  Temperatura máxima: "
                f"Membro {default_member} + P5 + P90"
            )

            print(
                f"  Temperatura mínima: "
                f"Membro {default_member} + P5 + P90"
            )

            print(
                f"  Precipitação: "
                f"Membro {default_member} + P5 + P90"
            )

        else:

            print(
                "\nMODO --member:"
            )

            print(
                "  Seleção: "
                + ", ".join(
                    [
                        (
                            f"M{x}"
                            if isinstance(
                                x,
                                int
                            )
                            else x
                        )
                        for x in selection
                    ]
                )
            )

        # ----------------------------------------------------
        # Dados no ponto
        # ----------------------------------------------------

        data = prepare_data(
            ds,
            args.latitude,
            args.longitude
        )

        # ----------------------------------------------------
        # Datas
        # ----------------------------------------------------

        dates = build_forecast_dates(
            ds,
            init_date
        )

        print(
            "\nPeríodo da previsão:"
        )

        print(
            f"  Inicial: "
            f"{dates[0].strftime('%d/%m/%Y')}"
        )

        print(
            f"  Final  : "
            f"{dates[-1].strftime('%d/%m/%Y')}"
        )

        print(
            f"  Número de períodos: "
            f"{len(dates)}"
        )

        # ----------------------------------------------------
        # Tabela
        # ----------------------------------------------------

        if selection is None:

            print_default_table(
                dates,
                data,
                default_member,
                args.model,
                args.local
            )

        else:

            print_selected_table(
                dates,
                data,
                selection,
                args.model,
                args.local
            )

        # ----------------------------------------------------
        # Nome do arquivo
        # ----------------------------------------------------

        output = args.output

        if not output.lower().endswith(
            ".png"
        ):

            output += ".png"

        # ----------------------------------------------------
        # Gráfico
        # ----------------------------------------------------

        print(
            "\n" + "=" * 80
        )

        print(
            "GERANDO GRÁFICO"
        )

        print(
            "=" * 80
        )

        if selection is None:

            plot_default(
                dates,
                data,
                default_member,
                args.model,
                output,
                args.local
            )

        else:

            plot_selected_members(
                dates,
                data,
                selection,
                args.model,
                output,
                args.local
            )

        print(
            "\nGráfico salvo em:"
        )

        print(
            f"  {os.path.abspath(output)}"
        )

        print(
            "\nConcluído.\n"
        )

    finally:

        ds.close()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\nExecução interrompida pelo usuário."
        )

        sys.exit(130)

    except Exception as exc:

        print(
            "\nERRO:",
            exc,
            file=sys.stderr
        )

        sys.exit(1)
