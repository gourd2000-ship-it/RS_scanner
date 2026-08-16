'use client';

import { useEffect, useState } from 'react';
import { SectorRsBar } from './_components/sector-rs-bar';
import { SectorFilter } from './_components/sector-filter';
import { FilterControls } from './_components/filter-controls';
import { RankingTable } from './_components/ranking-table';
import { TableSkeleton } from './_components/table-skeleton';
import { Pagination } from '@/components/ui/pagination';
import { Button } from '@/components/ui/button';
import { ErrorMessage } from '@/components/ui/error-message';
import { EmptyState } from '@/components/ui/empty-state';
import { getRankings } from '@/lib/api/rankings';
import { useSectorData } from '@/lib/hooks/use-sector-data';
import type { RankingItem } from '@/types/api';

type DashboardMarket = 'KOSPI' | 'KOSDAQ' | 'ALL';

type DashboardSortField =
  | 'rank_in_market'
  | 'rs_rating'
  | 'rs_1m'
  | 'rs_3m'
  | 'rs_6m'
  | 'rs_12m';

export default function HomePage() {
  const [market, setMarket] = useState<DashboardMarket>('KOSPI');
  const [selectedSector, setSelectedSector] = useState('all');
  const [excludeEtf, setExcludeEtf] = useState(true);
  const [period, setPeriod] = useState('12M');
  const [sortType, setSortType] = useState('representative');
  const [minMarketCap, setMinMarketCap] = useState('2000');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [rankings, setRankings] = useState<RankingItem[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sortBy, setSortBy] = useState<DashboardSortField>('rank_in_market');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(prev => {
        if (prev !== searchQuery) setCurrentPage(1);
        return searchQuery;
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    const fetchRankings = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await getRankings({
          market,
          page: currentPage,
          size: pageSize,
          sort_by: sortBy,
          order: sortOrder,
          exclude_etf: excludeEtf,
          sector: selectedSector !== 'all' ? selectedSector : undefined,
          search: debouncedSearch || undefined,
        });
        setRankings(response.items);
        setTotalCount(response.total_count);
      } catch (err) {
        console.error('Failed to fetch rankings:', err);
        setError(err instanceof Error ? err.message : '데이터를 불러오는데 실패했습니다');
      } finally {
        setLoading(false);
      }
    };

    fetchRankings();
  }, [market, currentPage, pageSize, sortBy, sortOrder, excludeEtf, selectedSector, debouncedSearch]);

  const handleRetry = () => {
    setError(null);
    setCurrentPage(1);
  };

  const handleSectorChange = (sectorId: string) => {
    setSelectedSector(sectorId);
    setCurrentPage(1);
  };

  const handleMarketChange = (nextMarket: DashboardMarket) => {
    setMarket(nextMarket);
    setSelectedSector('all');
    setCurrentPage(1);
  };

  const handlePeriodChange = (selectedPeriod: string) => {
    const periodSortMap = {
      '1M': 'rs_1m',
      '3M': 'rs_3m',
      '6M': 'rs_6m',
      '12M': 'rs_12m',
    } as const;
    setPeriod(selectedPeriod);
    setSortBy(periodSortMap[selectedPeriod as keyof typeof periodSortMap]);
    setSortOrder('desc');
    setCurrentPage(1);
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSort = (column: string, direction: 'asc' | 'desc') => {
    const sortField = column as DashboardSortField;
    setSortBy(sortField);
    setSortOrder(direction);
    setCurrentPage(1); // 정렬 변경 시 첫 페이지로
  };

  const totalPages = Math.ceil(totalCount / pageSize);

  // 섹터 데이터 가져오기
  const { sectorData, loading: sectorLoading } = useSectorData(market);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <span className="mr-1 text-sm font-medium text-gray-700">시장</span>
        <Button
          variant="outline"
          size="sm"
          active={market === 'KOSPI'}
          onClick={() => handleMarketChange('KOSPI')}
        >
          코스피
        </Button>
        <Button
          variant="outline"
          size="sm"
          active={market === 'KOSDAQ'}
          onClick={() => handleMarketChange('KOSDAQ')}
        >
          코스닥
        </Button>
        <Button
          variant="outline"
          size="sm"
          active={market === 'ALL'}
          onClick={() => handleMarketChange('ALL')}
        >
          전체
        </Button>
      </div>

      {/* 섹터 RS 막대 그래프 */}
      <SectorRsBar sectors={sectorData} loading={sectorLoading} />

      {/* 섹터 필터 버튼 */}
      <SectorFilter selectedSector={selectedSector} onSectorChange={handleSectorChange} />

      {/* 필터 컨트롤 */}
      <FilterControls
        period={period}
        onPeriodChange={handlePeriodChange}
        sortType={sortType}
        onSortTypeChange={setSortType}
        minMarketCap={minMarketCap}
        onMinMarketCapChange={setMinMarketCap}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        totalCount={totalCount}
        excludeEtf={excludeEtf}
        onExcludeEtfChange={setExcludeEtf}
      />

      {/* 랭킹 테이블 */}
      {loading ? (
        <TableSkeleton />
      ) : error ? (
        <div className="border rounded-lg bg-white">
          <ErrorMessage
            message={error}
            onRetry={handleRetry}
          />
        </div>
      ) : rankings.length === 0 ? (
        <div className="border rounded-lg bg-white">
          <EmptyState />
        </div>
      ) : (
        <>
          <RankingTable
            items={rankings}
            rankLabel={market === 'ALL' ? '전체순위' : '시장내순위'}
            onSort={handleSort}
          />

          {/* 페이지네이션 */}
          {totalPages > 1 && (
            <Pagination
              currentPage={currentPage}
              totalPages={totalPages}
              totalItems={totalCount}
              itemsPerPage={pageSize}
              onPageChange={handlePageChange}
            />
          )}
        </>
      )}
    </div>
  );
}
