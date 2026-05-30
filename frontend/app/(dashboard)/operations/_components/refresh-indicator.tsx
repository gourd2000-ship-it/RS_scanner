'use client';

import { RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils/cn';

interface RefreshIndicatorProps {
  lastRefresh: Date | null;
  isRefreshing: boolean;
  onRefresh: () => void;
}

export function RefreshIndicator({ lastRefresh, isRefreshing, onRefresh }: RefreshIndicatorProps) {
  const getTimeAgo = (date: Date | null) => {
    if (!date) return '데이터 없음';

    const seconds = Math.floor((new Date().getTime() - date.getTime()) / 1000);

    if (seconds < 10) return '방금 전';
    if (seconds < 60) return `${seconds}초 전`;

    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}분 전`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}시간 전`;

    const days = Math.floor(hours / 24);
    return `${days}일 전`;
  };

  return (
    <div className="flex items-center gap-3 text-sm text-gray-600">
      <div className="flex items-center gap-2">
        <span>마지막 갱신:</span>
        <span className="font-medium">{getTimeAgo(lastRefresh)}</span>
      </div>

      <button
        onClick={onRefresh}
        disabled={isRefreshing}
        className={cn(
          'flex items-center gap-1 px-3 py-1 rounded border transition-colors',
          isRefreshing
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
            : 'bg-white hover:bg-gray-50 text-gray-700 border-gray-300'
        )}
      >
        <RefreshCw
          className={cn(
            'w-4 h-4',
            isRefreshing && 'animate-spin'
          )}
        />
        <span>{isRefreshing ? '갱신중...' : '새로고침'}</span>
      </button>
    </div>
  );
}
