#!/usr/bin/env python3
"""Monta um PDF comparativo dos mapas de previsao sazonal de todos os modelos
para um dado mes de rodada, agrupado por variavel/tipo, com uma pagina por
mes de previsao (M1..M6) contendo a grade de todos os modelos disponiveis.
"""
import argparse
import glob
import json
import os
import re

from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

TIPOS = {
    "abs": "Previsão Absoluta",
    "anom": "Anomalia (vs Climatologia)",
}
# Temperaturas só com anomalia (mais útil que o valor médio e deixa o PDF menor);
# chuva com absoluto e anomalia.
VARIAVEIS = [
    ("PR", "Precipitação — Chuva Acumulada (mm)", ["abs", "anom"]),
    ("TMAX", "Temperatura Máxima (°C)", ["anom"]),
    ("TMIN", "Temperatura Mínima (°C)", ["anom"]),
]
MESES = [f"M{i}" for i in range(1, 7)]

LARGURA_PADRAO = 800  # largura de cada mapa em px (--largura); 1100 = alta resolução
CELL_W = LARGURA_PADRAO
QUALIDADE = 60  # qualidade JPEG das páginas (--qualidade); 800/60 ≈ 17 MB, cabe no Gmail
COLS = 4
ROWS = 2
PAD = 18
HEADER_H = 170
FOOTER_H = 60
MULTI = "MULTIMODELO"  # painel de consenso (gera_multimodelo.py), sempre o último
NOTA_MULTI = None      # texto explicativo do rodapé, montado em main() se houver MULTIMODELO
BG = (255, 255, 255)
TITLE_COLOR = (20, 20, 20)
SUBTITLE_COLOR = (90, 90, 90)


def encontra_modelos(saida_mapas_dir, rodada_tag):
    modelos = []
    for d in sorted(os.listdir(saida_mapas_dir)):
        full = os.path.join(saida_mapas_dir, d)
        if not os.path.isdir(full):
            continue
        m = re.match(rf"^([A-Za-z_]+)_{rodada_tag}$", d)
        if m:
            modelos.append((m.group(1), full))
    # o MULTIMODELO vai para o fim da grade (ocupa a 10ª posição do 5x2)
    modelos.sort(key=lambda x: x[0] == MULTI)
    return modelos


def nota_multimodelo(modelos):
    """Texto do rodapé que explica como o MULTIMODELO é calculado."""
    dir_multi = dict(modelos).get(MULTI)
    if not dir_multi:
        return None
    try:
        with open(os.path.join(dir_multi, "multimodelo.json")) as f:
            meta = json.load(f)
        usados, limiar = meta["modelos"], meta["limiar_concordancia"]
    except (OSError, KeyError, ValueError):
        usados, limiar = [m for m, _ in modelos if m != MULTI], 7
    n = len(usados)
    return [
        f"MULTIMODELO: média simples, com peso igual, dos {n} modelos ({', '.join(usados)}). "
        f"Anomalia = média das anomalias de cada modelo (previsão − hindcast do próprio modelo, "
        f"isto é, cada um contra a sua climatologia) = média das previsões − média dos hindcasts.",
        f"Absoluto = média das previsões. Pontilhado nos mapas de anomalia: menos de {limiar} dos {n} "
        f"modelos concordam com o sinal da média (consenso fraco). Grade de 1° (JMA interpolado de "
        f"1,25°); sem pesos por desempenho e sem membros individuais.",
    ]


def data_alvo(path):
    m = re.search(r"_M\d_(\d{6})\.png$", path)
    return m.group(1) if m else "????"


def carrega_redimensiona(path, cell_w):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    cell_h = round(cell_w * h / w)
    return img.resize((cell_w, cell_h), Image.LANCZOS)


def monta_pagina(modelos, saida_mapas_dir, rodada_tag, var_code, var_label,
                  tipo_code, tipo_label, mes_idx):
    itens = []
    alvo = None
    for nome_modelo, model_dir in modelos:
        padrao = os.path.join(
            model_dir, f"mapa_{nome_modelo}_{var_code}_{tipo_code}_{mes_idx}_*.png"
        )
        achados = glob.glob(padrao)
        if achados:
            path = achados[0]
            if alvo is None:
                alvo = data_alvo(path)
            itens.append((nome_modelo, path))
        else:
            itens.append((nome_modelo, None))

    if not any(p for _, p in itens):
        return None

    cell_h = round(CELL_W * 2200 / 2670)
    grid_w = COLS * CELL_W + (COLS + 1) * PAD
    grid_h = ROWS * cell_h + (ROWS + 1) * PAD
    page_w = grid_w
    page_h = HEADER_H + grid_h + FOOTER_H

    page = Image.new("RGB", (page_w, page_h), BG)
    draw = ImageDraw.Draw(page)

    f_title = ImageFont.truetype(FONT_BOLD, 46)
    f_subtitle = ImageFont.truetype(FONT_REG, 32)
    f_model_missing = ImageFont.truetype(FONT_BOLD, 30)

    titulo = f"{var_label} — {tipo_label}"
    subtitulo = f"Mês de previsão {mes_idx}  ·  Alvo: {alvo}  ·  Rodada: {rodada_tag}"
    draw.text((PAD, 22), titulo, font=f_title, fill=TITLE_COLOR)
    draw.text((PAD, 80), subtitulo, font=f_subtitle, fill=SUBTITLE_COLOR)
    draw.line([(PAD, HEADER_H - 8), (page_w - PAD, HEADER_H - 8)], fill=(200, 200, 200), width=2)

    for idx, (nome_modelo, path) in enumerate(itens):
        row = idx // COLS
        col = idx % COLS
        x = PAD + col * (CELL_W + PAD)
        y = HEADER_H + PAD + row * (cell_h + PAD)
        if path:
            thumb = carrega_redimensiona(path, CELL_W)
            page.paste(thumb, (x, y))
        else:
            draw.rectangle([x, y, x + CELL_W, y + cell_h], outline=(200, 200, 200), width=2)
            msg = f"{nome_modelo}\n(sem dado)"
            draw.multiline_text(
                (x + CELL_W // 2, y + cell_h // 2), msg, font=f_model_missing,
                fill=(160, 160, 160), anchor="mm", align="center",
            )
        draw.rectangle([x, y, x + CELL_W, y + cell_h], outline=(210, 210, 210), width=1)

    desenha_rodape(draw, page_h)

    return page


def quebra_linhas(paragrafos, largura, fonte):
    """Quebra cada parágrafo em linhas que caibam na largura (px) com a fonte dada."""
    linhas = []
    for par in paragrafos:
        atual = ""
        for palavra in par.split():
            teste = f"{atual} {palavra}".strip()
            if atual and fonte.getlength(teste) > largura:
                linhas.append(atual)
                atual = palavra
            else:
                atual = teste
        if atual:
            linhas.append(atual)
    return linhas


def desenha_rodape(draw, page_h):
    f_footer = ImageFont.truetype(FONT_REG, 22)
    y = page_h - FOOTER_H + 15
    if NOTA_MULTI:
        f_nota = ImageFont.truetype(FONT_REG, 26)
        for linha in NOTA_MULTI:
            draw.text((PAD, y), linha, font=f_nota, fill=(70, 70, 70))
            y += 38
        y += 6
    rodape = "Comparativo entre modelos — Copernicus C3S Seasonal Forecast"
    draw.text((PAD, y), rodape, font=f_footer, fill=(140, 140, 140))


def monta_capa(rodada_tag, modelos_nomes, page_w, page_h):
    page = Image.new("RGB", (page_w, page_h), (250, 250, 252))
    draw = ImageDraw.Draw(page)
    f_h1 = ImageFont.truetype(FONT_BOLD, 90)
    f_h2 = ImageFont.truetype(FONT_REG, 46)
    f_body = ImageFont.truetype(FONT_REG, 34)

    ano, mes = rodada_tag[:4], rodada_tag[4:]
    draw.text((page_w // 2, page_h // 2 - 160), "Comparativo de Previsões Sazonais",
              font=f_h1, fill=(20, 20, 20), anchor="mm", align="center")
    draw.text((page_w // 2, page_h // 2 - 60), f"Rodada {mes}/{ano}",
              font=f_h2, fill=(80, 80, 80), anchor="mm", align="center")
    draw.text((page_w // 2, page_h // 2 + 20),
              "Meses de previsão M1 a M6  ·  Chuva (absoluto e anomalia)  ·  Anomalia de T. Máxima e T. Mínima",
              font=f_body, fill=(110, 110, 110), anchor="mm", align="center")
    modelos_txt = "Modelos: " + ", ".join(modelos_nomes)
    draw.text((page_w // 2, page_h // 2 + 90), modelos_txt,
              font=f_body, fill=(110, 110, 110), anchor="mm", align="center")
    desenha_rodape(draw, page_h)
    return page


def monta_separador(titulo, subtitulo, page_w, page_h):
    page = Image.new("RGB", (page_w, page_h), (245, 247, 250))
    draw = ImageDraw.Draw(page)
    f_h1 = ImageFont.truetype(FONT_BOLD, 80)
    f_h2 = ImageFont.truetype(FONT_REG, 40)
    draw.text((page_w // 2, page_h // 2 - 30), titulo, font=f_h1,
              fill=(20, 20, 20), anchor="mm", align="center")
    draw.text((page_w // 2, page_h // 2 + 60), subtitulo, font=f_h2,
              fill=(100, 100, 100), anchor="mm", align="center")
    return page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rodada", default="202609", help="AAAAMM da rodada, ex: 202609")
    ap.add_argument("--saida-mapas", default="saida_mapas")
    ap.add_argument("--saida-pdf", default=None)
    ap.add_argument("--largura", type=int, default=LARGURA_PADRAO, help="Largura de cada mapa em px (padrão: %(default)s)")
    ap.add_argument("--qualidade", type=int, default=QUALIDADE, help="Qualidade JPEG (padrão: %(default)s)")
    args = ap.parse_args()

    modelos = encontra_modelos(args.saida_mapas, args.rodada)
    if not modelos:
        raise SystemExit(f"Nenhum modelo encontrado para a rodada {args.rodada}")
    print(f"Modelos encontrados ({len(modelos)}): {[m for m, _ in modelos]}")

    global COLS, ROWS, FOOTER_H, NOTA_MULTI, CELL_W
    CELL_W = args.largura
    n = len(modelos)
    # até 8 painéis: 4 colunas (4x2, layout original); 9-10 (9 modelos + MULTIMODELO): 5x2
    COLS = n if n <= 4 else (4 if n <= 8 else 5)
    ROWS = -(-n // COLS)
    nota = nota_multimodelo(modelos)
    if nota:
        largura_util = COLS * CELL_W + (COLS - 1) * PAD
        NOTA_MULTI = quebra_linhas(nota, largura_util, ImageFont.truetype(FONT_REG, 26))
        FOOTER_H = 60 + 38 * len(NOTA_MULTI) + 6

    cell_h = round(CELL_W * 2200 / 2670)
    grid_w = COLS * CELL_W + (COLS + 1) * PAD
    grid_h = ROWS * cell_h + (ROWS + 1) * PAD
    page_w = grid_w
    page_h = HEADER_H + grid_h + FOOTER_H

    paginas = []
    paginas.append(monta_capa(args.rodada, [m for m, _ in modelos], page_w, page_h))

    for var_code, var_label, tipos in VARIAVEIS:
        for tipo_code in tipos:
            tipo_label = TIPOS[tipo_code]
            paginas.append(monta_separador(var_label, tipo_label, page_w, page_h))
            for mes_idx in MESES:
                pg = monta_pagina(modelos, args.saida_mapas, args.rodada,
                                   var_code, var_label, tipo_code, tipo_label, mes_idx)
                if pg is not None:
                    paginas.append(pg)
                else:
                    print(f"  aviso: sem dados para {var_code}/{tipo_code}/{mes_idx}")

    saida_pdf = args.saida_pdf or f"Comparativo_Modelos_{args.rodada}.pdf"
    paginas[0].save(saida_pdf, save_all=True, append_images=paginas[1:], quality=args.qualidade)
    tam = os.path.getsize(saida_pdf) / 2**20
    print(f"PDF gerado: {saida_pdf}  ({len(paginas)} páginas, {tam:.1f} MB)")


if __name__ == "__main__":
    main()
