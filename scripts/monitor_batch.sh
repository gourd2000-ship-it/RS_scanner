#!/bin/bash

# RS Scanner 배치 작업 모니터링 스크립트
# 사용법: bash scripts/monitor_batch.sh

set -e

# 프로젝트 루트 디렉토리
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# 최신 로그 파일 찾기
LATEST_LOG=$(ls -t logs/batch_*.log 2>/dev/null | head -1)

if [ -z "$LATEST_LOG" ]; then
    echo "No batch log files found in logs/ directory"
    exit 1
fi

echo "===== Monitoring RS Scanner Batch ====="
echo "Log file: $LATEST_LOG"
echo "Press Ctrl+C to stop monitoring"
echo ""

# 로그 파일 모니터링 (진행 상황만 필터링)
tail -f "$LATEST_LOG" | grep -E "(Progress|Completed step|Starting step|starting|finished|created|ERROR|WARNING)" --line-buffered || tail -f "$LATEST_LOG"
