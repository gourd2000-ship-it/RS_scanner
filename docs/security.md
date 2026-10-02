# 보안 정책

## 보호 대상

DB 연결 문자열, 공급자 API 키·secret, 내부 서비스 Bearer token, 알림 webhook·bot token, 운영 백업과 원시 수집 파일은 비밀값이다. 가격·유니버스·감사·백테스트 lineage는 무결성을 보호해야 하는 운영 데이터다.

## 인증과 권한

| 주체 | 허용 작업 | 조건 | 명시적으로 금지되는 작업 |
|---|---|---|---|
| 사람 운영자 | 배치 실행, migration, 데이터 복구, 데이터셋 발행, 설정·DB 관리, 별도 운영 API | 운영 환경 직접 접근 또는 `OPERATOR_*` Bearer token과 허용 IP | 읽기 전용 자동화 token으로 관리자 작업 수행 |
| RS Scanner 배치 서비스 | 명부·가격·품질·RS·dataset 쓰기 | 운영 DB 서비스 계정, 승인된 실행 경로 | 브라우저·자동화 요청을 대신해 임의 쓰기 |
| 내부 자동화 도구 | 상태·RS·종목·백테스트 결과 읽기 | 허용 IP에서 Bearer token의 `status:read`, `rs:read`, `stock:read`, `backtest:read` 중 필요한 scope | repair, analysis, change request의 조회·변경, DB 직접 접속 |
| 외부 사용자 | 공개 조회 API와 프런트엔드 읽기 | HTTP 입력 검증·rate limit | 내부 API, DB, 비밀값 접근 |

내부 읽기 요청은 `AGENT_API_ENABLED`가 켜진 경우에만 처리한다. 서버는 요청의 실제 client IP를 allowlist와 대조하고 `Authorization: Bearer` token을 상수 시간 비교한다. token 누락·형식 오류·불일치는 401, 필요한 scope 부족·허용 IP 밖 요청은 403, 비활성 내부 기능은 404다. 신뢰된 reverse proxy가 별도로 구성되지 않은 상태에서는 `X-Forwarded-For`를 신뢰하지 않는다.

사람 운영자의 전체 권한은 운영 호스트·컨테이너·DB 접근과, 선택적으로 `OPERATOR_API_ENABLED`·`OPERATOR_SERVICE_TOKENS`·`OPERATOR_ALLOWED_IPS`로 켠 별도 운영 API로 부여된다. `AGENT_SERVICE_TOKENS`는 읽기 scope 이외 값을 폐기하므로 운영 API에 사용할 수 없다.

## 비밀값과 감사

비밀값은 Git 추적 파일·문서·테스트 fixture·로그·오류 응답에 넣지 않는다. 운영 시 secret store 또는 접근 제어된 환경 변수로 주입하고, `.env*`는 로컬에서만 유지한다. 비밀값이 채팅, 로그, 저장소, 잘못된 파일 권한 등으로 노출됐거나 노출 가능성이 있으면 즉시 폐기·교체하고, 기존 token을 무효화한 뒤 영향을 확인한다.

다음 이벤트는 요청 ID, 주체 식별자(원문 token 제외), 시간, 결과를 남긴다: 내부 인증 실패, scope/IP 거부, 운영자의 migration·복구·dataset 발행, 공급자 수집 실패, 데이터 보정·제외 결정. 가격이나 비밀값 전체를 인증 로그에 기록하지 않는다.
