#!/usr/bin/env bash
# Rotina do crontab: baixa a rodada do mês atual dos modelos já publicados no CDS
# e, quando todos estiverem prontos, gera o MULTIMODELO e o PDF comparativo (uma única vez).
#
# Pode rodar várias vezes por dia na janela de publicação (meio do mês):
#   - modelos com mapas já gerados são pulados (--pendentes);
#   - modelos ainda não publicados são pulados (consulta ao catálogo do CDS);
#   - uma trava (flock) impede duas execuções simultâneas.
#
# Avisos por e-mail (via mutt/msmtp, só se COPERNICUS_EMAIL_TO estiver definida), um de cada por rodada:
#   - rodada pronta: modelos usados e o PDF anexado (se couber no limite do Gmail);
#   - falha ao gerar o MULTIMODELO ou o PDF;
#   - no último dia da janela (DIA_LIMITE), se ainda faltarem modelos.
#
# Variáveis opcionais:
#   PYTHON               interpretador com as dependências (padrão: python3 do PATH)
#   COPERNICUS_EMAIL_TO  destinatários separados por vírgula (vazio = sem e-mail)
#   DIA_LIMITE           dia do mês em que avisa sobre modelos pendentes (padrão: 25)
#
# Exemplo de crontab (3x ao dia, dias 5 a 25):
#   0 8,14,20 5-25 * * PYTHON=$HOME/miniconda3/envs/copernicus/bin/python COPERNICUS_EMAIL_TO=voce@x.com /caminho/copernicus/cron_copernicus.sh

set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
EMAIL_TO="${COPERNICUS_EMAIL_TO:-}"
DIA_LIMITE="${DIA_LIMITE:-25}"
MAX_ANEXO_MB=18   # o Gmail aceita 25 MB por mensagem; o anexo cresce ~37% em base64
cd "$DIR" || exit 1
mkdir -p logs

RODADA="$(date +%Y%m)"
LOG="logs/automacao_${RODADA}.log"
PDF="Comparativo_Modelos_${RODADA}.pdf"
HOST="$(hostname)"

exec 9>"logs/.cron.lock"
if ! flock -n 9; then
    echo "$(date '+%F %T') execução anterior ainda em andamento; saindo." >> "$LOG"
    exit 0
fi

# envia_email <assunto> <arquivo com o corpo> [anexo]; tenta 3 vezes
envia_email() {
    local assunto="$1" corpo="$2" anexo="${3:-}" t
    [ -n "$EMAIL_TO" ] || { echo "[i] COPERNICUS_EMAIL_TO vazio; e-mail não enviado: $assunto"; return 0; }
    local -a dest
    IFS=',' read -r -a dest <<< "$EMAIL_TO"
    for t in 1 2 3; do
        if [ -n "$anexo" ]; then
            mutt -e 'set send_charset=utf-8' -s "$assunto" -a "$anexo" -- "${dest[@]}" < "$corpo"
        else
            mutt -e 'set send_charset=utf-8' -s "$assunto" -- "${dest[@]}" < "$corpo"
        fi && { echo "[i] E-mail enviado: $assunto"; return 0; }
        echo "[-] mutt falhou (tentativa $t/3)"
        sleep $((20 * t))
    done
    return 1
}

# Envia uma vez por rodada: a marca logs/.email_<tipo>_<rodada> evita repetir a cada execução.
envia_uma_vez() {
    local tipo="$1"; shift
    local marca="logs/.email_${tipo}_${RODADA}"
    [ -f "$marca" ] && return 0
    envia_email "$@" && touch "$marca"
}

CORPO="$(mktemp)"
trap 'rm -f "$CORPO"' EXIT

{
    echo "===== $(date '+%F %T') ====="
    "$PYTHON" -u automacao_copernicus.py --all --pendentes
    rc=$?
    if [ "$rc" -eq 0 ] && [ ! -f "$PDF" ]; then
        echo "[i] Todos os modelos prontos; gerando o MULTIMODELO e o PDF comparativo de ${RODADA}."
        mm_ok=1
        "$PYTHON" gera_multimodelo.py --rodada "$RODADA" \
            || { mm_ok=0; echo "[-] Falha no MULTIMODELO; o PDF sai só com os modelos."; }
        "$PYTHON" gera_pdf_comparativo.py --rodada "$RODADA"
        pdf_rc=$?

        if [ "$pdf_rc" -eq 0 ] && [ -f "$PDF" ]; then
            mb=$(( ($(stat -c %s "$PDF") + 524288) / 1048576 ))
            json="saida_mapas/MULTIMODELO_${RODADA}/multimodelo.json"
            {
                echo "Previsões sazonais Copernicus — rodada ${RODADA} pronta em $(date '+%d/%m/%Y %H:%M') (${HOST})."
                echo
                echo "Mapas: ${DIR}/saida_mapas/<MODELO>_${RODADA}/"
                echo "PDF comparativo: ${DIR}/${PDF} (${mb} MB)"
                if [ "$mm_ok" -eq 1 ] && [ -f "$json" ]; then
                    "$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); print("MULTIMODELO: %d modelos (%s); pontilhado onde menos de %d concordam com o sinal." % (len(d["modelos"]), ", ".join(d["modelos"]), d["limiar_concordancia"]))' "$json"
                else
                    echo "ATENÇÃO: o MULTIMODELO falhou; o PDF saiu só com os modelos individuais (ver o log)."
                fi
                echo
                if [ "$mb" -le "$MAX_ANEXO_MB" ]; then
                    echo "O PDF vai anexado."
                else
                    echo "O PDF tem ${mb} MB e passa do limite do e-mail; não foi anexado. Para baixar:"
                    echo "  rsync -av ${HOST}:${DIR}/${PDF} ."
                fi
                echo
                echo "Para trazer os mapas para o notebook (validação):"
                echo "  rsync -av --exclude 'Verificação/' ${HOST}:${DIR}/saida_mapas/ saida_mapas/"
                echo
                echo "Log: ${DIR}/${LOG}"
            } > "$CORPO"
            anexo=""
            [ "$mb" -le "$MAX_ANEXO_MB" ] && anexo="$PDF"
            # se o envio com anexo falhar (ex.: tamanho), tenta de novo sem ele
            envia_uma_vez pronta "[Copernicus] Rodada ${RODADA} pronta: mapas e PDF comparativo" "$CORPO" "$anexo" \
                || { [ -n "$anexo" ] && envia_uma_vez pronta "[Copernicus] Rodada ${RODADA} pronta (PDF não anexado)" "$CORPO"; }
        else
            {
                echo "Falha ao gerar o PDF comparativo da rodada ${RODADA} em $(date '+%d/%m/%Y %H:%M') (${HOST})."
                echo "O cron tenta de novo na próxima execução. Final do log (${DIR}/${LOG}):"
                echo
                tail -n 40 "$LOG"
            } > "$CORPO"
            envia_uma_vez falha "[Copernicus][FALHA] PDF comparativo ${RODADA}" "$CORPO"
        fi
    elif [ "$rc" -ne 0 ] && [ "$(date +%-d)" -ge "$DIA_LIMITE" ] && [ "$(date +%-H)" -ge 20 ]; then
        {
            echo "Rodada ${RODADA}: chegou o dia ${DIA_LIMITE} e ainda há modelos pendentes (${HOST})."
            echo "O cron deixa de rodar depois desse dia; o PDF comparativo não foi gerado."
            echo "Para gerar com os modelos disponíveis:"
            echo "  cd ${DIR}"
            echo "  ${PYTHON} gera_multimodelo.py --rodada ${RODADA}"
            echo "  ${PYTHON} gera_pdf_comparativo.py --rodada ${RODADA}"
            echo
            echo "Situação na última execução:"
            echo
            sed -n '/Resumo da rodada/,$p' "$LOG" | tail -n 15
        } > "$CORPO"
        envia_uma_vez pendente "[Copernicus] Rodada ${RODADA} incompleta no dia ${DIA_LIMITE}" "$CORPO"
    fi
} >> "$LOG" 2>&1
