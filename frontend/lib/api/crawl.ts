/**
 * Crawl API 클라이언트
 */

import { buildQueryString, fetchAPI } from './client';
import type {
  CrawlStatsResponse,
  PaginatedCrawlJobsResponse,
  CrawlJobItem,
  PaginatedCrawlFailuresResponse,
} from '@/types/api';

/**
 * 크롤링 통계 조회
 */
export async function getCrawlStats(): Promise<CrawlStatsResponse> {
  return fetchAPI<CrawlStatsResponse>('/api/v1/crawl/stats');
}

/**
 * 크롤링 작업 목록 조회
 */
export async function listCrawlJobs(
  page = 1,
  size = 20,
  status?: 'running' | 'completed' | 'failed'
): Promise<PaginatedCrawlJobsResponse> {
  const query = buildQueryString({ page, size, status });
  return fetchAPI<PaginatedCrawlJobsResponse>(`/api/v1/crawl/jobs${query}`);
}

/**
 * 크롤링 작업 상세 조회
 */
export async function getCrawlJob(jobId: number): Promise<CrawlJobItem> {
  return fetchAPI<CrawlJobItem>(`/api/v1/crawl/jobs/${jobId}`);
}

/**
 * 크롤링 실패 목록 조회
 */
export async function listCrawlFailures(
  page = 1,
  size = 50,
  jobId?: number
): Promise<PaginatedCrawlFailuresResponse> {
  const query = buildQueryString({ page, size, job_id: jobId });
  return fetchAPI<PaginatedCrawlFailuresResponse>(`/api/v1/crawl/failures${query}`);
}
