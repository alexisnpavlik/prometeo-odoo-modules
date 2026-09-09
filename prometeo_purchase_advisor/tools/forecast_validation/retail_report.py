"""Exploratory sensitivity checks; never select these additions on final outcomes."""
import sys,gzip,json,statistics
from pathlib import Path
import compare as m

def initialized(vals,alpha,beta=None):
    positive=[v for v in vals if v>0]
    if not positive:return 0.
    size=m.mean(positive);interval=len(vals)/len(positive);prob=1/interval;elapsed=1
    for v in vals:
        if beta is not None: prob+=beta*(int(v>0)-prob)
        if v>0:
            size+=alpha*(v-size)
            interval+=alpha*(elapsed-interval)
            elapsed=1
        else:elapsed+=1
    return size*prob if beta is not None else (1-alpha/2)*size/interval

def main(source,output):
    with gzip.open(source,'rt') as f:cases=[json.loads(r) for r in f]
    rows=[]
    for c in cases:
        p=m.forecasts(c)
        p['ewma_calendar_p95_0.3']=m.ewma(m.cap_values(c['train']),.3)
        for a in (.1,.2):
            p[f'sba_train_init_{a}']=initialized(c['train'],a)
            for b in (.05,.1):p[f'tsb_train_init_{a}_{b}']=initialized(c['train'],a,b)
        rows.append((c,p))
    methods=list(rows[0][1]);retail=[r for r in rows if r[0]['warehouse_id']!=3]
    groups={'retail_validation':[r for r in retail if r[0]['fold']<2],
        'retail_holdout':[r for r in retail if r[0]['fold']==2],
        'retail_vendor_holdout':[r for r in retail if r[0]['fold']==2 and r[0]['has_vendor']],
        'retail_daily_balance_available':[r for r in retail if r[0]['fold']==2 and r[0]['train_stock_valid'] and all(r[0]['test_available'])],
        'central_holdout':[r for r in rows if r[0]['warehouse_id']==3 and r[0]['fold']==2]}
    report={'case_count':len(cases),'groups':{g:{n:m.metrics(rs,n) for n in methods} for g,rs in groups.items()}}
    report['warehouses']={wid:{n:m.metrics([r for r in rows if r[0]['warehouse_id']==wid and r[0]['fold']==2],n) for n in ['actual_engine','guarded_odoo','weighted_calendar_p95']} for wid in sorted({c['warehouse_id'] for c in cases})}
    report['notes']=['Stock reconstructed retrospectively; this is not an archived point-in-time replay.','Guard, capped EWMA and train-initialized SBA/TSB are exploratory additions after initial results.','Vendor membership is current, not historical; customer moves proxy sales.','Validation horizons 14 days, holdout 28; origin windows selected per warehouse data end.']
    Path(output).write_text(json.dumps(report,indent=2))
    for g in groups:
        print(g)
        for n in ('actual_engine','guarded_odoo','weighted_calendar_p95','ewma_calendar_p95_0.3','sba_train_init_0.2','tsb_train_init_0.1_0.1','zero_control'):
            v=report['groups'][g][n];print(n,v['n'],round(v['wape_pct'],3),round(v['bias_pct'],3),round(v['rmse_units'],3))
    v=report['groups']['retail_validation']
    print('INIT_SELECTION',min((n for n in methods if 'train_init' in n),key=lambda n:v[n]['rmse_units']))
if __name__=='__main__':main(sys.argv[1],sys.argv[2])
