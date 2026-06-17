#!/usr/bin/env bash
# run_briefing.sh — cron에서 호출하는 래퍼
set -euo pipefail

# ── 사용자 환경에 맞게 수정 ──
PUSH_TO_GIT="true"                    # git 자동 커밋/푸시 여부

# API 키·모델은 현재 폴더의 .env 에서 daily_briefing.py 가 자동으로 읽습니다.
# (이 셸 스크립트에서 키를 export 할 필요가 없습니다)


# 결과를 git 저장소 안에 직접 생성
export BRIEFING_OUTPUT="./daily_briefing.md"

LOG="./briefing.log"
echo "===== $(date '+%F %T') 시작 ====="
echo "===== $(date '+%F %T') 시작 =====" >> "$LOG"
git pull --rebase >> "$LOG" 2>&1
python3 kospi_screener.py --exclude-etf --quiet >> "$LOG" 2>&1
python3 daily_briefing.py >> "$LOG" 2>&1

if [ "$PUSH_TO_GIT" = "true" ]; then
  git add daily_briefing.md
  git commit -m "chore: 데일리 브리핑 자동 업데이트 $(date '+%F %T')" >> "$LOG" 2>&1 || echo "변경 없음" >> "$LOG"
  git push >> "$LOG" 2>&1 || echo "[warn] git push 실패" >> "$LOG"
fi

echo "===== $(date '+%F %T') 종료 ====="
echo "===== $(date '+%F %T') 종료 =====" >> "$LOG"
