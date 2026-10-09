'use client';

import { FormEvent, useRef, useState } from 'react';
import type { BacktestIndicatorDailyItem, BacktestIndicatorKind, BacktestIndicatorQueryResponse } from '@/types/api';
import { buttonClass, inputClass } from './condition-editor';
import { buildIndicatorQueryPath, formatIndicatorCell, indicatorErrorMessage, IndicatorRequestGeneration, INDICATOR_PAGE_SIZE } from './indicator-view-model';

type QueryResult = { data: BacktestIndicatorQueryResponse | null; error: string; queried: boolean };
type QueryFilters = { code: string; start: string; end: string; instrumentId: string; seriesId: string; page: number };
type HttpFailure = { status: number; body: unknown };
const emptyResult = (): QueryResult => ({ data: null, error: '', queried: false });

async function fetchIndicator(kind: BacktestIndicatorKind, filters: QueryFilters): Promise<BacktestIndicatorQueryResponse> {
  const path = buildIndicatorQueryPath(kind, {
    ...filters,
    seriesId: filters.seriesId || undefined,
    instrumentId: filters.instrumentId || undefined,
  });
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw { status: response.status, body } satisfies HttpFailure;
  return body as BacktestIndicatorQueryResponse;
}

function IndicatorSummary({ title, result }: { title: string; result: QueryResult }) {
  if (!result.queried) return <p className="text-sm text-slate-500">아직 조회하지 않았습니다.</p>;
  if (result.error) return <p role="alert" className="text-sm text-rose-700">{result.error}</p>;
  const data = result.data;
  if (!data) return null;
  return <div className="space-y-2 text-xs text-slate-600">
    <p><strong>{title}</strong> · period {data.period} · {data.formula_version}</p>
    <p>현재 series {data.series_id} · generation {data.generation} (ID {data.generation_id}) · 기준일 {data.as_of} · 계산 시각 {data.calculated_at}</p>
    <p>instrument {data.instrument_id} · {data.source_provider} · adjustment {data.adjustment_policy}</p>
    <details>
      <summary className="cursor-pointer">source policy fingerprint 보기</summary>
      <code className="mt-1 block break-all text-[11px]">{data.source_policy_fingerprint}</code>
    </details>
  </div>;
}

function IndicatorCell({ kind, item, error }: { kind: BacktestIndicatorKind; item?: BacktestIndicatorDailyItem; error?: string }) {
  const cell = formatIndicatorCell(kind, item, error);
  const available = cell.status === '사용 가능';
  return <div className="min-w-40 space-y-1">
    <div className="flex flex-wrap items-center gap-2">
      <strong className="font-semibold tabular-nums">{cell.value}</strong>
      <span className={`rounded-full px-2 py-0.5 text-[11px] ${available ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>{cell.status}</span>
    </div>
    <p className="break-words text-xs text-slate-500">사유: {cell.reason}</p>
    <p className="text-xs text-slate-500">{cell.availableObservations}</p>
  </div>;
}

export default function IndicatorBrowser({ onAuthExpired }: { onAuthExpired: () => void }) {
  const [code, setCode] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [instrumentId, setInstrumentId] = useState('');
  const [volumeSeriesId, setVolumeSeriesId] = useState('');
  const [atrSeriesId, setAtrSeriesId] = useState('');
  const [page, setPage] = useState(1);
  const [volume, setVolume] = useState<QueryResult>(emptyResult);
  const [atr, setAtr] = useState<QueryResult>(emptyResult);
  const [searchError, setSearchError] = useState('');
  const [busy, setBusy] = useState(false);
  const requestGeneration = useRef(new IndicatorRequestGeneration());

  function clearResults() {
    requestGeneration.current.invalidate();
    setBusy(false);
    setPage(1);
    setVolume(emptyResult());
    setAtr(emptyResult());
    setSearchError('');
  }

  function updateText(setter: (value: string) => void, value: string) {
    setter(value);
    clearResults();
  }

  async function lookup(targetPage: number) {
    setSearchError('');
    const normalizedCode = code.trim();
    if (!normalizedCode) { setSearchError('종목 코드를 입력해주세요.'); clearResults(); return; }
    if (!start || !end || end < start) { setSearchError('시작일과 종료일을 확인해주세요.'); clearResults(); return; }
    for (const [label, value] of [['instrument ID', instrumentId], ['MA50 series ID', volumeSeriesId], ['ATR14 series ID', atrSeriesId]]) {
      if (value.trim() && !/^[1-9]\d*$/.test(value.trim())) {
        setSearchError(`${label}는 1 이상의 정수여야 합니다.`); clearResults(); return;
      }
    }

    const requestId = requestGeneration.current.begin();
    setBusy(true);
    const common = {
      code: normalizedCode, start, end, instrumentId: instrumentId.trim(), page: targetPage,
    };
    const outcomes = await Promise.allSettled([
      fetchIndicator('volume_sma', { ...common, seriesId: volumeSeriesId.trim() }),
      fetchIndicator('atr', { ...common, seriesId: atrSeriesId.trim() }),
    ]);
    if (!requestGeneration.current.isCurrent(requestId)) return;
    const resultFor = (outcome: typeof outcomes[number]): QueryResult => {
      if (outcome.status === 'fulfilled') return { data: outcome.value, error: '', queried: true };
      const failure = outcome.reason as HttpFailure;
      if (failure?.status === 401 || failure?.status === 403) onAuthExpired();
      return { data: null, error: indicatorErrorMessage(failure?.status ?? 0, failure?.body), queried: true };
    };
    setPage(targetPage);
    setVolume(resultFor(outcomes[0]));
    setAtr(resultFor(outcomes[1]));
    setBusy(false);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void lookup(1);
  }

  const dates = [...new Set([
    ...(volume.data?.items ?? []).map(item => item.trade_date),
    ...(atr.data?.items ?? []).map(item => item.trade_date),
  ])].sort();
  const volumeByDate = new Map((volume.data?.items ?? []).map(item => [item.trade_date, item]));
  const atrByDate = new Map((atr.data?.items ?? []).map(item => [item.trade_date, item]));
  const totalPages = Math.max(
    Math.ceil((volume.data?.total_count ?? 0) / INDICATOR_PAGE_SIZE),
    Math.ceil((atr.data?.total_count ?? 0) / INDICATOR_PAGE_SIZE),
  );
  const canNext = [volume.data, atr.data].some(data => data && page * INDICATOR_PAGE_SIZE < data.total_count);

  return <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
    <div>
      <h2 className="text-lg font-semibold">MA50·ATR14 날짜별 조회</h2>
      <p className="mt-1 text-sm text-slate-600">아래 값은 조회 시점의 현재 generation입니다. 과거 백테스트에 사용된 값이 아니며, 지표 조건을 쓴 실행은 실행 기록에 표시되는 snapshot ID와 hash로 입력을 고정합니다.</p>
    </div>
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <label className="text-sm font-medium">종목 코드
        <input className={`${inputClass} mt-1`} value={code} maxLength={20} onChange={event => updateText(setCode, event.target.value)} placeholder="예: 005930" required />
      </label>
      <label className="text-sm font-medium">시작일
        <input className={`${inputClass} mt-1`} type="date" value={start} onChange={event => updateText(setStart, event.target.value)} required />
      </label>
      <label className="text-sm font-medium">종료일
        <input className={`${inputClass} mt-1`} type="date" value={end} min={start || undefined} onChange={event => updateText(setEnd, event.target.value)} required />
      </label>
      <label className="text-sm font-medium">Instrument ID <span className="font-normal text-slate-500">(종목 모호성 해소 시)</span>
        <input className={`${inputClass} mt-1`} inputMode="numeric" value={instrumentId} onChange={event => updateText(setInstrumentId, event.target.value)} placeholder="선택" />
      </label>
      <label className="text-sm font-medium">MA50 series ID <span className="font-normal text-slate-500">(시리즈 모호성 해소 시)</span>
        <input className={`${inputClass} mt-1`} inputMode="numeric" value={volumeSeriesId} onChange={event => updateText(setVolumeSeriesId, event.target.value)} placeholder="선택" />
      </label>
      <label className="text-sm font-medium">ATR14 series ID <span className="font-normal text-slate-500">(시리즈 모호성 해소 시)</span>
        <input className={`${inputClass} mt-1`} inputMode="numeric" value={atrSeriesId} onChange={event => updateText(setAtrSeriesId, event.target.value)} placeholder="선택" />
      </label>
      <div className="flex items-end gap-3 sm:col-span-2 lg:col-span-3">
        <button type="submit" className={buttonClass} disabled={busy}>{busy ? '조회 중…' : '현재 지표 조회'}</button>
        <span className="text-xs text-slate-500">포함 기간 · 페이지당 {INDICATOR_PAGE_SIZE}건</span>
      </div>
    </form>
    {searchError && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{searchError}</p>}
    {(volume.queried || atr.queried) && <div className="grid gap-3 rounded-lg bg-slate-50 p-3 sm:grid-cols-2">
      <IndicatorSummary title="거래량 MA50" result={volume} />
      <IndicatorSummary title="ATR14" result={atr} />
    </div>}
    {dates.length > 0 ? <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full min-w-[760px] border-collapse text-left text-sm">
        <caption className="sr-only">현재 generation의 Volume MA50 및 ATR14 날짜별 값과 상태</caption>
        <thead className="bg-slate-50 text-xs text-slate-600">
          <tr><th scope="col" className="px-4 py-3">거래일</th><th scope="col" className="px-4 py-3">거래량 MA50 (주)</th><th scope="col" className="px-4 py-3">ATR14 (원)</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {dates.map(date => <tr key={date}>
            <th scope="row" className="whitespace-nowrap px-4 py-3 font-medium">{date}</th>
            <td className="px-4 py-3"><IndicatorCell kind="volume_sma" item={volumeByDate.get(date)} error={volume.error || undefined} /></td>
            <td className="px-4 py-3"><IndicatorCell kind="atr" item={atrByDate.get(date)} error={atr.error || undefined} /></td>
          </tr>)}
        </tbody>
      </table>
    </div> : (volume.queried || atr.queried) && !searchError && <p className="py-4 text-sm text-slate-500">요청한 기간에 반환된 날짜 행이 없습니다. 조회 오류와 현재 series 상태를 확인해주세요.</p>}
    {totalPages > 1 && <div className="flex items-center gap-3 text-sm">
      <button type="button" className={buttonClass} disabled={busy || page <= 1} onClick={() => void lookup(page - 1)}>이전</button>
      <span>{page} / {totalPages}</span>
      <button type="button" className={buttonClass} disabled={busy || !canNext} onClick={() => void lookup(page + 1)}>다음</button>
    </div>}
  </section>;
}
