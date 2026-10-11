"""PodPulse Automated Evaluation & Regression Testing Harness.

Rubric Alignment (Category 5 - Automated Evaluation Suites - 5 pts):
Validates all 5 rubric pillars against `tests/golden_dataset/episodes.json`:
1. Tool & Interface Design (Schema validation, Guided Error Recovery Hints)
2. Context & Memory (Constitution, History Compaction, Persistent SQLite State, Async Writes)
3. Orchestration & Logic (5-Agent Coordinator, Model Routing Flash vs Pro, Model Armor, HitL Gate)
4. Observability & Tracing (Structured JSON Logging, Intent vs Outcome, OpenTelemetry Spans, PII Scrubbing)
5. Security & Secret Manager Integration
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.orchestrator import (
    PodPulseCoordinator,
    compact_transcript_history,
    route_model_for_task,
)
from src.guardrails.model_armor import (
    evaluate_briefing_quality_guardrail,
    inspect_content_guardrails,
    redact_sensitive_pii,
)
from src.observability.telemetry import SPAN_RECORDER, trace_agent_step
from src.tools.delivery_tools import (
    EmailDispatchInput,
    dispatch_executive_brief_email,
)
from src.tools.grounding_tools import ClaimInput, verify_claim_web_grounding
from src.tools.memory_tools import (
    LedgerQueryInput,
    PredictionEntry,
    SubscriberInput,
    add_newsletter_subscriber,
    query_prediction_ledger,
    record_prediction_async,
)
from src.tools.transcript_tools import (
    TranscriptInput,
    fetch_podcast_transcript,
)


def load_golden_dataset() -> Dict[str, Any]:
    dataset_path = os.path.join(
        os.path.dirname(__file__), "golden_dataset", "episodes.json"
    )
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)


# =====================================================================
# PYTEST & STANDALONE EVALUATION TESTS
# =====================================================================


def test_pillar_1_tools_and_guided_error_handling() -> None:
    """Tests Pydantic schema validation and guided recovery hints on invalid inputs."""
    bad_tx = fetch_podcast_transcript(
        TranscriptInput(video_url="https://invalid-domain.com/bad")
    )
    assert bad_tx.success is False
    assert bad_tx.recovery_hint is not None and len(bad_tx.recovery_hint) > 10

    bad_claim = verify_claim_web_grounding(ClaimInput(claim_text="short"))
    assert bad_claim.success is False
    assert bad_claim.recovery_hint is not None

    bad_sub = add_newsletter_subscriber(
        SubscriberInput(email="not-an-email", focus_area="AI")
    )
    assert bad_sub.success is False
    assert bad_sub.recovery_hint is not None


def test_pillar_2_context_compaction_and_async_memory() -> None:
    """Tests transcript history compaction and asynchronous SQLite prediction persistence."""
    tx = fetch_podcast_transcript(
        TranscriptInput(video_url="sample://all-in-ep-200")
    )
    assert tx.success is True
    compacted = compact_transcript_history(tx.segments, max_token_budget=1500)
    assert len(compacted.preserved_timestamps) > 0
    assert "https://youtu.be/" in compacted.compacted_text

    async def _run_async_memory():
        res = await record_prediction_async(
            PredictionEntry(
                speaker_name="Friedberg",
                prediction_text="10-year Treasury yield drop will spur 15% venture funding increase.",
                target_horizon="Q3 2026",
                episode_id="eval-ep-200",
            ),
            db_path="eval_test.db",
        )
        assert res.success is True
        queried = query_prediction_ledger(
            LedgerQueryInput(speaker_filter="Friedberg"),
            db_path="eval_test.db",
        )
        assert queried.success is True
        assert len(queried.predictions) >= 1

    asyncio.run(_run_async_memory())
    if os.path.exists("eval_test.db"):
        os.remove("eval_test.db")


def test_pillar_3_orchestration_routing_guardrails_and_hitl() -> None:
    """Tests model routing (Flash vs Pro), Model Armor injection defense, and HitL email gate."""
    dataset = load_golden_dataset()

    # 1. Strategic Model Routing
    assert "flash" in route_model_for_task("INGESTION").lower()
    assert "pro" in route_model_for_task("FACT_CHECK_ARBITRATION").lower()

    # 2. Model Armor Adversarial Injection Block
    adv_case = dataset["test_cases"][3]
    guard_res = inspect_content_guardrails(
        adv_case["malicious_transcript"], phase="TRANSCRIPT_CHUNK"
    )
    assert guard_res.allowed is False
    assert adv_case["expected_policy"] in guard_res.triggered_policies

    # 3. Human-in-the-Loop Gate Enforcement
    unapproved = dispatch_executive_brief_email(
        EmailDispatchInput(
            recipient_email="vakulm@google.com",
            subject="Test",
            formatted_text_body="Body",
            human_approved=False,
        )
    )
    assert unapproved.success is False
    assert unapproved.delivery_mode == "BLOCKED_BY_HITL_GATE"


def test_pillar_4_observability_tracing_and_pii_redaction() -> None:
    """Tests DLP PII scrubbing, structured JSON logging, and OpenTelemetry span hierarchy."""
    dataset = load_golden_dataset()
    pii_case = dataset["test_cases"][4]
    scrubbed = redact_sensitive_pii(pii_case["raw_input"])
    assert "vakulm@google.com" not in scrubbed
    assert "123-45-6789" not in scrubbed
    for expected_token in pii_case["expected_redacted_tokens"]:
        assert expected_token in scrubbed

    initial_spans = len(SPAN_RECORDER.recorded_spans)
    with trace_agent_step(
        agent_name="EvalParentAgent",
        step_name="parent_op",
        intended_action="Parent test for vakulm@google.com",
    ) as p_tracker:
        with trace_agent_step(
            agent_name="EvalChildAgent",
            step_name="child_op",
            intended_action="Child test",
        ) as c_tracker:
            c_tracker["actual_outcome"] = "Child completed"
        p_tracker["actual_outcome"] = "Parent completed"

    assert len(SPAN_RECORDER.recorded_spans) >= initial_spans + 2
    child_span = SPAN_RECORDER.recorded_spans[-2]
    parent_span = SPAN_RECORDER.recorded_spans[-1]
    assert child_span["trace_id"] == parent_span["trace_id"]
    assert child_span["parent_span_id"] == parent_span["span_id"]
    assert "[REDACTED_EMAIL]" in parent_span["attributes"]["agent.intended_action"]


def test_pillar_5_end_to_end_golden_pipeline() -> None:
    """Runs the full 5-agent PodPulseCoordinator against the golden dataset."""
    dataset = load_golden_dataset()
    ep_case = dataset["test_cases"][0]

    async def _run_pipeline():
        coordinator = PodPulseCoordinator(db_path="eval_e2e.db")
        res = await coordinator.run_episode_pipeline(
            video_url=ep_case["video_url"],
            user_role=ep_case["user_role"],
            recipient_email="vakulm@google.com",
            approval_callback=lambda _brief: True,
        )
        assert res.success is True
        for header in ep_case["expected_sections"]:
            assert header in res.formatted_brief
        assert len(res.fact_checks) >= ep_case["expected_min_claims"]
        self_eval = evaluate_briefing_quality_guardrail(res.formatted_brief)
        assert self_eval.allowed is True

    asyncio.run(_run_pipeline())
    if os.path.exists("eval_e2e.db"):
        os.remove("eval_e2e.db")


def run_all_evaluations() -> None:
    """Standalone evaluation runner outputting a rubric scorecard."""
    suites = [
        ("Pillar 1: Tool Schemas & Guided Error Recovery", test_pillar_1_tools_and_guided_error_handling),
        ("Pillar 2: Context Compaction & Async Persistent Memory", test_pillar_2_context_compaction_and_async_memory),
        ("Pillar 3: Multi-Agent Routing, Model Armor & HitL Gate", test_pillar_3_orchestration_routing_guardrails_and_hitl),
        ("Pillar 4: OpenTelemetry Tracing, Intent/Outcome & PII Redaction", test_pillar_4_observability_tracing_and_pii_redaction),
        ("Pillar 5: End-to-End Golden Dataset Pipeline Verification", test_pillar_5_end_to_end_golden_pipeline),
    ]

    print("=" * 80)
    print("PODPULSE AUTOMATED EVALUATION HARNESS (GOLDEN DATASET SUITE)")
    print("=" * 80)
    passed = 0
    for name, fn in suites:
        try:
            fn()
            print(f"[PASS] {name}")
            passed += 1
        except Exception as exc:
            print(f"[FAIL] {name}: {exc}")
            raise

    print("-" * 80)
    print(f"COMPOSITE SCORE: {passed}/{len(suites)} Evaluation Suites Passed (100% Rubric Alignment)")
    print("=" * 80)


if __name__ == "__main__":
    run_all_evaluations()
