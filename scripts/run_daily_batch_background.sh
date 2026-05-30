#!/bin/bash

# RS Scanner 배치 작업 백그라운드 실행 스크립트
# 사용법: bash scripts/run_daily_batch_background.sh

set -e

# 프로젝트 루트 디렉토리
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# 로그 디렉토리 생성
mkdir -p logs

# 로그 파일 경로
LOG_FILE="logs/batch_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="logs/batch.pid"

echo "===== Starting RS Scanner Batch (Background) ====="
echo "Log file: $LOG_FILE"
echo "PID will be saved to: $PID_FILE"

# 가상환경 활성화 (존재하는 경우)
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 백그라운드 실행
nohup python -m app.main_batch > "$LOG_FILE" 2>&1 &

# PID 저장
echo $! > "$PID_FILE"

echo "Batch started with PID: $(cat $PID_FILE)"
echo "Monitor progress: tail -f $LOG_FILE"
echo ""
echo "To stop the batch: bash scripts/stop_batch.sh"
