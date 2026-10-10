#!/bin/bash
# RS Scanner 일일 배치 실행 스크립트
# crontab에 등록하여 매일 자동 실행

set -euo pipefail

# 스크립트 디렉토리로 이동
cd "$(dirname "$0")/.."

# 가상 환경 활성화
source .venv/bin/activate

# Python runner parses .env.production and .env without shell word splitting.

# 로그 디렉토리 생성
mkdir -p logs

# The runner holds both logs/daily_batch.lock and a PostgreSQL advisory lock
# across source collection, price validation, RS and all indicator steps.

# 배치 실행 (로그 파일에 기록)
LOG_FILE="logs/batch_$(date +%Y%m%d_%H%M%S).log"

echo "===== RS Scanner Daily Batch Started at $(date) =====" | tee -a "$LOG_FILE"

set +e
python scripts/run_daily_pipeline.py --apply --scheduled 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}
set -e

if [ $EXIT_CODE -eq 0 ]; then
    echo "===== Batch Completed Successfully at $(date) =====" | tee -a "$LOG_FILE"
else
    echo "===== Batch Failed with exit code $EXIT_CODE at $(date) =====" | tee -a "$LOG_FILE"
fi

# 오래된 로그 파일 삭제 (30일 이상)
find logs -name "batch_*.log" -mtime +30 -delete

exit $EXIT_CODE
