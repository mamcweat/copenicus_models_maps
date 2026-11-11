#!/usr/bin/env bash
# Rotina do crontab: baixa a rodada do mês atual dos modelos já publicados no CDS
# e, quando todos estiverem prontos, gera o MULTIMODELO e o PDF comparativo (uma única vez).
#
# Pode rodar várias vezes por dia na janela de publicação (meio do mês):
#   - modelos com mapas já gerados são pulados (--pendentes);
#   - modelos ainda não publicados são pulados (consulta ao catálogo do CDS);
#   - uma trava (flock) impede duas execuções simultâneas.
#
# Variáveis opcionais:
#   PYTHON  interpretador com as dependências (padrão: python3 do PATH)
#
# Exemplo de crontab (3x ao dia, dias 5 a 25):
#   0 8,14,20 5-25 * * PYTHON=$HOME/miniconda3/envs/copernicus/bin/python /caminho/copernicus/cron_copernicus.sh

set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
cd "$DIR" || exit 1
mkdir -p logs

RODADA="$(date +%Y%m)"
LOG="logs/automacao_${RODADA}.log"

exec 9>"logs/.cron.lock"
if ! flock -n 9; then
    echo "$(date '+%F %T') execução anterior ainda em andamento; saindo." >> "$LOG"
    exit 0
fi

{
    echo "===== $(date '+%F %T') ====="
    "$PYTHON" -u automacao_copernicus.py --all --pendentes
    rc=$?
    if [ "$rc" -eq 0 ] && [ ! -f "Comparativo_Modelos_${RODADA}.pdf" ]; then
        echo "[i] Todos os modelos prontos; gerando o MULTIMODELO e o PDF comparativo de ${RODADA}."
        "$PYTHON" gera_multimodelo.py --rodada "$RODADA" \
            || echo "[-] Falha no MULTIMODELO; o PDF sai só com os modelos."
        "$PYTHON" gera_pdf_comparativo.py --rodada "$RODADA"
    fi
} >> "$LOG" 2>&1
