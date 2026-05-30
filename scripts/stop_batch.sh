#!/bin/bash

# RS Scanner 배치 작업 중지 스크립트
# 사용법: bash scripts/stop_batch.sh

set -e

# 프로젝트 루트 디렉토리
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PID_FILE="logs/batch.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found at $PID_FILE"
    echo "Batch may not be running or was started manually."
    exit 1
fi

PID=$(cat "$PID_FILE")

echo "===== Stopping RS Scanner Batch ====="
echo "PID: $PID"

# 프로세스 존재 확인
if ps -p "$PID" > /dev/null 2>&1; then
    echo "Sending SIGTERM to process $PID..."
    kill "$PID"

    # 최대 10초 대기
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "Process stopped successfully."
            rm -f "$PID_FILE"
            exit 0
        fi
        echo "Waiting for process to stop... ($i/10)"
        sleep 1
    done

    # 여전히 실행 중이면 강제 종료
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Process did not stop gracefully. Sending SIGKILL..."
        kill -9 "$PID"
        echo "Process forcefully killed."
    fi

    rm -f "$PID_FILE"
else
    echo "Process $PID is not running."
    rm -f "$PID_FILE"
fi

echo "Batch stopped."
