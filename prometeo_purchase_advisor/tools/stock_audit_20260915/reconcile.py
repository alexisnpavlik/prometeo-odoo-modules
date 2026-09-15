import json
from datetime import date,timedelta
from pathlib import Path
companies=env['res.company'].search([])
env=env(context=dict(env.context,allowed_company_ids=companies.ids,tz='America/Argentina/Cordoba'))
env.cr.execute('SET TRANSACTION READ ONLY')
builder=env['prometeo.demand.series.builder']
print('AUDIT_TIMEZONE',builder._timezone())
start,end=date(2026,2,5),date(2026,9,6)
out=[]
for w in env['stock.warehouse'].search([]):
    env.cr.execute('''SELECT ml.product_id,(m.date AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS movement_day,
    SUM(CASE WHEN dst.usage='customer' THEN ml.quantity_product_uom ELSE -ml.quantity_product_uom END) qty
    FROM stock_move_line ml JOIN stock_move m ON m.id=ml.move_id JOIN stock_location src ON src.id=ml.location_id JOIN stock_location dst ON dst.id=ml.location_dest_id
    LEFT JOIN stock_picking p ON p.id=m.picking_id WHERE m.state='done' AND m.company_id=%s AND m.date >= %s AND m.date < %s
    AND ((src.usage='internal' AND src.parent_path LIKE %s AND dst.usage='customer') OR (dst.usage='internal' AND dst.parent_path LIKE %s AND src.usage='customer'))
    AND NOT EXISTS(SELECT 1 FROM res_company c WHERE c.partner_id=coalesce(p.partner_id,m.partner_id)) GROUP BY 1,2''',
    [builder._timezone(),w.company_id.id,builder._to_utc(start,builder._timezone()),builder._to_utc(end,builder._timezone()),w.view_location_id.parent_path+'%',w.view_location_id.parent_path+'%'])
    expected={(p,d):float(q) for p,d,q in env.cr.fetchall()}
    ids=list({p for p,d in expected})
    from odoo.addons.prometeo_purchase_advisor.models.datatypes import DemandSeries
    series=DemandSeries(warehouse_id=w.id,date_from=start,date_to=end,product_ids=ids)
    params=dict(company_id=w.company_id.id,product_ids=ids,wh_path=w.view_location_id.parent_path+'%',tz=builder._timezone(),date_from=builder._to_utc(start,builder._timezone()),date_to=builder._to_utc(end,builder._timezone()))
    builder._fill_demand(series,params)
    observed={(p,d):q for p,days in series.qty.items() for d,q in days.items()}
    errors=[(p,str(d),expected.get((p,d),0),observed.get((p,d),0)) for p,d in expected.keys()|observed.keys() if abs(expected.get((p,d),0)-observed.get((p,d),0))>.001]
    out.append(dict(warehouse=w.name,products=len(ids),product_days=len(expected),net_units=sum(expected.values()),mismatches=errors[:10],mismatch_count=len(errors)))
print('RECONCILIATION_JSON='+json.dumps(out))
env.cr.rollback()
