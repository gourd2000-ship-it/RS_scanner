# API Alembic revision 복구 — 2026-10-01 UTC

## 원인

DB는 같은 미니PC의 `rs_scanner_db` 컨테이너에서 실행되는 PostgreSQL 16 +
TimescaleDB다. 호스트에는 `127.0.0.1:5432`, API에는 Compose 서비스 이름
`postgres:5432`로 연결된다. API 이미지는 Python 애플리케이션과 의존성,
Alembic 파일을 묶은 실행 패키지이며 DB 데이터는 별도 볼륨에 있다.

기존 API 이미지는 2026-09-05에 빌드됐고 Alembic head는 `g3a4b5c6d7e8`이었다.
DB의 `alembic_version`은 `o8b9c0d1e2f3`였다. 다음 migration 7개가 소스에는
있지만 이미지에는 없어 `alembic upgrade head`에서 API 시작이 반복 실패했다.

`g3 → h2 → j3 → k4 → l5 → m6 → n7 → o8`

`o8b9c0d1e2f3_backtest_dataset_replay_indexes.py`는 backtest 가격/멤버십
복합 인덱스 두 개를 만드는 migration이다. DB에서 두 인덱스의 존재를 확인했다.
현재 소스도 head가 `o8b9c0d1e2f3` 하나이므로 적용 대기 migration은 없다.

## 조치

- 재시작 루프를 중지하고 기존 컨테이너 파일시스템을 Docker export/import로 보존했다.
  기존 이미지의 일부 content digest가 없어 tag/commit은 실패했지만 export는 성공했다.
- 보존 이미지: `rs_scanner-api:recovery-base-20261001`
  (`sha256:7588f94783e1a3fad44aa6d4fabaa6bdfd60dcea9a0b9ae7981f442385a5cc06`).
- `Dockerfile.migration-recovery`로 누락된 7개 파일을 추가했다. 애플리케이션
  소스와 설치된 의존성은 기존 컨테이너 것을 유지했다. 컨테이너의 환경변수는
  export/import에 복사되지 않으며 실행 시 Compose가 설정한다.
- 운영 배포 이미지: `rs_scanner-api:revision-repair-20261001`, 동일 이미지의
  `latest` 태그를 사용해 `docker compose up -d --no-deps --no-build api`로 배포했다.
  배포 이미지 ID: `sha256:54f2860ac24bd9af524173d8945e97b2f278eed0495140255a36bec6766fa656`.
- 전체 소스 재빌드 결과는 `rs_scanner-api:source-build-20261001`로 보존했으며
  운영에는 배포하지 않았다. 의존성 버전이 재해석되는 전체 재빌드는 별도 검증 대상이다.
- 첫 기동 확인에서 호스트 `APP_ENV=development`가 API에도 전달됨을 발견했다.
  해당 기동은 개발 초기화 경로를 거쳤다. Compose를 `API_APP_ENV` 기본값
  `production`으로 분리하고 다시 배포했다. 최종 기동에서는 Alembic으로만
  스키마를 확인한다. DB revision을 강제로 변경하는 stamp/downgrade는 하지 않았다.
- PostgreSQL 컨테이너/볼륨을 재생성하거나 수집 데이터를 삭제하지 않았다.

## 검증

- 배포 전 `PGOPTIONS=-c default_transaction_read_only=on`으로 운영 DB 읽기 전용
  연결을 강제하고 DB revision과 이미지 head의 동일성을 assert했다.
- 읽기 전용 TestClient 검사: health, 종목 목록, KOSPI RS 랭킹 모두 HTTP 200.
- 배포 후 실제 `127.0.0.1:8000`에서 동일 세 경로 HTTP 200.
- health: `status=ok`, `db_connected=true`, 운영 캐시 활성화.
- 실행 중 컨테이너의 `alembic current`와 `alembic heads` 모두 `o8b9c0d1e2f3 (head)`.
- 최종 기동 로그에서 migration 단계 통과 및 Uvicorn 기동 확인.
- 최종 확인: API `running / healthy`, `RestartCount=0`; PostgreSQL도 `healthy`.
- 컨테이너 내부 설정 `APP_ENV=production` 재확인 및 `git diff --check` 통과.

health에 표시되는 `last_batch_status=failed`는 이전 job 128의 RS 중단 기록이다.
API 장애 상태와 구별해야 한다. 랭킹 응답의 최신 RS 날짜는 여전히 2026-09-04이며,
운영 규모 RS 재계산과 가격 실패 분류는 이 API 복구 작업에서 수행하지 않았다.

## 재현과 유지보수

복구 base 이미지가 있는 같은 머신에서:

```sh
docker build -f Dockerfile.migration-recovery -t rs_scanner-api:revision-repair-20261001 .
docker run --rm --entrypoint alembic rs_scanner-api:revision-repair-20261001 heads
docker tag rs_scanner-api:revision-repair-20261001 rs_scanner-api:latest
docker compose up -d --no-deps --no-build api
```

다음 정식 릴리스에는 현재 미추적 상태인 migration 7개를 그에 대응하는 소스와
함께 버전 관리에 포함해야 한다. 기본 Dockerfile은 `alembic/`을 복사하므로,
정식 소스 이미지에서도 DB가 참조하는 revision과 모든 부모 파일의 포함 여부를
배포 전 확인한다. 이번 작업에서는 사용자 변경을 임의로 커밋하거나 스테이징하지 않았다.
