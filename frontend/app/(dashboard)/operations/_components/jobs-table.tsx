'use client';

import { CrawlJobItem } from '@/types/api';
import { cn } from '@/lib/utils/cn';
import { ArrowUp, ArrowDown } from 'lucide-react';
import { useState } from 'react';

interface JobsTableProps {
  jobs: CrawlJobItem[];
  onJobClick?: (id: number) => void;
  loading?: boolean;
}

type SortColumn = 'started_at' | 'status' | 'success_rate' | 'duration_seconds';

export function JobsTable({ jobs, onJobClick, loading }: JobsTableProps) {
  const [sortColumn, setSortColumn] = useState<SortColumn>('started_at');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

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
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return '-';
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m`;
  };

  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(column);
      setSortDirection('desc');
    }
  };

  const SortIcon = ({ column }: { column: SortColumn }) => {
    if (sortColumn !== column) return null;
    return sortDirection === 'asc' ? (
      <ArrowUp className="w-3 h-3 inline ml-1" />
    ) : (
      <ArrowDown className="w-3 h-3 inline ml-1" />
    );
  };

  if (loading) {
    return (
      <div className="border rounded-lg bg-white p-8 text-center text-gray-500">
        로딩중...
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div className="border rounded-lg bg-white p-8 text-center text-gray-500">
        작업 이력이 없습니다.
      </div>
    );
  }

  return (
    <div className="border rounded-lg overflow-hidden bg-white">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-gray-700">ID</th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">작업 유형</th>
              <th
                className="px-3 py-2 text-left font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('started_at')}
              >
                시작 시각 <SortIcon column="started_at" />
              </th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('status')}
              >
                상태 <SortIcon column="status" />
              </th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('duration_seconds')}
              >
                실행 시간 <SortIcon column="duration_seconds" />
              </th>
              <th className="px-3 py-2 text-center font-medium text-gray-700">처리 종목</th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('success_rate')}
              >
                성공률 <SortIcon column="success_rate" />
              </th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job, index) => (
              <tr
                key={job.id}
                className={cn(
                  'border-b transition-colors',
                  onJobClick && 'cursor-pointer hover:bg-gray-50',
                  index % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'
                )}
                onClick={() => onJobClick?.(job.id)}
              >
                <td className="px-3 py-2 font-mono text-gray-600">#{job.id}</td>
                <td className="px-3 py-2 font-medium">{job.job_type}</td>
                <td className="px-3 py-2 font-mono text-gray-600">
                  {formatDateTime(job.started_at)}
                </td>
                <td className="px-3 py-2 text-center">
                  <span
                    className={cn(
                      'inline-block px-2 py-1 rounded text-xs font-medium',
                      statusColors[job.status]
                    )}
                  >
                    {statusText[job.status]}
                  </span>
                </td>
                <td className="px-3 py-2 text-center font-mono text-gray-600">
                  {formatDuration(job.duration_seconds)}
                </td>
                <td className="px-3 py-2 text-center">
                  <span className="text-green-700 font-semibold">{job.symbols_succeeded}</span>
                  <span className="text-gray-400 mx-1">/</span>
                  <span className="text-red-700 font-semibold">{job.symbols_failed}</span>
                  <span className="text-gray-400 mx-1">/</span>
                  <span className="text-gray-600">{job.symbols_total}</span>
                </td>
                <td className="px-3 py-2 text-center">
                  {job.success_rate !== null ? (
                    <span
                      className={cn(
                        'font-semibold',
                        job.success_rate >= 95 ? 'text-green-600' :
                        job.success_rate >= 80 ? 'text-yellow-600' :
                        'text-red-600'
                      )}
                    >
                      {job.success_rate.toFixed(1)}%
                    </span>
                  ) : (
                    '-'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
