"""Read-only extraction: run through an Odoo shell against the review database."""
import gzip
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from odoo.addons.prometeo_purchase_advisor.models.datatypes import DemandSeries


def export(env, output):
    """Export sales folds. Inventory is retrospectively reconstructed, not archived."""
    env.cr.execute('SET TRANSACTION READ ONLY')
    companies = env['res.company'].search([])
    env = env(context=dict(env.context, allowed_company_ids=companies.ids, lang='en_US'))
    builder = env['prometeo.demand.series.builder']
    model = env['prometeo.demand.model'].new({
        'name': 'Backtest baseline', 'company_id': False, 'method': 'weighted_ma',
        'lookback_days': 90, 'weight_config': '14:0.5,30:0.3,90:0.2',
        'ignore_stockout_days': True, 'outlier_percentile': .95,
        'min_history_days': 21, 'service_level': .95,
    })
    calendar = env['prometeo.demand.model'].new(dict(
        name='Calendar baseline', company_id=False, method='weighted_ma',lookback_days=90,
        weight_config='14:0.5,30:0.3,90:0.2',ignore_stockout_days=False,
        outlier_percentile=.95,min_history_days=21,service_level=.95))
    metadata=[]
    count=0
    with gzip.open(output, 'wt') as handle:
        for wh in env['stock.warehouse'].search([('id','!=',1)]):
            path=wh.view_location_id.parent_path+'%'
            env.cr.execute("""
                SELECT sm.product_id,
                       (sm.date AT TIME ZONE 'UTC' AT TIME ZONE %s)::date,
                       SUM(CASE WHEN dest.usage='customer' THEN sm.product_qty ELSE -sm.product_qty END),
                       COUNT(*) FILTER (WHERE dest.usage='customer')
                  FROM stock_move sm
                  JOIN stock_location src ON src.id=sm.location_id
                  JOIN stock_location dest ON dest.id=sm.location_dest_id
                  LEFT JOIN stock_picking picking ON picking.id=sm.picking_id
                 WHERE sm.state='done' AND sm.company_id=%s
                   AND ((src.usage='internal' AND src.parent_path LIKE %s AND dest.usage='customer')
                     OR (dest.usage='internal' AND dest.parent_path LIKE %s AND src.usage='customer'))
                   AND NOT EXISTS (SELECT 1 FROM res_company c WHERE c.partner_id=COALESCE(picking.partner_id,sm.partner_id))
                 GROUP BY 1,2
            """,(builder._timezone(),wh.company_id.id,path,path))
            daily=defaultdict(dict); events=defaultdict(dict)
            for pid,day,qty,moves in env.cr.fetchall():
                daily[pid][day]=float(qty);events[pid][day]=moves
            if not daily: continue
            end=max(day for vals in daily.values() for day in vals)
            origins=[end-timedelta(days=i) for i in (56,42,28)]
            begin=origins[0]-timedelta(days=90)
            products=env['product.product'].with_context(active_test=False).browse(list(daily)).exists()
            ids=products.ids
            full=builder.build(wh,ids,begin,end)
            # Unclamped balances characterize whether the historical stock is credible.
            env.cr.execute("""
                SELECT sm.product_id,(sm.date AT TIME ZONE 'UTC' AT TIME ZONE %s)::date,
                       SUM((CASE WHEN dest.usage='internal' AND dest.parent_path LIKE %s THEN sm.product_qty ELSE 0 END)
                         - (CASE WHEN src.usage='internal' AND src.parent_path LIKE %s THEN sm.product_qty ELSE 0 END))
                  FROM stock_move sm JOIN stock_location src ON src.id=sm.location_id
                  JOIN stock_location dest ON dest.id=sm.location_dest_id
                 WHERE sm.state='done' AND sm.company_id=%s AND sm.product_id=ANY(%s)
                   AND sm.date >= %s
                 GROUP BY 1,2
            """,(builder._timezone(),path,path,wh.company_id.id,ids,builder._to_utc(begin,builder._timezone())))
            net=defaultdict(dict)
            for pid,day,qty in env.cr.fetchall(): net[pid][day]=float(qty or 0)
            onhand=builder._current_qty(wh,ids)
            raw_stock={}
            for pid in ids:
                running=onhand.get(pid,0)
                day=builder._today(builder._timezone())
                balances={}
                while day>=begin:
                    closing=running
                    running-=net[pid].get(day,0)
                    balances[day]=(running,closing)
                    day-=timedelta(days=1)
                raw_stock[pid]=balances
            with_vendor={p.id:bool(p.seller_ids) for p in products}
            company_meta={'warehouse_id':wh.id,'warehouse':wh.name,'last_recorded_day':end.isoformat(),
                'origins':[d.isoformat() for d in origins],'all_pairs':len(ids),'cases':0}
            for fold,origin in enumerate(origins):
                horizon=28 if fold==2 else 14
                date_from=origin-timedelta(days=90)
                eligible=[pid for pid in ids if full.first_move_date.get(pid,end)<=origin-timedelta(days=28)
                    and sum(q for d,q in daily[pid].items() if date_from<=d<origin)>0]
                train=DemandSeries(wh.id,date_from,origin,eligible,
                    qty={pid:{d:q for d,q in daily[pid].items() if date_from<=d<origin} for pid in eligible},
                    stockout_days={pid:{d for d in full.stockout_days.get(pid,set()) if date_from<=d<origin} for pid in eligible},
                    first_move_date={pid:full.first_move_date[pid] for pid in eligible},
                    move_count={pid:sum(n for d,n in events[pid].items() if date_from<=d<origin) for pid in eligible},
                    notes={pid:full.notes.get(pid,[]) for pid in eligible})
                # Empty reliability flags intentionally reproduce the legacy estimator.
                predictions=model.estimate(train)
                calendars=calendar.estimate(train)
                for pid in eligible:
                    effective=max(date_from,full.first_move_date[pid])
                    train_days=[effective+timedelta(days=i) for i in range((origin-effective).days)]
                    test_days=[origin+timedelta(days=i) for i in range(horizon)]
                    known_stock=all(min(raw_stock[pid][d])>=-.001 for d in train_days)
                    observable_train=[max(raw_stock[pid][d])>0 for d in train_days]
                    observable_test=[max(raw_stock[pid][d])>0 and min(raw_stock[pid][d])>=-.001 for d in test_days]
                    vals=[daily[pid].get(d,0) for d in train_days]
                    record={'warehouse_id':wh.id,'product_id':pid,'fold':fold,'origin':str(origin),'horizon':horizon,
                        'train':vals,'actual':[daily[pid].get(d,0) for d in test_days],
                        'train_stock_valid':known_stock,'train_available':observable_train,
                        'test_available':observable_test,'has_vendor':with_vendor[pid],
                        'baseline_rate':predictions[pid].adu,'calendar_rate':calendars[pid].adu,
                        'baseline_confidence':predictions[pid].confidence,'baseline_stockout_ratio':train.stockout_ratio(pid),
                        'baseline_sigma':predictions[pid].sigma,
                        'train_clamped':bool(full.notes.get(pid))}
                    handle.write(json.dumps(record)+'\n');count+=1;company_meta['cases']+=1
            metadata.append(company_meta)
            print(json.dumps(company_meta,ensure_ascii=False),flush=True)
    Path(output+'.metadata.json').write_text(json.dumps({'cases':count,'warehouses':metadata},ensure_ascii=False,indent=2))
    print('EXPORT_COMPLETE',count,output,flush=True)


if __name__=='__main__':
    export(env,os.getenv('ADVISOR_EXPORT','/tmp/advisor-backtest-month.jsonl.gz'))
    env.cr.rollback()
