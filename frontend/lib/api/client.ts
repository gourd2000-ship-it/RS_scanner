/**
 * API 클라이언트
 * FastAPI 백엔드와 통신하는 기본 fetch wrapper
 */

import { env } from '@/config/env';

const API_BASE_URL = env.NEXT_PUBLIC_API_URL;

export class APIError extends Error {
  constructor(
    public status: number,
    message: string,
    public data?: unknown
  ) {
    super(message);
    this.name = 'APIError';
  }
}

export async function fetchAPI<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  try {
    const res = await fetch(url, {
      credentials: 'include',
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });

    if (!res.ok) {
      const errorData: unknown = await res.json().catch(() => ({}));
      const detail = errorData && typeof errorData === 'object' && 'detail' in errorData
        ? errorData.detail
        : undefined;
      throw new APIError(
        res.status,
        typeof detail === 'string' ? detail : detail == null ? `API Error: ${res.status} ${res.statusText}` : JSON.stringify(detail) ?? String(detail),
        errorData
      );
    }

    return res.json();
  } catch (error) {
    if (error instanceof APIError) {
      throw error;
    }
    throw new Error(`Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/**
 * URL 쿼리 파라미터 생성
 */
type QueryParamValue = string | number | boolean | null | undefined;

export function buildQueryString<T extends { [K in keyof T]: QueryParamValue }>(params: T): string {
  const searchParams = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  });

  const queryString = searchParams.toString();
  return queryString ? `?${queryString}` : '';
}
