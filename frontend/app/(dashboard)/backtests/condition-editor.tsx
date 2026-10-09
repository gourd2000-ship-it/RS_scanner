'use client';

import { Condition, defaultThresholds, fields, fieldUnits, newRule, operators, Rule } from './form-model';

export const inputClass = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100';
export const buttonClass = 'rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50';

export default function ConditionEditor({ node, onChange, label }: { node: Condition; onChange: (node: Condition) => void; label: string }) {
  if (node.type === 'rule') return <div className="grid gap-2 sm:grid-cols-3">
    <label className="text-xs text-slate-600">지표
      <select aria-label={`${label} 지표`} className={inputClass} value={node.field} onChange={e => { const field = e.target.value as Rule['field']; onChange({ ...node, field, value: defaultThresholds[field] }); }}>
        {Object.entries(fields).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
      </select>
    </label>
    <label className="text-xs text-slate-600">비교
      <select aria-label={`${label} 비교`} className={inputClass} value={node.operator} onChange={e => onChange({ ...node, operator: e.target.value as Rule['operator'] })}>
        {Object.entries(operators).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
      </select>
    </label>
    <label className="text-xs text-slate-600">기준값 ({fieldUnits[node.field]})
      <input aria-label={`${label} 기준값`} className={inputClass} type="number" required step="any" min={node.field === 'return_n_days' ? -100 : 0} value={node.value} onChange={e => onChange({ ...node, value: e.target.value })} />
    </label>
    {node.field === 'return_n_days' && <label className="text-xs text-slate-600">수익률 계산 기간 (거래일)
      <input aria-label={`${label} 수익률 기간`} className={inputClass} type="number" required min="1" step="1" value={node.days} onChange={e => onChange({ ...node, days: e.target.value })} />
    </label>}
  </div>;
  return <fieldset className="min-w-0 space-y-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3 sm:p-4">
    <legend className="px-1 text-sm font-medium text-slate-700">{label}</legend>
    <select aria-label={`${label} 조합`} className={`${inputClass} sm:max-w-sm`} value={node.operator} onChange={e => onChange({ ...node, operator: e.target.value as 'AND' | 'OR' })}>
      <option value="AND">모든 조건을 만족 (AND)</option><option value="OR">하나 이상 만족 (OR)</option>
    </select>
    {node.children.map((child, index) => <div key={index} className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between text-xs text-slate-500"><span>조건 {index + 1}</span>
        <button type="button" className="px-2 py-1 text-rose-700 disabled:text-slate-300" disabled={node.children.length === 1} aria-label={`${label} 조건 ${index + 1} 삭제`} onClick={() => onChange({ ...node, children: node.children.filter((_, i) => i !== index) })}>삭제</button>
      </div>
      <ConditionEditor label={`${label} ${index + 1}`} node={child} onChange={updated => onChange({ ...node, children: node.children.map((item, i) => i === index ? updated : item) })} />
    </div>)}
    <div className="flex flex-wrap gap-2">
      <button type="button" className={buttonClass} onClick={() => onChange({ ...node, children: [...node.children, newRule()] })}>+ 조건 추가</button>
      <button type="button" className={buttonClass} onClick={() => onChange({ ...node, children: [...node.children, { type: 'group', operator: 'OR', children: [newRule()] }] })}>+ AND/OR 묶음 추가</button>
    </div>
  </fieldset>;
}
