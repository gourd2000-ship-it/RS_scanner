"""Read-only ATR(14) JSON report for one or more historical instruments."""
from __future__ import annotations
import argparse, json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from app.core.database import SessionLocal
from app.core.market_calendar import krx_market_day_status
from app.services.indicators.atr_service import AtrService
from app.services.indicators.contracts import EmaSourcePolicy
def d(v): return date.fromisoformat(v)
def dt(v): return datetime.fromisoformat(v.replace('Z','+00:00')).astimezone(UTC)
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--start',required=True,type=d); p.add_argument('--end',required=True,type=d); p.add_argument('--provider',required=True); p.add_argument('--adjustment-type',required=True); p.add_argument('--parser-version',required=True,action='append'); p.add_argument('--observation-cutoff',required=True,type=dt); p.add_argument('--instrument-id',required=True,type=int,action='append'); p.add_argument('--output',type=Path); a=p.parse_args(argv)
 if a.end<a.start: p.error('end는 start보다 빠를 수 없습니다')
 dates=tuple(x for x in (a.start+timedelta(days=i) for i in range((a.end-a.start).days+1)) if krx_market_day_status(x).is_open)
 policy=EmaSourcePolicy(a.provider,a.adjustment_type,tuple(sorted(set(a.parser_version))),a.observation_cutoff)
 with SessionLocal() as s:
  service=AtrService(s); targets=[]
  for iid in sorted(set(a.instrument_id)):
   r=service.calculate(instrument_id=iid,trade_dates=dates,policy=policy); counts={k:sum(v.status.value==k for v in r.values) for k in ('warming_up','data_unavailable','available')}; targets.append({'instrument_id':iid,'first_available':next((v.trade_date.isoformat() for v in r.values if v.status.value=='available'),None),'counts':counts,'result_hash':r.result_hash})
 report={'mode':'read_only_plan','indicator':'atr_14','targets':targets}
 rendered=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
 if a.output: a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(rendered,encoding='utf-8')
 else: print(rendered,end='')
if __name__=='__main__': main()
