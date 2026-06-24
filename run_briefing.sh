#!/usr/bin/env bash
# run_briefing.sh — cron에서 호출하는 래퍼
set -euo pipefail

# ── 사용자 환경에 맞게 수정 ──
PUSH_TO_GIT="true"                    # git 자동 커밋/푸시 여부

# API 키·모델은 현재 폴더의 .env 에서 daily_briefing.py 가 자동으로 읽습니다.
# (이 셸 스크립트에서 키를 export 할 필요가 없습니다)


# 결과를 git 저장소 안에 날짜별 파일로 생성 (날짜별 기록 보관)
BRIEFING_FILE="daily_briefing_$(date '+%Y%m%d').md"
export BRIEFING_OUTPUT="./${BRIEFING_FILE}"

LOG="./briefing.log"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG"
}

log "===== 시작 ====="

log "[0/4] git pull --rebase 중..."
git pull --rebase >> "$LOG" 2>&1
log "[0/4] git pull --rebase 완료"

log "[1/4] kospi_screener.py 실행 중..."
python3 kospi_screener.py --exclude-etf  >> "$LOG" 2>&1
log "[1/4] kospi_screener.py 완료"

log "[2/4] stock_prices.py 실행 중..."
python3 stock_prices.py >> "$LOG" 2>&1
log "[2/4] stock_prices.py 완료"

log "[3/4] daily_briefing.py 실행 중..."
python3 daily_briefing.py >> "$LOG" 2>&1
log "[3/4] daily_briefing.py 완료"

if [ "$PUSH_TO_GIT" = "true" ]; then
  log "[4/4] git commit/push 중..."
  git add "$BRIEFING_FILE" kospi_screener.csv stock_prices_result.csv stock_prices_result.md
  git commit -m "chore: 데일리 브리핑 자동 업데이트 $(date '+%F %T')" >> "$LOG" 2>&1 || echo "변경 없음" >> "$LOG"
  git push >> "$LOG" 2>&1 || echo "[warn] git push 실패" >> "$LOG"
  log "[4/4] git commit/push 완료"
fi

log "===== 종료 ====="
