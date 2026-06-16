# RS Scanner 테스트 가이드

## 빠른 시작

### 1단계: 백엔드 API 서버 시작

터미널 1에서 실행:

```bash
cd /home/autobot/dev/rs_scanner

# 가상 환경 활성화
source .venv/bin/activate

# API 서버 시작 (개발 모드)
export APP_ENV=development
uvicorn app.main_api:app --reload --host 0.0.0.0 --port 8000
```

서버가 시작되면 다음 메시지가 표시됩니다:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 2단계: API 동작 확인

터미널 2에서 실행:

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Expected output:
# {"status":"healthy","db_connected":true,...}

# Crawl stats (운영 페이지 API)
curl http://localhost:8000/api/v1/crawl/stats

# Rankings API
curl "http://localhost:8000/api/v1/rankings/rs?market=KOSPI&page=1&size=10"
```

### 3단계: 프론트엔드 개발 서버 시작

터미널 3에서 실행:

```bash
cd /home/autobot/dev/rs_scanner/frontend

# 의존성 설치 (최초 1회만)
npm install

# 환경 변수 설정
export NEXT_PUBLIC_API_URL=http://localhost:8000

# 개발 서버 시작
npm run dev
```

서버가 시작되면:
```
  ▲ Next.js 15.x.x
  - Local:        http://localhost:3000
  - Network:      http://0.0.0.0:3000

 ✓ Starting...
 ✓ Ready in 2.3s
```

### 4단계: 브라우저에서 접속

1. **메인 대시보드 (RS 랭킹)**
   - URL: http://localhost:3000
   - KOSPI/KOSDAQ 종목 RS 랭킹 테이블
   - 정렬, 필터링, 페이지네이션

2. **종목 상세 페이지**
   - URL: http://localhost:3000/stocks/005930 (삼성전자)
   - 가격 캔들스틱 차트
   - RS Rating 추이 차트

3. **운영 모니터링 페이지** ⭐ NEW
   - URL: http://localhost:3000/operations
   - 크롤링 작업 통계
   - 작업 이력 테이블
   - 실패 목록

---

## 데이터가 없는 경우

백엔드를 처음 실행하면 DB가 비어있습니다. 테스트 데이터를 생성하려면:

### 옵션 1: 배치 실행 (실제 네이버에서 크롤링)

```bash
cd /home/autobot/dev/rs_scanner
source .venv/bin/activate

# 전체 배치 실행 (20-30분 소요)
python -m app.main_batch
```

배치 실행 순서:
1. sync_symbols - 종목 목록 수집 (KOSPI ~900개, KOSDAQ ~1500개)
2. sync_benchmarks - 벤치마크 수집 (KOSPI, KOSDAQ 지수)
3. sync_daily_prices - 가격 데이터 수집 (90일치)
4. calculate_rs - RS Rating 계산

### 옵션 2: 통합 테스트 환경 사용

메모리 DB + 페이크 데이터로 빠르게 테스트:

```bash
cd /home/autobot/dev/rs_scanner

# 통합 테스트 실행
pytest tests/integration/api/ -v

# 특정 테스트만 실행
pytest tests/integration/api/test_rankings_api.py -v
```

---

## 운영 페이지 체크리스트

운영 페이지(`/operations`)에서 확인할 항목:

- [ ] Stats 카드 3개 표시
  - [ ] 최근 작업 카드 (started_at, duration, success_rate)
  - [ ] 전체 통계 (total/running/completed/failed)
  - [ ] 최근 실패 요약

- [ ] 작업 이력 테이블
  - [ ] Status 필터 버튼 (전체/실행중/완료/실패)
  - [ ] 테이블 정렬 가능
  - [ ] 페이지네이션 작동

- [ ] 실패 목록 테이블
  - [ ] 에러 메시지 truncate
  - [ ] 행 클릭 시 상세 정보 확장
  - [ ] 페이지네이션 작동

- [ ] 자동/수동 새로고침
  - [ ] 10초마다 자동 갱신
  - [ ] 새로고침 버튼 작동
  - [ ] 마지막 갱신 시각 표시

---

## 트러블슈팅

### CORS 에러

프론트엔드에서 API 호출 시 CORS 에러가 발생하면:

```python
# app/main_api.py에 CORS 미들웨어 추가 확인
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 포트 충돌

포트가 이미 사용중이면:

```bash
# 8000번 포트 사용 프로세스 확인
lsof -i :8000

# 3000번 포트 사용 프로세스 확인
lsof -i :3000

# 다른 포트로 실행
uvicorn app.main_api:app --port 8001
npm run dev -- -p 3001
```

### 데이터베이스 연결 오류

PostgreSQL이 필요한 경우:

```bash
# Docker로 PostgreSQL 시작
docker-compose up -d

# 또는 환경변수로 메모리 모드 사용
export APP_ENV=development
export USE_MEMORY_DB=true
```

---

## 성능 확인

### API 응답 시간 측정

```bash
# Health check
time curl http://localhost:8000/api/v1/health

# Rankings (캐싱 적용, 1시간 TTL)
time curl "http://localhost:8000/api/v1/rankings/rs?market=KOSPI&page=1&size=50"

# Crawl stats (캐싱 적용, 5분 TTL)
time curl http://localhost:8000/api/v1/crawl/stats
```

예상 응답 시간:
- Health: < 10ms
- Rankings (캐싱): 15-20ms
- Crawl stats (캐싱): 10-15ms

### 프론트엔드 개발자 도구

브라우저 개발자 도구(F12) 확인 항목:
- **Network 탭**: API 요청/응답 확인
- **Console 탭**: JavaScript 에러 확인
- **React DevTools**: 컴포넌트 상태 확인

---

## 다음 단계

프로덕션 배포를 원한다면:

```bash
# Docker Compose로 전체 스택 실행
docker-compose up -d

# 접속: http://localhost:3000
```

자세한 배포 가이드는 `docs/deployment.md` 참조.
