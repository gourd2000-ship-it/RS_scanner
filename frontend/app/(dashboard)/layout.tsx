import { ReactNode } from 'react';

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* 헤더 */}
      <header className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-8">
              <h1 className="text-xl font-bold text-gray-900">RS Scanner</h1>
              <nav className="flex gap-6">
                <a href="/" className="text-blue-600 font-medium border-b-2 border-blue-600 pb-4">
                  종합 RS
                </a>
                <a href="/52w-high" className="text-gray-600 hover:text-gray-900 pb-4">
                  52주 신고가
                </a>
                <a href="/valuation" className="text-gray-600 hover:text-gray-900 pb-4">
                  벨류에이션
                </a>
                <a href="/lift" className="text-gray-600 hover:text-gray-900 pb-4">
                  리프트
                </a>
                <a href="/operations" className="text-gray-600 hover:text-gray-900 pb-4">
                  운영 모니터링
                </a>
              </nav>
            </div>
          </div>
        </div>
      </header>

      {/* 메인 콘텐츠 */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {children}
      </main>
    </div>
  );
}
