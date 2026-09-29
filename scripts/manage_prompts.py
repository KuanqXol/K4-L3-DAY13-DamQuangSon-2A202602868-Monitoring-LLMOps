from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

from langfuse import get_client


PROMPT_NAME = "day13-chat"
PROMPT_V1 = """Feature={{feature}}
Docs={{docs}}
Question={{message}}

Answer using the retrieved documents and keep the response concise."""
PROMPT_V2 = """Feature={{feature}}
Docs={{docs}}
Question={{message}}

Answer in two short paragraphs. Use the retrieved documents when relevant and
state uncertainty when the documents do not answer the question."""
MANAGED_LABELS = {"baseline", "candidate", "production"}


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return {key: getattr(value, key) for key in dir(value) if not key.startswith("_")}


def project_name(client: Any) -> str:
    try:
        response = client.api.projects.get()
        projects = getattr(response, "data", []) or []
        if projects:
            project = projects[0]
            return str(getattr(project, "name", "") or _dump(project).get("name", ""))
    except Exception:
        pass
    return "unknown-project"


def prompt_versions(client: Any) -> dict[int, dict[str, Any]]:
    response = client.api.prompts.list(name=PROMPT_NAME, limit=50)
    versions: dict[int, dict[str, Any]] = {}
    for item in getattr(response, "data", []) or []:
        payload = _dump(item)
        raw_versions = payload.get("versions", getattr(item, "versions", [])) or []
        for version in raw_versions:
            version = int(version)
            prompt = client.get_prompt(
                PROMPT_NAME,
                version=version,
                type="text",
                max_retries=1,
                fetch_timeout_seconds=5,
            )
            versions[version] = {
                "version": version,
                "labels": list(getattr(prompt, "labels", []) or []),
                "created_at": payload.get("last_updated_at", ""),
            }
    return versions


def set_labels(client: Any, version: int, labels: list[str]) -> None:
    client.update_prompt(name=PROMPT_NAME, version=version, new_labels=labels)


def ensure_bootstrap(client: Any) -> dict[int, dict[str, Any]]:
    versions = prompt_versions(client)
    if 1 not in versions:
        created = client.create_prompt(
            name=PROMPT_NAME,
            prompt=PROMPT_V1,
            labels=["baseline", "production"],
            type="text",
            commit_message="CP2 baseline prompt v1",
        )
        versions[int(created.version)] = {
            "version": int(created.version),
            "labels": list(getattr(created, "labels", [])),
        }

    versions = prompt_versions(client)
    if 2 not in versions:
        created = client.create_prompt(
            name=PROMPT_NAME,
            prompt=PROMPT_V2,
            labels=["candidate"],
            type="text",
            commit_message="CP2 candidate prompt v2",
        )
        versions[int(created.version)] = {
            "version": int(created.version),
            "labels": list(getattr(created, "labels", [])),
        }

    versions = prompt_versions(client)
    if 1 in versions and 2 in versions:
        set_labels(client, 1, ["baseline", "production"])
        set_labels(client, 2, ["candidate"])
    return prompt_versions(client)


def labels_without_managed(labels: list[str]) -> list[str]:
    return [label for label in labels if label not in MANAGED_LABELS]


def apply_action(client: Any, action: str) -> dict[int, dict[str, Any]]:
    versions = ensure_bootstrap(client)
    if action == "bootstrap":
        return versions
    if 1 not in versions or 2 not in versions:
        raise RuntimeError("day13-chat must have versions 1 and 2 before label changes")

    labels_v1 = labels_without_managed(versions[1]["labels"])
    labels_v2 = labels_without_managed(versions[2]["labels"])
    if action == "promote":
        set_labels(client, 1, labels_v1 + ["baseline"])
        set_labels(client, 2, labels_v2 + ["candidate", "production"])
    elif action == "rollback":
        set_labels(client, 2, labels_v2 + ["candidate"])
        set_labels(client, 1, labels_v1 + ["baseline", "production"])
    else:
        raise ValueError(f"Unsupported action: {action}")
    return prompt_versions(client)


def render_status(client: Any, action: str, versions: dict[int, dict[str, Any]]) -> str:
    lines = [
        f"Action: {action}",
        f"Project: {project_name(client)}",
        f"Prompt: {PROMPT_NAME}",
        f"Versions found: {len(versions)}",
    ]
    for version in sorted(versions):
        labels = ", ".join(sorted(versions[version]["labels"])) or "(none)"
        lines.append(f"- version={version} labels={labels}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage CP2 Langfuse prompt versions")
    parser.add_argument(
        "action",
        choices=["bootstrap", "promote", "rollback", "demonstrate-rollback"],
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    client = get_client()
    if args.action == "demonstrate-rollback":
        bootstrap = ensure_bootstrap(client)
        promoted = apply_action(client, "promote")
        rolled_back = apply_action(client, "rollback")
        output = (
            render_status(client, "bootstrap", bootstrap)
            + render_status(client, "promote production -> v2", promoted)
            + render_status(client, "rollback production -> v1", rolled_back)
        )
    else:
        versions = apply_action(client, args.action)
        output = render_status(client, args.action, versions)

    client.flush()
    print(output, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
