"""Unit tests for SOCGrader."""
import pytest

from app.models import Action, ActionType, BusinessOutage
from app.soc_grader import SOCGrader


ATTACKER = "10.0.0.1"
DECOY_A = "10.0.0.2"
DECOY_B = "10.0.0.3"


def _action(action_type: ActionType, target_ip: str) -> Action:
    return Action(action_type=action_type, target_ip=target_ip, session_id="test")


# --- Score clamping at 0.0 boundary ---

def test_score_does_not_go_below_zero():
    grader = SOCGrader(sla_penalty_rate=0.5)
    grader.survival_score = 0.2
    grader.active_outages.append(
        BusinessOutage(target_ip=DECOY_A, created_at_tick=0, penalty_per_tick=0.5)
    )
    grader.apply_tick_penalties(tick_cost=10)  # penalty = 5.0, way over 0.2
    assert grader.survival_score == 0.15  # epsilon floor


def test_score_does_not_exceed_one_on_correct_block():
    grader = SOCGrader(sla_penalty_rate=0.05)
    grader.survival_score = 0.85  # already at epsilon ceiling
    result = grader.grade_action(_action(ActionType.BlockIP, ATTACKER), ATTACKER, 0)
    assert result.survival_score == 0.85  # clamped at max


# --- Simultaneous outages accumulate correctly ---

def test_simultaneous_outages_accumulate():
    grader = SOCGrader(sla_penalty_rate=0.1)
    grader.survival_score = 0.75
    # Create two outages
    grader.grade_action(_action(ActionType.BlockIP, DECOY_A), ATTACKER, 0)
    grader.grade_action(_action(ActionType.BlockIP, DECOY_B), ATTACKER, 0)
    assert len(grader.active_outages) == 2

    # Each wrong block applies -0.12 shock: 0.75 - 0.12 - 0.12 = 0.51
    # Then each outage contributes 0.1 per tick; tick_cost=1 → total penalty = 0.2
    # Final: 0.51 - 0.2 = 0.31
    grader.apply_tick_penalties(tick_cost=1)
    assert abs(grader.survival_score - 0.31) < 1e-2


def test_simultaneous_outages_each_contribute_independently():
    grader = SOCGrader(sla_penalty_rate=0.05)
    grader.survival_score = 0.75
    grader.grade_action(_action(ActionType.BlockIP, DECOY_A), ATTACKER, 0)
    grader.grade_action(_action(ActionType.BlockIP, DECOY_B), ATTACKER, 0)
    # Each wrong block applies -0.12 shock: 0.75 - 0.12 - 0.12 = 0.51
    # 2 outages × 0.05 rate × 2 tick_cost = 0.2 penalty
    # Final: 0.51 - 0.2 = 0.31
    grader.apply_tick_penalties(tick_cost=2)
    assert abs(grader.survival_score - 0.31) < 1e-2


# --- resolve_outage removes only the targeted outage ---

def test_resolve_outage_removes_only_targeted():
    grader = SOCGrader(sla_penalty_rate=0.1)
    grader.grade_action(_action(ActionType.BlockIP, DECOY_A), ATTACKER, 0)
    grader.grade_action(_action(ActionType.BlockIP, DECOY_B), ATTACKER, 0)
    assert len(grader.active_outages) == 2

    removed = grader.resolve_outage(DECOY_A)
    assert removed is True
    assert len(grader.active_outages) == 1
    assert grader.active_outages[0].target_ip == DECOY_B


def test_resolve_outage_returns_false_when_not_found():
    grader = SOCGrader(sla_penalty_rate=0.1)
    result = grader.resolve_outage("10.0.0.99")
    assert result is False


def test_resolve_outage_via_grade_action():
    grader = SOCGrader(sla_penalty_rate=0.1)
    grader.grade_action(_action(ActionType.BlockIP, DECOY_A), ATTACKER, 0)
    result = grader.grade_action(_action(ActionType.ResolveOutage, DECOY_A), ATTACKER, 1)
    assert result.outage_resolved is True
    assert len(grader.active_outages) == 0


# --- Other action types produce no score change ---

def test_allow_ip_no_score_change():
    grader = SOCGrader(sla_penalty_rate=0.1)
    grader.survival_score = 0.7
    result = grader.grade_action(_action(ActionType.AllowIP, DECOY_A), ATTACKER, 0)
    assert result.reward == 0.0
    assert grader.survival_score == 0.7


def test_isolate_host_no_score_change():
    grader = SOCGrader(sla_penalty_rate=0.1)
    grader.survival_score = 0.6
    result = grader.grade_action(_action(ActionType.IsolateHost, DECOY_A), ATTACKER, 0)
    assert result.reward == 0.0
    assert grader.survival_score == 0.6
