#!/usr/bin/env python3
"""Relatório em PDF da validação de um mês-alvo, separado por rodada.

Lê as saídas do valida_previsoes.py (Verificação/<PASTA>/validacao/) de todas as
pastas cujo alvo é o mês pedido (M1 da rodada do mês, M2 da rodada anterior, ...)
e monta um PDF A4 (HTML + google-chrome headless):

  1. resumo do mês: mapa observado, anomalia por região e líderes por rodada
  2. comparação entre rodadas (prazos) para o mesmo alvo
  3. uma seção por rodada: campos na grade comum, ranking por região e métricas
  4. contexto: ranking consolidado de todas as pastas validadas; metodologia

Uso:
    python gera_relatorio_validacao.py --alvo 202610
Saída: saida_mapas/Verificação/Relatorio_Validacao_<MES><AA>.pdf
       (HTML e figuras de apoio em Verificação/relatorio_<MES><AA>/)
"""
import argparse
import glob
import html
import os
import subprocess
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
MESES_EXT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]
GERAL, BRASIL = "América do Sul (geral)", "Brasil"
REGIOES_BR = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul", "MATOPIBA"]
# cores categóricas (paleta validada, 3 primeiros slots passam em todos os pares)
COR_LEAD = {"M1": "#2a78d6", "M2": "#eb6834", "M3": "#1baf7a"}
COR_EXTRA = ["#eda100", "#e87ba4", "#008300"]


def rotulo(aaaamm):
    return f"{MESES[int(aaaamm[4:]) - 1]}{aaaamm[2:4]}"


def menos_meses(aaaamm, n):
    a, m = int(aaaamm[:4]), int(aaaamm[4:]) - 1 - n
    a += m // 12
    return f"{a:04d}{m % 12 + 1:02d}"


def br(x, d=2, sinal=False):
    if pd.isna(x):
        return "—"
    s = f"{x:+.{d}f}" if sinal else f"{x:.{d}f}"
    return s.replace(".", ",").replace("-", "−")


def esc(s):
    return html.escape(str(s))


def carrega(base, alvo):
    blocos = []
    for arq in glob.glob(os.path.join(base, "*", "validacao", "metricas_ranking_*.csv")):
        df = pd.read_csv(arq, dtype={"alvo": str})
        if df.empty or df.alvo.iloc[0] != alvo:
            continue
        pasta = df.pasta.iloc[0]
        lead = df.lead.iloc[0]
        k = int(lead[1:])
        blocos.append({"pasta": pasta, "lead": lead, "k": k, "rodada": menos_meses(alvo, k - 1),
                       "df": df, "dir": os.path.abspath(os.path.join(base, pasta))})
    return sorted(blocos, key=lambda b: b["k"])


def tom_rank(r, n):
    """Fundo sequencial (verde) para posições: 1º mais escuro."""
    if pd.isna(r):
        return ""
    t = 1 - (r - 1) / max(n - 1, 1)
    alpha = 0.10 + 0.55 * t ** 1.5
    return f"background: rgba(27,140,90,{alpha:.2f});"


def tabela_metricas(g, n):
    linhas = []
    for r in g.sort_values(["rank_geral", "score_geral"]).itertuples():
        linhas.append(
            f"<tr><td class='c' style='{tom_rank(r.rank_geral, n)}'><b>{r.rank_geral}º</b></td>"
            f"<td class='l'><b>{esc(r.modelo)}</b></td>"
            f"<td class='c'>{r.rank_quant}º</td><td class='c'>{r.rank_qual}º</td>"
            f"<td>{br(r.corr)}</td><td>{br(r.acc)}</td><td>{br(r.rmse, 1)}</td>"
            f"<td>{br(r.vies, 1, True)}</td><td>{br(r.acerto_cat, 0)}</td><td>{br(r.hss)}</td>"
            f"<td>{br(r.acerto_sinal, 0)}</td></tr>")
    return ("<table class='met'><thead><tr><th>Geral</th><th class='l'>Modelo</th><th>Quant.</th>"
            "<th>Qual.</th><th>Corr</th><th>ACC</th><th>RMSE<br>mm</th><th>Viés<br>mm</th>"
            "<th>Acerto<br>3 cat. %</th><th>HSS</th><th>Acerto<br>sinal %</th></tr></thead><tbody>"
            + "".join(linhas) + "</tbody></table>")


def figura_dots(blocos, regiao, saida):
    """Correlação por modelo, um ponto por rodada (prazo)."""
    df = pd.concat([b["df"] for b in blocos])
    df = df[df.regiao == regiao]
    ordem = df.groupby("modelo")["corr"].mean().sort_values().index.tolist()
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=200)
    for i, b in enumerate(blocos):
        g = b["df"][b["df"].regiao == regiao].set_index("modelo")
        cor = COR_LEAD.get(b["lead"], COR_EXTRA[i % len(COR_EXTRA)])
        y = [ordem.index(m) for m in g.index]
        ax.scatter(g["corr"], y, s=46, color=cor, edgecolor="white", linewidth=1.2, zorder=3,
                   label=f"Rodada {b['rodada'][4:]}/{b['rodada'][:4]} ({b['lead']})")
    for j, m in enumerate(ordem):
        v = df[df.modelo == m]["corr"]
        ax.plot([v.min(), v.max()], [j, j], color="#c9c8c2", lw=2, zorder=1, solid_capstyle="round")
    ax.set_yticks(range(len(ordem)))
    ax.set_yticklabels(ordem, fontsize=9, color="#2b2b29")
    ax.set_xlabel(f"Correlação espacial com o observado — {regiao}", fontsize=9, color="#555")
    ax.grid(axis="x", color="#e6e5e0", lw=0.8)
    ax.set_axisbelow(True)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#bbb")
    ax.tick_params(axis="x", labelsize=8, colors="#555")
    ax.tick_params(axis="y", length=0)
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(saida)
    plt.close(fig)


CSS = """
@page { size: A4; margin: 14mm 13mm 14mm 13mm; }
body { font-family: 'DejaVu Sans', sans-serif; font-size: 9.2pt; color: #222; line-height: 1.38; }
h1 { font-size: 20pt; margin: 0 0 2mm 0; color: #1b3a57; }
h2 { font-size: 14pt; color: #1b3a57; border-bottom: 2px solid #1b3a57; padding-bottom: 1.5mm;
     margin: 0 0 3mm 0; }
h3 { font-size: 10.5pt; color: #1b3a57; margin: 4mm 0 1.5mm 0; }
.sub { color: #555; font-size: 10pt; margin-bottom: 4mm; }
.quebra { page-break-before: always; }
.faixa { background: #1b3a57; color: white; padding: 2.5mm 4mm; border-radius: 2mm; margin-bottom: 3mm;
         font-size: 10.5pt; }
.faixa b { font-size: 12pt; }
table { border-collapse: collapse; width: 100%; margin: 1mm 0 2mm 0; page-break-inside: avoid; }
th { background: #eef1f5; color: #1b3a57; font-size: 7.8pt; padding: 1mm 1.2mm; border-bottom: 1px solid #9aa9b8; }
td { padding: 0.75mm 1.2mm; border-bottom: 1px solid #e3e3e3; text-align: right; font-size: 8.6pt; }
td.l, th.l { text-align: left; } td.c, th.c { text-align: center; }
.met td { font-variant-numeric: tabular-nums; }
.grid2 { display: flex; gap: 5mm; align-items: flex-start; }
.grid2 > div { flex: 1; }
img { max-width: 100%; }
.nota { color: #555; font-size: 8.2pt; }
ul { margin: 1mm 0 2mm 0; padding-left: 5mm; } li { margin-bottom: 1mm; }
.caixa { border: 1px solid #c9d3dd; border-radius: 2mm; padding: 2.5mm 3.5mm; background: #f7f9fb; }
.pos { color: #1a5b8c; font-weight: bold; } .neg { color: #b03a1f; font-weight: bold; }
"""


def lideres(g, n=3):
    g = g.sort_values(["rank_geral", "score_geral"])
    return ", ".join(f"{r.rank_geral}º {r.modelo}" for r in g.head(n).itertuples())


def classe_anom(v):
    return "pos" if v > 0 else "neg"


def antecedencia(k):
    if k == 1:
        return "rodada do próprio mês"
    return f"{k - 1} {'mês' if k == 2 else 'meses'} de antecedência"


def secao_rodada(b, alvo, n_mod, fig_dir):
    df = b["df"]
    rod = b["rodada"]
    out = [f"<div class='quebra'></div><h2>Rodada {rod[4:]}/{rod[:4]} → alvo {alvo[4:]}/{alvo[:4]} "
           f"({b['lead']})</h2>",
           f"<div class='faixa'>Previsão emitida em <b>{MESES_EXT[int(rod[4:]) - 1]}/{rod[:4]}</b> para "
           f"<b>{MESES_EXT[int(alvo[4:]) - 1]}/{alvo[:4]}</b> · prazo {b['lead']} "
           f"({antecedencia(b['k'])}) · pasta {esc(b['pasta'])}</div>"]
    g, gb = df[df.regiao == GERAL], df[df.regiao == BRASIL]
    best_b = gb.sort_values(["rank_geral", "score_geral"]).iloc[0]
    pior_b = gb.sort_values(["rank_geral", "score_geral"]).iloc[-1]
    vies_neg = (gb.vies < 0).sum()
    out.append("<div class='caixa'><ul>"
               f"<li><b>América do Sul:</b> {lideres(g)}.</li>"
               f"<li><b>Brasil:</b> {lideres(gb)}. O melhor ({esc(best_b.modelo)}) teve correlação "
               f"{br(best_b['corr'])} e acerto de sinal de {br(best_b.acerto_sinal, 0)}%; o último "
               f"({esc(pior_b.modelo)}), correlação {br(pior_b['corr'])}.</li>"
               f"<li><b>Viés no Brasil:</b> {vies_neg} de {len(gb)} modelos previram menos chuva que a "
               f"observada (viés médio {br(gb.vies.mean(), 1, True)} mm).</li></ul></div>")
    out.append(f"<h3>Observado × previsões na grade comum de 1°</h3>"
               f"<img src='{os.path.join(b['dir'], 'validacao', 'campos_' + b['pasta'] + '.png')}' "
               f"style='height: 178mm; display:block; margin: 0 auto;'>")
    linhas = []
    for reg in REGIOES_BR:
        gg = df[df.regiao == reg].sort_values(["rank_geral", "score_geral"])
        if gg.empty:
            continue
        top = gg.iloc[0]
        linhas.append(f"<tr><td class='l'><b>{reg}</b></td>"
                      f"<td>{br(gg.obs_media.iloc[0], 0, True)}</td>"
                      f"<td class='l'>{esc(', '.join(gg.modelo.head(3)))}</td>"
                      f"<td>{br(top['corr'])}</td>"
                      f"<td class='l'>{esc(gg.iloc[-1].modelo)}</td></tr>")
    out.append("<div class='quebra'></div>"
               f"<h3>Ranking por região — rodada {rod[4:]}/{rod[:4]} ({b['lead']})</h3>"
               "<div class='grid2'><div style='flex: 0 0 92mm'>"
               f"<img src='{os.path.join(b['dir'], 'validacao', 'ranking_' + b['pasta'] + '.png')}' "
               "style='width: 92mm;'></div><div>"
               "<table><thead><tr><th class='l'>Região</th><th>Anom.<br>obs. mm</th>"
               "<th class='l'>1º, 2º, 3º</th><th>Corr<br>do 1º</th><th class='l'>Último</th></tr></thead><tbody>"
               + "".join(linhas) + "</tbody></table>"
               "<div class='nota'>Regiões pequenas têm poucas células; em estação seca o HSS tende a zero.</div>"
               "</div></div>")
    for reg in [GERAL, BRASIL]:
        gg = df[df.regiao == reg]
        out.append(f"<h3>{reg} — anomalia média observada {br(gg.obs_media.iloc[0], 0, True)} mm · "
                   f"{int(gg.n_celulas.iloc[0])} células</h3>" + tabela_metricas(gg, n_mod))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alvo", required=True, help="Mês verificado, AAAAMM")
    ap.add_argument("--dir", default="saida_mapas/Verificação")
    args = ap.parse_args()
    alvo, base = args.alvo, args.dir

    blocos = carrega(base, alvo)
    if not blocos:
        raise SystemExit(f"Nenhuma pasta validada com alvo {alvo}. Rode valida_previsoes.py antes.")
    nome = rotulo(alvo)
    rel_dir = os.path.abspath(os.path.join(base, f"relatorio_{nome}"))
    os.makedirs(rel_dir, exist_ok=True)
    modelos = sorted(set().union(*[set(b["df"].modelo) for b in blocos]))
    n_mod = len(modelos)
    mes_txt = f"{MESES_EXT[int(alvo[4:]) - 1]}/{alvo[:4]}"

    obs = sorted(glob.glob(os.path.join(blocos[0]["dir"], "OBS*.png")))
    obs_img = os.path.abspath(obs[0]) if obs else None

    # ---------------- página 1: resumo ----------------
    p = [f"<h1>Validação das previsões sazonais de chuva — {mes_txt}</h1>",
         f"<div class='sub'>Modelos do Copernicus C3S ({n_mod}: {', '.join(modelos)}) × observado "
         f"CPTEC-MERGE · anomalia mensal de chuva (mm) · {len(blocos)} rodadas com alvo em {mes_txt} · "
         f"gerado em {date.today().strftime('%d/%m/%Y')}</div>"]
    d0 = blocos[0]["df"]
    anom = d0.groupby("regiao", sort=False).obs_media.first()
    lin_anom = "".join(f"<tr><td class='l'>{esc(r)}</td><td class='{classe_anom(v)}'>{br(v, 0, True)}</td></tr>"
                       for r, v in anom.items())
    lin_rod = []
    for b in blocos:
        d = b["df"]
        lin_rod.append(f"<tr><td class='l'><b>{b['rodada'][4:]}/{b['rodada'][:4]}</b> ({b['lead']})</td>"
                       f"<td class='l'>{esc(lideres(d[d.regiao == GERAL]))}</td>"
                       f"<td class='l'>{esc(lideres(d[d.regiao == BRASIL]))}</td></tr>")
    p.append("<div class='grid2'><div>"
             + (f"<img src='{obs_img}' style='width: 100%;'>" if obs_img else "")
             + "<div class='nota'>Anomalia observada (CPTEC-MERGE).</div></div><div>"
             "<h3 style='margin-top:0'>Anomalia média observada por região</h3>"
             "<table><thead><tr><th class='l'>Região</th><th>mm</th></tr></thead><tbody>"
             + lin_anom + "</tbody></table>"
             "<div class='nota'>Média ponderada por cos(lat) na grade de 1°, apenas continente, "
             "valores saturados em ±140 mm.</div></div></div>")
    p.append("<h3>Três primeiros colocados por rodada</h3><table><thead><tr><th class='l'>Rodada (prazo)</th>"
             "<th class='l'>América do Sul</th><th class='l'>Brasil</th></tr></thead><tbody>"
             + "".join(lin_rod) + "</tbody></table>")

    # destaques automáticos
    todos = pd.concat([b["df"] for b in blocos])
    tb = todos[todos.regiao == BRASIL]
    rk_med = tb.groupby("modelo").rank_geral.mean().sort_values()
    corr_med = tb.groupby("modelo")["corr"].mean()
    vies_med = tb.groupby("modelo").vies.mean()
    amplitude = tb.groupby("modelo").rank_geral.agg(lambda s: s.max() - s.min()).sort_values(ascending=False)
    dest = [f"<li><b>Melhor no Brasil, na média das {len(blocos)} rodadas:</b> {esc(rk_med.index[0])} "
            f"(posição média {br(rk_med.iloc[0], 1)}, correlação média {br(corr_med[rk_med.index[0]])}); "
            f"em seguida {esc(rk_med.index[1])} e {esc(rk_med.index[2])}.</li>",
            f"<li><b>Pior no Brasil:</b> {esc(rk_med.index[-1])} (posição média {br(rk_med.iloc[-1], 1)}).</li>",
            f"<li><b>Viés:</b> {(vies_med < 0).sum()} de {len(vies_med)} modelos subestimaram a chuva no Brasil "
            f"na média das rodadas; o maior viés positivo foi do {esc(vies_med.idxmax())} "
            f"({br(vies_med.max(), 1, True)} mm) e o mais negativo do {esc(vies_med.idxmin())} "
            f"({br(vies_med.min(), 1, True)} mm).</li>"]
    if len(blocos) > 1 and amplitude.iloc[0] >= 4:
        dest.append(f"<li><b>Instabilidade entre prazos:</b> {esc(amplitude.index[0])} variou "
                    f"{int(amplitude.iloc[0])} posições entre as rodadas no Brasil, o que indica acerto "
                    "ocasional, não habilidade consistente.</li>")
    p.append("<h3>Destaques</h3><div class='caixa'><ul>" + "".join(dest) + "</ul></div>")

    # ---------------- página 2: comparação entre rodadas ----------------
    p.append("<div class='quebra'></div><h2>Comparação entre rodadas (mesmo alvo)</h2>"
             f"<div class='sub'>Cada coluna é uma rodada diferente prevendo {mes_txt}. "
             "M1 = rodada do próprio mês; M2 = um mês antes; M3 = dois meses antes.</div>")
    cab = "".join(f"<th colspan='3'>{b['rodada'][4:]}/{b['rodada'][:4]} ({b['lead']})</th>" for b in blocos)
    sub = "".join("<th>Pos.</th><th>Corr</th><th>Viés</th>" for _ in blocos)
    for reg in [GERAL, BRASIL]:
        linhas = []
        ordem = todos[todos.regiao == reg].groupby("modelo").rank_geral.mean().sort_values().index
        for m in ordem:
            cel = []
            for b in blocos:
                r = b["df"][(b["df"].regiao == reg) & (b["df"].modelo == m)]
                if r.empty:
                    cel.append("<td></td><td></td><td></td>")
                    continue
                r = r.iloc[0]
                cel.append(f"<td class='c' style='{tom_rank(r.rank_geral, n_mod)}'>{r.rank_geral}º</td>"
                           f"<td>{br(r['corr'])}</td><td>{br(r.vies, 0, True)}</td>")
            med = todos[(todos.regiao == reg) & (todos.modelo == m)].rank_geral.mean()
            linhas.append(f"<tr><td class='l'><b>{esc(m)}</b></td>{''.join(cel)}<td class='c'>{br(med, 1)}</td></tr>")
        p.append(f"<h3>{reg}</h3><table class='met'><thead><tr><th class='l' rowspan='2'>Modelo</th>{cab}"
                 f"<th rowspan='2'>Posição<br>média</th></tr><tr>{sub}</tr></thead><tbody>"
                 + "".join(linhas) + "</tbody></table>")
    fig_dots = os.path.join(rel_dir, "corr_por_rodada_brasil.png")
    figura_dots(blocos, BRASIL, fig_dots)
    p.append("<h3>Correlação espacial no Brasil por rodada</h3>"
             f"<img src='{fig_dots}' style='width: 140mm; display:block; margin: 0 auto;'>"
             "<div class='nota'>A linha cinza liga a pior e a melhor rodada de cada modelo: quanto mais "
             "curta, mais estável é o desempenho entre prazos. Viés em mm (previsto − observado).</div>")

    # ---------------- seções por rodada ----------------
    for b in blocos:
        p.append(secao_rodada(b, alvo, n_mod, rel_dir))

    # ---------------- contexto e metodologia ----------------
    cons_arq = os.path.join(base, "ranking_consolidado.csv")
    p.append("<div class='quebra'></div><h2>Contexto e metodologia</h2>")
    if os.path.exists(cons_arq):
        cons = pd.read_csv(cons_arq)
        n_p = int(cons.n_pastas.max())
        pastas = sorted(os.path.basename(os.path.dirname(os.path.dirname(a))) for a in
                        glob.glob(os.path.join(base, "*", "validacao", "metricas_ranking_*.csv")))
        linhas = []
        for reg in [GERAL, BRASIL] + REGIOES_BR:
            g = cons[cons.regiao == reg].sort_values("posicao")
            if len(g):
                linhas.append(f"<tr><td class='l'><b>{esc(reg)}</b></td><td class='l'>"
                              + esc("  ".join(f"{r.posicao}º {r.modelo}" for r in g.itertuples()))
                              + "</td></tr>")
        p.append(f"<h3>Ranking consolidado de todas as validações ({n_p} pastas: {esc(', '.join(pastas))})</h3>"
                 "<table><thead><tr><th class='l'>Região</th><th class='l'>Ordem (posição média)</th></tr>"
                 "</thead><tbody>" + "".join(linhas) + "</tbody></table>"
                 "<div class='nota'>Ainda são poucos meses: o ranking consolidado é indicativo e muda "
                 "bastante a cada mês incluído.</div>")
    p.append("""<h3>Como a validação é feita</h3><ul>
<li><b>Fontes:</b> mapas PNG de anomalia de chuva de cada modelo (previsão − hindcast, gerados por
<code>gera_mapas_previsao.py</code>) e o mapa de anomalia do CPTEC-MERGE.</li>
<li><b>Georreferenciamento automático:</b> costa, fronteiras e estados (Natural Earth) são ajustados às
linhas pretas de cada imagem, o que compensa extensões e escalas diferentes.</li>
<li><b>Decodificação:</b> cada pixel recebe o valor central da sua classe de cor (previsão: classes de
−300 a 300 mm, branco ±20 mm; observado: classes de 20 mm, branco ±10 mm).</li>
<li><b>Grade comum de 1°:</b> média dos pixels por célula, apenas continente, ponderação por cos(lat) e
saturação em ±140 mm, porque o observado não distingue valores acima de ±120 mm.</li>
<li><b>Métricas quantitativas:</b> correlação de Pearson (padrão espacial), ACC não centrado, RMSE, MAE e
viés (previsto − observado).</li>
<li><b>Métricas qualitativas:</b> 3 categorias com limiar de ±20 mm (abaixo, normal, acima): % de acerto,
Heidke Skill Score (0 = acaso, 1 = perfeito) e acerto de sinal.</li>
<li><b>Ranking:</b> média das posições em corr, ACC, RMSE e |viés| (quantitativo) e em HSS, acerto
categórico e acerto de sinal (qualitativo); o geral é a média dos dois.</li></ul>
<h3>Cuidados de interpretação</h3><ul>
<li>Os valores vêm de classes de cor, então a precisão é da ordem da largura da classe.</li>
<li>O MERGE é ruidoso nos Andes e na Colômbia, o que reduz a correlação na América do Sul; o recorte
Brasil é mais confiável.</li>
<li>O MERGE também tem "buracos" secos causados por estações com dado errado (análise MSWEP × MERGE,
set–out/2026), sobretudo no Sul, em SP e no Centro-Oeste, que podem penalizar modelos que acertaram.</li>
<li>Regiões pequenas (Sul, MATOPIBA) têm poucas células, e uma região em estação seca (Nordeste no
inverno) fica quase toda na categoria normal, com HSS próximo de zero.</li></ul>""")

    doc = (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>Validação {nome}</title>"
           f"<style>{CSS}</style></head><body>" + "\n".join(p) + "</body></html>")
    html_arq = os.path.join(rel_dir, f"relatorio_{nome}.html")
    with open(html_arq, "w") as f:
        f.write(doc)
    pdf = os.path.abspath(os.path.join(base, f"Relatorio_Validacao_{nome}.pdf"))
    subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--allow-file-access-from-files", f"--print-to-pdf={pdf}", html_arq],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"-> {pdf}\n   (HTML: {html_arq})")


if __name__ == "__main__":
    main()
