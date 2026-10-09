# 시스템 구성

`frontend`의 Next.js 화면은 공개 조회 API를 소비한다. `app/main_api.py`의 FastAPI는 공개 종목·랭킹·상태 API와 Bearer scope가 필요한 내부 읽기 API를 제공한다. API는 service → repository → SQLAlchemy model 순으로 PostgreSQL/TimescaleDB를 읽으며, 브라우저와 내부 자동화 도구가 DB에 직접 접속하지 않는다.

`app/main_batch.py`와 `scripts/`는 별도 서비스 실행 경로다. Naver, KRX, Kiwoom REST·파일 브리지, 선택적 EOD 공급자에서 명부·OHLCV를 수집하여 관측, canonical 가격, 품질 판정, RS, 백테스트 데이터셋을 DB에 기록한다. 이 경로만 운영 DB 쓰기 권한을 사용한다. 공급자 응답·자격 증명은 API 응답이나 프런트엔드로 전달하지 않는다.

대표 흐름은 다음과 같다.

1. 배치가 거래일·종목 명부를 기준으로 공급자 관측을 저장하고, 출처와 조정 기준을 연결한다.
2. 검증 서비스가 기대 거래일 대비 결측·구조 오류·검토 대상을 판정한다.
3. RS 계산은 적격 가격과 유니버스를 사용해 날짜별 점수와 lineage를 기록한다.
4. 클린 데이터셋 생성기는 `complete` 종목·연도 구간만 고정된 dataset으로 물질화한다.
5. 읽기 API와 프런트엔드는 dataset/RS의 상태·coverage와 함께 결과를 반환한다.

백테스트 경로에는 전략·버전 저장과 실행 요청 API, 고정 dataset·RS 입력 선택,
종가 신호를 다음 거래일 시가 체결로 계산하는 시뮬레이터, 결과 저장·조회 API가
구현돼 있다. `/backtests` 화면은 전략 입력·실행 요청·상태 조회를 제공한다.
별도 실행 워커의 운영 진입점과 화면의 결과 상세 조회, 발행 dataset을 이용한
종단 간 운영 검증은 남아 있다.

백엔드 의존 방향은 API → services → repositories/models/core다. crawler는 service가 호출하며, crawler가 API·프런트엔드에 의존해서는 안 된다. `alembic`은 모델 변경에 맞춘 스키마 이력만 관리한다. `frontend`는 API 계약과 환경 변수만 의존하고 Python 모듈이나 DB에 의존하지 않는다.

외부 경계는 공급자 계약과 운영 환경이다. KRX/KIND의 역사 명부·상장폐지 coverage 및 이용 조건은 확정되지 않았고, Kiwoom의 수정주가 의미·장기 범위도 공급자별로 확인해야 한다. 따라서 현재 데이터셋은 과거 전체 시장의 완전한 복원이 아니라, 확인된 생존 lifecycle의 검증 완료 구간이다.
