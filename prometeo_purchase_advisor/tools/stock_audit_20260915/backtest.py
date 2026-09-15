import json
from datetime import date,timedelta
companies=env['res.company'].search([])
env=env(user=2,su=True,context=dict(env.context,allowed_company_ids=companies.ids))
env.cr.execute('SET TRANSACTION READ ONLY')
builder=env['prometeo.demand.series.builder']
model=env.ref('prometeo_purchase_advisor.demand_model_default')
cut=date(2026,8,6);end=cut+timedelta(days=14)
results=[]
for wid in [2,5,6,9,12]:
 w=env['stock.warehouse'].browse(wid)
 env.cr.execute('''SELECT m.product_id,SUM(ml.quantity_product_uom) qty FROM stock_move m JOIN stock_move_line ml ON ml.move_id=m.id JOIN stock_location s ON s.id=m.location_id JOIN stock_location d ON d.id=m.location_dest_id LEFT JOIN stock_picking p ON p.id=m.picking_id JOIN product_product pp ON pp.id=m.product_id JOIN product_template pt ON pt.id=pp.product_tmpl_id WHERE m.state='done' AND m.company_id=%s AND s.usage='internal' AND d.usage='customer' AND s.parent_path LIKE %s AND m.date>=%s AND m.date<%s AND pt.is_storable AND pt.purchase_ok AND NOT EXISTS(SELECT 1 FROM res_company c WHERE c.partner_id=coalesce(p.partner_id,m.partner_id)) GROUP BY m.product_id ORDER BY qty DESC,m.product_id LIMIT 100''',[w.company_id.id,w.view_location_id.parent_path+'%',builder._to_utc(cut-timedelta(days=90),builder._timezone()),builder._to_utc(cut,builder._timezone())])
 ids=[r[0] for r in env.cr.fetchall()]
 series=builder.with_company(w.company_id).build(w,ids,cut-timedelta(days=90),cut)
 future=builder.with_company(w.company_id).build(w,ids,cut,end)
 estimates=model.estimate(series)
 actual=[max(future.total_qty(p),0) for p in ids]
 predictions={'weighted':[estimates[p].adu*14 for p in ids], 'mean14':[max(series.total_qty(p,14),0) for p in ids], 'mean30':[max(series.total_qty(p,30),0)/30*14 for p in ids]}
 rows={}
 for key,values in predictions.items():
  rows[key]=dict(actual=sum(actual),predicted=sum(values),wape=100*sum(abs(a-b) for a,b in zip(actual,values))/sum(actual) if sum(actual) else None,bias=100*(sum(values)-sum(actual))/sum(actual) if sum(actual) else None)
 results.append(dict(warehouse=w.name,products=len(ids),train_from=str(series.date_from),cut=str(cut),end_exclusive=str(end),unreliable_stock=len(series.unreliable_stock_ids),models=rows))
print('BACKTEST_JSON='+json.dumps(results))
env.cr.rollback()
