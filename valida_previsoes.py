#!/usr/bin/env python3
"""Validacao espacial das previsoes de anomalia de chuva (Copernicus) contra o
observado (CPTEC-MERGE), a partir apenas das imagens PNG.

Estrutura esperada (uma pasta por mes verificado):
    saida_mapas/Verificação/<PASTA>/mapa_<MODELO>_PR_anom_M<k>_<AAAAMM>.png
    saida_mapas/Verificação/<PASTA>/OBS*.png  (mapa observado CPTEC-MERGE)

Etapas:
  1. Georreferenciamento: cada PNG e calibrado ajustando (chamfer matching) a
     linha de costa, fronteiras e estados do Natural Earth as linhas pretas
     desenhadas no mapa. Isso resolve extensoes/escalas de pixel diferentes.
  2. Decodificacao: cada pixel e convertido no valor central da classe da
     paleta correspondente (paletas distintas para previsao e observado).
  3. Grade comum: os valores sao agregados (media) numa grade regular
     (padrao 1 grau, resolucao dos modelos), o que suaviza o ruido do MERGE.
     Os valores sao saturados em +-SATURACAO mm, pois o observado nao
     distingue nada acima de +-120 mm.
  4. Metricas (ponderadas por cos(lat), apenas continente):
       quantitativas: correlacao de Pearson, ACC (nao centrado), RMSE, MAE, vies
       qualitativas: acerto em 3 categorias (abaixo/normal/acima, limiar +-20 mm
                     comum as duas escalas), Heidke (HSS) e acerto de sinal
  5. Ranking por regiao (geral e regioes do Brasil) e relatorio em PDF.

Uso:
    python valida_previsoes.py                      # todas as pastas
    python valida_previsoes.py --pasta SET26        # uma pasta
    python valida_previsoes.py --res 0.5 --debug    # grade de 0,5 grau + figuras de calibracao
"""
import argparse
import glob
import os
import re

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import pandas as pd
import shapely
from cartopy.io import shapereader
from PIL import Image
from scipy import ndimage, optimize

# ---------------------------------------------------------------------------
# Configuracao das paletas
# Cada entrada: (cor RGB, valor representativo da classe em mm)
# ---------------------------------------------------------------------------
def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

# gera_mapas_previsao.py -> get_cmap_anomalia_chuva()
PALETA_PREVISAO = [
    (_hex("#5B0000"), -350), (_hex("#8B2500"), -250), (_hex("#C84B31"), -175),
    (_hex("#D98880"), -125), (_hex("#E6B0AA"), -75), (_hex("#FADBD8"), -35),
    (_hex("#FFFFFF"), 0),
    (_hex("#B2C6D5"), 35), (_hex("#7FA0B5"), 75), (_hex("#4A7C9D"), 125),
    (_hex("#1A5B8C"), 175), (_hex("#0D3B66"), 250), (_hex("#051C3B"), 350),
]

# CPTEC-MERGE (Rural Clima): classes de 20 mm, faixa branca de -10 a 10 mm,
# saturando em +-120 mm (a cor de >120 e a mesma do triangulo >140).
PALETA_OBS = [
    ((130, 0, 0), -140), ((207, 0, 0), -110), ((240, 61, 0), -90),
    ((250, 120, 41), -70), ((250, 161, 61), -50), ((255, 219, 84), -30),
    ((255, 250, 204), -15), ((255, 255, 255), 0), ((224, 255, 255), 15),
    ((181, 240, 250), 30), ((150, 209, 250), 50), ((77, 163, 245), 70),
    ((31, 110, 245), 90), ((26, 51, 209), 110), ((0, 0, 158), 140),
]

# Distancia RGB maxima para aceitar um pixel como cor da paleta
# (linhas, textos e pixels de antialiasing sao descartados)
TOL_COR = 28.0

# Saturacao comum aplicada aos dois campos (mm)
SATURACAO = 140.0

# Limiares das categorias qualitativas (comuns as duas escalas)
LIM_CATEGORIA = 20.0

# Busca da extensao geografica de cada tipo de imagem:
# (lon_esq, lon_dir, lat_sup, lat_inf) - faixa de busca de cada borda do quadro
BUSCA_EXTENSAO = {
    "previsao": [(-115, -105), (-25, -15), (15, 25), (-65, -55)],
    "obs": [(-90, -76), (-38, -26), (8, 18), (-52, -40)],
}

# Regioes de analise: nome -> lista de UFs (None = todo o continente na grade)
REGIOES = {
    "América do Sul (geral)": None,
    "Brasil": ["AC", "AM", "AP", "PA", "RO", "RR", "TO", "AL", "BA", "CE", "MA",
               "PB", "PE", "PI", "RN", "SE", "DF", "GO", "MS", "MT", "ES", "MG",
               "RJ", "SP", "PR", "RS", "SC"],
    "Norte": ["AC", "AM", "AP", "PA", "RO", "RR", "TO"],
    "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste": ["DF", "GO", "MS", "MT"],
    "Sudeste": ["ES", "MG", "RJ", "SP"],
    "Sul": ["PR", "RS", "SC"],
    "MATOPIBA": ["MA", "TO", "PI", "BA"],
}

# Metricas usadas no ranking: (coluna, maior_e_melhor)
METRICAS_QUANT = [("corr", True), ("acc", True), ("rmse", False), ("abs_vies", False)]
METRICAS_QUAL = [("hss", True), ("acerto_cat", True), ("acerto_sinal", True)]

# Cores das classes para os paineis da grade comum
NIVEIS_PLOT = [-140, -100, -60, -20, 20, 60, 100, 140]
CORES_PLOT = ["#8B2500", "#C84B31", "#E69A7A", "#FADBD8", "#FFFFFF",
              "#B2C6D5", "#4A7C9D", "#1A5B8C", "#0D3B66"]


# ---------------------------------------------------------------------------
# Geometrias de referencia (Natural Earth, ja em cache do cartopy)
# ---------------------------------------------------------------------------
_CACHE = {}


def linhas_referencia(passo=0.1):
    """Pontos (lon, lat) amostrados ao longo de costa, fronteiras e estados."""
    if "linhas" in _CACHE:
        return _CACHE["linhas"]
    arquivos = [
        shapereader.natural_earth("50m", "physical", "coastline"),
        shapereader.natural_earth("50m", "cultural", "admin_0_boundary_lines_land"),
        shapereader.natural_earth("50m", "cultural", "admin_1_states_provinces_lines"),
    ]
    caixa = shapely.box(-120, -65, -10, 25)
    pts = []
    for arq in arquivos:
        for geom in gpd.read_file(arq).geometry:
            geom = geom.intersection(caixa)
            if geom.is_empty:
                continue
            for linha in getattr(geom, "geoms", [geom]):
                if linha.geom_type != "LineString" or linha.length == 0:
                    continue
                d = np.arange(0, linha.length, passo)
                p = shapely.get_coordinates(shapely.line_interpolate_point(linha, d))
                pts.append(p)
    _CACHE["linhas"] = np.vstack(pts)
    return _CACHE["linhas"]


def poligonos_paises():
    if "paises" not in _CACHE:
        g = gpd.read_file(shapereader.natural_earth("50m", "cultural", "admin_0_countries"))
        _CACHE["paises"] = shapely.union_all(g.geometry.values)
    return _CACHE["paises"]


def poligonos_ufs():
    if "ufs" not in _CACHE:
        g = gpd.read_file(shapereader.natural_earth("50m", "cultural", "admin_1_states_provinces_lakes"))
        g = g[g.adm0_a3 == "BRA"]
        _CACHE["ufs"] = dict(zip(g.postal, g.geometry))
    return _CACHE["ufs"]


# ---------------------------------------------------------------------------
# Leitura e georreferenciamento das imagens
# ---------------------------------------------------------------------------
def mascara_linhas_pretas(rgb):
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    return (mx < 110) & ((mx - mn) < 45)


def detecta_quadro(escuro):
    """Retorna (x0, x1, y0, y1) do retangulo do mapa (linhas pretas longas)."""
    h, w = escuro.shape

    def maior_seq(v):
        best, cur = 0, 0
        for x in v:
            cur = cur + 1 if x else 0
            best = max(best, cur)
        return best

    linhas = [y for y in np.where(escuro.sum(axis=1) > 0.4 * w)[0] if maior_seq(escuro[y]) > 0.4 * w]
    colunas = [x for x in np.where(escuro.sum(axis=0) > 0.4 * h)[0] if maior_seq(escuro[:, x]) > 0.4 * h]
    if len(linhas) < 2 or len(colunas) < 2:
        raise RuntimeError("quadro do mapa nao encontrado")
    x0, y0 = min(colunas), min(linhas)
    # as bordas direita/inferior sao o fim das linhas que partem do canto superior
    # esquerdo (evita confundir com o contorno da barra de cores)
    x1 = x0 + np.argmin(escuro[y0:y0 + 3, x0:].any(axis=0)) - 1
    y1 = y0 + np.argmin(escuro[y0:, x0:x0 + 3].any(axis=1)) - 1
    return x0, x1, y0, y1


def _custo(params, pts, dist, quadro, cap):
    lon_e, lon_d, lat_s, lat_i = params
    x0, x1, y0, y1 = quadro
    px = x0 + (pts[:, 0] - lon_e) / (lon_d - lon_e) * (x1 - x0)
    py = y0 + (lat_s - pts[:, 1]) / (lat_s - lat_i) * (y1 - y0)
    dentro = (px >= x0 + 3) & (px <= x1 - 3) & (py >= y0 + 3) & (py <= y1 - 3)
    if dentro.sum() < 200:
        return cap
    d = dist[py[dentro].astype(int), px[dentro].astype(int)]
    return np.minimum(d, cap).mean()


def georreferencia(rgb, tipo):
    """Calibra a extensao (lon_esq, lon_dir, lat_sup, lat_inf) das bordas do quadro."""
    escuro = mascara_linhas_pretas(rgb)
    quadro = detecta_quadro(escuro)
    x0, x1, y0, y1 = quadro
    interior = np.zeros_like(escuro)
    interior[y0 + 3:y1 - 2, x0 + 3:x1 - 2] = escuro[y0 + 3:y1 - 2, x0 + 3:x1 - 2]
    dist = ndimage.distance_transform_edt(~interior)

    todos = linhas_referencia()
    rng = np.random.default_rng(0)
    amostra = todos[rng.choice(len(todos), size=min(3000, len(todos)), replace=False)]

    # 1) busca grosseira em grade (passo de 1 grau), x e y alternados
    faixas = BUSCA_EXTENSAO[tipo]
    melhor = [np.mean(f) for f in faixas]
    for _ in range(3):
        for idx in ((0, 1), (2, 3)):
            a_vals = np.arange(faixas[idx[0]][0], faixas[idx[0]][1] + 0.01, 1.0)
            b_vals = np.arange(faixas[idx[1]][0], faixas[idx[1]][1] + 0.01, 1.0)
            best_c = np.inf
            for a in a_vals:
                for b in b_vals:
                    p = list(melhor)
                    p[idx[0]], p[idx[1]] = a, b
                    c = _custo(p, amostra, dist, quadro, cap=40)
                    if c < best_c:
                        best_c, best_p = c, p
            melhor = best_p

    # 2) refinamento continuo com todos os pontos, raio de captura decrescente
    for cap in (15, 6):
        res = optimize.minimize(_custo, melhor, args=(todos, dist, quadro, cap),
                                method="Nelder-Mead",
                                options={"xatol": 0.005, "fatol": 1e-4, "maxiter": 2000})
        melhor = list(res.x)
    erro_px = _custo(melhor, todos, dist, quadro, cap=6)
    return quadro, tuple(melhor), erro_px


def decodifica(rgb, paleta):
    """Converte cada pixel no valor da classe (NaN se nao pertence a paleta)."""
    cores = np.array([c for c, _ in paleta], dtype=float)
    valores = np.array([v for _, v in paleta], dtype=float)
    # decodifica apenas as cores distintas (poucas centenas) e espalha o resultado
    codigo = (rgb[..., 0].astype(np.int32) << 16) | (rgb[..., 1].astype(np.int32) << 8) | rgb[..., 2]
    unicos, inverso = np.unique(codigo.ravel(), return_inverse=True)
    u_rgb = np.stack([(unicos >> 16) & 255, (unicos >> 8) & 255, unicos & 255], axis=1).astype(float)
    d2 = ((u_rgb[:, None, :] - cores[None, :, :]) ** 2).sum(axis=2)
    idx = d2.argmin(axis=1)
    ok = d2[np.arange(len(idx)), idx] <= TOL_COR ** 2
    out = np.where(ok, valores[idx], np.nan)[inverso]
    return out.reshape(rgb.shape[:2])


def regrade(campo_px, quadro, ext, lons, lats, res):
    """Media dos pixels de cada celula da grade regular (centros lons x lats)."""
    x0, x1, y0, y1 = quadro
    lon_e, lon_d, lat_s, lat_i = ext
    sub = campo_px[y0 + 2:y1 - 1, x0 + 2:x1 - 1]
    ys, xs = np.mgrid[y0 + 2:y1 - 1, x0 + 2:x1 - 1]
    plon = lon_e + (xs - x0) / (x1 - x0) * (lon_d - lon_e)
    plat = lat_s - (ys - y0) / (y1 - y0) * (lat_s - lat_i)
    ix = np.floor((plon - (lons[0] - res / 2)) / res).astype(int)
    iy = np.floor((plat - (lats[0] - res / 2)) / res).astype(int)
    ok = (ix >= 0) & (ix < len(lons)) & (iy >= 0) & (iy < len(lats))
    valido = ok & np.isfinite(sub)
    soma = np.zeros((len(lats), len(lons)))
    cont = np.zeros_like(soma)
    total = np.zeros_like(soma)
    np.add.at(soma, (iy[valido], ix[valido]), np.clip(sub[valido], -SATURACAO, SATURACAO))
    np.add.at(cont, (iy[valido], ix[valido]), 1)
    np.add.at(total, (iy[ok], ix[ok]), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        media = soma / cont
    media[(cont < 0.3 * total) | (total == 0)] = np.nan
    return media


def carrega_mapa(caminho, tipo, debug_dir=None):
    rgb = np.array(Image.open(caminho).convert("RGB")).astype(np.int16)
    quadro, ext, erro = georreferencia(rgb, tipo)
    paleta = PALETA_OBS if tipo == "obs" else PALETA_PREVISAO
    campo = decodifica(rgb, paleta)
    if debug_dir:
        figura_calibracao(rgb, quadro, ext, os.path.join(debug_dir, "calib_" + os.path.basename(caminho)))
    return {"rgb": rgb, "quadro": quadro, "ext": ext, "erro_px": erro, "campo": campo}


def figura_calibracao(rgb, quadro, ext, saida):
    x0, x1, y0, y1 = quadro
    lon_e, lon_d, lat_s, lat_i = ext
    pts = linhas_referencia()
    px = x0 + (pts[:, 0] - lon_e) / (lon_d - lon_e) * (x1 - x0)
    py = y0 + (lat_s - pts[:, 1]) / (lat_s - lat_i) * (y1 - y0)
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(rgb.astype(np.uint8))
    ax.plot(px, py, ",", color="lime")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.set_title(f"Calibração: lon {lon_e:.2f}..{lon_d:.2f}  lat {lat_i:.2f}..{lat_s:.2f}")
    fig.savefig(saida, dpi=110, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Mascaras e metricas
# ---------------------------------------------------------------------------
def mascaras_regioes(lons, lats):
    LON, LAT = np.meshgrid(lons, lats)
    terra = shapely.contains_xy(poligonos_paises(), LON, LAT)
    ufs = poligonos_ufs()
    mascaras = {}
    for nome, lista in REGIOES.items():
        if lista is None:
            mascaras[nome] = terra
        else:
            geom = shapely.union_all([ufs[u] for u in lista])
            # celulas cujo centro cai na regiao (1 grau ja e grosseiro p/ UFs pequenas)
            mascaras[nome] = shapely.contains_xy(geom, LON, LAT)
    return mascaras


def heidke(cat_o, cat_p, w):
    n = w.sum()
    pc = (w * (cat_o == cat_p)).sum() / n
    esperado = sum((w * (cat_o == k)).sum() * (w * (cat_p == k)).sum() for k in (-1, 0, 1)) / n ** 2
    return pc, (pc - esperado) / (1 - esperado) if esperado < 1 else np.nan


def categoriza(x):
    return np.where(x > LIM_CATEGORIA, 1, np.where(x < -LIM_CATEGORIA, -1, 0))


def calcula_metricas(obs, prev, peso):
    ok = np.isfinite(obs) & np.isfinite(prev) & (peso > 0)
    o, p, w = obs[ok], prev[ok], peso[ok]
    if len(o) < 5:
        return None
    sw = w.sum()
    mo, mp = (w * o).sum() / sw, (w * p).sum() / sw
    cov = (w * (o - mo) * (p - mp)).sum()
    so = np.sqrt((w * (o - mo) ** 2).sum())
    sp = np.sqrt((w * (p - mp) ** 2).sum())
    corr = cov / (so * sp) if so > 0 and sp > 0 else np.nan
    den = np.sqrt((w * o ** 2).sum() * (w * p ** 2).sum())
    acc = (w * o * p).sum() / den if den > 0 else np.nan
    erro = p - o
    co, cp = categoriza(o), categoriza(p)
    pc, hss = heidke(co, cp, w)
    sinal = co != 0
    acerto_sinal = (w[sinal] * (np.sign(p[sinal]) == co[sinal])).sum() / w[sinal].sum() if sinal.any() else np.nan
    return {
        "n_celulas": int(len(o)),
        "corr": corr,
        "acc": acc,
        "rmse": np.sqrt((w * erro ** 2).sum() / sw),
        "mae": (w * np.abs(erro)).sum() / sw,
        "vies": (w * erro).sum() / sw,
        "abs_vies": abs((w * erro).sum() / sw),
        "acerto_cat": 100 * pc,
        "hss": hss,
        "acerto_sinal": 100 * acerto_sinal,
        "obs_media": mo,
        "prev_media": mp,
    }


def ranking(df):
    """Ranking por regiao: media dos ranks quantitativos, qualitativos e geral."""
    saida = []
    for regiao, g in df.groupby("regiao", sort=False):
        g = g.copy()
        for col, maior in METRICAS_QUANT + METRICAS_QUAL:
            g["rk_" + col] = g[col].rank(ascending=not maior, method="min")
        g["score_quant"] = g[["rk_" + c for c, _ in METRICAS_QUANT]].mean(axis=1)
        g["score_qual"] = g[["rk_" + c for c, _ in METRICAS_QUAL]].mean(axis=1)
        g["score_geral"] = (g["score_quant"] + g["score_qual"]) / 2
        g["rank_quant"] = g["score_quant"].rank(method="min").astype(int)
        g["rank_qual"] = g["score_qual"].rank(method="min").astype(int)
        g["rank_geral"] = g["score_geral"].rank(method="min").astype(int)
        saida.append(g.sort_values("score_geral"))
    return pd.concat(saida)


# ---------------------------------------------------------------------------
# Figuras e relatorio
# ---------------------------------------------------------------------------
def _cmap_plot():
    cmap = ListedColormap(CORES_PLOT[1:-1])
    cmap.set_under(CORES_PLOT[0])
    cmap.set_over(CORES_PLOT[-1])
    return cmap, BoundaryNorm(NIVEIS_PLOT, cmap.N)


def _contornos(ax):
    for geom in [poligonos_paises()] + list(poligonos_ufs().values()):
        for poly in getattr(geom, "geoms", [geom]):
            x, y = poly.exterior.xy
            ax.plot(x, y, color="k", lw=0.4)


def figura_campos(lons, lats, obs, prevs, terra, titulo, saida):
    cmap, norm = _cmap_plot()
    paineis = [("OBSERVADO", obs)] + list(prevs.items())
    ncol = 3
    nlin = int(np.ceil(len(paineis) / ncol))
    fig, axs = plt.subplots(nlin, ncol, figsize=(4.2 * ncol, 4.6 * nlin))
    axs = np.atleast_1d(axs).ravel()
    for ax, (nome, campo) in zip(axs, paineis):
        c = np.where(terra, campo, np.nan)
        m = ax.pcolormesh(lons, lats, c, cmap=cmap, norm=norm, shading="nearest")
        _contornos(ax)
        ax.set_xlim(lons[0] - 0.5, lons[-1] + 0.5)
        ax.set_ylim(lats[0] - 0.5, lats[-1] + 0.5)
        ax.set_aspect("equal")
        ax.set_title(nome, fontsize=10, fontweight="bold")
        ax.tick_params(labelsize=7)
    for ax in axs[len(paineis):]:
        ax.axis("off")
    fig.colorbar(m, ax=axs.tolist(), orientation="horizontal", fraction=0.03, pad=0.04,
                 extend="both", label="Anomalia de chuva (mm) — grade comum, saturada em ±140 mm")
    fig.suptitle(titulo, fontsize=13, fontweight="bold", y=0.93)
    fig.savefig(saida, dpi=130, bbox_inches="tight")
    return fig


def figura_ranking(rk, titulo, saida):
    tab = rk.pivot(index="modelo", columns="regiao", values="rank_geral")
    tab = tab[list(dict.fromkeys(rk.regiao))]
    tab = tab.sort_values(tab.columns[0])
    fig, ax = plt.subplots(figsize=(1.3 * tab.shape[1] + 3, 0.5 * tab.shape[0] + 2))
    im = ax.imshow(tab.values, cmap="RdYlGn_r", vmin=1, vmax=len(tab))
    ax.set_xticks(range(tab.shape[1]), tab.columns, rotation=30, ha="right", fontsize=9)
    ax.set_yticks(range(tab.shape[0]), tab.index, fontsize=9)
    for i in range(tab.shape[0]):
        for j in range(tab.shape[1]):
            v = tab.values[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{int(v)}º", ha="center", va="center", fontsize=9, fontweight="bold")
    ax.set_title(titulo, fontsize=12, fontweight="bold")
    fig.colorbar(im, ax=ax, label="posição no ranking geral", shrink=0.8)
    fig.savefig(saida, dpi=130, bbox_inches="tight")
    return fig


def pagina_tabelas(blocos, colunas, rotulos):
    """Uma pagina A4 deitada com ate 4 tabelas empilhadas: blocos = [(titulo, df)]."""
    fig = plt.figure(figsize=(11.7, 8.3))
    larguras = [0.05, 0.13] + [0.82 / (len(colunas) - 2)] * (len(colunas) - 2)
    altura = 0.93 / len(blocos) if len(blocos) > 2 else 0.31
    for i, (titulo, df) in enumerate(blocos):
        topo = 0.97 - i * altura
        fig.text(0.04, topo, titulo, fontsize=10.5, fontweight="bold", va="top")
        celulas = [[f"{r[c]:.2f}" if isinstance(r[c], (float, np.floating)) else str(r[c])
                    for c in colunas] for _, r in df.iterrows()]
        ax = fig.add_axes([0.04, topo - altura + 0.02, 0.92, altura - 0.05])
        ax.axis("off")
        t = ax.table(cellText=celulas, colLabels=rotulos, colWidths=larguras,
                     loc="upper center", cellLoc="center")
        t.auto_set_font_size(False)
        t.set_fontsize(7.5)
        t.scale(1, 1.05)
    return fig


TEXTO_METODO = """Metodologia
• Georreferenciamento: cada imagem é calibrada ajustando linha de costa, fronteiras e estados
  (Natural Earth) às linhas pretas do mapa — compensa extensões e escalas de pixel diferentes
  entre o mapa do modelo e o do CPTEC-MERGE.
• Decodificação: cada pixel recebe o valor central da sua classe de cor, com a paleta própria de cada
  fonte (previsão: classes -300…300 mm, branco ±20 mm; observado: classes de 20 mm, branco ±10 mm).
• Grade comum de {res}°: média dos pixels por célula, apenas continente. Ambos os campos são
  saturados em ±140 mm, pois o observado não diferencia valores acima de ±120 mm.
• Quantitativo: correlação de Pearson (padrão espacial), ACC não centrado (concordância de anomalia),
  RMSE, MAE e viés (previsto − observado), ponderados por cos(lat).
• Qualitativo: 3 categorias com limiar comum de ±{lim:.0f} mm (abaixo / normal / acima):
  % de acerto, Heidke Skill Score (HSS; 0 = acaso, 1 = perfeito) e acerto de sinal
  (% das células com anomalia observada significativa em que o modelo acertou o sinal).
• Ranking: média das posições em corr, ACC, RMSE e |viés| (quantitativo) e em HSS, acerto
  categórico e acerto de sinal (qualitativo); o ranking geral é a média dos dois.
Limitações: valores vêm de classes de cor (resolução ≈ largura da classe); mapas de contorno
suavizam o campo do modelo; regiões pequenas têm poucas células na grade."""


def processa_pasta(pasta, res, debug):
    nome = os.path.basename(pasta.rstrip("/"))
    obs_arqs = sorted(glob.glob(os.path.join(pasta, "OBS*.png")))
    prev_arqs = sorted(glob.glob(os.path.join(pasta, "mapa_*_PR_anom_M*_*.png")))
    if not obs_arqs or not prev_arqs:
        print(f"[{nome}] ignorada (sem OBS*.png ou mapas de previsão)")
        return None
    saida = os.path.join(pasta, "validacao")
    os.makedirs(saida, exist_ok=True)
    debug_dir = None
    if debug:
        debug_dir = os.path.join(saida, "calibracao")
        os.makedirs(debug_dir, exist_ok=True)

    print(f"[{nome}] observado: {os.path.basename(obs_arqs[0])}")
    obs = carrega_mapa(obs_arqs[0], "obs", debug_dir)
    print(f"    extensão obs: lon {obs['ext'][0]:.2f}..{obs['ext'][1]:.2f} "
          f"lat {obs['ext'][3]:.2f}..{obs['ext'][2]:.2f}  (erro de ajuste {obs['erro_px']:.2f} px)")

    prevs, info = {}, []
    for arq in prev_arqs:
        m = re.match(r"mapa_(.+)_PR_anom_(M\d)_(\d{6})\.png$", os.path.basename(arq))
        modelo, lead, alvo = m.groups()
        d = carrega_mapa(arq, "previsao", debug_dir)
        prevs[modelo] = d
        info.append((modelo, lead, alvo))
        print(f"    {modelo:<13} {lead} ext lon {d['ext'][0]:.2f}..{d['ext'][1]:.2f} "
              f"lat {d['ext'][3]:.2f}..{d['ext'][2]:.2f}  (erro {d['erro_px']:.2f} px)")
        if d["erro_px"] > 3:
            print(f"    ATENÇÃO: ajuste geográfico ruim para {modelo}; confira com --debug")
    if obs["erro_px"] > 3:
        print("    ATENÇÃO: ajuste geográfico ruim para o observado; confira com --debug")

    # grade comum = intersecao das extensoes
    lon_min = max([obs["ext"][0]] + [d["ext"][0] for d in prevs.values()])
    lon_max = min([obs["ext"][1]] + [d["ext"][1] for d in prevs.values()])
    lat_max = min([obs["ext"][2]] + [d["ext"][2] for d in prevs.values()])
    lat_min = max([obs["ext"][3]] + [d["ext"][3] for d in prevs.values()])
    lons = np.arange(np.ceil(lon_min / res) * res + res / 2, lon_max - res / 2 + 1e-6, res)
    lats = np.arange(np.ceil(lat_min / res) * res + res / 2, lat_max - res / 2 + 1e-6, res)

    obs_g = regrade(obs["campo"], obs["quadro"], obs["ext"], lons, lats, res)
    prev_g = {k: regrade(d["campo"], d["quadro"], d["ext"], lons, lats, res) for k, d in prevs.items()}

    mascaras = mascaras_regioes(lons, lats)
    peso = np.cos(np.deg2rad(lats))[:, None] * np.ones((1, len(lons)))
    linhas = []
    for modelo, lead, alvo in info:
        for regiao, msk in mascaras.items():
            met = calcula_metricas(obs_g, prev_g[modelo], peso * msk)
            if met:
                linhas.append({"pasta": nome, "modelo": modelo, "lead": lead, "alvo": alvo,
                               "regiao": regiao, **met})
    df = pd.DataFrame(linhas)
    rk = ranking(df)
    rk.to_csv(os.path.join(saida, f"metricas_ranking_{nome}.csv"), index=False, float_format="%.4f")

    # relatorio
    lead_txt = ", ".join(sorted({l for _, l, _ in info}))
    alvo_txt = info[0][2]
    pdf_path = os.path.join(saida, f"Validacao_{nome}.pdf")
    with PdfPages(pdf_path) as pdf:
        fig = plt.figure(figsize=(11.7, 8.3))
        fig.text(0.05, 0.92, f"Validação espacial — anomalia de chuva {alvo_txt[4:]}/{alvo_txt[:4]}",
                 fontsize=18, fontweight="bold")
        fig.text(0.05, 0.87, f"Pasta {nome} · previsões {lead_txt} · observado CPTEC-MERGE · "
                 f"{len(prevs)} modelos", fontsize=11, color="#444")
        fig.text(0.05, 0.08, TEXTO_METODO.format(res=res, lim=LIM_CATEGORIA), fontsize=9.5,
                 family="DejaVu Sans", va="bottom")
        geral = rk[rk.regiao == "América do Sul (geral)"]
        bras = rk[rk.regiao == "Brasil"]
        txt = "Ranking geral (América do Sul):  " + "  ".join(
            f"{r.rank_geral}º {r.modelo}" for r in geral.itertuples())
        txt += "\nRanking geral (Brasil):  " + "  ".join(
            f"{r.rank_geral}º {r.modelo}" for r in bras.itertuples())
        fig.text(0.05, 0.78, txt, fontsize=10.5, fontweight="bold")
        pdf.savefig(fig)
        plt.close(fig)

        fig = figura_ranking(rk, f"Ranking geral por região — {nome}",
                             os.path.join(saida, f"ranking_{nome}.png"))
        pdf.savefig(fig)
        plt.close(fig)

        fig = figura_campos(lons, lats, obs_g, prev_g, mascaras["América do Sul (geral)"],
                            f"Observado × previsões na grade comum ({res}°) — {nome}",
                            os.path.join(saida, f"campos_{nome}.png"))
        pdf.savefig(fig)
        plt.close(fig)

        cols = ["rank_geral", "modelo", "rank_quant", "rank_qual", "corr", "acc", "rmse",
                "vies", "acerto_cat", "hss", "acerto_sinal", "n_celulas"]
        rot = ["Geral", "Modelo", "Quant.", "Qual.", "Corr", "ACC", "RMSE", "Viés",
               "Acerto 3cat %", "HSS", "Acerto sinal %", "Células"]
        blocos = [(f"{regiao} — {nome}   (anomalia média observada: {g.obs_media.iloc[0]:+.0f} mm)", g)
                  for regiao, g in rk.groupby("regiao", sort=False)]
        for i in range(0, len(blocos), 4):
            fig = pagina_tabelas(blocos[i:i + 4], cols, rot)
            pdf.savefig(fig)
            plt.close(fig)
    print(f"    -> {pdf_path}")
    return rk


def consolida(todos, base):
    df = pd.concat(todos)
    cons = (df.groupby(["regiao", "modelo"], sort=False)
              .agg(rank_medio=("rank_geral", "mean"), score_medio=("score_geral", "mean"),
                   corr_media=("corr", "mean"),
                   rmse_medio=("rmse", "mean"), hss_medio=("hss", "mean"),
                   n_pastas=("pasta", "nunique"))
              .reset_index())
    # desempate pela media dos scores (posicao media nas metricas individuais)
    cons["chave"] = cons["rank_medio"] + cons["score_medio"] / 100
    cons["posicao"] = cons.groupby("regiao")["chave"].rank(method="min").astype(int)
    cons = cons.drop(columns="chave")
    cons = cons.sort_values(["regiao", "posicao"])
    arq = os.path.join(base, "ranking_consolidado.csv")
    cons.to_csv(arq, index=False, float_format="%.3f")
    print(f"\nRanking consolidado ({df.pasta.nunique()} pastas) -> {arq}")
    for regiao in REGIOES:
        g = cons[cons.regiao == regiao]
        if len(g):
            print(f"  {regiao:<24} " + "  ".join(f"{r.posicao}º {r.modelo}" for r in g.itertuples()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="saida_mapas/Verificação", help="Diretório com as pastas de verificação")
    ap.add_argument("--pasta", nargs="*", help="Pastas específicas (padrão: todas)")
    ap.add_argument("--res", type=float, default=1.0, help="Resolução da grade comum em graus (padrão 1.0)")
    ap.add_argument("--debug", action="store_true", help="Salva figuras de calibração geográfica")
    args = ap.parse_args()

    pastas = args.pasta or sorted(d for d in os.listdir(args.dir) if os.path.isdir(os.path.join(args.dir, d)))
    todos = []
    for p in pastas:
        rk = processa_pasta(os.path.join(args.dir, p), args.res, args.debug)
        if rk is not None:
            todos.append(rk)
            g = rk[rk.regiao == "América do Sul (geral)"]
            print("    Ranking geral: " + "  ".join(f"{r.rank_geral}º {r.modelo}" for r in g.itertuples()))
    if len(todos) > 1:
        consolida(todos, args.dir)


if __name__ == "__main__":
    main()
