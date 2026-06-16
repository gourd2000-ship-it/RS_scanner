#!/bin/bash
# RS Scanner 프론트엔드 시작 스크립트

set -e

cd "$(dirname "$0")/frontend"

echo "🎨 RS Scanner 프론트엔드 시작 중..."
echo ""

# node_modules 확인
if [ ! -d "node_modules" ]; then
    echo "📦 의존성 설치 중... (최초 1회, 2-3분 소요)"
    npm install
    echo "✓ 의존성 설치 완료"
    echo ""
fi

# 환경 변수 설정
export NEXT_PUBLIC_API_URL=http://localhost:8000

echo "✓ 환경 변수 설정 완료"
echo ""

# 기존 프로세스 확인 및 종료
echo "🔍 포트 3000 확인 중..."
EXISTING_PID=$(lsof -ti :3000 || true)
if [ -n "$EXISTING_PID" ]; then
    echo "⚠️  포트 3000이 이미 사용중입니다 (PID: $EXISTING_PID)"
    echo "   기존 프로세스를 종료합니다..."
    kill $EXISTING_PID 2>/dev/null || true
    sleep 2
    echo "✓ 기존 프로세스 종료 완료"
else
    echo "✓ 포트 3000 사용 가능"
fi
echo ""

# 백엔드 연결 확인
echo "🔌 백엔드 API 연결 확인 중..."
if curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    echo "✓ 백엔드 API 연결 성공"
else
    echo "⚠️  백엔드 API가 실행되지 않았습니다."
    echo "   먼저 다른 터미널에서 './start_backend.sh'를 실행하세요."
    echo ""
    read -p "계속하시겠습니까? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "========================================="
echo "  프론트엔드 개발 서버 시작"
echo "  URL: http://localhost:3000"
echo ""
echo "  페이지:"
echo "  - RS 랭킹: http://localhost:3000"
echo "  - 종목 상세: http://localhost:3000/stocks/005930"
echo "  - 운영 모니터링: http://localhost:3000/operations"
echo "========================================="
echo ""
echo "Ctrl+C로 종료"
echo ""

# 개발 서버 시작
npm run dev
