#!/bin/bash
# crontab 설정 스크립트
# RS Scanner 일일 배치를 cron에 등록합니다

set -euo pipefail

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
umask 077
mkdir -p "$PROJECT_ROOT/logs"
CRON_BACKUP="$PROJECT_ROOT/logs/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"
crontab -l > "$CRON_BACKUP" 2>/dev/null || true

# cron uses the host timezone; do not assume CRON_TZ support on Debian cron.
case "$(date +%Z)" in
    UTC) PRIMARY_HOUR=7 ;;
    KST) PRIMARY_HOUR=16 ;;
    *) echo "지원하지 않는 호스트 시간대입니다. UTC 또는 KST에서 설정하세요." >&2; exit 1 ;;
esac

# 새로운 cron 작업 추가
echo "cron 작업 추가 중..."
echo ""
echo "다음 작업이 추가됩니다:"
echo "  - 평일(월~금) 한국시간 오후 4시 30분 (KST 16:30 = UTC 07:30)에 배치 실행"
echo "  - 휴장일 건너뛰기, 원본 갱신 → 가격 검증 → RS·EMA 4종·MA50·ATR14"
echo ""

# 기존 RS Scanner cron 작업 제거 후 추가
CRON_CANDIDATE="$(mktemp "$PROJECT_ROOT/logs/.crontab_candidate.XXXXXX")"
{ grep -v -F -e "$BATCH_SCRIPT" -e "# RS Scanner Daily Batch" "$CRON_BACKUP" || true
  echo "# RS Scanner Daily Batch - KST 16:30; closed sessions only"
  echo "30 $PRIMARY_HOUR * * 1-5 $BATCH_SCRIPT"
} > "$CRON_CANDIDATE"
if ! crontab "$CRON_CANDIDATE"; then
    echo "cron 등록 권한이 없습니다. 호스트 운영자가 이 파일을 등록해야 합니다: $CRON_CANDIDATE" >&2
    exit 1
fi
rm -f "$CRON_CANDIDATE"

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
