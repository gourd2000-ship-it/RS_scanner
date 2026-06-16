#!/bin/bash
# crontab 설정 스크립트
# RS Scanner 일일 배치를 cron에 등록합니다

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BATCH_SCRIPT="$PROJECT_ROOT/scripts/run_daily_batch.sh"

echo "RS Scanner crontab 설정"
echo "========================"
echo "프로젝트 루트: $PROJECT_ROOT"
echo "배치 스크립트: $BATCH_SCRIPT"
echo ""

# 현재 crontab 백업
echo "현재 crontab 백업 중..."
crontab -l > /tmp/crontab_backup_$(date +%Y%m%d_%H%M%S).txt 2>/dev/null || true

# 새로운 cron 작업 추가
echo "cron 작업 추가 중..."
echo ""
echo "다음 작업이 추가됩니다:"
echo "  - 평일(월~금) 오후 5시 (17:00)에 배치 실행"
echo ""

# 기존 RS Scanner cron 작업 제거 후 추가
(crontab -l 2>/dev/null | grep -v "run_daily_batch.sh" || true; \
 echo "# RS Scanner Daily Batch - 평일 오후 5시 실행 (정규장 마감 후)"; \
 echo "0 17 * * 1-5 $BATCH_SCRIPT") | crontab -

echo "✓ crontab 설정 완료!"
echo ""
echo "현재 crontab 확인:"
crontab -l | grep -A 2 "RS Scanner"
echo ""
echo "수동 실행 테스트:"
echo "  $BATCH_SCRIPT"
echo ""
echo "로그 확인:"
echo "  tail -f $PROJECT_ROOT/logs/batch_*.log"
