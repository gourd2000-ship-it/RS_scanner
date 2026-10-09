import type { BacktestIndicatorDailyItem, BacktestIndicatorKind } from '@/types/api';

export const INDICATOR_PAGE_SIZE = 250;

export class IndicatorRequestGeneration {
  private current = 0;

  begin(): number {
    this.current += 1;
    return this.current;
  }

  invalidate(): void {
    this.current += 1;
  }

  isCurrent(requestId: number): boolean {
    return this.current === requestId;
  }
}

function describe(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(describe).filter(Boolean).join(' / ');
  if (typeof value === 'object') return Object.entries(value).map(([key, child]) => `${key}: ${describe(child)}`).join(', ');
  return String(value);
}

export function indicatorErrorMessage(status: number, body: unknown): string {
  const detail = body && typeof body === 'object' && 'detail' in body ? describe(body.detail) : '';
  if (status === 401) return '운영자 로그인이 필요합니다. 다시 로그인해주세요.';
  if (status === 403) return '운영자 세션이 만료되었습니다. 다시 로그인해주세요.';
  if (status === 404) return detail || '종목 또는 계산된 현재 지표 시리즈를 찾지 못했습니다.';
  if (status === 409) return detail || '여러 종목 또는 지표 시리즈가 일치합니다. 안내된 ID를 입력한 뒤 다시 조회해주세요.';
  if (status === 422) return detail || '조회 조건이나 선택한 ID를 확인해주세요.';
  if (status === 503) return '조회 서비스가 준비되지 않았습니다. 잠시 후 다시 시도해주세요.';
  return detail || '지표를 조회하지 못했습니다. 잠시 후 다시 시도해주세요.';
}

export function buildIndicatorQueryPath(kind: BacktestIndicatorKind, input: {
  code: string;
  start: string;
  end: string;
  instrumentId?: string;
  seriesId?: string;
  page: number;
}): string {
  const params = new URLSearchParams({
    code: input.code,
    start: input.start,
    end: input.end,
  });
  if (input.instrumentId) params.set('instrument_id', input.instrumentId);
  if (input.seriesId) params.set('series_id', input.seriesId);
  params.set('page', String(input.page));
  params.set('size', String(INDICATOR_PAGE_SIZE));
  const route = kind === 'volume_sma' ? 'volume-sma50' : 'atr14';
  return `/api/v1/backtests/indicators/${route}?${params.toString()}`;
}

export function formatIndicatorCell(
  kind: BacktestIndicatorKind,
  item?: BacktestIndicatorDailyItem,
  queryError?: string,
): { value: string; status: string; reason: string; availableObservations: string } {
  const unit = kind === 'volume_sma' ? '주' : '원';
  if (queryError) {
    return { value: '값 없음', status: '조회 실패', reason: queryError, availableObservations: '관측 수 없음' };
  }
  if (!item) {
    return { value: '값 없음', status: '행 없음', reason: 'indicator_value_missing', availableObservations: '관측 수 없음' };
  }
  const status = ({
    available: '사용 가능',
    warming_up: '계산 준비 중',
    data_unavailable: '사용 불가',
  } as Record<string, string>)[item.status] ?? item.status;
  return {
    value: item.value === null ? '값 없음' : `${item.value}${unit}`,
    status,
    reason: item.reason_code ?? '사유 없음',
    availableObservations: `관측 ${item.available_observations}개`,
  };
}
