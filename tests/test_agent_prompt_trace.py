from __future__ import annotations

from contextlib import contextmanager

from app import agent as agent_module


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.span_updates: list[dict] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)


class RecordingObservation:
    def __init__(self, name: str, as_type: str) -> None:
        self.name = name
        self.as_type = as_type
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


def test_agent_records_prompt_version_with_v4_observation_api(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    propagated: list[dict] = []

    @contextmanager
    def record_attributes(**kwargs):
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(agent_module, "propagate_attributes", record_attributes)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
        correlation_id="req-12345678",
    )

    span_update = client.span_updates[-1]
    assert span_update["metadata"] == {
        "doc_count": 1,
        "query_preview": "Explain traces",
        "prompt_name": "day13-chat",
        "prompt_label": "production",
        "prompt_version": "3",
        "prompt_source": "langfuse",
        "prompt_fetch_error": "",
    }
    assert span_update["version"] == "3"
    assert propagated[0]["metadata"]["correlation_id"] == "req-12345678"
    assert propagated[-1]["prompt"] is client.prompt


def test_agent_creates_retrieval_and_generation_children(monkeypatch) -> None:
    client = RecordingLangfuseClient()
    observations: list[RecordingObservation] = []

    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "candidate")
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)
    monkeypatch.setattr(
        agent_module,
        "get_current_trace_id",
        lambda _: "trace-cp2-test-0000000000000000000000000001",
    )

    @contextmanager
    def record_observation(**kwargs):
        observation = RecordingObservation(kwargs["name"], kwargs["as_type"])
        observations.append(observation)
        yield observation

    monkeypatch.setattr(agent_module, "start_observation", record_observation)

    agent = agent_module.LabAgent()
    result = agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
        correlation_id="req-12345678",
    )

    assert [(item.name, item.as_type) for item in observations] == [
        ("retrieval", "retriever"),
        ("llm-generation", "generation"),
    ]
    generation_updates = observations[1].updates
    assert generation_updates[-1]["usage_details"]["prompt_tokens"] == result.tokens_in
    assert generation_updates[-1]["usage_details"]["completion_tokens"] == result.tokens_out
    assert generation_updates[-1]["cost_details"]["total_cost"] == result.cost_usd
    assert result.trace_id == "trace-cp2-test-0000000000000000000000000001"
