'use client';

import { Button } from '@/components/ui/button';
import { Search } from 'lucide-react';

interface FilterControlsProps {
  period: string;
  onPeriodChange: (period: string) => void;
  sortType: string;
  onSortTypeChange: (type: string) => void;
  minMarketCap: string;
  onMinMarketCapChange: (value: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  totalCount: number;
  excludeEtf: boolean;
  onExcludeEtfChange: (value: boolean) => void;
}

const PERIODS = [
  { id: '12M', label: '12M' },
  { id: '1M', label: '1M' },
  { id: '3M', label: '3M' },
  { id: '6M', label: '6M' },
];

const SORT_TYPES = [
  { id: 'representative', label: '대표주' },
  { id: 'mid_category', label: '중분류' },
];

const MARKET_CAPS = [
  { id: '2000', label: '2,000억+' },
  { id: '1000', label: '1,000억+' },
  { id: '500', label: '500억+' },
  { id: 'all', label: '전체' },
];

export function FilterControls({
  period,
  onPeriodChange,
  sortType,
  onSortTypeChange,
  minMarketCap,
  onMinMarketCapChange,
  searchQuery,
  onSearchChange,
  totalCount,
  excludeEtf,
  onExcludeEtfChange,
}: FilterControlsProps) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      {/* 왼쪽: 기간 선택 */}
      <div className="flex items-center gap-2">
        {PERIODS.map((p) => (
          <Button
            key={p.id}
            variant="outline"
            size="sm"
            active={period === p.id}
            onClick={() => onPeriodChange(p.id)}
          >
            {p.label}
          </Button>
        ))}
        <span className="mx-2 text-gray-300">|</span>
        {SORT_TYPES.map((s) => (
          <Button
            key={s.id}
            variant="ghost"
            size="sm"
            active={sortType === s.id}
            onClick={() => onSortTypeChange(s.id)}
            className={sortType === s.id ? 'text-blue-600' : 'text-gray-600'}
          >
            {s.label}
          </Button>
        ))}
      </div>

      {/* 오른쪽: ETF 토글 + 시가총액 필터 + 검색 */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => onExcludeEtfChange(!excludeEtf)}
          className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
            excludeEtf
              ? 'bg-blue-50 border-blue-300 text-blue-700'
              : 'border-gray-300 text-gray-500'
          }`}
        >
          ETF 제외
        </button>
        <select
          value={minMarketCap}
          onChange={(e) => onMinMarketCapChange(e.target.value)}
          className="px-3 py-1.5 border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {MARKET_CAPS.map((mc) => (
            <option key={mc.id} value={mc.id}>
              {mc.label}
            </option>
          ))}
        </select>

        <div className="relative">
          <input
            type="text"
            placeholder="종목명/종목코드"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-9 pr-3 py-1.5 border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          />
          <Search className="absolute left-2.5 top-2 w-4 h-4 text-gray-400" />
        </div>

        <span className="text-sm text-gray-600">{totalCount.toLocaleString()}개 종목</span>
      </div>
    </div>
  );
}
