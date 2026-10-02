# 변경 기준

- Python 코드는 API → service → repository/model 방향을 지킨다. API endpoint가 직접 가격·유니버스·RS의 쓰기 규칙을 구현하거나 crawler가 API 계층을 import하면 안 된다.
- 가격·유니버스·RS·dataset 변경에는 source, adjustment policy, 관측 시각, 정책 또는 run 식별자를 보존한다. canonical 값을 in-place로 바꿔 기존 dataset 재현성을 잃으면 안 된다.
- Alembic revision은 append-only다. 이미 적용된 revision을 수정·삭제하거나 모델 변경을 migration 없이 배포하면 안 된다.
- 새 외부 입력은 명시적 schema 검증과 실패 사유를 가져야 한다. 공급자 오류·빈 응답을 휴장, 상폐, 정상 0건으로 바꾸면 안 된다.
- 내부 자동화 API에는 읽기 scope만 발급한다. 쓰기 endpoint를 새로 열거나 write scope를 발급하려면 사람 운영자용 인증·감사 설계를 먼저 추가한다.
- 변경 전후 관련 테스트를 실행한다. migration은 빈 DB와 기존 데이터가 있는 격리 PostgreSQL에서 upgrade 검증을 하고, 데이터셋 변경은 pagination/replay와 quality gate를 검증한다.
- 문서의 현재 사실은 `docs/`의 이 문서 집합에 갱신한다. 날짜가 지난 README, 진행 보고서, `*.legacy-*` 문서는 근거·과거 기록으로만 사용하며 현재 계약으로 인용하지 않는다.
