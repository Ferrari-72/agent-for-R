"""Render validated resource-pilot JSON as a standalone, read-only HTML report."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from statistics import median
import sys

# The isolated CLI deliberately exposes only this caller-owned source directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from resource_pilot_data import number, successful, summarize, validate


def esc(value):
    return html.escape(str(value), quote=True)


def chart(rows, metric, title, unit):
    solvers = list(dict.fromkeys(row["solver"] for row in rows))
    values = []
    for solver in solvers:
        selected = [number(row, metric) for row in rows
                    if row["solver"] == solver and successful(row)]
        values.append(median(selected) if selected else None)
    width, left, right, top, band = 1000, 230, 100, 38, 42
    height = top + max(1, len(solvers)) * band + 44
    maximum = max((value for value in values if value is not None), default=1) or 1
    plot_width = width - left - right
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">',
           '<defs><pattern id="texture-' + metric + '-' + esc(rows[0]["case_id"]) + '" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" class="texture-line"/></pattern></defs>',
           f'<text x="{left}" y="18" class="chart-title">{esc(title)} · {esc(unit)}</text>']
    for i in range(5):
        xpos = left + i * plot_width / 4
        out.append(f'<line x1="{xpos:.1f}" y1="{top}" x2="{xpos:.1f}" y2="{height-28}" class="grid"/>')
        out.append(f'<text x="{xpos:.1f}" y="{height-7}" text-anchor="middle" class="tick">{maximum*i/4:.3g}</text>')
    for index, (solver, value) in enumerate(zip(solvers, values)):
        y = top + index * band + band / 2
        own = [row for row in rows if row["solver"] == solver]
        success = sum(successful(row) for row in own)
        out.append(f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" class="label">{esc(solver)}</text>')
        if value is None:
            out.append(f'<text x="{left+8}" y="{y+4:.1f}" class="label">No successful execution (0/{len(own)})</text>')
            continue
        length = value / maximum * plot_width
        end = left + length
        radius = min(4, length / 2)
        path = f'M {left},{y-8} H {end-radius} Q {end},{y-8} {end},{y-8+radius} V {y+8-radius} Q {end},{y+8} {end-radius},{y+8} H {left} Z'
        tip = f"{solver}: median {value:.6g} {unit}; successful {success}/{len(own)} repeats"
        out.append(f'<g class="mark" tabindex="0" data-tip="{esc(tip)}" aria-label="{esc(tip)}"><path d="{path}" class="bar"/><path d="{path}" class="texture" style="fill:url(#texture-{metric}-{esc(rows[0]["case_id"])})"/><rect x="{left}" y="{y-14}" width="{max(length,24)}" height="28" fill="transparent"/><text x="{end+8:.1f}" y="{y+4:.1f}" class="label">{value:.4g}</text><title>{esc(tip)}</title></g>')
    out.append('</svg>')
    return ''.join(out)


def render(report):
    rows = validate(report)
    cases = list(dict.fromkeys(row["case_id"] for row in rows))
    solvers = list(dict.fromkeys(row["solver"] for row in rows))
    metrics = (("cost", "Symbolic FLOPs", "FLOPs"),
               ("algorithm_wall_seconds", "Algorithm wall time", "seconds"),
               ("peak_elements", "Peak tensor size", "elements"))
    views = []
    for case_id in cases:
        selected = [row for row in rows if row["case_id"] == case_id]
        charts = ''.join(f'<section><h2>{title}</h2>{chart(selected,key,title,unit)}</section>' for key,title,unit in metrics)
        summary_rows = []
        for solver, values in summarize(selected).items():
            def fmt(key):
                value = values[key]
                return '—' if value is None else f'{value:.5g}'
            summary_rows.append('<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in (
                solver, f"{values['successes']}/{values['rows']}", fmt('cost_median'),
                fmt('algorithm_wall_seconds_median'), fmt('peak_elements_median'))) + '</tr>')
        views.append(f'<div class="case-view" data-case="{esc(case_id)}" {"hidden" if case_id != cases[0] else ""}>{charts}<section><h2>Selected structure · successful-repeat medians</h2><div class="scroll"><table><thead><tr><th>Solver</th><th>Success / rows</th><th>FLOPs</th><th>Algorithm seconds</th><th>Peak elements</th></tr></thead><tbody>{"".join(summary_rows)}</tbody></table></div></section></div>')
    detail_rows = []
    for row in rows:
        cells = [row.get(k) for k in ('case_id','solver','repeat','status','cost','peak_elements',
                                     'algorithm_wall_seconds','process_wall_seconds','max_rss_kib')]
        cells.append(json.dumps(row.get('error'), ensure_ascii=False) if row.get('error') else '')
        detail_rows.append('<tr data-case="' + esc(row['case_id']) + '">' + ''.join(f'<td>{esc("—" if v is None else v)}</td>' for v in cells) + '</tr>')
    run_id = esc(report.get('run_id','unidentified run'))
    image = report.get('image', {})
    image_id = esc(image.get('id','unknown') if isinstance(image,dict) else image)
    data = json.dumps(report,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    options = ''.join(f'<option value="{esc(case)}">{esc(case)}</option>' for case in cases)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Resource pilot · {run_id}</title>
<style>
:root{{--surface:#fcfcfb;--ink:#0b0b0b;--secondary:#52514e;--grid:#e1e0d9;--page:#f9f9f7;--series:#2a78d6;--texture:#104281;color-scheme:light}}
:root[data-theme="dark"]{{--surface:#1a1a19;--ink:#f0efec;--secondary:#c3c2b7;--grid:#2c2c2a;--page:#0d0d0d;--series:#3987e5;--texture:#cde2fb;color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:14px system-ui,-apple-system,"Segoe UI",sans-serif}}main{{max-width:1200px;margin:auto;padding:24px}}header{{display:flex;justify-content:space-between;align-items:start;gap:16px;border-bottom:1px solid var(--grid);padding-bottom:16px}}h1{{font-size:22px;margin:0 0 8px}}h2{{font-size:16px;margin:20px 0 8px}}p,.muted{{color:var(--secondary)}}.filters{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:18px 0}}select,button{{background:var(--surface);color:var(--ink);border:1px solid var(--grid);padding:7px 10px;border-radius:4px}}button{{cursor:pointer}}section{{border-top:1px solid var(--grid);padding:4px 0 12px}}svg{{display:block;width:100%;color:var(--ink)}}svg text{{fill:var(--ink);font:12px system-ui}}svg .tick{{fill:var(--secondary);font-variant-numeric:tabular-nums}}svg .chart-title{{font-weight:600}}.grid{{stroke:var(--grid);stroke-width:1}}.bar{{fill:var(--series)}}.mark:focus .bar,.mark:hover .bar{{filter:brightness(1.12)}}.texture{{display:none}}.texture-line{{stroke:var(--texture);stroke-width:1}}[data-texture="true"] .texture{{display:block}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;background:var(--surface);font-variant-numeric:tabular-nums}}th,td{{padding:7px 9px;border-bottom:1px solid var(--grid);text-align:left;white-space:nowrap}}th{{background:var(--surface);color:var(--secondary)}}.notice{{border-left:3px solid var(--grid);padding:8px 12px;background:var(--surface)}}.tooltip{{position:fixed;max-width:420px;background:var(--surface);color:var(--ink);border:1px solid var(--grid);padding:10px;pointer-events:none;z-index:3}}[hidden]{{display:none!important}}@media(prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--surface:#1a1a19;--ink:#f0efec;--secondary:#c3c2b7;--grid:#2c2c2a;--page:#0d0d0d;--series:#3987e5;--texture:#cde2fb;color-scheme:dark}}}}@media print, (forced-colors:active){{.texture{{display:block}}.filters,button{{display:none}}}}
</style></head><body><main><header><div><h1>Public engineering resource pilot</h1><div class="muted">Run {run_id}</div><div class="muted">Image {image_id}</div></div><button id="theme" type="button">Toggle theme</button></header>
<p>{len(cases)} structures · {len(solvers)} solvers · {len(rows)} execution rows. All structures are exposed engineering material.</p>
<p class="notice">Each chart compares one structure. One blue metric series, solver categories labeled directly; bars start at zero. Values are medians of successful repeats, not an across-structure ranking. Failures are retained below. Peak tensor elements are symbolic and differ from process RSS; RSS can inherit a process-start high-water mark.</p>
<div class="filters"><label>Structure <select id="case">{options}</select></label><label><input type="checkbox" id="texture">Texture</label><label><input type="checkbox" id="allrows" checked>Show all rows in table</label></div>
{''.join(views)}<section><h2>All executions</h2><p id="row-count" class="muted"></p><div class="scroll"><table id="executions"><thead><tr><th>Case</th><th>Solver</th><th>Repeat</th><th>Status</th><th>FLOPs</th><th>Peak elements</th><th>Algorithm s</th><th>Process s</th><th>RSS KiB</th><th>Error</th></tr></thead><tbody>{''.join(detail_rows)}</tbody></table></div></section>
<script type="application/json" id="source-data">{data}</script><div id="tooltip" class="tooltip" role="tooltip" hidden></div><script>
const root=document.documentElement, select=document.getElementById('case'), allrows=document.getElementById('allrows'), tip=document.getElementById('tooltip');
function update(){{document.querySelectorAll('.case-view').forEach(el=>el.hidden=el.dataset.case!==select.value);let count=0;document.querySelectorAll('#executions tbody tr').forEach(el=>{{el.hidden=!allrows.checked&&el.dataset.case!==select.value;if(!el.hidden)count++}});document.getElementById('row-count').textContent=count+' rows shown; failures and missing values remain in the table.';tip.hidden=true}}
select.addEventListener('change',update);allrows.addEventListener('change',update);update();
document.getElementById('texture').addEventListener('change',e=>root.dataset.texture=e.target.checked);
document.getElementById('theme').addEventListener('click',()=>{{const dark=root.dataset.theme?root.dataset.theme==='dark':matchMedia('(prefers-color-scheme:dark)').matches;root.dataset.theme=dark?'light':'dark'}});
function show(el,event){{tip.textContent=el.dataset.tip;tip.hidden=false;const box=el.getBoundingClientRect(),x=event.clientX||box.left,y=event.clientY||box.top;tip.style.left=Math.max(8,Math.min(innerWidth-tip.offsetWidth-8,x+12))+'px';tip.style.top=Math.max(8,Math.min(innerHeight-tip.offsetHeight-8,y+12))+'px'}}
document.querySelectorAll('.mark').forEach(el=>{{el.addEventListener('pointermove',e=>show(el,e));el.addEventListener('focus',e=>show(el,e));el.addEventListener('pointerleave',()=>tip.hidden=true);el.addEventListener('blur',()=>tip.hidden=true)}});
</script></main></body></html>'''


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args(argv)
    report=json.loads(args.input.read_text(encoding='utf-8'))
    page=render(report)
    with args.output.open('x',encoding='utf-8',newline='\n') as target:
        target.write(page)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
