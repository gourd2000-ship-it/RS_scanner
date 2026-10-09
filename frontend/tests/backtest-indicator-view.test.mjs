import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildIndicatorQueryPath, formatIndicatorCell, indicatorErrorMessage, IndicatorRequestGeneration } from '../app/(dashboard)/backtests/indicator-view-model.ts';

test('indicator query paths preserve required range and optional identity filters', () => {
  const path = buildIndicatorQueryPath('volume_sma', {
    code: '005930', start: '2025-01-02', end: '2025-02-03', instrumentId: '12', seriesId: '45', page: 2,
  });
  assert.equal(path, '/api/v1/backtests/indicators/volume-sma50?code=005930&start=2025-01-02&end=2025-02-03&instrument_id=12&series_id=45&page=2&size=250');
  assert.equal(buildIndicatorQueryPath('atr', {
    code: 'A/B', start: '2025-01-02', end: '2025-01-02', page: 1,
  }), '/api/v1/backtests/indicators/atr14?code=A%2FB&start=2025-01-02&end=2025-01-02&page=1&size=250');
});

test('indicator cells show exact decimal, unit, status, reason, and observation count', () => {
  assert.deepEqual(formatIndicatorCell('volume_sma', {
    trade_date: '2025-01-02', value: '100000.1250', status: 'available', reason_code: null, available_observations: 50,
  }), {
    value: '100000.1250주', status: '사용 가능', reason: '사유 없음', availableObservations: '관측 50개',
  });
  assert.deepEqual(formatIndicatorCell('atr', {
    trade_date: '2025-01-03', value: null, status: 'warming_up', reason_code: 'insufficient_history', available_observations: 9,
  }), {
    value: '값 없음', status: '계산 준비 중', reason: 'insufficient_history', availableObservations: '관측 9개',
  });
});

test('missing API rows are explicit and preserve query failures as failures', () => {
  assert.deepEqual(formatIndicatorCell('atr', undefined), {
    value: '값 없음', status: '행 없음', reason: 'indicator_value_missing', availableObservations: '관측 수 없음',
  });
  assert.deepEqual(formatIndicatorCell('volume_sma', undefined, '시리즈 선택이 필요합니다.'), {
    value: '값 없음', status: '조회 실패', reason: '시리즈 선택이 필요합니다.', availableObservations: '관측 수 없음',
  });
});

test('ambiguous-series and invalid-selection API details stay visible to the operator', () => {
  assert.equal(indicatorErrorMessage(409, { detail: { series_ids: [7, 12] } }), 'series_ids: 7 / 12');
  assert.equal(indicatorErrorMessage(422, { detail: 'series_id does not match instrument' }), 'series_id does not match instrument');
});

test('changing filters invalidates an in-flight response before it can replace current results', () => {
  const requests = new IndicatorRequestGeneration();
  const oldRequest = requests.begin();
  assert.equal(requests.isCurrent(oldRequest), true);
  requests.invalidate();
  const newRequest = requests.begin();
  assert.equal(requests.isCurrent(oldRequest), false);
  assert.equal(requests.isCurrent(newRequest), true);
});
