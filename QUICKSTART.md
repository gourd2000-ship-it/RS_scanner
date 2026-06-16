# 🚀 빠른 시작 가이드

## 1분 안에 시작하기

### Step 1: 백엔드 시작 (터미널 1)

```bash
cd /home/autobot/dev/rs_scanner
./start_backend.sh
```

백엔드가 실행되면 다음이 표시됩니다:
```
✓ 가상 환경 활성화
✓ 환경 변수 설정 완료
✓ PostgreSQL 연결 성공

========================================
  백엔드 API 서버 시작
  URL: http://localhost:8000
  Docs: http://localhost:8000/docs
========================================

INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

### Step 2: 프론트엔드 시작 (터미널 2)

```bash
cd /home/autobot/dev/rs_scanner
./start_frontend.sh
```

프론트엔드가 실행되면:
```
✓ 환경 변수 설정 완료
✓ 백엔드 API 연결 성공

========================================
  프론트엔드 개발 서버 시작
  URL: http://localhost:3000
========================================

▲ Next.js 15.x.x
- Local:   http://localhost:3000
✓ Ready in 2.3s
```

### Step 3: 브라우저에서 접속

**운영 모니터링 페이지 (새로 만든 기능!)**
- http://localhost:3000/operations

**기타 페이지**
- http://localhost:3000 - RS 랭킹 대시보드
- http://localhost:3000/stocks/005930 - 삼성전자 상세

---

## 운영 페이지에서 확인할 것

### 1. 통계 카드 3개
- **최근 작업**: 마지막 크롤링 작업 정보
- **전체 통계**: 총 작업 수, 실행중/완료/실패 개수
- **최근 실패**: 실패 횟수 요약

### 2. 작업 이력 테이블
- Status 필터 (전체/실행중/완료/실패)
- 시작 시각, 실행 시간, 성공률 표시
- 페이지네이션

### 3. 실패 목록
- 실패한 종목 코드, 에러 클래스
- 행 클릭 시 상세 정보 확장
- URL, 에러 메시지 전체 보기

### 4. 자동 새로고침
- 10초마다 자동 갱신
- 수동 새로고침 버튼
- 마지막 갱신 시각 표시 ("2분 전")

---

## 데이터가 없다면?

백엔드를 처음 실행하면 DB가 비어있습니다.

### 옵션 1: 테스트 데이터 생성

```bash
# 터미널 3에서
cd /home/autobot/dev/rs_scanner
source .venv/bin/activate

# 배치 실행 (20-30분 소요)
python -m app.main_batch
```

### 옵션 2: API 테스트만 확인

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Crawl stats
curl http://localhost:8000/api/v1/crawl/stats

# Expected:
# {"total_jobs":0,"running_jobs":0,"completed_jobs":0,...}
```

---

## PostgreSQL이 없다면?

PostgreSQL 없이도 테스트할 수 있습니다:

```bash
# Docker로 간단하게 시작
docker-compose up -d

# 또는 메모리 DB 모드로 실행
export USE_MEMORY_DB=true
./start_backend.sh
```

---

## 문제 해결

### CORS 에러
프론트엔드에서 API 호출 시 CORS 에러가 나면:
- 백엔드가 http://localhost:8000에서 실행중인지 확인
- `app/main_api.py`에 CORS 미들웨어가 설정되어 있는지 확인

### 포트 충돌
```bash
# 포트 사용 확인
lsof -i :8000  # 백엔드
lsof -i :3000  # 프론트엔드

# 프로세스 종료
kill -9 <PID>
```

### npm install 오류
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

---

## 더 자세한 정보

- 전체 테스트 가이드: `TEST_GUIDE.md`
- 배포 가이드: `docs/deployment.md`
- 아키텍처 문서: `docs/rs_scanner_architecture.md`
- API 문서: http://localhost:8000/docs (백엔드 실행 후)

---

## 확인 완료!

운영 페이지가 정상 작동하면 Phase 5 완료입니다! 🎉

다음은:
- Phase 6: 운영 안정화 (CORS, Docker, 알림)
- 프로덕션 배포

질문이 있으면 언제든지 물어보세요!
