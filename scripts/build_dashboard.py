from __future__ import annotations

import argparse
import html
import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((p / 100) * len(ordered)) - 1))
    return ordered[index]


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [parse_timestamp(str(record["ts"])) for record in records if record.get("ts")]
    end = max(timestamps) if timestamps else datetime.now(timezone.utc)
    start = end - timedelta(minutes=60)
    records = [
        record
        for record in records
        if record.get("ts") and start <= parse_timestamp(str(record["ts"])) <= end
    ]
    requests = [record for record in records if record.get("event") == "request_received"]
    responses = [record for record in records if record.get("event") == "response_sent"]
    failures = [record for record in records if record.get("event") == "request_failed"]
    latencies = [float(record["latency_ms"]) for record in responses if record.get("latency_ms") is not None]
    ttft = [float(record["ttft_ms"]) for record in responses if record.get("ttft_ms") is not None]
    costs = [float(record["cost_usd"]) for record in responses if record.get("cost_usd") is not None]
    tokens_in = [int(record["tokens_in"]) for record in responses if record.get("tokens_in") is not None]
    tokens_out = [int(record["tokens_out"]) for record in responses if record.get("tokens_out") is not None]
    quality = [float(record["quality_score"]) for record in responses if record.get("quality_score") is not None]
    retrieval_values = [record.get("tool_success") for record in responses if record.get("tool_success") is not None]
    retrieval_success = (
        sum(1 for value in retrieval_values if value is True) / len(retrieval_values) * 100
        if retrieval_values
        else 0.0
    )
    duration_minutes = max((end - start).total_seconds() / 60, 1)
    request_rate = len(requests) / duration_minutes
    error_rate = len(failures) / len(requests) * 100 if requests else 0.0
    return {
        "window_start": start,
        "window_end": end,
        "records": len(records),
        "latency": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
            "ttft_p95": percentile(ttft, 95),
            "series": latencies,
        },
        "traffic": {"requests": len(requests), "rate": request_rate},
        "errors": {
            "count": len(failures),
            "rate": error_rate,
            "retrieval_success": retrieval_success,
        },
        "cost": {"total": sum(costs), "per_minute": sum(costs) / duration_minutes, "series": costs},
        "tokens": {"input": sum(tokens_in), "output": sum(tokens_out)},
        "quality": {"mean": statistics.fmean(quality) if quality else 0.0, "series": quality},
    }


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def svg_series(values: list[float], color: str) -> str:
    width, height = 420, 62
    if not values:
        return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="No data"></svg>'
    maximum = max(values) or 1
    minimum = min(values)
    span = maximum - minimum or 1
    points = []
    for index, value in enumerate(values):
        x = index / max(len(values) - 1, 1) * width
        y = height - ((value - minimum) / span * (height - 8)) - 4
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Metric trend">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />'
        "</svg>"
    )


def panel(title: str, accent: str, body: str, threshold: str, chart: str = "") -> str:
    return f"""
    <section class="panel" style="--accent:{accent}">
      <div class="panel-head"><h2>{html.escape(title)}</h2><span class="dot"></span></div>
      <div class="panel-body">{body}</div>
      {chart}
      <div class="threshold">Threshold / SLO: {html.escape(threshold)}</div>
    </section>
    """


def render(metrics: dict[str, Any], source: str, slo: dict[str, Any]) -> str:
    window_start = metrics["window_start"].strftime("%Y-%m-%d %H:%M UTC")
    window_end = metrics["window_end"].strftime("%Y-%m-%d %H:%M UTC")
    target = slo["primary_slo"]["target_percent"]
    latency = metrics["latency"]
    traffic = metrics["traffic"]
    errors = metrics["errors"]
    cost = metrics["cost"]
    tokens = metrics["tokens"]
    quality = metrics["quality"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>K4-L3A Monitoring Dashboard</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background:#101619; color:#e9f0ed; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:linear-gradient(135deg,#101619 0%,#182326 52%,#11181a 100%); min-height:100vh; }}
    main {{ max-width:1440px; margin:0 auto; padding:32px 34px 48px; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:end; border-bottom:1px solid #314247; padding-bottom:24px; margin-bottom:24px; }}
    .eyebrow {{ color:#78d4be; text-transform:uppercase; letter-spacing:.14em; font-size:12px; font-weight:700; }}
    h1 {{ margin:7px 0 8px; font-size:32px; letter-spacing:0; }}
    .sub {{ color:#a8b9b5; margin:0; font-size:14px; }}
    .window {{ text-align:right; color:#d8e4df; font-size:13px; line-height:1.7; }}
    .window strong {{ color:#f3c969; font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }}
    .panel {{ background:#172125; border:1px solid #2b3a3e; border-top:3px solid var(--accent); min-height:225px; padding:18px; box-shadow:0 16px 36px rgba(0,0,0,.16); }}
    .panel-head {{ display:flex; justify-content:space-between; align-items:center; }}
    .panel h2 {{ margin:0; font-size:15px; letter-spacing:0; font-weight:700; }}
    .dot {{ width:9px; height:9px; border-radius:50%; background:var(--accent); box-shadow:0 0 14px var(--accent); }}
    .panel-body {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:20px; }}
    .metric {{ border-left:2px solid #385057; padding-left:10px; }}
    .metric-label {{ display:block; color:#91a6a1; font-size:11px; text-transform:uppercase; letter-spacing:.08em; margin-bottom:6px; }}
    .metric-value {{ font-size:24px; font-weight:750; color:#f5fbf8; }}
    .metric-value small {{ font-size:12px; color:#9db0ab; font-weight:600; }}
    .chart {{ margin-top:16px; height:62px; border-bottom:1px solid #2c3b3f; }}
    .chart svg {{ width:100%; height:100%; }}
    .threshold {{ color:#9db0ab; font-size:11px; margin-top:12px; }}
    .good {{ color:#7ee0a9; }} .warn {{ color:#f3c969; }} .bad {{ color:#ff8d80; }}
    footer {{ color:#829590; font-size:12px; margin-top:22px; display:flex; justify-content:space-between; gap:20px; }}
    @media (max-width:1000px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media (max-width:650px) {{ main {{ padding:22px 16px 36px; }} header {{ display:block; }} .window {{ text-align:left; margin-top:16px; }} .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div><div class="eyebrow">AI observability / CP2 runtime</div><h1>K4-L3A Monitoring &amp; LLMOps</h1><p class="sub">Six operational signals from structured application logs</p></div>
    <div class="window"><strong>Last 60 minutes</strong><br>{html.escape(window_start)} → {html.escape(window_end)}<br>Refresh: 30s · Source: {html.escape(source)}</div>
  </header>
  <div class="grid">
    {panel("Latency percentiles and TTFT", "#78d4be", f'<div class="metric"><span class="metric-label">P50</span><span class="metric-value">{fmt(latency["p50"])} <small>ms</small></span></div><div class="metric"><span class="metric-label">P95</span><span class="metric-value">{fmt(latency["p95"])} <small>ms</small></span></div><div class="metric"><span class="metric-label">P99</span><span class="metric-value">{fmt(latency["p99"])} <small>ms</small></span></div><div class="metric"><span class="metric-label">TTFT P95</span><span class="metric-value">{fmt(latency["ttft_p95"])} <small>ms</small></span></div>', "P95 latency ≤ 3000 ms", svg_series(latency["series"], "#78d4be"))}
    {panel("Request traffic", "#f3c969", f'<div class="metric"><span class="metric-label">Requests</span><span class="metric-value">{traffic["requests"]}</span></div><div class="metric"><span class="metric-label">Rate</span><span class="metric-value">{fmt(traffic["rate"])} <small>req/min</small></span></div>', "Rate ≥ 1 request/minute")}
    {panel("Error rate and retrieval success", "#ff8d80", f'<div class="metric"><span class="metric-label">Errors</span><span class="metric-value {"good" if errors["rate"] <= 2 else "bad"}">{fmt(errors["rate"])} <small>%</small></span></div><div class="metric"><span class="metric-label">Retrieval success</span><span class="metric-value {"good" if errors["retrieval_success"] >= 90 else "bad"}">{fmt(errors["retrieval_success"])} <small>%</small></span></div>', "Error rate ≤ 2%; retrieval success ≥ 90%")}
    {panel("Cost over time", "#d9a7ff", f'<div class="metric"><span class="metric-label">Total</span><span class="metric-value">${cost["total"]:.4f}</span></div><div class="metric"><span class="metric-label">Per minute</span><span class="metric-value">${cost["per_minute"]:.4f}</span></div>', "Daily cost ≤ $2.50", svg_series(cost["series"], "#d9a7ff"))}
    {panel("Input and output tokens", "#7eb7ff", f'<div class="metric"><span class="metric-label">Input</span><span class="metric-value">{tokens["input"]:,}</span></div><div class="metric"><span class="metric-label">Output</span><span class="metric-value">{tokens["output"]:,}</span></div>', "Window total ≤ 50,000 tokens")}
    {panel("Quality proxy", "#7ee0a9", f'<div class="metric"><span class="metric-label">Mean score</span><span class="metric-value {"good" if quality["mean"] >= .75 else "warn"}">{quality["mean"]:.2f} <small>/ 1.00</small></span></div><div class="metric"><span class="metric-label">SLO target</span><span class="metric-value">{target:.1f} <small>% success</small></span></div>', "Quality mean ≥ 0.75", svg_series(quality["series"], "#7ee0a9"))}
  </div>
  <footer><span>Generated from {html.escape(source)} · sanitized aggregate view</span><span>Primary SLO: {target:.1f}% fast successful requests · error budget: {100 - target:.1f}%</span></footer>
</main>
</body>
</html>
"""


def write_evidence(path: Path, metrics: dict[str, Any], dashboard_label: str) -> None:
    lines = [
        "CP2 dashboard runtime evidence",
        f"Dashboard artifact: {dashboard_label}",
        f"Time range: {metrics['window_start'].strftime('%Y-%m-%d %H:%M UTC')} -> {metrics['window_end'].strftime('%Y-%m-%d %H:%M UTC')} (60 minutes)",
        "Refresh: 30 seconds",
        "Panels: latency/TTFT, traffic, errors/retrieval, cost, tokens, quality",
        "",
        f"Latency: P50={metrics['latency']['p50']:.1f} ms; P95={metrics['latency']['p95']:.1f} ms; P99={metrics['latency']['p99']:.1f} ms; TTFT P95={metrics['latency']['ttft_p95']:.1f} ms",
        f"Traffic: requests={metrics['traffic']['requests']}; rate={metrics['traffic']['rate']:.2f} requests/minute",
        f"Errors: error_rate={metrics['errors']['rate']:.2f}%; retrieval_success={metrics['errors']['retrieval_success']:.2f}%",
        f"Cost: total=${metrics['cost']['total']:.6f}; per_minute=${metrics['cost']['per_minute']:.6f}",
        f"Tokens: input={metrics['tokens']['input']}; output={metrics['tokens']['output']}",
        f"Quality: mean={metrics['quality']['mean']:.3f}",
        "Thresholds: latency P95<=3000 ms; error rate<=2%; retrieval success>=90%; quality>=0.75; daily cost<=2.50 USD.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the six-panel CP2 dashboard")
    parser.add_argument("--log-path", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "dashboard" / "index.html")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=REPO_ROOT / "submission" / "evidence",
    )
    args = parser.parse_args()
    records = load_records(args.log_path)
    if not records:
        print(f"No valid logs found in {args.log_path}")
        return 1
    metrics = compute(records)
    slo = yaml.safe_load((REPO_ROOT / "config" / "slo.yaml").read_text(encoding="utf-8"))
    source = display_path(args.log_path)
    dashboard_label = display_path(args.output)
    page = render(metrics, source, slo)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    evidence_html = args.evidence_dir / "11-dashboard-overview.html"
    evidence_txt = args.evidence_dir / "11-dashboard-overview.txt"
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_html.write_text(page, encoding="utf-8")
    write_evidence(evidence_txt, metrics, dashboard_label)
    print(f"dashboard={args.output}")
    print(f"evidence_html={evidence_html}")
    print(f"evidence_text={evidence_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
