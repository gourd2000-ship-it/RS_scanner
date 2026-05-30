'use client';

import { CrawlFailureItem } from '@/types/api';
import { cn } from '@/lib/utils/cn';
import { useState } from 'react';

interface FailuresTableProps {
  failures: CrawlFailureItem[];
  loading?: boolean;
}

export function FailuresTable({ failures, loading }: FailuresTableProps) {
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const formatDateTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const truncateMessage = (message: string, maxLength = 60) => {
    if (message.length <= maxLength) return message;
    return message.substring(0, maxLength) + '...';
  };

  const toggleRow = (id: number) => {
    setExpandedRow(expandedRow === id ? null : id);
  };

  if (loading) {
    return (
      <div className="border rounded-lg bg-white p-8 text-center text-gray-500">
        로딩중...
      </div>
    );
  }

  if (failures.length === 0) {
    return (
      <div className="border rounded-lg bg-white p-8 text-center text-gray-500">
        실패 기록이 없습니다.
      </div>
    );
  }

  return (
    <div className="border rounded-lg overflow-hidden bg-white">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-gray-700">발생 시각</th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">작업 ID</th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">종목 코드</th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">타입</th>
              <th className="px-3 py-2 text-center font-medium text-gray-700">HTTP</th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">에러 클래스</th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">에러 메시지</th>
              <th className="px-3 py-2 text-center font-medium text-gray-700">재시도</th>
            </tr>
          </thead>
          <tbody>
            {failures.map((failure, index) => (
              <>
                <tr
                  key={failure.id}
                  className={cn(
                    'border-b transition-colors cursor-pointer hover:bg-gray-50',
                    index % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'
                  )}
                  onClick={() => toggleRow(failure.id)}
                >
                  <td className="px-3 py-2 font-mono text-gray-600">
                    {formatDateTime(failure.created_at)}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-600">#{failure.job_id}</td>
                  <td className="px-3 py-2 font-mono font-semibold">{failure.target_key}</td>
                  <td className="px-3 py-2 text-gray-600">{failure.target_type}</td>
                  <td className="px-3 py-2 text-center">
                    {failure.http_status ? (
                      <span
                        className={cn(
                          'font-mono',
                          failure.http_status >= 500 ? 'text-red-600' :
                          failure.http_status >= 400 ? 'text-yellow-600' :
                          'text-gray-600'
                        )}
                      >
                        {failure.http_status}
                      </span>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-gray-600">
                    {failure.error_class}
                  </td>
                  <td className="px-3 py-2 text-gray-700">
                    <span
                      className="cursor-help"
                      title={failure.error_message}
                    >
                      {truncateMessage(failure.error_message)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span
                      className={cn(
                        'inline-block px-2 py-1 rounded text-xs font-medium',
                        failure.retry_count > 3 ? 'bg-red-100 text-red-800' :
                        failure.retry_count > 0 ? 'bg-yellow-100 text-yellow-800' :
                        'bg-gray-100 text-gray-800'
                      )}
                    >
                      {failure.retry_count}회
                    </span>
                  </td>
                </tr>
                {expandedRow === failure.id && (
                  <tr className="bg-blue-50">
                    <td colSpan={8} className="px-3 py-3">
                      <div className="space-y-2 text-sm">
                        <div>
                          <span className="font-semibold text-gray-700">URL:</span>
                          <div className="mt-1 font-mono text-xs break-all text-gray-600 bg-white p-2 rounded">
                            {failure.url}
                          </div>
                        </div>
                        <div>
                          <span className="font-semibold text-gray-700">에러 메시지:</span>
                          <div className="mt-1 text-gray-700 bg-white p-2 rounded">
                            {failure.error_message}
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
