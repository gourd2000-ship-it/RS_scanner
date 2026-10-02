# RS Scanner

개인 연구용 KOSPI·KOSDAQ 상대강도(RS) 데이터 시스템입니다. FastAPI·PostgreSQL 배치가 종목·OHLCV·RS를 누적하고, Next.js와 읽기 API가 검증된 결과를 제공합니다.

매매 추천·주문·수익 보장 서비스가 아닙니다. 현재 백테스트 데이터는 검증 완료 OHLCV 구간만 제공하며, 상장폐지 lifecycle과 부분·검토 구간은 포함하지 않습니다. 매매 체결 시뮬레이터는 아직 구현되지 않았습니다.

개발과 운영 방법은 [운영 절차](docs/operations.md), 데이터 규칙은 [도메인 규칙](docs/business-rules.md), API는 [외부 계약](docs/contracts.md), 남은 작업은 [현재 상태](docs/tracking/status.md)를 확인하세요.
