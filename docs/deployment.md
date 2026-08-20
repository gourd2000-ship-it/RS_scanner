# RS Scanner 배포 가이드

## 목차
1. [로컬 개발 환경](#로컬-개발-환경)
2. [Docker를 이용한 배포](#docker를-이용한-배포)
3. [프로덕션 배포](#프로덕션-배포)
4. [환경변수 설정](#환경변수-설정)
5. [트러블슈팅](#트러블슈팅)

---

## 로컬 개발 환경

### 1. 사전 요구사항
- Python 3.12+
- PostgreSQL 16+ (또는 Docker)
- Git

### 2. 설치

```bash
# 저장소 클론
git clone https://github.com/yourusername/rs_scanner.git
cd rs_scanner

# 가상 환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 의존성 설치
pip install -e ".[dev]"
```

### 3. 데이터베이스 설정

#### Option A: Docker 사용 (권장)

```bash
# PostgreSQL 컨테이너 시작
docker-compose up -d postgres

# 마이그레이션 실행
alembic upgrade head
```

#### Option B: 로컬 PostgreSQL 사용

```bash
# 데이터베이스 생성
createdb rs_scanner

# .env 파일 생성
cat > .env << EOF
DATABASE_URL=postgresql+psycopg://your_user:your_password@localhost:5432/rs_scanner
APP_ENV=development
NAVER_REQUEST_TIMEOUT=30
EOF

# 마이그레이션 실행
alembic upgrade head
```

### 4. 테스트 데이터 생성

```bash
# 샘플 데이터로 테스트
python scripts/test_with_sample_data.py
```

### 5. API 서버 실행

```bash
# 개발 모드 (자동 리로드)
uvicorn app.main_api:app --reload

# API 문서: http://localhost:8000/docs
```

### 6. 배치 실행

```bash
# 전체 파이프라인 실행
python -m app.main_batch

# Naver universe snapshot과 심볼 동기화만 실행 (가격/RS 미실행)
python -m app.main_batch --symbols-only
```

---

## Docker를 이용한 배포

### 1. Docker Compose로 전체 스택 실행

```bash
# 전체 서비스 시작 (DB + API)
docker-compose up -d

# 로그 확인
docker-compose logs -f api

# 서비스 중지
docker-compose down

# 볼륨까지 삭제 (데이터 초기화)
docker-compose down -v
```

### 2. API만 빌드 및 실행

```bash
# 이미지 빌드
docker build -t rs-scanner-api .

# 컨테이너 실행 (DB가 이미 실행 중이어야 함)
docker run -d \
  --name rs-scanner-api \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql+psycopg://rs_scanner:rs_scanner_dev@host.docker.internal:5432/rs_scanner \
  -e APP_ENV=production \
  rs-scanner-api
```

### 3. 환경변수 오버라이드

```bash
# .env.production 파일 생성
cat > .env.production << EOF
POSTGRES_USER=rs_scanner
POSTGRES_PASSWORD=secure_password_here
POSTGRES_DB=rs_scanner
APP_ENV=production
API_PORT=8000
EOF

# 환경변수 파일 사용
docker-compose --env-file .env.production up -d
```

---

## 프로덕션 배포

### 1. AWS ECS/Fargate 배포

#### 이미지 빌드 및 푸시

```bash
# ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
  docker login --username AWS --password-stdin YOUR_ACCOUNT.dkr.ecr.ap-northeast-2.amazonaws.com

# 이미지 빌드 및 태그
docker build -t rs-scanner-api .
docker tag rs-scanner-api:latest YOUR_ACCOUNT.dkr.ecr.ap-northeast-2.amazonaws.com/rs-scanner-api:latest

# ECR에 푸시
docker push YOUR_ACCOUNT.dkr.ecr.ap-northeast-2.amazonaws.com/rs-scanner-api:latest
```

#### RDS PostgreSQL 설정

1. AWS RDS에서 PostgreSQL 16 인스턴스 생성
2. TimescaleDB 확장 설치 (필요시)
3. 보안 그룹 설정 (ECS 태스크에서 5432 포트 접근 허용)

#### ECS 태스크 정의

```json
{
  "family": "rs-scanner-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "YOUR_ACCOUNT.dkr.ecr.ap-northeast-2.amazonaws.com/rs-scanner-api:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "APP_ENV",
          "value": "production"
        }
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:secretsmanager:ap-northeast-2:YOUR_ACCOUNT:secret:rs-scanner/db-url"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/rs-scanner-api",
          "awslogs-region": "ap-northeast-2",
          "awslogs-stream-prefix": "api"
        }
      }
    }
  ]
}
```

### 2. Kubernetes 배포

#### deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rs-scanner-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rs-scanner-api
  template:
    metadata:
      labels:
        app: rs-scanner-api
    spec:
      containers:
      - name: api
        image: rs-scanner-api:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: rs-scanner-secrets
              key: database-url
        - name: APP_ENV
          value: "production"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: rs-scanner-api-service
spec:
  selector:
    app: rs-scanner-api
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

---

## 환경변수 설정

### 필수 환경변수

| 변수명 | 설명 | 기본값 | 예시 |
|--------|------|--------|------|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | - | `postgresql+psycopg://user:pass@localhost:5432/rs_scanner` |
| `API_DATABASE_URL` | Docker Compose API 컨테이너 전용 PostgreSQL 연결 문자열. 미설정 시 Compose의 `postgres` 서비스 사용 | Compose 내부 기본값 | `postgresql+psycopg://user:pass@postgres:5432/rs_scanner` |
| `APP_ENV` | 실행 환경 | `development` | `development`, `test`, `production` |

### 선택 환경변수

| 변수명 | 설명 | 기본값 |
|--------|------|--------|
| `NAVER_REQUEST_TIMEOUT` | Naver API 타임아웃 (초) | `30` |
| `KRX_AUTH_KEY` | KRX Open API 인증키. `.env` 또는 Secret Manager에서만 주입하고 로그·Git에 남기지 않음 | - |
| `KRX_API_BASE_URL` | KRX 개발 명세서의 운영 API base URL. 인증키·query string은 포함하지 않음 | - |
| `KIWOOM_FALLBACK_ENABLED` | legacy Kiwoom 폴백 설정. 일일 batch에서는 무시되며 항상 `false` 유지 | `false` |
| `KIWOOM_FALLBACK_TRANSPORT` | 전환 전 adapter 경로 (`rest` 또는 legacy `file`) | `rest` |
| `KIWOOM_API_BASE_URL` | Kiwoom REST 운영/모의투자 도메인 | `https://api.kiwoom.com` |
| `KIWOOM_APP_KEY` | Kiwoom 앱키 (Secret 관리 권장) | - |
| `KIWOOM_SECRET_KEY` | Kiwoom 시크릿키 (Secret 관리 필수) | - |
| `KIWOOM_REQUESTS_PER_SECOND` | Kiwoom 요청 속도 제한 | `4` |
| `KIWOOM_MAX_RETRIES` | Kiwoom 일시 오류 재시도 횟수 | `2` |
| `KIWOOM_MAX_CONCURRENCY` | Kiwoom 동시 요청 수 | `1` |
| `KIWOOM_MAX_REQUESTS_PER_BATCH` | 한 배치에서 폴백할 최대 종목 수 | `500` |
| `KIWOOM_FALLBACK_CODES` | canary용 쉼표 구분 종목 allowlist; 비우면 eligible 대상 전체 | `` |
| `KIWOOM_MAX_CONTINUATIONS` | 종목별 연속조회 페이지 상한 | `20` |
| `KIWOOM_ADJUSTED_PRICE_TYPE` | 수정주가 조회 여부 (`1` 권장) | `1` |
| `KIWOOM_TOKEN_REFRESH_MARGIN_SECONDS` | 토큰 만료 전 갱신 여유 시간 | `60` |
| `KIWOOM_BRIDGE_DIR` | 전환 전 legacy Sam 파일 브리지 루트 | `/srv/rs_scanner-share/kiwoom` |
| `KIWOOM_BRIDGE_TIMEOUT` | legacy 브리지 결과 대기 시간 (초) | `120` |
| `KIWOOM_BRIDGE_POLL_INTERVAL` | legacy 브리지 polling 간격 (초) | `1` |
| `KIWOOM_BRIDGE_MAX_ROWS_PER_SYMBOL` | legacy 브리지 요청의 종목별 최대 행 수 | `6000` |
| `KIWOOM_CLI_PROFILE` | Sam이 사용할 선택적 kiwoomcli 프로필 | - |
| `AGENT_API_ENABLED` | Hermes Agent API emergency off flag | `true` |
| `AGENT_SERVICE_TOKENS` | Hermes/Sam scope token; Secret으로 주입하며 저장소에 기록하지 않음 | - |
| `AGENT_ALLOWED_IPS` | Agent API 허용 CIDR 목록; 비어 있으면 제한 없음 | - |
| `AGENT_FRESHNESS_MAX_AGE_HOURS` | Agent 데이터 freshness 허용 시간 | `36` |
| `AGENT_RATE_LIMIT` | Agent API 분당 요청 한도 | `60` |
| `REPAIR_API_ENABLED` | 보존된 legacy Repair API의 첫 번째 활성화 flag | `false` |
| `LEGACY_REPAIR_API_ENABLED` | legacy Repair API의 두 번째 명시적 활성화 flag | `false` |
| `REPAIR_CLAIM_LEASE_SECONDS` | Sam 업무 claim lease 시간 | `300` |
| `REPAIR_MAX_ROWS` | 한 repair 결과의 최대 행 수 | `6000` |
| `REPAIR_RECONCILER_ENABLED` | legacy 설정. 일일 batch에서는 무시 | `false` |
| `REPAIR_APPLY_BATCH_SIZE` | 한 번에 반영할 completed repair 수 | `100` |
| `ANALYSIS_API_ENABLED` | 사용자 요청 기반 Sam 주간 분석 API 활성화 | `false` |
| `POSTGRES_USER` | PostgreSQL 사용자명 | `rs_scanner` |
| `POSTGRES_PASSWORD` | PostgreSQL 비밀번호 | `rs_scanner_dev` |
| `POSTGRES_DB` | 데이터베이스 이름 | `rs_scanner` |
| `POSTGRES_PORT` | PostgreSQL 포트 | `5432` |
| `API_PORT` | API 서버 포트 | `8000` |

### 환경별 설정

#### 개발 (Development)
```bash
DATABASE_URL=postgresql+psycopg://rs_scanner:rs_scanner_dev@localhost:5432/rs_scanner
APP_ENV=development
```

#### 테스트 (Test)
```bash
TEST_DATABASE_URL=postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test
APP_ENV=test
```

#### 프로덕션 (Production)
```bash
DATABASE_URL=postgresql+psycopg://rs_scanner:SECURE_PASSWORD@db.example.com:5432/rs_scanner
# Compose API를 별도 DB에 연결할 때만 설정한다. 로컬 Compose는 생략하면 된다.
# API_DATABASE_URL=postgresql+psycopg://rs_scanner:SECURE_PASSWORD@db.example.com:5432/rs_scanner
APP_ENV=production
NAVER_REQUEST_TIMEOUT=60
KIWOOM_FALLBACK_ENABLED=false
REPAIR_API_ENABLED=false
LEGACY_REPAIR_API_ENABLED=false
REPAIR_RECONCILER_ENABLED=false
ANALYSIS_API_ENABLED=false
# AGENT_SERVICE_TOKENS는 Secret Manager에서 주입한다.
# KIWOOM_APP_KEY와 KIWOOM_SECRET_KEY는 Secret Manager에서 주입한다.
# KRX_AUTH_KEY는 Secret Manager 또는 gitignore된 .env에서만 주입한다.
# KRX_API_BASE_URL은 KRX 개발 명세서의 인증키 없는 base URL만 설정한다.
```

현행 운영 경로는 [주간 분석 PRD](prd-weekly-crawl-quality-analysis.md)다.
`KIWOOM_FALLBACK_ENABLED`, repair reconciler, 공유 폴더 브리지는 일일 batch에서 사용하지
않는다. Kiwoom은 Sam이 보고서 evidence를 만들 때 제한 표본으로만 호출한다. 인증정보는
로그와 리포트에 기록하지 않는다.

Compose 배포에서는 반드시 환경 파일을 명시해 설정과 Secret을 컨테이너에 전달한다.
기본값은 Repair API와 reconciler가 모두 꺼진 상태이므로, staging canary 승인 전에는
그대로 유지한다.

```bash
docker compose --env-file .env.production build api
docker compose --env-file .env.production up -d api
```

Sam 분석 API를 켤 때만 `.env.production` 또는 Secret 주입 계층에 아래 값을 설정한다.
각 역할 token은 분리한다. Compose가 host port를 `127.0.0.1`에 publish하는 것이 첫 번째
네트워크 경계다. Docker NAT 환경에서는 container가 host 요청을 loopback IP로 보지 않을 수
있으므로, `AGENT_ALLOWED_IPS`는 실제 source IP를 probe로 확인하기 전에는 비워 둔다.
내부 API는 신뢰된 reverse proxy 없이 loopback에 직접 바인딩하므로 `X-Forwarded-For`는
allowlist 판단에 사용하지 않는다.

```text
ANALYSIS_API_ENABLED=true
REPAIR_API_ENABLED=false
LEGACY_REPAIR_API_ENABLED=false
REPAIR_RECONCILER_ENABLED=false
KIWOOM_FALLBACK_ENABLED=false
# Docker gateway/source IP를 별도 probe로 확인한 뒤에만 설정한다.
AGENT_ALLOWED_IPS=
AGENT_SERVICE_TOKENS=<operator-token>=analysis:request,analysis:read,analysis:review;<sam-token>=analysis:read,analysis:accept,analysis:submit;<codex-token>=analysis:read,codex:request,codex:result
```

---

## 트러블슈팅

### 1. 데이터베이스 연결 실패

**문제:** `sqlalchemy.exc.OperationalError: could not connect to server`

**해결:**
```bash
# PostgreSQL 서비스 상태 확인
docker-compose ps postgres

# 로그 확인
docker-compose logs postgres

# 재시작
docker-compose restart postgres
```

### 2. 마이그레이션 실패

**문제:** `alembic.util.exc.CommandError: Can't locate revision identified by`

**해결:**
```bash
# 현재 마이그레이션 상태 확인
alembic current

# 마이그레이션 히스토리 확인
alembic history

# 처음부터 다시 실행
alembic downgrade base
alembic upgrade head
```

### 3. 테스트 실패

**문제:** `IntegrityError: duplicate key value violates unique constraint`

**해결:**
```bash
# 전용 테스트 PostgreSQL 시작
docker-compose -f docker-compose.test.yml up -d postgres_test

# 마이그레이션 재실행
DATABASE_URL="postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test" alembic upgrade head
```

### 4. Docker 빌드 실패

**문제:** `ERROR: failed to solve: process "/bin/sh -c pip install ..." did not complete successfully`

**해결:**
```bash
# 캐시 무시하고 빌드
docker-compose build --no-cache api

# 빌드 로그 상세히 확인
docker-compose build --progress=plain api
```

### 5. API 응답 느림

**문제:** API 응답이 5초 이상 걸림

**해결:**
```bash
# 쿼리 성능 분석
python scripts/test_query_performance.py

# 인덱스 확인
psql rs_scanner -c "\d+ symbols"
psql rs_scanner -c "\d+ rs_scores"

# 캐시 활성화 (프로덕션 환경)
export APP_ENV=production
```

### 6. 크롤링 중단

**문제:** 배치 작업이 중간에 멈춤

**해결:**
```bash
# 크롤링 실패 내역 확인
curl http://localhost:8000/api/v1/crawl/failures

# Rate limit 조정
# app/crawler/rate_limiter.py에서 MIN_DELAY, MAX_DELAY 값 증가

# 재시도 횟수 확인
# app/crawler/retry.py에서 MAX_RETRIES 확인
```

---

## 모니터링 및 로그

### Health Check

```bash
# API 상태 확인
curl http://localhost:8000/api/v1/health

# 응답 예시
{
  "status": "ok",
  "db_connected": true,
  "cache": {
    "rankings_cache_size": 2,
    "stats_cache_size": 1,
    "stock_detail_cache_size": 5,
    "cache_enabled": true
  }
}
```

### 로그 확인

```bash
# Docker Compose 로그
docker-compose logs -f api
docker-compose logs -f postgres

# 특정 시간대 로그
docker-compose logs --since 2024-05-29T10:00:00 api

# 로그 파일 (로컬 실행 시)
tail -f api_server.log
```

### 메트릭 수집

프로덕션 환경에서는 다음 도구들을 사용하여 모니터링:
- **Prometheus**: 메트릭 수집
- **Grafana**: 대시보드
- **CloudWatch** (AWS): 로그 및 메트릭
- **Sentry**: 에러 추적

---

## 백업 및 복구

### 데이터베이스 백업

```bash
# 전체 백업
docker exec rs_scanner_db pg_dump -U rs_scanner rs_scanner > backup_$(date +%Y%m%d).sql

# 압축 백업
docker exec rs_scanner_db pg_dump -U rs_scanner rs_scanner | gzip > backup_$(date +%Y%m%d).sql.gz
```

### 데이터베이스 복구

```bash
# SQL 파일에서 복구
docker exec -i rs_scanner_db psql -U rs_scanner rs_scanner < backup_20240529.sql

# 압축 파일에서 복구
gunzip < backup_20240529.sql.gz | docker exec -i rs_scanner_db psql -U rs_scanner rs_scanner
```

---

## 성능 최적화 팁

1. **캐싱 활성화**: `APP_ENV=production` 설정
2. **DB 인덱스 확인**: 정기적으로 `scripts/test_query_performance.py` 실행
3. **Connection Pool 조정**: SQLAlchemy pool_size 조정
4. **Rate Limiting**: Naver 크롤러 속도 조정
5. **리소스 모니터링**: CPU, 메모리, DB 연결 수 확인

---

## 보안 권장사항

1. ✅ `.env` 파일은 절대 Git에 커밋하지 않기
2. ✅ 프로덕션에서는 강력한 비밀번호 사용
3. ✅ HTTPS 사용 (리버스 프록시 또는 ALB)
4. ✅ PostgreSQL 외부 접속 차단 (방화벽 설정)
5. ✅ 정기적인 보안 업데이트 적용
6. ✅ API Rate Limiting 적용

---

## 라이선스

MIT License
