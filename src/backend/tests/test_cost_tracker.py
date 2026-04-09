"""Tests for pipeline/cost_tracker.py — per-run LLM cost tracking."""

from __future__ import annotations

from pipeline.cost_tracker import CostEntry, PipelineCostTracker


class TestCostEntry:
    def test_fields(self):
        entry = CostEntry(
            stage="gemini",
            model="gemini-2.5-pro",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.000625,
        )
        assert entry.stage == "gemini"
        assert entry.model == "gemini-2.5-pro"
        assert entry.input_tokens == 100
        assert entry.output_tokens == 50
        assert entry.cost_usd == 0.000625

    def test_defaults(self):
        entry = CostEntry(stage="test", model="test-model")
        assert entry.input_tokens == 0
        assert entry.output_tokens == 0
        assert entry.cost_usd == 0.0


class TestPipelineCostTracker:
    def test_record_known_model_cost(self):
        tracker = PipelineCostTracker()
        entry = tracker.record("gpt_judge", "gpt-4o", input_tokens=1000, output_tokens=500)
        expected_cost = (1000 * 2.50 + 500 * 10.00) / 1_000_000
        assert entry.cost_usd == round(expected_cost, 6)
        assert entry.stage == "gpt_judge"
        assert entry.model == "gpt-4o"

    def test_record_unknown_model_uses_fallback(self):
        tracker = PipelineCostTracker()
        entry = tracker.record(
            "custom", "totally-unknown-model", input_tokens=1000, output_tokens=500
        )
        expected_cost = (1000 * 5.0 + 500 * 15.0) / 1_000_000
        assert entry.cost_usd == round(expected_cost, 6)

    def test_total_cost_usd(self):
        tracker = PipelineCostTracker()
        tracker.record("stage1", "gpt-4o", input_tokens=1000, output_tokens=500)
        tracker.record("stage2", "gpt-4o-mini", input_tokens=2000, output_tokens=1000)
        expected = sum(e.cost_usd for e in tracker.entries)
        assert tracker.total_cost_usd == round(expected, 6)

    def test_total_input_tokens(self):
        tracker = PipelineCostTracker()
        tracker.record("a", "gpt-4o", input_tokens=1000, output_tokens=0)
        tracker.record("b", "gpt-4o", input_tokens=2000, output_tokens=0)
        assert tracker.total_input_tokens == 3000

    def test_total_output_tokens(self):
        tracker = PipelineCostTracker()
        tracker.record("a", "gpt-4o", input_tokens=0, output_tokens=300)
        tracker.record("b", "gpt-4o", input_tokens=0, output_tokens=700)
        assert tracker.total_output_tokens == 1000

    def test_summary_structure(self):
        tracker = PipelineCostTracker()
        tracker.record("gemini", "gemini-2.5-pro", input_tokens=500, output_tokens=200)
        tracker.record("gpt_judge", "gpt-4o", input_tokens=1000, output_tokens=400)
        tracker.record("gemini", "gemini-2.5-pro", input_tokens=600, output_tokens=300)

        summary = tracker.summary()

        assert "total_cost_usd" in summary
        assert "total_input_tokens" in summary
        assert "total_output_tokens" in summary
        assert "call_count" in summary
        assert summary["call_count"] == 3
        assert "by_stage" in summary
        assert "gemini" in summary["by_stage"]
        assert "gpt_judge" in summary["by_stage"]
        assert summary["by_stage"]["gemini"]["calls"] == 2
        assert summary["by_stage"]["gpt_judge"]["calls"] == 1
        assert summary["total_input_tokens"] == 500 + 1000 + 600
        assert summary["total_output_tokens"] == 200 + 400 + 300

    def test_empty_tracker_zeroes(self):
        tracker = PipelineCostTracker()
        assert tracker.total_cost_usd == 0.0
        assert tracker.total_input_tokens == 0
        assert tracker.total_output_tokens == 0
        summary = tracker.summary()
        assert summary["call_count"] == 0
        assert summary["by_stage"] == {}
