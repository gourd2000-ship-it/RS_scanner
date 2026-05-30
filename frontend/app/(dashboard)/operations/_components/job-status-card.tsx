'use client';

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { CrawlJobItem } from '@/types/api';
import { cn } from '@/lib/utils/cn';

interface JobStatusCardProps {
  job: CrawlJobItem;
  onClick?: () => void;
}

export function JobStatusCard({ job, onClick }: JobStatusCardProps) {
  const statusColors = {
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
    running: 'bg-blue-100 text-blue-800',
  };

  const statusText = {
    completed: '완료',
    failed: '실패',
    running: '실행중',
  };

  const formatDateTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return '-';
    if (seconds < 60) return `${seconds}초`;
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}분 ${secs}초`;
  };

  return (
    <Card
      className={cn(
        'hover:shadow-md transition-shadow',
        onClick && 'cursor-pointer'
      )}
      onClick={onClick}
    >
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">{job.job_type}</CardTitle>
          <span
            className={cn(
              'inline-block px-2 py-1 rounded text-sm font-medium',
              statusColors[job.status]
            )}
          >
            {statusText[job.status]}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-600">시작 시각</span>
            <span className="font-mono">{formatDateTime(job.started_at)}</span>
          </div>
          {job.finished_at && (
            <div className="flex justify-between">
              <span className="text-gray-600">종료 시각</span>
              <span className="font-mono">{formatDateTime(job.finished_at)}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-gray-600">실행 시간</span>
            <span className="font-mono">{formatDuration(job.duration_seconds)}</span>
          </div>
        </div>

        {/* 성공률 Progress Bar */}
        {job.success_rate !== null && (
          <div className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="text-gray-600">성공률</span>
              <span className="font-semibold">{job.success_rate.toFixed(1)}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className={cn(
                  'h-2 rounded-full transition-all',
                  job.success_rate >= 95 ? 'bg-green-500' :
                  job.success_rate >= 80 ? 'bg-yellow-500' :
                  'bg-red-500'
                )}
                style={{ width: `${job.success_rate}%` }}
              />
            </div>
          </div>
        )}

        {/* 종목 처리 통계 */}
        <div className="grid grid-cols-3 gap-2 text-sm">
          <div className="text-center p-2 bg-gray-50 rounded">
            <div className="text-gray-600 text-xs">전체</div>
            <div className="font-semibold">{job.symbols_total}</div>
          </div>
          <div className="text-center p-2 bg-green-50 rounded">
            <div className="text-gray-600 text-xs">성공</div>
            <div className="font-semibold text-green-700">{job.symbols_succeeded}</div>
          </div>
          <div className="text-center p-2 bg-red-50 rounded">
            <div className="text-gray-600 text-xs">실패</div>
            <div className="font-semibold text-red-700">{job.symbols_failed}</div>
          </div>
        </div>

        {/* 메시지 */}
        {job.message && (
          <div className="text-sm text-gray-600 p-2 bg-gray-50 rounded">
            {job.message}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
