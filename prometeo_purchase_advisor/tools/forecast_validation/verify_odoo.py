"""Verify Odoo output against exported cases on a disposable database copy.

Run via Odoo shell; inputs/outputs configured with ADVISOR_CASES/ADVISOR_VERIFIED.
"""
import os
import gzip,json
from collections import defaultdict
from datetime import date,timedelta
from pathlib import Path
from odoo.addons.prometeo_purchase_advisor.models.datatypes import DemandSeries
env.cr.execute('SET TRANSACTION READ ONLY')
companies=env['res.company'].search([])
env=env(context=dict(env.context,allowed_company_ids=companies.ids,lang='en_US'))
with gzip.open(os.getenv('ADVISOR_CASES', '/tmp/advisor-backtest-month.jsonl.gz'),'rt') as f: cases=[json.loads(r) for r in f]
groups=defaultdict(list)
for c in cases: groups[(c['warehouse_id'],c['origin'])].append(c)
model=env['prometeo.demand.model'].new(dict(name='Verify guard',method='weighted_ma',lookback_days=90,weight_config='14:0.5,30:0.3,90:0.2',ignore_stockout_days=True,outlier_percentile=.95,min_history_days=21,service_level=.95))
changed_baselines=0
for (wid,origin),rows in groups.items():
    end=date.fromisoformat(origin)
    series=env['prometeo.demand.series.builder'].build(env['stock.warehouse'].browse(wid),[c['product_id'] for c in rows],end-timedelta(days=90),end)
    estimates=model.estimate(series)
    unreliable=series.unreliable_stock_ids
    series.unreliable_stock_ids=set()
    legacy=model.estimate(series)
    for c in rows:
        pid=c['product_id']
        c['guarded_rate']=estimates[pid].adu
        c['guarded_confidence']=estimates[pid].confidence
        c['guard_unreliable']=pid in unreliable
        if abs(legacy[pid].adu-c['baseline_rate'])>1e-8: changed_baselines+=1
        expected=c['calendar_rate'] if pid in unreliable else c['baseline_rate']
        assert abs(estimates[pid].adu-expected)<1e-8,(wid,pid,origin,estimates[pid].adu,expected)
    print(wid,origin,len(rows),len(unreliable),flush=True)
with gzip.open(os.getenv('ADVISOR_VERIFIED', '/tmp/advisor-backtest-verified.jsonl.gz'),'wt') as f:
    for c in cases:f.write(json.dumps(c)+'\n')
assert changed_baselines==0,changed_baselines
print('VERIFIED',len(cases),'legacy differences',changed_baselines,flush=True)
env.cr.rollback()
