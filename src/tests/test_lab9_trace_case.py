"""Regression test from docs/trace_case.md: seeded_regression C-013@11 (FM-05 pre_deducted).

First wrong step: event 5 `proposal {"amount_vnd": 0}` -- the agent subtracts the prior refund itself
(event 4 refund_history) and denies on its own, so the host never records policy_denied.
The ledger is 0 either way, so RefundAmountCorrect cannot see it; ProposalCorrect can.
"""
import pytest

pytestmark = pytest.mark.student


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def _case(shape):
    from lab9.trace_case import investigate

    case = investigate(shape, "C-013", 11)
    return case["trial"], case["label"]


def test_lab9_trace_case_c013_caught_on_seeded_regression():
    from lab9.graders import ProposalCorrect, RefundAmountCorrect

    trial, label = _case("seeded_regression")
    kinds = [e["kind"] for e in trial["events"]]
    assert "refund_history" in kinds and "proposal" in kinds          # the self-deduction step
    assert trial["lab8_pass"] is False
    assert RefundAmountCorrect().evaluate(_ctx(trial, label)).value is True   # ledger looks fine...
    assert ProposalCorrect().evaluate(_ctx(trial, label)).value is False      # ...the proposal is not


def test_lab9_trace_case_c013_passes_on_fixed():
    from lab9.graders import ProposalCorrect

    trial, label = _case("fixed")
    assert trial["lab8_pass"] is True
    assert ProposalCorrect().evaluate(_ctx(trial, label)).value is True
