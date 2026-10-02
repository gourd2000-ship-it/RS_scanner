# RS Scanner

개인 연구용 국내 주식 상대강도(RS) 데이터 시스템이다. Python 3.12/FastAPI와 PostgreSQL 기반 배치가 KOSPI·KOSDAQ 데이터를 누적하고, Next.js 화면과 읽기 API가 검증된 결과를 제공한다. 매매 추천·주문·수익 보장 서비스가 아니며, 현재 백테스트는 검증 완료 OHLCV 구간만 데이터셋으로 제공한다.

```
.
├── CLAUDE.md                         → 작업 시작점
├── AGENTS.md                         → 작업 시작점(동일 내용)
├── docs/
│   ├── architecture.md                → 구성 요소와 데이터 흐름
│   ├── business-rules.md              → RS·OHLCV·백테스트 도메인 규칙
│   ├── security.md                    → 권한, 비밀값, 감사 정책
│   ├── standards.md                   → 변경·검증의 필수 규칙
│   ├── engineering-notes.md           → 재현성·공급자·데이터 품질의 함정
│   ├── operations.md                  → 개발·배치·감사 실행 절차
│   ├── contracts.md                   → HTTP·파일·공급자 계약
│   └── tracking/
│       ├── status.md                  → 구현 현황과 남은 일
│       ├── findings.md                → 미해결 데이터·기술 문제
│       └── decisions/
│           ├── index.md               → 결정 목록
│           └── 0001-*.md              → 결정 근거
├── app/AGENTS.md                      → 백엔드 계층·데이터 변경 경계
├── alembic/AGENTS.md                  → 스키마 migration 규칙
├── scripts/AGENTS.md                  → 운영 스크립트 실행 경계
└── frontend/AGENTS.md                 → Next.js 화면·API 소비 경계
```

## 작업 전 확인

1. 항상 `docs/standards.md`, `docs/engineering-notes.md`, 대상 모듈의 `AGENTS.md`를 읽는다.
2. 스키마·가격 저장·백테스트 데이터셋 변경 전에는 `docs/business-rules.md`, `docs/contracts.md`, `alembic/AGENTS.md`를 읽는다.
3. 외부 공급자·대량 수집·OHLCV 보정 전에는 `docs/operations.md`, `docs/engineering-notes.md`, 관련 source contract와 최근 감사 결과를 읽는다.
4. 인증·토큰·내부 API 변경 전에는 `docs/security.md`와 `app/core/agent_auth.py`의 scope 검증 경로를 읽는다.

## 반드시 지킬 것

- 검증 완료가 아닌 OHLCV 구간, 상장폐지 lifecycle, identity 미확인 lifecycle을 백테스트 입력으로 발행하지 않는다.
- 관측 원본·출처·조정 기준·감사 판정은 덮어쓰거나 추측으로 보정하지 않는다.
- 내부 자동화 도구에는 읽기 scope만 부여한다. 크롤링·누적 배치는 별도 서비스 실행 권한으로만 DB를 쓴다.
- 비밀값을 저장소, 로그, 보고서, 예제에 넣지 않는다. 노출 가능성이 생기면 즉시 교체한다.
- schema migration, 운영 DB 변경, 대량 재수집·데이터셋 발행은 검증과 명시적 운영 결정을 거친다.

## 문제 처리

권한 우회, 비밀값 노출, 운영 DB 손상 가능성, 가격·유니버스 lineage 손실, 검증되지 않은 데이터의 백테스트 발행은 즉시 사용자에게 알린다. 그 외 재현 가능한 문제는 `docs/tracking/findings.md`에 증거·영향·다음 조치를 기록한다.
