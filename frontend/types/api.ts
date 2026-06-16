/**
 * API 응답 타입 정의
 * 백엔드 FastAPI 스키마와 일치
 */

export type MarketType = 'KOSPI' | 'KOSDAQ';

export interface RankingItem {
  code: string;
  name: string;
  market: MarketType;
  trade_date: string;
  rs_rating: number;
  rank_in_market: number;
  return_3m: number;
  return_6m: number;
  return_9m: number;
  return_12m: number;
  relative_return_score: number;
  close: number;
  change_rate: number;
}

export interface RsRankingResponse {
  market: MarketType;
  trade_date: string | null;
  total_count: number;
  page: number;
  size: number;
  items: RankingItem[];
}

export interface SymbolItem {
  code: string;
  name: string;
  market: MarketType;
  sector: string | null;
  industry: string | null;
  is_active: boolean;
  listed_at: string | null;
}

export interface PaginatedSymbolsResponse {
  total_count: number;
  page: number;
  size: number;
  items: SymbolItem[];
}

export interface HealthResponse {
  status: string;
  db_connected: boolean;
  cache: {
    rankings_cache_size: number;
    stats_cache_size: number;
    stock_detail_cache_size: number;
    cache_enabled: boolean;
  };
  last_batch_at: string | null;
  last_batch_status: string | null;
}

// 프론트엔드 전용 타입
export interface RankingQueryParams {
  market: MarketType;
  page?: number;
  size?: number;
  min_rs?: number;
  max_rs?: number;
  sort_by?: 'rank_in_market' | 'rs_rating' | 'return_3m' | 'return_6m' | 'return_9m' | 'return_12m' | 'relative_return_score';
  order?: 'asc' | 'desc';
  trade_date?: string;
  exclude_etf?: boolean;
  sector?: string;
}

export interface SectorData {
  sector: string;
  rs_rating: number;
  market: MarketType;
  count: number;
}

// 종목 상세 페이지 관련 타입
export interface DailyPriceItem {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change_rate: number;
}

export interface RsScoreItem {
  trade_date: string;
  rs_rating: number;
  rank_in_market: number;
  return_3m: number;
  return_6m: number;
  return_9m: number;
  return_12m: number;
  relative_return_score: number;
  rs_percentile: number;
}

export interface SymbolDetailResponse {
  symbol: SymbolItem;
  latest_price: DailyPriceItem | null;
  latest_rs: RsScoreItem | null;
  benchmark_name: string | null;
}

export interface RsSeriesResponse {
  code: string;
  name: string;
  market: MarketType;
  rs_scores: RsScoreItem[];
}

export interface PaginatedPricesResponse {
  total_count: number;
  page: number;
  size: number;
  items: DailyPriceItem[];
}

// 크롤링 모니터링 관련 타입
export interface CrawlJobItem {
  id: number;
  job_type: string;
  started_at: string;  // ISO datetime
  finished_at: string | null;
  status: 'running' | 'completed' | 'failed';
  symbols_total: number;
  symbols_succeeded: number;
  symbols_failed: number;
  message: string | null;
  duration_seconds: number | null;
  success_rate: number | null;  // percentage 0-100
}

export interface CrawlFailureItem {
  id: number;
  job_id: number;
  target_type: string;  // 'symbol' | 'benchmark'
  target_key: string;   // stock code
  url: string;
  http_status: number | null;
  error_class: string;
  error_message: string;
  retry_count: number;
  created_at: string;  // ISO datetime
}

export interface CrawlStatsResponse {
  total_jobs: number;
  running_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  total_failures: number;
  latest_job: CrawlJobItem | null;
}

export interface PaginatedCrawlJobsResponse {
  total_count: number;
  page: number;
  size: number;
  items: CrawlJobItem[];
}

export interface PaginatedCrawlFailuresResponse {
  total_count: number;
  page: number;
  size: number;
  items: CrawlFailureItem[];
}
