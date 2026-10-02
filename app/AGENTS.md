# 백엔드 작업 규칙

`app`은 API, 배치, crawler, service, repository, model을 포함한다. 요청은 API → service → repository/model 방향으로 흐르며, crawler는 service가 호출한다. endpoint에 가격·유니버스·RS 규칙이나 직접 DB mutation을 넣지 않는다.

가격·유니버스·RS·backtest dataset을 바꿀 때는 관측 source, adjustment policy, effective/observed 시각, validation과 run lineage를 유지한다. `complete`가 아닌 구간이나 상장폐지 lifecycle을 dataset 입력에 포함하지 않는다.

`app/core/agent_auth.py`는 내부 자동화와 사람 운영자의 인증 경계다. 자동화 endpoint에는 필요한 읽기 scope만 요구하고, repair·analysis·change request 변경은 별도 운영자 token만 허용한다. token·원문 credential을 로그·응답에 넣지 않는다.

관련 단위·API 테스트와 `python -m compileall app`을 실행한다. 스키마를 바꾸면 `alembic/AGENTS.md`를 따른다.
