#!/bin/bash
# RS Scanner 백엔드 시작 스크립트

set -e

cd "$(dirname "$0")"

echo "🚀 RS Scanner 백엔드 시작 중..."
echo ""

# 가상 환경 활성화
if [ -d ".venv" ]; then
    echo "✓ 가상 환경 활성화"
    source .venv/bin/activate
else
    echo "❌ 가상 환경을 찾을 수 없습니다. 먼저 'python -m venv .venv'를 실행하세요."
    exit 1
fi

# 환경 변수 설정
export APP_ENV=development

echo "✓ 환경 변수 설정 완료"
echo ""

# 기존 프로세스 확인 및 종료
echo "🔍 포트 8000 확인 중..."
EXISTING_PID=$(lsof -ti :8000 || true)
if [ -n "$EXISTING_PID" ]; then
    echo "⚠️  포트 8000이 이미 사용중입니다 (PID: $EXISTING_PID)"
    echo "   기존 프로세스를 종료합니다..."
    kill $EXISTING_PID 2>/dev/null || true
    sleep 2
    echo "✓ 기존 프로세스 종료 완료"
else
    echo "✓ 포트 8000 사용 가능"
fi
echo ""

# PostgreSQL 연결 확인
echo "📊 데이터베이스 연결 확인 중..."
if pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
    echo "✓ PostgreSQL 연결 성공"
else
    echo "⚠️  PostgreSQL이 실행되지 않았습니다."
    echo "   다음 명령으로 시작하세요: docker-compose up -d"
    echo ""
    echo "   또는 메모리 DB 모드로 계속합니다..."
    export USE_MEMORY_DB=true
fi

echo ""
echo "========================================="
echo "  백엔드 API 서버 시작"
echo "  URL: http://localhost:8000"
echo "  Docs: http://localhost:8000/docs"
echo "========================================="
echo ""
echo "Ctrl+C로 종료"
echo ""

# API 서버 시작
uvicorn app.main_api:app --reload --host 0.0.0.0 --port 8000
