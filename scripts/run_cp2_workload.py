from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")


def read_queries() -> list[dict[str, str]]:
    path = REPO_ROOT / "data" / "sample_queries.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def run(label: str, output: Path, repeat: int) -> int:
    os.environ["LANGFUSE_PROMPT_LABEL"] = label

    from app.main import app
    from app.tracing import flush_traces, get_langfuse_client

    payloads = read_queries() * repeat
    records: list[dict[str, object]] = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://cp2.local") as client:
        for payload in payloads:
            response = await client.post("/chat", json=payload)
            body = response.json()
            records.append(
                {
                    "status_code": response.status_code,
                    "correlation_id": body.get("correlation_id"),
                    "trace_id": body.get("trace_id"),
                    "feature": payload["feature"],
                    "prompt_label": label,
                }
            )

    flush_traces(get_langfuse_client())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2), encoding="utf-8")

    failed = [record for record in records if record["status_code"] != 200]
    missing_trace = [record for record in records if not record["trace_id"]]
    print(f"prompt_label={label}")
    print(f"requests={len(records)}")
    print(f"successful={len(records) - len(failed)}")
    print(f"trace_ids={len(records) - len(missing_trace)}")
    print(f"output={output.as_posix()}")
    if failed or missing_trace:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create real CP2 traces in Langfuse")
    parser.add_argument("--label", choices=["baseline", "candidate", "production"])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    label = args.label or os.getenv("LANGFUSE_PROMPT_LABEL", "production")
    output = args.output or (REPO_ROOT / "data" / f"cp2-workload-{label}.json")
    return asyncio.run(run(label, output, max(1, args.repeat)))


if __name__ == "__main__":
    raise SystemExit(main())
