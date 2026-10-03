'use client';

import { FormEvent, useEffect, useState } from 'react';
import { APIError, fetchAPI } from '@/lib/api/client';

type Run = { run_id: string; status: string; reason?: unknown; metrics?: Record<string, { value: string | null; null_reason?: string | null }> };
type Page<T> = { page: number; size: number; total_count: number; items: T[] };

const starter = JSON.stringify({
  market: 'BOTH', rebalance_interval_trading_days: 5, max_holdings: 10,
  max_position_weight: '0.1', cash_reserve_ratio: '0', buy_fee_rate: '0', sell_fee_rate: '0',
  buy_slippage_rate: '0', sell_slippage_rate: '0',
  buy_conditions: { type: 'group', operator: 'AND', children: [{ type: 'rule', field: 'rs_rating', operator: 'gte', value: '80' }] },
  sell_conditions: { type: 'group', operator: 'OR', children: [{ type: 'rule', field: 'rs_rating', operator: 'lt', value: '70' }] },
}, null, 2);

export default function BacktestsPage() {
  const [csrf, setCsrf] = useState(''); const [password, setPassword] = useState('');
  const [authed, setAuthed] = useState(false); const [name, setName] = useState('새 전략');
  const [configuration, setConfiguration] = useState(starter); const [strategyVersionId, setStrategyVersionId] = useState<number>();
  const [start, setStart] = useState(''); const [end, setEnd] = useState(''); const [runs, setRuns] = useState<Run[]>([]); const [message, setMessage] = useState('');
  const headers = () => ({ 'X-CSRF-Token': csrf });
  const refreshCsrf = async () => { const value = await fetchAPI<{ csrf_token: string }>('/api/v1/backtests/auth/csrf'); setCsrf(value.csrf_token); };
  const refreshRuns = async () => { const page = await fetchAPI<Page<Run>>('/api/v1/backtests/runs'); setRuns(page.items); };
  useEffect(() => { refreshCsrf().catch(() => setMessage('접속 준비에 실패했습니다.')); }, []);
  const login = async (event: FormEvent) => { event.preventDefault(); try { await fetchAPI<void>('/api/v1/backtests/auth/login', { method: 'POST', headers: headers(), body: JSON.stringify({ password }) }); await refreshCsrf(); await refreshRuns(); setAuthed(true); setMessage('운영자 접속이 완료되었습니다.'); } catch (error) { setMessage(error instanceof Error ? error.message : '로그인에 실패했습니다.'); } };
  const save = async () => { try { const config = JSON.parse(configuration); const strategy = await fetchAPI<{ current_version_id: number }>('/api/v1/backtests/strategies', { method: 'POST', headers: headers(), body: JSON.stringify({ name, configuration: config }) }); setStrategyVersionId(strategy.current_version_id); setMessage('전략을 저장했습니다.'); } catch (error) { setMessage(error instanceof Error ? error.message : '전략 저장에 실패했습니다.'); } };
  const run = async () => { if (!strategyVersionId) return setMessage('먼저 전략을 저장하세요.'); try { const result = await fetchAPI<Run>('/api/v1/backtests/runs', { method: 'POST', headers: headers(), body: JSON.stringify({ strategy_version_id: strategyVersionId, start, end }) }); setRuns([result, ...runs]); setMessage('백테스트를 대기열에 넣었습니다.'); } catch (error) { const detail = error instanceof APIError ? error.data?.run : null; if (detail) setRuns([detail, ...runs]); setMessage(error instanceof Error ? error.message : '실행을 시작하지 못했습니다.'); } };
  if (!authed) return <section className="max-w-md space-y-4"><h2 className="text-2xl font-bold">백테스트 운영자 접속</h2><form onSubmit={login} className="space-y-3"><input className="w-full rounded border p-2" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="운영자 비밀번호" required /><button className="rounded bg-blue-600 px-4 py-2 text-white">접속</button></form><p>{message}</p></section>;
  return <section className="space-y-6"><h2 className="text-2xl font-bold">국내 주식 백테스트</h2><p className="text-sm text-gray-600">검증 완료 구간만 사용하며, 결과는 개인 연구용입니다.</p><div className="space-y-3 rounded border bg-white p-4"><input className="w-full rounded border p-2" value={name} onChange={(e) => setName(e.target.value)} /><textarea className="h-80 w-full rounded border p-2 font-mono text-sm" value={configuration} onChange={(e) => setConfiguration(e.target.value)} /><button onClick={save} className="rounded bg-blue-600 px-4 py-2 text-white">전략 저장</button></div><div className="flex gap-2"><input className="rounded border p-2" type="date" value={start} onChange={(e) => setStart(e.target.value)} /><input className="rounded border p-2" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /><button onClick={run} className="rounded bg-green-600 px-4 py-2 text-white">실행</button></div><p>{message}</p><div className="space-y-2">{runs.map((item) => <article key={item.run_id} className="rounded border bg-white p-3"><b>{item.status}</b><span className="ml-3 text-sm">{item.run_id}</span>{item.metrics && <pre className="mt-2 overflow-auto text-xs">{JSON.stringify(item.metrics, null, 2)}</pre>}</article>)}</div></section>;
}
