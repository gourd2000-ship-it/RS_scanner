import { z } from 'zod';

export const fields = {
  rs_rating: 'RS 점수', rank_in_market: '시장 내 RS 순위', close: '종가',
  volume: '거래량', volume_sma50: '거래량 MA50', atr14: 'ATR14', return_n_days: '기간 수익률',
} as const;
export const fieldUnits: Record<keyof typeof fields, string> = {
  rs_rating: '점', rank_in_market: '위', close: '원', volume: '주',
  volume_sma50: '주', atr14: '원', return_n_days: '%',
};
export const defaultThresholds: Record<keyof typeof fields, string> = {
  rs_rating: '80', rank_in_market: '80', close: '80', volume: '80',
  volume_sma50: '100000', atr14: '1000', return_n_days: '5',
};
export const operators = { gte: '이상 (≥)', gt: '초과 (>)', lte: '이하 (≤)', lt: '미만 (<)', eq: '같음 (=)' } as const;
export type Rule = { type: 'rule'; field: keyof typeof fields; operator: keyof typeof operators; value: string; days: string };
export type Condition = Rule | { type: 'group'; operator: 'AND' | 'OR'; children: Condition[] };
export type Draft = {
  market: 'KOSPI' | 'KOSDAQ' | 'BOTH'; interval: string; holdings: string;
  weight: string; reserve: string; buyFee: string; sellFee: string;
  buySlippage: string; sellSlippage: string; stop: string; take: string; maxDays: string;
  buy: Condition; sell: Condition;
};
export const newRule = (): Rule => ({ type: 'rule', field: 'rs_rating', operator: 'gte', value: '80', days: '20' });
export const initialDraft = (): Draft => ({
  market: 'BOTH', interval: '5', holdings: '10', weight: '10', reserve: '0',
  buyFee: '0', sellFee: '0', buySlippage: '0', sellSlippage: '0', stop: '', take: '', maxDays: '',
  buy: { type: 'group', operator: 'AND', children: [newRule()] },
  sell: { type: 'group', operator: 'OR', children: [{ ...newRule(), operator: 'lt', value: '70' }] },
});

const numeric = (value: string, label: string, min: number, max = Infinity, integer = false): number => {
  const n = Number(value);
  if (!value.trim() || !Number.isFinite(n) || n < min || n > max || (integer && !Number.isInteger(n))) {
    throw new Error(`${label} 입력값을 확인해주세요.`);
  }
  return n;
};
const ratio = (value: string, label: string, max = 99.9999) => numeric(value, label, 0, max) / 100;

export type WireCondition = { type: 'rule'; field: keyof typeof fields; operator: keyof typeof operators; value: number | string; n_days?: number } |
  { type: 'group'; operator: 'AND' | 'OR'; children: WireCondition[] };

export function encodeCondition(node: Condition): WireCondition {
  if (node.type === 'group') {
    if (!node.children.length) throw new Error('조건 묶음에는 조건이 하나 이상 필요합니다.');
    return { type: 'group', operator: node.operator, children: node.children.map(encodeCondition) };
  }
  const value = numeric(node.value, fields[node.field], node.field === 'return_n_days' ? -100 : 0);
  return {
    type: 'rule', field: node.field, operator: node.operator,
    value: node.field === 'return_n_days' ? value / 100 : value,
    ...(node.field === 'return_n_days' ? { n_days: numeric(node.days, '수익률 기간', 1, Infinity, true) } : {}),
  };
}

export function encodeDraft(draft: Draft) {
  const weight = ratio(draft.weight, '종목별 최대 비중', 100);
  if (weight <= 0) throw new Error('종목별 최대 비중은 0%보다 커야 합니다.');
  const stop = draft.stop === '' ? null : ratio(draft.stop, '손절', 100);
  const take = draft.take === '' ? null : ratio(draft.take, '익절', Infinity);
  if (stop === 0 || take === 0) throw new Error('손절·익절은 0보다 큰 값으로 입력하거나 비워두세요.');
  return {
    market: draft.market, rebalance_interval_trading_days: numeric(draft.interval, '매수 검토 주기', 1, Infinity, true),
    max_holdings: numeric(draft.holdings, '최대 보유 종목', 1, Infinity, true), max_position_weight: weight,
    cash_reserve_ratio: ratio(draft.reserve, '최소 현금 비중'),
    buy_fee_rate: ratio(draft.buyFee, '매수 수수료'), sell_fee_rate: ratio(draft.sellFee, '매도 수수료'),
    buy_slippage_rate: ratio(draft.buySlippage, '매수 슬리피지'), sell_slippage_rate: ratio(draft.sellSlippage, '매도 슬리피지'),
    stop_loss_rate: stop === null ? null : -stop, take_profit_rate: take,
    max_holding_trading_days: draft.maxDays === '' ? null : numeric(draft.maxDays, '최대 보유 기간', 1, Infinity, true),
    buy_conditions: encodeCondition(draft.buy), sell_conditions: encodeCondition(draft.sell),
  };
}

const conditionSchema: z.ZodType<WireCondition> = z.lazy(() => z.union([
  z.object({ type: z.literal('group'), operator: z.enum(['AND', 'OR']), children: z.array(conditionSchema).min(1) }),
  z.object({ type: z.literal('rule'), field: z.enum(['rs_rating', 'rank_in_market', 'close', 'volume', 'volume_sma50', 'atr14', 'return_n_days']),
    operator: z.enum(['gt', 'gte', 'lt', 'lte', 'eq']), value: z.union([z.string(), z.number()]), n_days: z.number().optional() }),
]));
const numberLike = z.union([z.string(), z.number()]);
const configSchema = z.object({
  market: z.enum(['KOSPI', 'KOSDAQ', 'BOTH']).optional(), markets: z.array(z.enum(['KOSPI', 'KOSDAQ'])).optional(),
  rebalance_interval_trading_days: z.number().optional(), rebalance_interval_days: z.number().optional(),
  max_holdings: z.number(), max_position_weight: numberLike, cash_reserve_ratio: numberLike,
  buy_fee_rate: numberLike, sell_fee_rate: numberLike, buy_slippage_rate: numberLike, sell_slippage_rate: numberLike,
  stop_loss_rate: numberLike.nullish(), take_profit_rate: numberLike.nullish(),
  max_holding_trading_days: z.number().nullish(), max_holding_days: z.number().nullish(),
  buy_conditions: conditionSchema, sell_conditions: conditionSchema,
});
const percent = (value: string | number) => String(Number((Number(value) * 100).toPrecision(12)));
function decodeCondition(node: WireCondition): Condition {
  if (node.type === 'group') return { ...node, children: node.children.map(decodeCondition) };
  return { type: 'rule', field: node.field, operator: node.operator,
    value: node.field === 'return_n_days' ? percent(node.value) : String(node.value), days: String(node.n_days ?? 20) };
}
function editableRoot(node: WireCondition): Condition {
  const decoded = decodeCondition(node);
  return decoded.type === 'group' ? decoded : { type: 'group', operator: 'AND', children: [decoded] };
}
export function decodeDraft(raw: unknown): Draft {
  const c = configSchema.parse(raw);
  const draft: Draft = {
    market: c.market ?? (c.markets?.length === 2 ? 'BOTH' : c.markets?.[0] ?? 'BOTH'),
    interval: String(c.rebalance_interval_trading_days ?? c.rebalance_interval_days ?? 5), holdings: String(c.max_holdings),
    weight: percent(c.max_position_weight), reserve: percent(c.cash_reserve_ratio),
    buyFee: percent(c.buy_fee_rate), sellFee: percent(c.sell_fee_rate),
    buySlippage: percent(c.buy_slippage_rate), sellSlippage: percent(c.sell_slippage_rate),
    stop: c.stop_loss_rate == null ? '' : percent(-Number(c.stop_loss_rate)),
    take: c.take_profit_rate == null ? '' : percent(c.take_profit_rate),
    maxDays: String(c.max_holding_trading_days ?? c.max_holding_days ?? ''),
    buy: editableRoot(c.buy_conditions), sell: editableRoot(c.sell_conditions),
  };
  encodeDraft(draft);
  return draft;
}
