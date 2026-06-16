#!/bin/bash
# RS Scanner 일일 배치 실행 스크립트
# crontab에 등록하여 매일 자동 실행

set -e

# 스크립트 디렉토리로 이동
cd "$(dirname "$0")/.."

# 가상 환경 활성화
source .venv/bin/activate

# 환경 변수 로드
export $(grep -v '^#' .env.production | xargs)

# 로그 디렉토리 생성
mkdir -p logs

# 배치 실행 (로그 파일에 기록)
LOG_FILE="logs/batch_$(date +%Y%m%d_%H%M%S).log"

echo "===== RS Scanner Daily Batch Started at $(date) =====" | tee -a "$LOG_FILE"

python -m app.main_batch 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "===== Batch Completed Successfully at $(date) =====" | tee -a "$LOG_FILE"
else
    echo "===== Batch Failed with exit code $EXIT_CODE at $(date) =====" | tee -a "$LOG_FILE"
fi

# 오래된 로그 파일 삭제 (30일 이상)
find logs -name "batch_*.log" -mtime +30 -delete

exit $EXIT_CODE
