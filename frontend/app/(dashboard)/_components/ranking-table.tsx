'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Star, ArrowUp, ArrowDown } from 'lucide-react';
import type { RankingItem } from '@/types/api';
import { cn } from '@/lib/utils/cn';
import {
  formatNumber,
  formatPercent,
  getRsColorClass,
  getChangeColorClass,
} from '@/lib/utils/format';

interface RankingTableProps {
  items: RankingItem[];
  onSort?: (column: string, direction: 'asc' | 'desc') => void;
}

type SortColumn = 'rank_in_market' | 'rs_rating' | 'return_1m' | 'return_3m' | 'return_6m' | 'return_9m' | 'return_12m';

function formatReturnPercent(value: number | null): string {
  return value === null ? '-' : formatPercent(value * 100);
}

export function RankingTable({ items, onSort }: RankingTableProps) {
  const [favorites, setFavorites] = useState<Set<string>>(new Set());
  const [sortColumn, setSortColumn] = useState<SortColumn>('rank_in_market');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');

  const toggleFavorite = (code: string) => {
    setFavorites((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(code)) {
        newSet.delete(code);
      } else {
        newSet.add(code);
      }
      return newSet;
    });
  };

  const handleSort = (column: SortColumn) => {
    const newDirection = sortColumn === column && sortDirection === 'asc' ? 'desc' : 'asc';
    setSortColumn(column);
    setSortDirection(newDirection);
    onSort?.(column, newDirection);
  };

  const sortIcon = (column: SortColumn) => {
    if (sortColumn !== column) return null;
    return sortDirection === 'asc' ? (
      <ArrowUp className="w-3 h-3 inline ml-1" />
    ) : (
      <ArrowDown className="w-3 h-3 inline ml-1" />
    );
  };

  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-gray-700">
                <Star className="w-4 h-4" />
              </th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">섹터</th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('rank_in_market')}
              >
                시장내순위 {sortIcon('rank_in_market')}
              </th>
              <th className="px-3 py-2 text-left font-medium text-gray-700">종목명</th>
              <th className="px-3 py-2 text-right font-medium text-gray-700">현재가</th>
              <th className="px-3 py-2 text-right font-medium text-gray-700">등락율</th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('rs_rating')}
              >
                RS {sortIcon('rs_rating')}
              </th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('return_1m')}
              >
                수익률(1M) {sortIcon('return_1m')}
              </th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('return_3m')}
              >
                수익률(3M) {sortIcon('return_3m')}
              </th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('return_6m')}
              >
                수익률(6M) {sortIcon('return_6m')}
              </th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('return_9m')}
              >
                수익률(9M) {sortIcon('return_9m')}
              </th>
              <th
                className="px-3 py-2 text-center font-medium text-gray-700 cursor-pointer hover:bg-gray-100"
                onClick={() => handleSort('return_12m')}
              >
                수익률(12M) {sortIcon('return_12m')}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr
                key={item.code}
                className={cn(
                  'border-b hover:bg-gray-50 transition-colors',
                  index % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'
                )}
              >
                <td className="px-3 py-2">
                  <button
                    onClick={() => toggleFavorite(item.code)}
                    className="hover:scale-110 transition-transform"
                  >
                    <Star
                      className={cn(
                        'w-4 h-4',
                        favorites.has(item.code)
                          ? 'fill-yellow-400 text-yellow-400'
                          : 'text-gray-300'
                      )}
                    />
                  </button>
                </td>
                <td className="px-3 py-2 text-gray-700">-</td>
                <td className="px-3 py-2 text-center text-gray-700">{item.rank_in_market}</td>
                <td className="px-3 py-2">
                  <Link href={`/stocks/${item.code}`} className="block hover:bg-gray-100 -mx-3 px-3 py-1 rounded transition-colors">
                    <div className="font-medium text-gray-900 hover:text-blue-600 transition-colors">{item.name}</div>
                    <div className="text-xs text-gray-500">{item.code}</div>
                  </Link>
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {formatNumber(item.close)}
                </td>
                <td className={cn('px-3 py-2 text-right font-mono', getChangeColorClass(item.change_rate))}>
                  {formatPercent(item.change_rate)}
                </td>
                <td className={cn('px-3 py-2 text-center font-bold', getRsColorClass(item.rs_rating))}>
                  {item.rs_rating}
                </td>
                <td className={cn('px-3 py-2 text-center font-mono', getChangeColorClass((item.return_1m ?? 0) * 100))}>{formatReturnPercent(item.return_1m)}</td>
                <td className={cn('px-3 py-2 text-center font-mono', getChangeColorClass(item.return_3m * 100))}>{formatReturnPercent(item.return_3m)}</td>
                <td className={cn('px-3 py-2 text-center font-mono', getChangeColorClass(item.return_6m * 100))}>{formatReturnPercent(item.return_6m)}</td>
                <td className={cn('px-3 py-2 text-center font-mono', getChangeColorClass(item.return_9m * 100))}>{formatReturnPercent(item.return_9m)}</td>
                <td className={cn('px-3 py-2 text-center font-mono', getChangeColorClass(item.return_12m * 100))}>{formatReturnPercent(item.return_12m)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
