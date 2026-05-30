# RS Scanner Frontend

IBD 스타일 Relative Strength 스캐너 프론트엔드

## 개발 서버 실행

```bash
npm run dev
```

http://localhost:3000 에서 확인

## 백엔드 API 서버

프론트엔드 실행 전에 백엔드 API 서버를 먼저 시작해야 합니다:

```bash
cd ..
uvicorn app.main_api:app --reload
```

## 구현된 기능

- ✅ 섹터 RS 막대 그래프
- ✅ 섹터 필터 버튼
- ✅ 기간/정렬 컨트롤
- ✅ 종목 검색
- ✅ RS 랭킹 테이블 (정렬 가능)
- ✅ 즐겨찾기 기능
- ✅ API 연동

## TODO

- [ ] 페이지네이션
- [ ] 종목 상세 페이지 (/stocks/[code])
- [ ] 차트 구현 (ECharts)
- [ ] 관리자 페이지 (/admin)
- [ ] 에러 바운더리
- [ ] 로딩 스켈레톤
- [ ] 반응형 디자인
- [ ] 다크 모드

## 프로젝트 구조

```
frontend/
├── types/              # TypeScript 타입 정의
├── lib/
│   ├── api/           # API 클라이언트
│   └── utils/         # 유틸리티 함수
├── config/            # 환경 설정
├── components/
│   ├── ui/            # 공통 UI 컴포넌트
│   ├── charts/        # 차트 컴포넌트
│   └── layout/        # 레이아웃 컴포넌트
├── app/
│   ├── (dashboard)/   # 대시보드 라우트 그룹
│   │   ├── _components/
│   │   ├── layout.tsx
│   │   └── page.tsx
│   └── layout.tsx     # Root 레이아웃
```

## 기술 스택

- **Framework**: Next.js 16.2.6 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Charts**: Apache ECharts
- **Data Fetching**: SWR
- **Validation**: Zod
- **Icons**: Lucide React
