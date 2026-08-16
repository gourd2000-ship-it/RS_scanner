/**
 * 랭킹 테이블 로딩 스켈레톤
 */

export function TableSkeleton() {
  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-gray-700 w-10"></th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">섹터</th>
              <th className="px-3 py-2 text-center font-medium text-gray-700">시장내순위</th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">종목명</th>
              <th className="px-3 py-2 text-right font-medium text-gray-700">현재가</th>
              <th className="px-3 py-2 text-right font-medium text-gray-700">등락율</th>
              <th className="px-3 py-2 text-center font-medium text-gray-700">RS</th>
              <th className="px-3 py-2 text-center font-medium text-gray-700">RS(1M)</th>
              <th className="px-3 py-2 text-center font-medium text-gray-700">RS(3M)</th>
              <th className="px-3 py-2 text-center font-medium text-gray-700">RS(6M)</th>
              <th className="px-3 py-2 text-right font-medium text-gray-700">RS(12M)</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 10 }).map((_, index) => (
              <tr key={index} className="border-b bg-white">
                <td className="px-3 py-2">
                  <div className="w-4 h-4 bg-gray-200 rounded animate-pulse"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-16 h-4 bg-gray-200 rounded animate-pulse"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-8 h-4 bg-gray-200 rounded animate-pulse mx-auto"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="space-y-1">
                    <div className="w-24 h-4 bg-gray-200 rounded animate-pulse"></div>
                    <div className="w-16 h-3 bg-gray-200 rounded animate-pulse"></div>
                  </div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-20 h-4 bg-gray-200 rounded animate-pulse ml-auto"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-16 h-4 bg-gray-200 rounded animate-pulse ml-auto"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-8 h-4 bg-gray-200 rounded animate-pulse mx-auto"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-8 h-4 bg-gray-200 rounded animate-pulse mx-auto"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-8 h-4 bg-gray-200 rounded animate-pulse mx-auto"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-8 h-4 bg-gray-200 rounded animate-pulse mx-auto"></div>
                </td>
                <td className="px-3 py-2">
                  <div className="w-8 h-4 bg-gray-200 rounded animate-pulse mx-auto"></div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
