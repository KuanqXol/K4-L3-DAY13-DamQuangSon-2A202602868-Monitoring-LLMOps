from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import metrics
from .mock_llm import FakeLLM
from .mock_rag import retrieve
from .pii import hash_user_id, summarize_text
from .prompt_management import resolve_prompt
from .tracing import (
    get_current_trace_id,
    get_langfuse_client,
    observe,
    propagate_attributes,
    start_observation,
    tracing_enabled,
    update_observation,
)


@dataclass
class AgentResult:
    answer: str
    latency_ms: int
    ttft_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    quality_score: float
    trace_id: str | None = None


class LabAgent:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.llm = FakeLLM(model=model)

    @observe(name="lab-agent-run", as_type="agent", capture_input=False, capture_output=False)
    def run(
        self,
        user_id: str,
        feature: str,
        session_id: str,
        message: str,
        correlation_id: str,
    ) -> AgentResult:
        langfuse_client = get_langfuse_client()
        with propagate_attributes(
            user_id=hash_user_id(user_id),
            session_id=session_id,
            tags=["lab", feature, self.model],
            trace_name="day13-agent-request",
            environment=os.getenv("APP_ENV", "dev"),
            metadata={
                "feature": feature,
                "model": self.model,
                "correlation_id": correlation_id,
            },
        ):
            started = time.perf_counter()
            with start_observation(
                name="retrieval",
                as_type="retriever",
                input={"query_preview": summarize_text(message)},
                metadata={
                    "correlation_id": correlation_id,
                    "feature": feature,
                },
            ) as retrieval_observation:
                try:
                    docs = retrieve(message)
                except Exception as exc:
                    update_observation(
                        retrieval_observation,
                        level="ERROR",
                        status_message=type(exc).__name__,
                        output={"retrieval_success": False},
                    )
                    raise
                update_observation(
                    retrieval_observation,
                    output={
                        "doc_count": len(docs),
                        "documents_preview": [summarize_text(doc) for doc in docs],
                        "retrieval_success": True,
                    },
                )

            prompt = resolve_prompt(
                langfuse_client,
                feature=feature,
                docs=docs,
                message=message,
                enabled=tracing_enabled(),
            )
            langfuse_client.update_current_span(
                metadata={
                    "doc_count": len(docs),
                    "query_preview": summarize_text(message),
                    "prompt_name": prompt.name,
                    "prompt_label": prompt.label,
                    "prompt_version": prompt.version,
                    "prompt_source": prompt.source,
                    "prompt_fetch_error": prompt.fetch_error or "",
                },
                version=prompt.version,
            )

            with propagate_attributes(prompt=prompt.managed_prompt):
                completion_start_time = datetime.now(timezone.utc)
                with start_observation(
                    name="llm-generation",
                    as_type="generation",
                    input={
                        "prompt_name": prompt.name,
                        "prompt_label": prompt.label,
                        "prompt_version": prompt.version,
                        "prompt_preview": summarize_text(prompt.text),
                    },
                    metadata={
                        "correlation_id": correlation_id,
                        "feature": feature,
                        "prompt_source": prompt.source,
                        "prompt_name": prompt.name,
                        "prompt_label": prompt.label,
                        "prompt_version": prompt.version,
                    },
                    model=self.model,
                    model_parameters={"temperature": 0.0},
                    completion_start_time=completion_start_time,
                    prompt=prompt.managed_prompt,
                ) as generation_observation:
                    try:
                        response = self.llm.generate(prompt.text)
                    except Exception as exc:
                        update_observation(
                            generation_observation,
                            level="ERROR",
                            status_message=type(exc).__name__,
                        )
                        raise

                    input_cost = round((response.usage.input_tokens / 1_000_000) * 3, 6)
                    output_cost = round((response.usage.output_tokens / 1_000_000) * 15, 6)
                    cost_usd = round(input_cost + output_cost, 6)
                    update_observation(
                        generation_observation,
                        output={"answer_preview": summarize_text(response.text)},
                        usage_details={
                            "prompt_tokens": response.usage.input_tokens,
                            "completion_tokens": response.usage.output_tokens,
                            "total_tokens": response.usage.input_tokens
                            + response.usage.output_tokens,
                        },
                        cost_details={
                            "input_cost": input_cost,
                            "output_cost": output_cost,
                            "total_cost": cost_usd,
                        },
                    )
            quality_score = self._heuristic_quality(message, response.text, docs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            trace_id = get_current_trace_id(langfuse_client)

        metrics.record_request(
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            cost_usd=cost_usd,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            quality_score=quality_score,
        )

        return AgentResult(
            answer=response.text,
            latency_ms=latency_ms,
            ttft_ms=response.ttft_ms,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            cost_usd=cost_usd,
            quality_score=quality_score,
            trace_id=trace_id,
        )

    def _estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        input_cost = (tokens_in / 1_000_000) * 3
        output_cost = (tokens_out / 1_000_000) * 15
        return round(input_cost + output_cost, 6)

    def _heuristic_quality(self, question: str, answer: str, docs: list[str]) -> float:
        score = 0.5
        if docs:
            score += 0.2
        if len(answer) > 40:
            score += 0.1
        if question.lower().split()[0:1] and any(token in answer.lower() for token in question.lower().split()[:3]):
            score += 0.1
        if "[REDACTED" in answer:
            score -= 0.2
        return round(max(0.0, min(1.0, score)), 2)
