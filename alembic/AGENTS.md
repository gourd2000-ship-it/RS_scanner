# 스키마 변경 규칙

revision은 append-only다. 적용된 migration을 고치거나 삭제하지 말고 새 revision으로 전진·되돌림을 표현한다. 모델의 nullable, FK, unique/index 변경은 기존 운영 데이터와 backfill·replay 경로의 호환성을 먼저 확인한다.

가격·종목 identity·listing event·dataset 테이블 변경은 source/lineage 보존과 과거 dataset 재현성을 깨지 않아야 한다. destructive migration, 대량 데이터 rewrite, 운영 DB 적용은 격리 PostgreSQL에서 upgrade 검증과 복구 계획을 갖춘 뒤 사람 운영자가 실행한다.

revision 추가 후 `alembic upgrade head`를 격리 DB에서 검증하고, 관련 integration test를 실행한다.
