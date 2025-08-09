#!/usr/bin/env bash
set -euo pipefail

# === 설정 ===
APP_DIR="${APP_DIR:-$HOME/crypto-bot}"     # 프로젝트 루트
TARGETS=("bot" "requirements.txt")         # 공유할 대상 (필요 시 추가)
EXCLUDES=(                                  # tar에서 제외할 항목
  "--exclude=.env"                          # 요청사항: .env 제외
  "--exclude=.venv"                         # 불필요/대용량
  "--exclude=.git"                          # 불필요/민감 가능
  "--exclude=__pycache__"
  "--exclude=*.pyc"
)
SPLIT_SIZE="${SPLIT_SIZE:-5000}"           # 바이트 단위 분할 크기(기본 5KB)

# === 출력 디렉터리 ===
STAMP="$(date +%Y%m%d-%H%M%S)"
OUTDIR="/tmp/share_bot_${STAMP}"
mkdir -p "$OUTDIR"

echo "[share] app dir      : $APP_DIR"
echo "[share] out dir      : $OUTDIR"
echo "[share] split size   : ${SPLIT_SIZE} bytes"

# === tar.gz 생성 ===
echo "[share] creating tar.gz (exclude .env, .venv, .git, __pycache__, *.pyc)"
pushd "$APP_DIR" >/dev/null
tar -czf "$OUTDIR/bot.tar.gz" "${EXCLUDES[@]}" "${TARGETS[@]}"
popd >/dev/null

# === base64 변환 ===
echo "[share] base64 encoding..."
base64 "$OUTDIR/bot.tar.gz" > "$OUTDIR/bot.b64"

# === 분할 ===
echo "[share] splitting into chunks..."
split -b "$SPLIT_SIZE" "$OUTDIR/bot.b64" "$OUTDIR/bot_part_"

# === 안내 ===
COUNT=$(ls -1 "$OUTDIR"/bot_part_* | wc -l | tr -d ' ')
echo
echo "============================================================"
echo "[DONE] Created $COUNT chunks in: $OUTDIR"
echo
echo "1) 아래 명령으로 조각 목록 확인:"
echo "   ls -1 $OUTDIR/bot_part_*"
echo
echo "2) 각 조각을 순서대로 채팅에 붙여넣기 (코드블록으로!):"
echo "   cat $OUTDIR/bot_part_aa   # → 내용 복사해서"
echo "   # 채팅에 \`\`\` 로 감싸서 붙여넣기"
echo
echo "3) 필요시 분할 크기 조정하려면:"
echo "   SPLIT_SIZE=4000 bash scripts/share_bot_source.sh"
echo
echo "※ 포함 대상: ${TARGETS[*]}"
echo "※ 제외 대상: ${EXCLUDES[*]}"
echo "============================================================"
