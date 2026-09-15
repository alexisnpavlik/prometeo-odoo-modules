import subprocess,json
from pathlib import Path

def q(sql):
 r=subprocess.run(['docker','exec','odoo-postgres18-1','psql','-U','odoo','-d','prod','-Atc','SELECT coalesce(json_agg(x),\'[]\'::json) FROM ('+sql+') x'],capture_output=True,text=True,check=True)
 return json.loads(r.stdout)
base='''WITH actual AS (SELECT move_id,sum(quantity_product_uom) qty FROM stock_move_line GROUP BY move_id), m AS (
 SELECT sm.*,coalesce(a.qty,0) actual,src.usage src_usage,dst.usage dst_usage,
 sw.id sw,dw.id dw,coalesce(sp.partner_id,sm.partner_id) partner,
 EXISTS(SELECT 1 FROM res_company c WHERE c.partner_id=coalesce(sp.partner_id,sm.partner_id)) intercompany
 FROM stock_move sm LEFT JOIN actual a ON a.move_id=sm.id JOIN stock_location src ON src.id=sm.location_id JOIN stock_location dst ON dst.id=sm.location_dest_id
 LEFT JOIN stock_picking sp ON sp.id=sm.picking_id
 LEFT JOIN stock_warehouse sw ON src.parent_path LIKE (SELECT parent_path FROM stock_location WHERE id=sw.view_location_id)||'%%'
 LEFT JOIN stock_warehouse dw ON dst.parent_path LIKE (SELECT parent_path FROM stock_location WHERE id=dw.view_location_id)||'%%'
 WHERE sm.state='done') '''
out={}
out['flows']=q(base+'''SELECT w.name,
 count(*) FILTER(WHERE sw=w.id AND dst_usage='customer' AND NOT intercompany) sales_moves,
 sum(actual) FILTER(WHERE sw=w.id AND dst_usage='customer' AND NOT intercompany) sales,
 sum(actual) FILTER(WHERE dw=w.id AND src_usage='customer' AND NOT intercompany) returns,
 sum(actual) FILTER(WHERE dw=w.id AND src_usage='supplier' AND NOT intercompany) external_receipts,
 sum(actual) FILTER(WHERE dw=w.id AND (src_usage='transit' OR intercompany)) transfer_in,
 sum(actual) FILTER(WHERE sw=w.id AND (dst_usage='transit' OR intercompany)) transfer_out,
 sum(actual) FILTER(WHERE dw=w.id AND src_usage='inventory') adjustment_in,
 sum(actual) FILTER(WHERE sw=w.id AND dst_usage='inventory') adjustment_out,
 max(date) FILTER(WHERE sw=w.id AND dst_usage='customer' AND NOT intercompany) last_sale
 FROM m JOIN stock_warehouse w ON w.id=m.sw OR w.id=m.dw GROUP BY w.id,w.name ORDER BY w.id''')
out['planned_actual_differences']=q(base+'''SELECT id,date,company_id,product_id,src_usage,dst_usage,product_qty planned,actual,intercompany FROM m WHERE abs(product_qty-actual)>.001 ORDER BY date''')
out['stock_ledger']=q('''WITH lines AS(SELECT product_id,location_dest_id loc,quantity_product_uom qty FROM stock_move_line WHERE state='done' UNION ALL SELECT product_id,location_id,-quantity_product_uom FROM stock_move_line WHERE state='done'), ledger AS(SELECT product_id,loc,sum(qty) qty FROM lines GROUP BY 1,2), quants AS(SELECT product_id,location_id loc,sum(quantity) qty FROM stock_quant GROUP BY 1,2)
 SELECT w.name,count(*) positions,count(*) FILTER(WHERE coalesce(q.qty,0)<-.001) negative_positions,count(*) FILTER(WHERE abs(coalesce(q.qty,0)-coalesce(l.qty,0))>.001) mismatches,sum(coalesce(q.qty,0)) on_hand,sum(coalesce(l.qty,0)) ledger_net
 FROM quants q FULL JOIN ledger l USING(product_id,loc) JOIN stock_location loc ON loc.id=coalesce(q.loc,l.loc) JOIN stock_warehouse w ON loc.parent_path LIKE (SELECT parent_path FROM stock_location WHERE id=w.view_location_id)||'%%' WHERE loc.usage='internal' GROUP BY w.id,w.name ORDER BY w.id''')
out['pending']=q('''SELECT w.name,count(*) moves,sum(sm.product_qty) expected,sum(sm.product_qty) FILTER(WHERE sm.date<'2026-08-06') older_30_days_at_snapshot,min(sm.date) earliest,max(sm.date) latest FROM stock_move sm JOIN stock_location src ON src.id=sm.location_id JOIN stock_location dst ON dst.id=sm.location_dest_id JOIN stock_warehouse w ON dst.parent_path LIKE (SELECT parent_path FROM stock_location WHERE id=w.view_location_id)||'%%' WHERE sm.state IN ('waiting','confirmed','partially_available','assigned') AND src.usage IN ('supplier','transit') AND dst.usage='internal' GROUP BY w.id,w.name ORDER BY w.id''')
out['pos_totals']=q('''SELECT o.company_id,count(distinct o.id) orders,sum(l.qty) net_qty,min(o.date_order) first_sale,max(o.date_order) last_sale FROM pos_order o JOIN pos_order_line l ON l.order_id=o.id WHERE o.state IN ('paid','done','invoiced') GROUP BY o.company_id ORDER BY 1''')
Path('/tmp/advisor-stock-audit/data.json').write_text(json.dumps(out,indent=2,default=str))
print(json.dumps(out,indent=2))
