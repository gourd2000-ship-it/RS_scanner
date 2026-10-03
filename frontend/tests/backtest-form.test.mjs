import assert from 'node:assert/strict';
import { test } from 'node:test';
import { decodeDraft, encodeDraft, initialDraft, newRule } from '../app/(dashboard)/backtests/form-model.ts';

test('percent inputs and positive loss magnitude become API ratios', () => {
  const result = encodeDraft({ ...initialDraft(), weight: '25', reserve: '10', buyFee: '0.015', sellSlippage: '0.1', stop: '5', take: '20' });
  assert.equal(result.max_position_weight, 0.25);
  assert.equal(result.cash_reserve_ratio, 0.1);
  assert.equal(result.buy_fee_rate, 0.00015);
  assert.equal(result.sell_slippage_rate, 0.001);
  assert.equal(result.stop_loss_rate, -0.05);
  assert.equal(result.take_profit_rate, 0.2);
});

test('nested AND/OR and return lookback survive save and load', () => {
  const draft = initialDraft();
  draft.buy.children.push({ type: 'group', operator: 'OR', children: [
    { ...newRule(), field: 'return_n_days', value: '-5', days: '60' },
    { ...newRule(), field: 'volume', value: '100000' },
  ] });
  const wire = encodeDraft(draft);
  assert.equal(wire.buy_conditions.children[1].children[0].value, -0.05);
  assert.equal(wire.buy_conditions.children[1].children[0].n_days, 60);
  assert.deepEqual(encodeDraft(decodeDraft(wire)), wire);
});

test('load backend internal names and numeric strings; single rules remain editable', () => {
  const wire = encodeDraft(initialDraft());
  delete wire.market;
  delete wire.rebalance_interval_trading_days;
  delete wire.max_holding_trading_days;
  const loaded = decodeDraft({ ...wire, markets: ['KOSDAQ'], rebalance_interval_days: 10,
    max_holding_days: 30, max_position_weight: '0.15', buy_conditions: wire.buy_conditions.children[0] });
  assert.equal(loaded.market, 'KOSDAQ');
  assert.equal(loaded.interval, '10');
  assert.equal(loaded.maxDays, '30');
  assert.equal(loaded.weight, '15');
  assert.equal(loaded.buy.type, 'group');
  assert.equal(loaded.buy.children[0].value, '80');
});

test('blank optional exits are disabled and invalid inputs are rejected', () => {
  const wire = encodeDraft(initialDraft());
  assert.equal(wire.stop_loss_rate, null);
  assert.equal(wire.take_profit_rate, null);
  assert.equal(wire.max_holding_trading_days, null);
  for (const patch of [{ weight: '' }, { reserve: '100' }, { buyFee: 'NaN' }, { interval: '1.5' }, { stop: '-5' }, { take: '0' }]) {
    assert.throws(() => encodeDraft({ ...initialDraft(), ...patch }));
  }
  assert.throws(() => encodeDraft({ ...initialDraft(), buy: { ...newRule(), field: 'return_n_days', days: '0' } }));
  assert.throws(() => decodeDraft({ ...wire, buy_conditions: { type: 'group', operator: 'AND', children: [] } }));
});
