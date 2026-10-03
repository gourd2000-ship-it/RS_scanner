'use client';

import { FormEvent, useState } from 'react';
import ConditionEditor, { buttonClass, inputClass } from './condition-editor';
import { decodeDraft, Draft, encodeDraft, initialDraft } from './form-model';

type Page<T> = { page: number; size: number; total_count: number; items: T[] };
type Version = { version_id: number; version_number: number; configuration: unknown };
type Strategy = { strategy_id: string; name: string; current_version_id: number; versions: Version[] };
type Run = { run_id: string; status: string; start: string; end: string; reason?: unknown };
const base = '/api/v1/backtests';
const primary = 'rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50';
const statusNames: Record<string, string> = { queued: '대기 중', running: '실행 중', completed: '완료', data_unavailable: '검증 데이터 부족', failed: '실패', cancelled: '취소됨' };

class RequestError extends Error {
  constructor(public status: number, public body: unknown) {
    super(status === 401 ? '로그인이 필요하거나 비밀번호가 올바르지 않습니다.' : status === 403 ? '접속 정보가 만료되었습니다. 다시 로그인해주세요.' : status === 429 ? '요청이 많습니다. 잠시 후 다시 시도해주세요.' : status === 503 ? '서비스가 준비되지 않았습니다. 잠시 후 다시 시도해주세요.' : '요청을 처리하지 못했습니다. 입력값을 확인해주세요.');
  }
}
async function request<T>(path: string, method = 'GET', body?: unknown, csrf?: string): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = response.status === 204 ? undefined : await response.json();
  if (!response.ok) throw new RequestError(response.status, data);
  return data as T;
}
function reasonText(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(reasonText).filter(Boolean).join(' / ');
  if (typeof value === 'object') return Object.entries(value).map(([key, v]) => `${key}: ${reasonText(v)}`).join(', ');
  return String(value);
}

function NumberField({ label, value, onChange, unit, optional = false, min = 0, max, integer = false, hint }: {
  label: string; value: string; onChange: (value: string) => void; unit: string; optional?: boolean;
  min?: number; max?: number; integer?: boolean; hint?: string;
}) {
  return <label className="block space-y-1.5 text-sm font-medium text-slate-700">
    <span>{label} <span className="font-normal text-slate-500">({unit})</span></span>
    <input className={inputClass} type="number" value={value} min={min} max={max} step={integer ? 1 : 'any'} required={!optional}
      placeholder={optional ? '사용 안 함' : undefined} onChange={e => onChange(e.target.value)} />
    {hint && <span className="block text-xs font-normal text-slate-500">{hint}</span>}
  </label>;
}

export default function BacktestsPage() {
  const [csrf, setCsrf] = useState('');
  const [password, setPassword] = useState('');
  const [authed, setAuthed] = useState(false);
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [name, setName] = useState('RS 추세 전략');
  const [strategies, setStrategies] = useState<Page<Strategy>>({ page: 1, size: 20, total_count: 0, items: [] });
  const [selected, setSelected] = useState<Strategy | null>(null);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [runs, setRuns] = useState<Page<Run>>({ page: 1, size: 10, total_count: 0, items: [] });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  function change<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft(previous => ({ ...previous, [key]: value })); setSavedVersion(null);
  }
  function fail(value: unknown) {
    setError(value instanceof Error ? value.message : '요청에 실패했습니다. 잠시 후 다시 시도해주세요.');
    if (value instanceof RequestError && [401, 403].includes(value.status)) { setAuthed(false); setCsrf(''); }
  }
  async function action(work: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await work(); } catch (e) { fail(e); } finally { setBusy(false); }
  }
  async function refresh(strategyPage = strategies.page, runPage = runs.page) {
    const [s, r] = await Promise.all([
      request<Page<Strategy>>(`/strategies?page=${strategyPage}&size=20`), request<Page<Run>>(`/runs?page=${runPage}&size=10`),
    ]);
    setStrategies(s); setRuns(r);
  }
  function load(strategy: Strategy, versionId = strategy.current_version_id) {
    const version = strategy.versions.find(v => v.version_id === versionId);
    if (!version) { setError('저장된 전략 버전을 찾지 못했습니다.'); return; }
    try {
      const next = decodeDraft(version.configuration);
      setDraft(next); setName(strategy.name); setSelected(strategy); setSavedVersion(versionId); setLoadedVersion(versionId);
      setError(''); setMessage(`${strategy.name} · 버전 ${version.version_number}을 불러왔습니다.`);
    } catch { setError('이 전략의 설정을 불러올 수 없습니다. 원본 전략은 변경되지 않았습니다.'); }
  }
  function reset() {
    setDraft(initialDraft()); setName('RS 추세 전략'); setSelected(null); setSavedVersion(null); setLoadedVersion(null); setMessage('새 전략을 작성합니다.'); setError('');
  }
  function login(event: FormEvent) {
    event.preventDefault();
    void action(async () => {
      const preauth = await request<{ csrf_token: string }>('/auth/csrf');
      const auth = await request<{ csrf_token: string }>('/auth/login', 'POST', { password }, preauth.csrf_token);
      // Login returns the CSRF value bound to the new operator session.
      setCsrf(auth.csrf_token); setPassword(''); setAuthed(true); await refresh();
    });
  }
  function save(event: FormEvent) {
    event.preventDefault();
    void action(async () => {
      const configuration = encodeDraft(draft);
      if (!name.trim()) throw new Error('전략 이름을 입력해주세요.');
      if (selected) {
        const version = await request<Version>(`/strategies/${selected.strategy_id}/versions`, 'POST', { configuration }, csrf);
        setSavedVersion(version.version_id); setLoadedVersion(version.version_id);
        setSelected({ ...selected, current_version_id: version.version_id, versions: [...selected.versions, version] });
      } else {
        const strategy = await request<Strategy>('/strategies', 'POST', { name: name.trim(), configuration }, csrf);
        setSelected(strategy); setSavedVersion(strategy.current_version_id); setLoadedVersion(strategy.current_version_id);
      }
      setMessage('전략을 저장했습니다. 아래에서 기간을 지정하고 실행하세요.');
      setStrategies(await request<Page<Strategy>>('/strategies?page=1&size=20'));
    });
  }
  function run(event: FormEvent) {
    event.preventDefault();
    void action(async () => {
      if (!savedVersion) throw new Error('변경한 조건을 먼저 저장해주세요.');
      if (!start || !end || start >= end) throw new Error('종료일은 시작일보다 뒤여야 합니다.');
      try {
        await request<Run>('/runs', 'POST', { strategy_version_id: savedVersion, start, end }, csrf);
        setMessage('실행을 요청했습니다. 실행 기록에서 상태를 확인하세요.');
      } catch (e) {
        if (!(e instanceof RequestError) || e.status !== 409) throw e;
        setError(`검증된 데이터가 부족하여 실행하지 못했습니다. ${reasonText(e.body && typeof e.body === 'object' && 'reason' in e.body ? e.body.reason : null)}`);
      }
      setRuns(await request<Page<Run>>('/runs?page=1&size=10'));
    });
  }
  const notice = <div aria-live="polite">{error && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}{message && <p role="status" className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-800">{message}</p>}</div>;

  if (!authed) return <section className="mx-auto max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
    <p className="text-xs font-semibold tracking-widest text-blue-600">RS SCANNER</p>
    <h1 className="mb-2 mt-3 text-2xl font-bold">백테스트 운영자 접속</h1>
    <p className="mb-6 text-sm text-slate-500">저장된 전략을 불러오거나 새로운 매매 조건을 만들어보세요.</p>
    <form onSubmit={login} className="space-y-4"><label className="block text-sm font-medium">운영자 비밀번호
      <input className={`${inputClass} mt-2`} type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required />
    </label><button disabled={busy} className={`${primary} w-full`}>{busy ? '접속 중…' : '접속'}</button></form><div className="mt-4">{notice}</div>
  </section>;

  return <section className="space-y-6 text-slate-900">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-2xl font-bold">국내 주식 백테스트</h1><p className="mt-1 text-sm text-slate-500">조건을 선택하고, 저장한 전략으로 과거 성과를 확인하세요.</p></div>
      <button className={buttonClass} disabled={busy} onClick={() => void action(async () => { await request('/auth/logout', 'POST', undefined, csrf); setAuthed(false); setCsrf(''); })}>로그아웃</button>
    </header>
    {notice}
    <fieldset disabled={busy} className="space-y-6">
      <div className="grid gap-3 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-[1fr_auto]">
        <label className="text-sm font-medium">저장된 전략 불러오기
          <select className={`${inputClass} mt-2`} value={strategies.items.some(s => s.strategy_id === selected?.strategy_id) ? selected!.strategy_id : ''} onChange={e => { const s = strategies.items.find(s => s.strategy_id === e.target.value); if (s) load(s); }}>
            <option value="" disabled>전략을 선택하세요</option>{strategies.items.map(s => <option key={s.strategy_id} value={s.strategy_id}>{s.name}</option>)}
          </select>
        </label><button type="button" onClick={reset} className={`${buttonClass} self-end`}>+ 새 전략</button>
        {strategies.total_count > 20 && <div className="flex items-center gap-3 text-sm"><button className={buttonClass} disabled={strategies.page === 1} onClick={() => void action(() => refresh(strategies.page - 1))}>이전 전략</button><span>{strategies.page} / {Math.ceil(strategies.total_count / 20)}</span><button className={buttonClass} disabled={strategies.page * 20 >= strategies.total_count} onClick={() => void action(() => refresh(strategies.page + 1))}>다음 전략</button></div>}
        {selected && <label className="text-sm">저장 버전<select className={`${inputClass} mt-1`} value={loadedVersion ?? ''} onChange={e => load(selected, Number(e.target.value))}>{selected.versions.map(v => <option key={v.version_id} value={v.version_id}>버전 {v.version_number}</option>)}</select></label>}
      </div>
      <form onSubmit={save} className="space-y-5">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="mb-4 text-lg font-semibold">1. 기본 설정</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <label className="space-y-1.5 text-sm font-medium">전략 이름<input className={inputClass} value={name} maxLength={255} required readOnly={!!selected} onChange={e => { setName(e.target.value); setSavedVersion(null); }} /></label>
            <label className="space-y-1.5 text-sm font-medium">대상 시장<select className={inputClass} value={draft.market} onChange={e => change('market', e.target.value as Draft['market'])}><option value="BOTH">KOSPI + KOSDAQ</option><option value="KOSPI">KOSPI</option><option value="KOSDAQ">KOSDAQ</option></select></label>
            <div className="rounded-lg bg-slate-50 p-3 text-sm"><span className="block text-slate-500">최초 투자금 · 동일 비중</span><strong className="text-lg">10,000,000원</strong></div>
            <NumberField label="매수 검토 주기" unit="거래일" min={1} integer value={draft.interval} onChange={v => change('interval', v)} hint="매도 조건은 주기와 관계없이 매일 확인합니다." />
            <NumberField label="최대 보유 종목" unit="개" min={1} integer value={draft.holdings} onChange={v => change('holdings', v)} />
            <NumberField label="종목별 최대 비중" unit="%" min={0.0001} max={100} value={draft.weight} onChange={v => change('weight', v)} />
            <NumberField label="최소 현금 비중" unit="%" max={99.9999} value={draft.reserve} onChange={v => change('reserve', v)} hint="남은 현금은 다른 종목에 재배분하지 않습니다." />
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="mb-1 text-lg font-semibold">2. 매수·매도 조건</h2><p className="mb-4 text-sm text-slate-500">지표와 기준을 선택하세요. 묶음을 추가하면 AND와 OR를 함께 사용할 수 있습니다.</p>
          <div className="grid items-start gap-4 xl:grid-cols-2"><ConditionEditor label="매수 조건" node={draft.buy} onChange={v => change('buy', v)} /><ConditionEditor label="매도 조건" node={draft.sell} onChange={v => change('sell', v)} /></div>
          <p className="mt-3 text-xs text-slate-500">종가로 신호를 확인하고 다음 거래일 시가에 체결합니다. 매도 후 매수하며, 종료일에는 종가로 전량 청산합니다.</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="mb-1 text-lg font-semibold">3. 청산과 거래 비용</h2><p className="mb-4 text-sm text-slate-500">손절·익절·최대 보유 기간은 비워두면 사용하지 않습니다. 비율은 % 단위입니다.</p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <NumberField label="손절" unit="% 손실" optional min={0.0001} max={100} value={draft.stop} onChange={v => change('stop', v)} hint="예: 5 입력 → 매수가 대비 5% 하락 시 신호" />
            <NumberField label="익절" unit="% 이익" optional min={0.0001} value={draft.take} onChange={v => change('take', v)} />
            <NumberField label="최대 보유 기간" unit="거래일" optional integer min={1} value={draft.maxDays} onChange={v => change('maxDays', v)} />
            <NumberField label="매수 수수료" unit="%" max={99.9999} value={draft.buyFee} onChange={v => change('buyFee', v)} />
            <NumberField label="매도 수수료" unit="%" max={99.9999} value={draft.sellFee} onChange={v => change('sellFee', v)} />
            <NumberField label="매수 슬리피지" unit="%" max={99.9999} value={draft.buySlippage} onChange={v => change('buySlippage', v)} />
            <NumberField label="매도 슬리피지" unit="%" max={99.9999} value={draft.sellSlippage} onChange={v => change('sellSlippage', v)} />
          </div><p className="mt-3 text-xs text-slate-500">슬리피지는 체결 가격의 불리한 차이를 반영합니다. 예: 0.1 입력 → 매수 가격 +0.1%, 매도 가격 −0.1%. 세금은 계산하지 않습니다.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3"><button className={primary} type="submit">{busy ? '처리 중…' : selected ? '새 버전으로 저장' : '전략 저장'}</button><span className="text-sm text-slate-500">{savedVersion ? '저장 완료 · 실행할 수 있습니다.' : '입력하거나 수정한 조건을 먼저 저장하세요.'}</span></div>
      </form>
      <form onSubmit={run} className="space-y-4 rounded-xl border border-blue-200 bg-blue-50/50 p-5">
        <h2 className="text-lg font-semibold">4. 기간 선택과 실행</h2><div className="grid gap-4 sm:grid-cols-3"><label className="text-sm font-medium">시작일<input className={`${inputClass} mt-1`} type="date" required value={start} onChange={e => setStart(e.target.value)} /></label><label className="text-sm font-medium">종료일<input className={`${inputClass} mt-1`} type="date" required value={end} min={start || undefined} onChange={e => setEnd(e.target.value)} /></label><button type="submit" className={`${primary} self-end`} disabled={!savedVersion || !start || !end || start >= end}>백테스트 실행</button></div><p className="text-xs text-slate-600">양쪽 날짜 모두 거래일이어야 합니다. 검증 완료 구간만 사용하며 결과에는 KOSPI·KOSDAQ을 모두 비교합니다.</p>
      </form>
      <div className="rounded-xl border border-slate-200 bg-white p-5"><div className="mb-3 flex justify-between"><h2 className="text-lg font-semibold">실행 기록</h2><button className={buttonClass} onClick={() => void action(() => refresh())}>새로고침</button></div>
        {!runs.items.length && <p className="py-4 text-sm text-slate-500">아직 실행 기록이 없습니다.</p>}
        <ul className="divide-y divide-slate-100">{runs.items.map(item => <li key={item.run_id} className="space-y-1 py-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><strong>{statusNames[item.status] ?? item.status}</strong><span>{item.start} ~ {item.end}</span></div>{item.reason != null && <p className="break-words text-rose-700">{reasonText(item.reason)}</p>}<p className="break-all text-xs text-slate-400">실행 번호: {item.run_id}</p></li>)}</ul>
        {runs.total_count > 10 && <div className="mt-3 flex items-center gap-3 text-sm"><button className={buttonClass} disabled={runs.page === 1} onClick={() => void action(() => refresh(strategies.page, runs.page - 1))}>이전 기록</button><span>{runs.page} / {Math.ceil(runs.total_count / 10)}</span><button className={buttonClass} disabled={runs.page * 10 >= runs.total_count} onClick={() => void action(() => refresh(strategies.page, runs.page + 1))}>다음 기록</button></div>}
      </div>
    </fieldset>
    <p className="text-xs text-slate-500">개인 연구용입니다. 상장폐지 종목은 제외되며, 결과는 실제 매매 성과를 보장하지 않습니다.</p>
  </section>;
}
