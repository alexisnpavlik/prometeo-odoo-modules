"""Compare fixed algorithms without selecting parameters on the last holdout."""
import argparse
import gzip
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def mean(values):
    return sum(values)/len(values) if values else 0.


def cap_values(values, percentile=.95):
    if len(values)<10: return values
    cap=sorted(values)[math.ceil(percentile*len(values))-1]
    return [min(value,cap) for value in values] if cap>0 else values


def ewma(values, alpha):
    if not values: return 0.
    level=values[0]
    for value in values[1:]: level+=alpha*(value-level)
    return max(level,0.)


def sba(values, alpha):
    positives=[i for i,value in enumerate(values) if value>0]
    if not positives: return 0.
    first=positives[0]; size=values[first]; interval=first+1; elapsed=1
    for value in values[first+1:]:
        if value>0:
            size+=alpha*(value-size)
            interval+=alpha*(elapsed-interval)
            elapsed=1
        else: elapsed+=1
    return (1-alpha/2)*size/interval


def tsb(values, alpha, beta):
    positives=[i for i,value in enumerate(values) if value>0]
    if not positives: return 0.
    first=positives[0]; size=values[first]; probability=1/(first+1)
    for value in values[first+1:]:
        probability+=beta*(int(value>0)-probability)
        if value>0: size+=alpha*(value-size)
    return size*probability


def forecasts(case):
    """Initial candidate grid; guarded_odoo is a subsequent diagnostic correction."""
    vals=case['train']
    result={'actual_engine':case['baseline_rate'],'weighted_calendar_p95':case['calendar_rate'],
            'zero_control':0.}
    for length in (14,28,56,90):
        result[f'mean_{length}']=max(mean(vals[-length:]),0.)
    for alpha in (.05,.1,.2,.3):
        result[f'ewma_{alpha}']=ewma(vals,alpha)
    for alpha in (.1,.2): result[f'sba_{alpha}']=sba(vals,alpha)
    for alpha,beta in ((.1,.05),(.1,.1),(.2,.1)):
        result[f'tsb_{alpha}_{beta}']=tsb(vals,alpha,beta)
    # Current weighting on calendar days without winsorization.
    usable=[(n,w) for n,w in ((14,.5),(30,.3),(90,.2)) if n<=len(vals)]
    if not usable: usable=[(14,1.)]
    result['weighted_calendar_raw']=max(sum(mean(vals[-n:])*w for n,w in usable)/sum(w for n,w in usable),0.)
    if 'guarded_rate' in case:
        result['guarded_odoo'] = case['guarded_rate']
    return result


def metrics(rows, name):
    """Horizon-total WAPE and bias plus squared loss, shortages and excess."""
    if not rows: return {'n':0}
    errors=[]; under=over=actual=predicted=scale_errors=0.; scale_count=0
    for case,pred in rows:
        h=len(case['actual']); truth=max(sum(case['actual']),0.)
        forecast=pred[name]*h; error=forecast-truth
        actual+=truth; predicted+=forecast; under+=max(-error,0); over+=max(error,0)
        errors.append(error)
        scale=mean([(b-a)**2 for a,b in zip(case['train'],case['train'][1:])])
        if scale>0:
            scale_errors+=(error/h)**2/scale; scale_count+=1
    return {'n':len(rows),'actual':actual,'predicted':predicted,
        'wape_pct':100*(under+over)/actual if actual else None,
        'bias_pct':100*(predicted-actual)/actual if actual else None,
        'rmse_units':math.sqrt(mean([e*e for e in errors])),
        'rmsse_rate':math.sqrt(scale_errors/scale_count) if scale_count else None,
        'short_units':under,'excess_units':over}


def main(path, destination):
    with gzip.open(path,'rt') as handle: cases=[json.loads(row) for row in handle]
    rows=[(case,forecasts(case)) for case in cases]
    algorithms=list(rows[0][1]); validation=[r for r in rows if r[0]['fold']<2]; test=[r for r in rows if r[0]['fold']==2]
    masks={
        'validation_all':validation,'holdout_all':test,
        'holdout_vendor':[r for r in test if r[0]['has_vendor']],
        'holdout_stock_valid':[r for r in test if r[0]['train_stock_valid']],
        'holdout_fully_observable':[r for r in test if r[0]['train_stock_valid'] and all(r[0]['test_available'])],
        'holdout_sparse':[r for r in test if sum(v>0 for v in r[0]['train'])/len(r[0]['train'])<.2],
        'holdout_frequent':[r for r in test if sum(v>0 for v in r[0]['train'])/len(r[0]['train'])>=.2],
    }
    report={'source':path,'case_count':len(cases),'algorithms':algorithms,'groups':{},'warehouses':{}}
    for group, subset in masks.items():
        report['groups'][group]={name:metrics(subset,name) for name in algorithms}
    # Pick using only earlier validation blocks, then evaluate that fixed choice.
    competitors=[name for name in algorithms if name!='zero_control']
    report['validation_choice_rmse']=min(competitors,key=lambda n:report['groups']['validation_all'][n]['rmse_units'])
    for wid in sorted({c['warehouse_id'] for c in cases}):
        subset=[r for r in test if r[0]['warehouse_id']==wid]
        report['warehouses'][wid]={name:metrics(subset,name) for name in algorithms}
    report['data_quality']={
        'test_cases':len(test),'invalid_training_stock':sum(not r[0]['train_stock_valid'] for r in test),
        'fully_observable':len(masks['holdout_fully_observable']),
        'zero_actual':sum(sum(r[0]['actual'])<=0 for r in test),
        'median_positive_day_share':statistics.median(sum(v>0 for v in r[0]['train'])/len(r[0]['train']) for r in test),
        'baseline_high_confidence':sum(r[0]['baseline_confidence']>=.5 for r in test)}
    Path(destination).write_text(json.dumps(report,indent=2))
    for group in ('validation_all','holdout_all','holdout_vendor','holdout_fully_observable'):
        print(group)
        for name,m in sorted(report['groups'][group].items(),key=lambda item:item[1].get('rmse_units',float('inf'))):
            if m['n']:print(name, 'n',m['n'],'WAPE',round(m['wape_pct'] or 0,2),'bias',round(m['bias_pct'] or 0,2),'RMSE',round(m['rmse_units'],3))
    print('CHOICE',report['validation_choice_rmse']);print('QUALITY',report['data_quality'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('output')
    args=parser.parse_args();main(args.source,args.output)
