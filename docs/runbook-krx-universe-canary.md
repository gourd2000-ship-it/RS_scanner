# KRX Universe Authority Canary Runbook

## Preconditions

- Alembic revision is at the application head and the KRX schema is present.
- `KRX_SHADOW_INGESTION_ENABLED=true` has produced completed shadow snapshots.
- The latest reconciliation report records mapping rate, unmatched, ambiguous, and legacy counts.
- Keep `UNIVERSE_AUTHORITY=naver_last_completed` until an operator explicitly starts a canary.

## Canary procedure

1. Choose one market only, then set `UNIVERSE_AUTHORITY=krx` and
   `UNIVERSE_CANARY_MARKETS=<market>`.
2. Before each daily batch, confirm the current KRX snapshot is `completed` and the
   immutable target is backed by the most recent explicitly `approved` KRX/Naver
   reconciliation run with mapping rate at least `0.995`. A newly created run remains
   `pending_review` until the next operator review; it does not replace the approved
   canary snapshot automatically.
   After reviewing the report, record that approval with
   `python scripts/approve_universe_reconciliation.py --run-id <id> --approved-by <operator>`.
3. Confirm the batch-generated reconciliation JSON report in `reports/krx_universe/` and retain it.
   The CLI `scripts/report_universe_reconciliation.py` remains available for an on-demand read-only report.
4. After reviewing and approving the current reconciliation run, record the daily
   decision from immutable batch evidence:

   ```bash
   python scripts/record_universe_canary_decision.py \
     --job-id <job-id> --market KOSPI --decision continue --approved-by <operator>
   ```

   The command rejects a KRX decision when the current reconciliation run or the
   immutable target-selection run is not approved, or when the current mapping rate
   is below `UNIVERSE_MAPPING_RATE_THRESHOLD`. Run for two trading days in one market
   before expanding.
5. After expansion, retain five consecutive trading-day reports before an authority cutover decision.

Until ETF/ETN membership is independently approved, a stock KRX canary replaces only
stock targets in its market. Existing Naver ETF/ETN targets remain in the batch and
must be evaluated separately; they are never silently dropped by the canary.

## Automatic fallback conditions

The price target must remain `naver_last_completed` for a market when any condition applies:

- KRX snapshot is missing, partial, or failed.
- No `approved` KRX/Naver reconciliation run is available for the selected immutable snapshot.
- Mapping rate is below `UNIVERSE_MAPPING_RATE_THRESHOLD` (default `0.995`).
- The market is not listed in `UNIVERSE_CANARY_MARKETS`.
- The authority flag is not exactly `krx`.

Do not delete KRX snapshots, reconciliation runs, price history, or RS history during fallback.

## Rollback

1. Set `UNIVERSE_AUTHORITY=naver_last_completed`.
2. Clear `UNIVERSE_CANARY_MARKETS` only after the decision is recorded.
3. Generate a reconciliation report and record the trigger, affected market, and operator.
4. Open a follow-up task for the failed gate; do not automatically deactivate symbols or rewrite provider mappings.

## Daily decision log template

```markdown
## YYYY-MM-DD — KOSPI|KOSDAQ

- KRX snapshot: <id>, <completed|partial|failed>, as-of <date>
- Naver snapshot: <id>, <completed|partial|failed>
- Reconciliation run: <id>
- Mapping rate: <value>
- Eligible / expected-no-trade / excluded / review-required: <counts>
- Legacy price requests: <count>
- Authority used: <krx|naver_last_completed>
- Fallback reason: <none|reason>
- Operator decision: <continue|expand|rollback>
- Operator and timestamp: <name>, <timestamp>
```

## Cutover gate

Approve full KRX authority only when five consecutive trading days show:

- KRX completed ratio: 100%
- Price-eligible mapping rate: at least 99.5%
- Legacy Naver price requests: 0
- No unexplained target or coverage regression
- Explicit operator approval recorded in the daily decision log
