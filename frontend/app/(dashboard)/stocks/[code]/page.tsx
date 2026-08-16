'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, TrendingUp, TrendingDown } from 'lucide-react';
import { getStockDetail, getPriceHistory, getRsHistory } from '@/lib/api/stocks';
import { ErrorMessage } from '@/components/ui/error-message';
import { Button } from '@/components/ui/button';
import { CandlestickChart } from './_components/candlestick-chart';
import { RsTrendChart } from './_components/rs-trend-chart';
import type { SymbolDetailResponse, DailyPriceItem, RsScoreItem } from '@/types/api';
import { formatNumber, formatPercent, getRsColorClass } from '@/lib/utils/format';

function formatReturnPercent(value: number | null): string {
  return value === null ? '-' : formatPercent(value * 100);
}

export default function StockDetailPage() {
  const params = useParams();
  const router = useRouter();
  const code = params.code as string;

  const [stockData, setStockData] = useState<SymbolDetailResponse | null>(null);
  const [priceData, setPriceData] = useState<DailyPriceItem[]>([]);
  const [rsData, setRsData] = useState<RsScoreItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [chartLoading, setChartLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStockData = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getStockDetail(code);
        setStockData(data);
      } catch (err) {
        console.error('Failed to fetch stock detail:', err);
        setError(err instanceof Error ? err.message : '데이터를 불러오는데 실패했습니다');
      } finally {
        setLoading(false);
      }
    };

    fetchStockData();
  }, [code]);

  useEffect(() => {
    const fetchChartData = async () => {
      setChartLoading(true);
      try {
        const [prices, rsHistory] = await Promise.all([
          getPriceHistory(code, 1, 100),
          getRsHistory(code, 90),
        ]);
        setPriceData(prices.items);
        setRsData(rsHistory.rs_scores);
      } catch (err) {
        console.error('Failed to fetch chart data:', err);
      } finally {
        setChartLoading(false);
      }
    };

    fetchChartData();
  }, [code]);

  const handleRetry = () => {
    setError(null);
    setStockData(null);
  };

  const handleBack = () => {
    router.back();
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <div className="w-24 h-10 bg-gray-200 rounded animate-pulse" />
          <div className="w-48 h-8 bg-gray-200 rounded animate-pulse" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="border rounded-lg p-4 bg-white">
              <div className="w-32 h-6 bg-gray-200 rounded animate-pulse mb-2" />
              <div className="w-24 h-8 bg-gray-200 rounded animate-pulse" />
            </div>
          ))}
        </div>
        <div className="border rounded-lg bg-white p-6">
          <div className="w-full h-96 bg-gray-200 rounded animate-pulse" />
        </div>
      </div>
    );
  }

  if (error || !stockData) {
    return (
      <div className="border rounded-lg bg-white">
        <ErrorMessage message={error || '종목 정보를 찾을 수 없습니다'} onRetry={handleRetry} />
      </div>
    );
  }

  const { symbol, latest_price, latest_rs } = stockData;
  const changeRate = latest_price?.change_rate || 0;
  const isPositive = changeRate > 0;
  const isNegative = changeRate < 0;

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="flex items-center gap-4">
        <Button onClick={handleBack} variant="outline" size="sm" className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          목록
        </Button>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">{symbol.name}</h1>
            <span className="text-sm text-gray-500">{symbol.code}</span>
            <span
              className={`text-xs px-2 py-1 rounded ${
                symbol.market === 'KOSPI' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'
              }`}
            >
              {symbol.market}
            </span>
            {symbol.sector && (
              <span className="text-sm text-gray-600 border-l pl-3 ml-1">{symbol.sector}</span>
            )}
          </div>
          {latest_price && (
            <div className="flex items-center gap-3 mt-2">
              <span className="text-3xl font-bold">
                {formatNumber(latest_price.close)}원
              </span>
              <span
                className={`text-xl font-semibold flex items-center gap-1 ${
                  isPositive ? 'text-red-600' : isNegative ? 'text-blue-600' : 'text-gray-600'
                }`}
              >
                {isPositive ? (
                  <TrendingUp className="w-5 h-5" />
                ) : isNegative ? (
                  <TrendingDown className="w-5 h-5" />
                ) : null}
                {formatPercent(changeRate)}
              </span>
              <span className="text-sm text-gray-500">
                {latest_price.trade_date}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* RS 및 주요 지표 카드 */}
      {latest_rs && (
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          <div className="border rounded-lg p-4 bg-white">
            <div className="text-sm text-gray-600 mb-1">RS Rating</div>
            <div className={`text-3xl font-bold ${getRsColorClass(latest_rs.rs_rating)}`}>
              {latest_rs.rs_rating}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              시장 내 {latest_rs.rank_in_market}위
            </div>
          </div>

          <div className="border rounded-lg p-4 bg-white">
            <div className="text-sm text-gray-600 mb-1">1개월 수익률</div>
            <div className={`text-2xl font-semibold ${
              latest_rs.return_1m && latest_rs.return_1m > 0 ? 'text-red-600' : latest_rs.return_1m && latest_rs.return_1m < 0 ? 'text-blue-600' : 'text-gray-600'
            }`}>
              {formatReturnPercent(latest_rs.return_1m)}
            </div>
          </div>

          <div className="border rounded-lg p-4 bg-white">
            <div className="text-sm text-gray-600 mb-1">3개월 상대수익률</div>
            <div className={`text-2xl font-semibold ${
              latest_rs.return_3m > 0 ? 'text-red-600' : latest_rs.return_3m < 0 ? 'text-blue-600' : 'text-gray-600'
            }`}>
              {formatReturnPercent(latest_rs.return_3m)}
            </div>
          </div>

          <div className="border rounded-lg p-4 bg-white">
            <div className="text-sm text-gray-600 mb-1">6개월 상대수익률</div>
            <div className={`text-2xl font-semibold ${
              latest_rs.return_6m > 0 ? 'text-red-600' : latest_rs.return_6m < 0 ? 'text-blue-600' : 'text-gray-600'
            }`}>
              {formatReturnPercent(latest_rs.return_6m)}
            </div>
          </div>

          <div className="border rounded-lg p-4 bg-white">
            <div className="text-sm text-gray-600 mb-1">12개월 상대수익률</div>
            <div className={`text-2xl font-semibold ${
              latest_rs.return_12m > 0 ? 'text-red-600' : latest_rs.return_12m < 0 ? 'text-blue-600' : 'text-gray-600'
            }`}>
              {formatReturnPercent(latest_rs.return_12m)}
            </div>
          </div>
        </div>
      )}

      {/* 가격 차트 */}
      <div className="border rounded-lg bg-white p-6">
        <h2 className="text-lg font-semibold mb-4">가격 차트</h2>
        <CandlestickChart data={priceData} loading={chartLoading} />
      </div>

      {/* RS 추이 차트 */}
      <div className="border rounded-lg bg-white p-6">
        <h2 className="text-lg font-semibold mb-4">RS 추이</h2>
        <RsTrendChart data={rsData} loading={chartLoading} />
      </div>
    </div>
  );
}
