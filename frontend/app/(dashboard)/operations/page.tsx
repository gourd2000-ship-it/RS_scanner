'use client';

import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Pagination } from '@/components/ui/pagination';
import { JobStatusCard, JobsTable, FailuresTable, RefreshIndicator } from './_components';
import {
  getCrawlStats,
  listCrawlJobs,
  listCrawlFailures,
} from '@/lib/api/crawl';
import type {
  CrawlStatsResponse,
  CrawlJobItem,
  CrawlFailureItem,
} from '@/types/api';

export default function OperationsPage() {
  // Stats
  const [stats, setStats] = useState<CrawlStatsResponse | null>(null);

  // Jobs
  const [jobs, setJobs] = useState<CrawlJobItem[]>([]);
  const [jobsPage, setJobsPage] = useState(1);
  const [jobsSize] = useState(20);
  const [jobsTotal, setJobsTotal] = useState(0);
  const [jobStatusFilter, setJobStatusFilter] = useState<'running' | 'completed' | 'failed' | null>(null);

  // Failures
  const [failures, setFailures] = useState<CrawlFailureItem[]>([]);
  const [failuresPage, setFailuresPage] = useState(1);
  const [failuresSize] = useState(50);
  const [failuresTotal, setFailuresTotal] = useState(0);

  // UI State
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);

  // Fetch stats
  const fetchStats = async () => {
    setIsRefreshing(true);
    try {
      const data = await getCrawlStats();
      setStats(data);
      setLastRefresh(new Date());
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Fetch jobs
  const fetchJobs = async () => {
    setLoading(true);
    try {
      const response = await listCrawlJobs(jobsPage, jobsSize, jobStatusFilter || undefined);
      setJobs(response.items);
      setJobsTotal(response.total_count);
    } catch (error) {
      console.error('Failed to fetch jobs:', error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch failures
  const fetchFailures = async () => {
    try {
      const response = await listCrawlFailures(failuresPage, failuresSize);
      setFailures(response.items);
      setFailuresTotal(response.total_count);
    } catch (error) {
      console.error('Failed to fetch failures:', error);
    }
  };

  // Initial load
  useEffect(() => {
    fetchStats();
    fetchJobs();
    fetchFailures();
  }, []);

  // Refetch jobs when page or filter changes
  useEffect(() => {
    fetchJobs();
  }, [jobStatusFilter, jobsPage]);

  // Refetch failures when page changes
  useEffect(() => {
    fetchFailures();
  }, [failuresPage]);

  // Auto-refresh stats every 10 seconds
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      fetchStats();
    }, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh]);

  const handleRefresh = () => {
    fetchStats();
    fetchJobs();
    fetchFailures();
  };

  const handleJobsPageChange = (page: number) => {
    setJobsPage(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleFailuresPageChange = (page: number) => {
    setFailuresPage(page);
  };

  const jobsTotalPages = Math.ceil(jobsTotal / jobsSize);
  const failuresTotalPages = Math.ceil(failuresTotal / failuresSize);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">운영 모니터링</h1>
        <RefreshIndicator
          lastRefresh={lastRefresh}
          isRefreshing={isRefreshing}
          onRefresh={handleRefresh}
        />
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Latest Job Card */}
        {stats?.latest_job && (
          <JobStatusCard job={stats.latest_job} />
        )}

        {/* Summary Stats Card */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">전체 통계</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-600">전체 작업</span>
                <span className="text-2xl font-bold">{stats?.total_jobs || 0}</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div className="text-center p-2 bg-blue-50 rounded">
                  <div className="text-gray-600 text-xs">실행중</div>
                  <div className="font-semibold text-blue-700">{stats?.running_jobs || 0}</div>
                </div>
                <div className="text-center p-2 bg-green-50 rounded">
                  <div className="text-gray-600 text-xs">완료</div>
                  <div className="font-semibold text-green-700">{stats?.completed_jobs || 0}</div>
                </div>
                <div className="text-center p-2 bg-red-50 rounded">
                  <div className="text-gray-600 text-xs">실패</div>
                  <div className="font-semibold text-red-700">{stats?.failed_jobs || 0}</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Failures Summary Card */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">최근 실패</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <span className="text-gray-600">전체 실패 횟수</span>
              <span className="text-3xl font-bold text-red-600">{stats?.total_failures || 0}</span>
            </div>
            {failures.length > 0 && (
              <div className="mt-4 pt-4 border-t space-y-2">
                <div className="text-sm text-gray-600">최근 실패</div>
                {failures.slice(0, 3).map((failure) => (
                  <div key={failure.id} className="flex justify-between text-xs">
                    <span className="font-mono">{failure.target_key}</span>
                    <span className="text-gray-500">{failure.error_class.split('.').pop()}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Jobs Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold">작업 이력</h2>

          {/* Status Filter */}
          <div className="flex gap-2">
            <button
              onClick={() => setJobStatusFilter(null)}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                jobStatusFilter === null
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              전체
            </button>
            <button
              onClick={() => setJobStatusFilter('running')}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                jobStatusFilter === 'running'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              실행중
            </button>
            <button
              onClick={() => setJobStatusFilter('completed')}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                jobStatusFilter === 'completed'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              완료
            </button>
            <button
              onClick={() => setJobStatusFilter('failed')}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                jobStatusFilter === 'failed'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              실패
            </button>
          </div>
        </div>

        <JobsTable jobs={jobs} loading={loading} />

        {jobsTotalPages > 1 && (
          <Pagination
            currentPage={jobsPage}
            totalPages={jobsTotalPages}
            totalItems={jobsTotal}
            itemsPerPage={jobsSize}
            onPageChange={handleJobsPageChange}
          />
        )}
      </div>

      {/* Failures Section */}
      <div className="space-y-4">
        <h2 className="text-2xl font-bold">최근 실패 목록</h2>

        <FailuresTable failures={failures} />

        {failuresTotalPages > 1 && (
          <Pagination
            currentPage={failuresPage}
            totalPages={failuresTotalPages}
            totalItems={failuresTotal}
            itemsPerPage={failuresSize}
            onPageChange={handleFailuresPageChange}
          />
        )}
      </div>
    </div>
  );
}
