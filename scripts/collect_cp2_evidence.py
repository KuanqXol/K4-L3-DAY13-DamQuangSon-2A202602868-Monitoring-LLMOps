from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

from langfuse import get_client


OBSERVATION_FIELDS = (
    "core,basic,time,io,metadata,model,usage,prompt,metrics,trace_context"
)
SAFE_METADATA_KEYS = frozenset(
    {
        "correlation_id",
        "doc_count",
        "feature",
        "model",
        "prompt_fetch_error",
        "prompt_label",
        "prompt_name",
        "prompt_source",
        "prompt_version",
        "query_preview",
    }
)


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return jsonable(value)
    # Langfuse v4's v2 observation model stores selected field groups on the
    # instance, while model_dump() only exposes the core response schema.
    raw = getattr(value, "__dict__", None)
    if isinstance(raw, dict):
        return jsonable({key: item for key, item in raw.items() if not key.startswith("_")})
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"))
    if hasattr(value, "dict"):
        return jsonable(value.dict())
    return {}


def workload_trace_ids() -> list[str]:
    ids: list[str] = []
    for path in sorted((REPO_ROOT / "data").glob("cp2-workload-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids.extend(str(item["trace_id"]) for item in payload if item.get("trace_id"))
    return list(dict.fromkeys(ids))


def project_name(client: Any) -> str:
    try:
        response = client.api.projects.get()
        projects = getattr(response, "data", []) or []
        if projects:
            return str(getattr(projects[0], "name", "unknown-project"))
    except Exception:
        pass
    return "unknown-project"


def fetch_observations(client: Any, trace_id: str) -> list[dict[str, Any]]:
    response = client.api.observations.get_many(
        fields=OBSERVATION_FIELDS,
        trace_id=trace_id,
        limit=100,
    )
    return [dump(item) for item in (getattr(response, "data", []) or [])]


def parse_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return value if isinstance(value, dict) else {}


def safe_metadata(value: Any) -> dict[str, Any]:
    metadata = parse_mapping(value)
    return {
        key: jsonable(metadata[key])
        for key in SAFE_METADATA_KEYS
        if key in metadata
    }


def trace_summary(trace_id: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    root = next(
        (
            item
            for item in observations
            if item.get("is_root_observation") or not item.get("parent_observation_id")
        ),
        observations[0] if observations else {},
    )
    # The legacy trace endpoint is unavailable for newer Langfuse organizations.
    # The v2 observations response carries the trace context and root metadata.
    merged: dict[str, Any] = {}
    for observation in observations:
        merged.update(safe_metadata(observation.get("metadata")))
    return {
        "id": trace_id,
        "timestamp": root.get("start_time", ""),
        "name": root.get("trace_name") or "day13-agent-request",
        "metadata": merged,
        "observations": observations,
    }


def write_trace_list(path: Path, project: str, traces: list[dict[str, Any]]) -> None:
    lines = [
        "CP2 Langfuse trace list",
        f"Project: {project}",
        "Trace name: day13-agent-request",
        f"Traces collected: {len(traces)}",
        "",
    ]
    for index, trace in enumerate(traces, start=1):
        metadata = trace["metadata"]
        lines.append(
            f"{index:02d}. trace_id={trace['id']} "
            f"correlation_id={metadata.get('correlation_id', '(not returned)')} "
            f"prompt_version={metadata.get('prompt_version', '(not returned)')} "
            f"prompt_label={metadata.get('prompt_label', '(not returned)')}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_waterfall(path: Path, project: str, trace: dict[str, Any]) -> None:
    lines = [
        "CP2 Langfuse trace waterfall",
        f"Project: {project}",
        f"Trace ID: {trace['id']}",
        "",
    ]
    observations = trace["observations"]
    by_id = {item.get("id"): item for item in observations}

    def depth(item: dict[str, Any]) -> int:
        current = item
        level = 0
        seen: set[str] = set()
        while current.get("parent_observation_id") in by_id:
            parent_id = current.get("parent_observation_id")
            if parent_id in seen:
                break
            seen.add(parent_id)
            current = by_id[parent_id]
            level += 1
        return level

    for item in sorted(observations, key=lambda value: value.get("start_time", "")):
        indent = "  " * depth(item)
        lines.append(
            f"{indent}- name={item.get('name')} type={item.get('type')} "
            f"observation_id={item.get('id')} "
            f"parent={item.get('parent_observation_id') or '(root)'}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_metadata(path: Path, project: str, trace: dict[str, Any]) -> None:
    generation = next(
        (item for item in trace["observations"] if item.get("type") == "GENERATION" or item.get("name") == "llm-generation"),
        {},
    )
    metadata = trace["metadata"]
    usage = generation.get("usage_details") or {}
    costs = generation.get("cost_details") or {}
    lines = [
        "CP2 Langfuse trace metadata",
        f"Project: {project}",
        f"Trace ID: {trace['id']}",
        f"Correlation ID: {metadata.get('correlation_id', '(not returned)')}",
        f"Prompt name: {metadata.get('prompt_name', generation.get('prompt_name', '(not returned)'))}",
        f"Prompt label: {metadata.get('prompt_label', '(not returned)')}",
        f"Prompt version: {metadata.get('prompt_version', generation.get('prompt_version', '(not returned)'))}",
        f"Model: {generation.get('model') or metadata.get('model', '(not returned)')}",
        f"Usage details: {json.dumps(usage, sort_keys=True)}",
        f"Cost details: {json.dumps(costs, sort_keys=True)}",
        "Raw prompt/output: not captured; only sanitized previews are instrumented.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    client = get_client()
    wanted_ids = workload_trace_ids()
    if not wanted_ids:
        print("No CP2 workload trace IDs found. Run run_cp2_workload.py first.")
        return 1

    traces_by_id: dict[str, dict[str, Any]] = {}
    last_error = ""
    for attempt in range(5):
        for trace_id in wanted_ids:
            try:
                observations = fetch_observations(client, trace_id)
                traces_by_id[trace_id] = trace_summary(trace_id, observations)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        if len(traces_by_id) >= min(10, len(wanted_ids)):
            break
        time.sleep(2)

    traces = [traces_by_id[trace_id] for trace_id in wanted_ids if trace_id in traces_by_id]
    if len(traces) < 10:
        print(f"Only {len(traces)} traces were readable; last error: {last_error}")
        return 1

    project = project_name(client)
    evidence_dir = REPO_ROOT / "submission" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    write_trace_list(evidence_dir / "06-trace-list.txt", project, traces[:20])
    waterfall = next(
        (
            trace
            for trace in traces
            if any(item.get("name") == "retrieval" for item in trace["observations"])
            and any(item.get("name") == "llm-generation" for item in trace["observations"])
        ),
        traces[0],
    )
    write_waterfall(evidence_dir / "07-trace-waterfall.txt", project, waterfall)
    write_metadata(evidence_dir / "08-trace-metadata.txt", project, waterfall)
    client.flush()
    print(f"project={project}")
    print(f"traces={len(traces)}")
    print(f"waterfall_trace_id={waterfall['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
