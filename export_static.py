"""Export a standalone store analytics dashboard."""
import base64
from html import escape
import json
from pathlib import Path

from config import RESULTS_DIR, TASK_DIR


def export(results_dir=RESULTS_DIR, output=None):
    output = output or TASK_DIR / "public" / "index.html"
    reports = json.loads((results_dir / "summary.json").read_text(encoding="utf-8"))
    tabs, sections = [], []
    for index, report in enumerate(reports):
        store = escape(report["store"])
        tabs.append(f'<button role="tab" aria-selected="{str(index == 0).lower()}" onclick="showStore({index})">{store}</button>')
        image = base64.b64encode((results_dir / report["store"] / "daily_revenue.png").read_bytes()).decode()
        days = "".join(f'<tr><td>{escape(row["date"])}</td><td>${float(row["revenue_usd"]):,.2f}</td></tr>'
                       for row in report["top_5_days"])
        authors = "".join(f'<p class="featured">{escape(row["name"])}</p><p class="muted">{row["books_sold"]:,} books sold</p>'
                          for row in report["most_popular_author_sets"])
        buyers = "".join(f'<p class="featured">{escape(" · ".join(row["aliases"]))}</p><code>{escape(json.dumps(row["user_ids"]))}</code><p class="muted">${float(row["total_usd"]):,.2f} total spending</p>'
                         for row in report["best_buyers"])
        sections.append(f'''<section role="tabpanel" {'hidden' if index else ''}>
          <div class="heading"><div><p class="eyebrow">INDEPENDENT STORE VIEW</p><h2>{store}</h2></div><span class="badge">{report['order_count']:,} cleaned orders</span></div>
          <div class="metrics">
            <article><span>Revenue</span><strong>${float(report['revenue_usd']):,.2f}</strong></article>
            <article><span>Real unique customers</span><strong>{report['unique_users']:,}</strong></article>
            <article><span>Unique author sets</span><strong>{report['unique_author_sets']:,}</strong></article>
            <article><span>Books sold</span><strong>{report['books_sold']:,}</strong></article>
          </div>
          <div class="revenue"><article><h3>Daily revenue</h3><img src="data:image/png;base64,{image}" alt="{store} daily revenue line chart in USD"></article>
          <article><h3>Top 5 revenue days</h3><table><thead><tr><th>Date</th><th>Revenue</th></tr></thead><tbody>{days}</tbody></table></article></div>
          <div class="people"><article><h3>Most popular author set</h3>{authors}</article><article><h3>Best buyer · all aliases</h3>{buyers}</article></div>
        </section>''')
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Store Intelligence — retail analytics</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f7f9;color:#172a3e;font:16px/1.5 system-ui,-apple-system,sans-serif}
header{background:#172a3e;color:white;padding:36px max(24px,calc((100vw - 1280px)/2))}header h1{font-size:34px;letter-spacing:-1px;margin:6px 0}
.eyebrow{letter-spacing:2px;font-size:11px;font-weight:700;color:#6b8794;margin:0}header .eyebrow{color:#a2d6cf}header p{color:#c4d0da;margin:0}
main{max-width:1328px;margin:auto;padding:28px 24px 48px}nav{display:flex;gap:8px;margin-bottom:30px;flex-wrap:wrap}
button{font:inherit;font-weight:600;padding:10px 22px;border:1px solid #d3dfe4;border-radius:6px;background:white;color:#455d6b;cursor:pointer}
button[aria-selected=true]{background:#167d76;border-color:#167d76;color:white}.heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
h2{font-size:26px;margin:2px 0}h3{font-size:17px;margin:0 0 20px}article{background:white;border:1px solid #e0e7ed;border-radius:10px;padding:24px}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.metrics span,.muted{color:#637687;font-size:13px}.metrics strong{display:block;font-size:28px;letter-spacing:-.7px;margin-top:8px}
.revenue{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-top:20px}.people{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px}
img{width:100%;height:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:13px 0;border-bottom:1px solid #edf0f3}td:last-child,th:last-child{text-align:right;font-variant-numeric:tabular-nums}
.featured{font-size:19px;font-weight:600;margin-bottom:8px}code{background:#f1f5f7;padding:6px 10px;border-radius:5px;font-size:15px}.badge{font-size:12px;color:#637687}footer{font-size:12px;color:#637687;margin-top:24px}
@media(max-width:850px){.metrics{grid-template-columns:repeat(2,1fr)}.revenue,.people{grid-template-columns:1fr}.metrics strong{font-size:24px}article{padding:18px}}
</style><header><p class="eyebrow">RETAIL ANALYTICS</p><h1>Store Intelligence</h1><p>Revenue, authors and reconciled customers. Every store, independently.</p></header>
<main><nav role="tablist" aria-label="Stores">''' + "".join(tabs) + "</nav>" + "".join(sections) + '''
<footer>All revenue in USD · EUR 1 = USD 1.2 · Exact cents, rounded per order line · Customer aliases reconciled under the one-changed-field assumption.<br>Static dashboard. The full Streamlit application adds chat and interactive filters.</footer></main>
<script>function showStore(index){document.querySelectorAll('[role=tabpanel]').forEach((el,i)=>el.hidden=i!==index);document.querySelectorAll('[role=tab]').forEach((el,i)=>el.setAttribute('aria-selected',String(i===index)));}</script></html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(f"Static dashboard: {output}")
    return output


if __name__ == "__main__":
    export()
