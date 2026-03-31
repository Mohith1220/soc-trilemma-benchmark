"""
Property-based tests for OpenEnv SOC Trilemma.
Each test maps to a correctness property from the design document.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models import ActionType, ACTION_COSTS


# --- Property 9: All action types have a positive cost ---

@settings(max_examples=100)
@given(action_type=st.sampled_from(list(ActionType)))
def test_all_action_types_have_positive_cost(action_type: ActionType):
    # Feature: openenv-soc-trilemma, Property 9: All action types have a positive cost
    # Validates: Requirements 3.4
    assert action_type in ACTION_COSTS, f"{action_type} missing from ACTION_COSTS"
    assert ACTION_COSTS[action_type] > 0, (
        f"ACTION_COSTS[{action_type}] = {ACTION_COSTS[action_type]} is not positive"
    )


# --- Property 24: Invalid task YAML raises ConfigurationError ---

import os
import tempfile

from app.config import load_task_config
from app.exceptions import ConfigurationError


# Strategy: generate dicts that are missing at least one required field
_REQUIRED_FIELDS = ["max_steps", "stage_time_budgets", "sla_penalty_rate", "num_decoys"]

_VALID_BASE = {
    "max_steps": 100,
    "stage_time_budgets": {
        "Recon": 30,
        "Lateral_Movement": 25,
        "Exfiltration": 20,
    },
    "sla_penalty_rate": 0.05,
    "num_decoys": 2,
}


def _dict_to_yaml(d: dict) -> str:
    import yaml
    return yaml.dump(d)


@settings(max_examples=100)
@given(missing_field=st.sampled_from(_REQUIRED_FIELDS))
def test_invalid_task_yaml_raises_configuration_error(missing_field: str):
    # Feature: openenv-soc-trilemma, Property 24: Invalid task YAML raises ConfigurationError
    # Validates: Requirements 8.4
    data = {k: v for k, v in _VALID_BASE.items() if k != missing_field}
    yaml_content = _dict_to_yaml(data)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        with pytest.raises(ConfigurationError):
            load_task_config(tmp_path)
    finally:
        os.unlink(tmp_path)


# --- Property 1: Seed determinism ---
# --- Property 4: SeedEngine role assignment uses template IP pool ---

from app.models import DPIEntry, DPITemplate, KillChainStage
from app.seed_engine import SeedEngine

# Strategy: DPITemplate with at least 3 IPs in ip_pool
_IP_POOL_BASE = [
    "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5",
    "10.0.0.6", "10.0.0.7",
]

_SAMPLE_ENTRY = DPIEntry(
    src_ip="10.0.0.1",
    dst_ip="10.0.0.2",
    protocol="TCP",
    payload_summary="sample",
    flags=[],
)

st_ip_pool = st.lists(
    st.from_regex(r"10\.0\.\d{1,3}\.\d{1,3}", fullmatch=True),
    min_size=3,
    max_size=10,
    unique=True,
)

st_dpi_template = st_ip_pool.map(
    lambda pool: DPITemplate(
        stage=KillChainStage.Recon,
        entries=[_SAMPLE_ENTRY],
        ip_pool=pool,
    )
)


@settings(max_examples=100)
@given(seed=st.integers(), template=st_dpi_template)
def test_seed_determinism(seed: int, template: DPITemplate):
    # Feature: openenv-soc-trilemma, Property 1: Seed determinism
    # Validates: Requirements 1.2
    engine = SeedEngine()
    num_decoys = min(2, len(template.ip_pool) - 1)
    r1 = engine.assign_roles(seed, template, num_decoys)
    r2 = engine.assign_roles(seed, template, num_decoys)
    assert r1.attacker_ip == r2.attacker_ip
    assert r1.decoy_ips == r2.decoy_ips


@settings(max_examples=100)
@given(seed=st.integers(), template=st_dpi_template)
def test_role_assignment_uses_template_ip_pool(seed: int, template: DPITemplate):
    # Feature: openenv-soc-trilemma, Property 4: SeedEngine role assignment uses template IP pool
    # Validates: Requirements 2.2
    engine = SeedEngine()
    num_decoys = min(2, len(template.ip_pool) - 1)
    assignment = engine.assign_roles(seed, template, num_decoys)
    ip_pool_set = set(template.ip_pool)

    # All assigned IPs must come from the pool
    assert assignment.attacker_ip in ip_pool_set
    for ip in assignment.decoy_ips:
        assert ip in ip_pool_set

    # No IP should appear in both roles
    assert assignment.attacker_ip not in assignment.decoy_ips


# --- Property 15: Stage advances when time budget is exhausted ---
# --- Property 16: Exfiltration failure terminates ---

from app.kill_chain import KillChain

_STAGE_BUDGETS = {
    KillChainStage.Recon: 30,
    KillChainStage.LateralMovement: 25,
    KillChainStage.Exfiltration: 20,
}

# Strategy: generate a budget value and a tick cost that exceeds it
st_budget = st.integers(min_value=1, max_value=50)
st_excess = st.integers(min_value=0, max_value=20)


@settings(max_examples=100)
@given(budget=st_budget, excess=st_excess)
def test_stage_advances_when_budget_exhausted(budget: int, excess: int):
    # Feature: openenv-soc-trilemma, Property 15: Stage advances when time budget is exhausted
    # Validates: Requirements 5.2, 5.3
    budgets = {
        KillChainStage.Recon: budget,
        KillChainStage.LateralMovement: budget,
        KillChainStage.Exfiltration: budget,
    }
    kc = KillChain()
    # Advance tick past the budget
    kc.advance_tick(budget + excess)
    assert kc.should_advance_stage(budgets) is True
    new_stage = kc.advance_stage()
    assert new_stage == KillChainStage.LateralMovement


@settings(max_examples=100)
@given(budget=st_budget, excess=st_excess)
def test_exfiltration_failure_terminates(budget: int, excess: int):
    # Feature: openenv-soc-trilemma, Property 16: Exfiltration failure terminates the episode
    # Validates: Requirements 5.4
    budgets = {
        KillChainStage.Recon: budget,
        KillChainStage.LateralMovement: budget,
        KillChainStage.Exfiltration: budget,
    }
    kc = KillChain()
    # Advance to Exfiltration stage
    kc.advance_stage()
    kc.advance_stage()
    assert kc.stage == KillChainStage.Exfiltration

    # Advance tick past the exfiltration budget (relative to stage_tick_start)
    kc.advance_tick(budget + excess)
    assert kc.should_advance_stage(budgets) is True

    # advance_stage at Exfiltration returns None (terminal)
    result = kc.advance_stage()
    assert result is None
    assert kc.is_terminal() is True


# --- Properties 10–14: SOCGrader ---

from app.models import Action, ActionType
from app.soc_grader import SOCGrader

# Strategies
st_ipv4 = st.builds(
    lambda a, b: f"10.0.{a}.{b}",
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=1, max_value=254),
)
st_penalty_rate = st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False)
st_tick = st.integers(min_value=0, max_value=1000)
st_tick_cost = st.integers(min_value=1, max_value=10)


def _make_action(action_type: ActionType, target_ip: str) -> Action:
    return Action(action_type=action_type, target_ip=target_ip, session_id="test")


@settings(max_examples=100)
@given(
    rate=st_penalty_rate,
    attacker_ip=st_ipv4,
    tick=st_tick,
    initial_score=st.floats(min_value=0.0, max_value=0.8, allow_nan=False, allow_infinity=False),
)
def test_correct_block_increases_survival_score(
    rate: float, attacker_ip: str, tick: int, initial_score: float
):
    # Feature: openenv-soc-trilemma, Property 10: Correct block increases survival score
    # Validates: Requirements 3.5
    grader = SOCGrader(sla_penalty_rate=rate)
    grader.survival_score = initial_score
    before = grader.survival_score
    action = _make_action(ActionType.BlockIP, attacker_ip)
    result = grader.grade_action(action, attacker_ip, tick)
    assert result.survival_score >= before


@settings(max_examples=100)
@given(
    rate=st_penalty_rate,
    attacker_ip=st_ipv4,
    decoy_ip=st_ipv4,
    tick=st_tick,
)
def test_incorrect_block_creates_business_outage(
    rate: float, attacker_ip: str, decoy_ip: str, tick: int
):
    # Feature: openenv-soc-trilemma, Property 11: Incorrect block creates a Business Outage
    # Validates: Requirements 3.6
    # Ensure attacker and decoy are different IPs
    if attacker_ip == decoy_ip:
        return
    grader = SOCGrader(sla_penalty_rate=rate)
    before_count = len(grader.active_outages)
    action = _make_action(ActionType.BlockIP, decoy_ip)
    result = grader.grade_action(action, attacker_ip, tick)
    assert result.outage_created is True
    assert len(grader.active_outages) == before_count + 1
    assert grader.active_outages[-1].target_ip == decoy_ip


@settings(max_examples=100)
@given(
    rate=st_penalty_rate,
    n_outages=st.integers(min_value=1, max_value=5),
    tick_cost=st_tick_cost,
    initial_score=st.floats(min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_sla_penalties_apply_per_active_outage_per_tick(
    rate: float, n_outages: int, tick_cost: int, initial_score: float
):
    # Feature: openenv-soc-trilemma, Property 12: SLA penalties apply per active outage per tick
    # Validates: Requirements 4.1, 4.2
    grader = SOCGrader(sla_penalty_rate=rate)
    grader.survival_score = initial_score
    # Add N outages manually
    for i in range(n_outages):
        from app.models import BusinessOutage
        grader.active_outages.append(
            BusinessOutage(target_ip=f"10.0.0.{i + 1}", created_at_tick=0, penalty_per_tick=rate)
        )
    expected_penalty = n_outages * rate * tick_cost
    expected_score = max(0.0, min(1.0, initial_score - expected_penalty))
    grader.apply_tick_penalties(tick_cost)
    assert abs(grader.survival_score - expected_score) < 1e-7


@settings(max_examples=100)
@given(
    rate=st_penalty_rate,
    attacker_ip=st_ipv4,
    decoy_ip=st_ipv4,
    tick=st_tick,
    tick_cost=st_tick_cost,
)
def test_survival_score_always_clamped(
    rate: float, attacker_ip: str, decoy_ip: str, tick: int, tick_cost: int
):
    # Feature: openenv-soc-trilemma, Property 13: Survival score is always clamped to [0.0, 1.0]
    # Validates: Requirements 4.3
    grader = SOCGrader(sla_penalty_rate=rate)
    # Apply many incorrect blocks to drive score down
    for _ in range(20):
        if attacker_ip != decoy_ip:
            action = _make_action(ActionType.BlockIP, decoy_ip)
            grader.grade_action(action, attacker_ip, tick)
        grader.apply_tick_penalties(tick_cost)
        assert 0.0 <= grader.survival_score <= 1.0
    # Apply correct block to drive score up
    action = _make_action(ActionType.BlockIP, attacker_ip)
    grader.grade_action(action, attacker_ip, tick)
    assert 0.0 <= grader.survival_score <= 1.0


@settings(max_examples=100)
@given(
    rate=st_penalty_rate,
    attacker_ip=st_ipv4,
    decoy_ip=st_ipv4,
    tick=st_tick,
    tick_cost=st_tick_cost,
)
def test_resolving_outage_removes_it_from_active_penalties(
    rate: float, attacker_ip: str, decoy_ip: str, tick: int, tick_cost: int
):
    # Feature: openenv-soc-trilemma, Property 14: Resolving an outage removes it from active penalties
    # Validates: Requirements 4.4
    if attacker_ip == decoy_ip:
        return
    grader = SOCGrader(sla_penalty_rate=rate)
    # Create an outage
    action = _make_action(ActionType.BlockIP, decoy_ip)
    grader.grade_action(action, attacker_ip, tick)
    assert len(grader.active_outages) == 1

    # Resolve it
    resolve_action = _make_action(ActionType.ResolveOutage, decoy_ip)
    result = grader.grade_action(resolve_action, attacker_ip, tick)
    assert result.outage_resolved is True
    assert len(grader.active_outages) == 0

    # Subsequent tick advance should not apply the resolved outage's penalty
    score_before = grader.survival_score
    grader.apply_tick_penalties(tick_cost)
    assert grader.survival_score == score_before


# --- Property 6: DPITemplate serialization round-trip ---
# --- Property 19: render_dashboard includes all observation fields ---

import json

from app.pretty_printer import PrettyPrinter
from app.models import DPISnapshot, Observation

_printer = PrettyPrinter()

# Strategy for DPITemplate (reuse st_dpi_template defined above)

@settings(max_examples=100)
@given(template=st_dpi_template)
def test_dpi_template_serialization_round_trip(template: DPITemplate):
    # Feature: openenv-soc-trilemma, Property 6: DPITemplate serialization round-trip
    # Validates: Requirements 2.4
    json_str = _printer.dpi_template_to_json(template)
    restored = DPITemplate.model_validate_json(json_str)
    assert restored == template


# Strategy for Observation
st_alert_message = st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" ._-"))

st_alert = st.builds(
    lambda msg: __import__("app.models", fromlist=["Alert"]).Alert(
        message=msg, severity="info", tick=0
    ),
    msg=st_alert_message,
)

st_dpi_snapshot = st_dpi_template.map(
    lambda t: DPISnapshot(
        stage=t.stage,
        entries=t.entries,
        attacker_ip=t.ip_pool[0],
        decoy_ips=t.ip_pool[1:3],
    )
)

st_observation = st.builds(
    lambda snapshot, alerts, score, tick, done: Observation(
        stage=snapshot.stage,
        dpi_data=snapshot,
        alerts=alerts,
        survival_score=score,
        tick=tick,
        done=done,
        dom="",
    ),
    snapshot=st_dpi_snapshot,
    alerts=st.lists(st_alert, min_size=0, max_size=5),
    score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    tick=st.integers(min_value=0, max_value=1000),
    done=st.booleans(),
)


@settings(max_examples=100)
@given(obs=st_observation)
def test_render_dashboard_includes_all_observation_fields(obs: Observation):
    # Feature: openenv-soc-trilemma, Property 19: render_dashboard includes all observation fields
    # Validates: Requirements 6.2, 6.3
    html = _printer.render_dashboard(obs)
    assert obs.stage.value in html
    assert str(obs.survival_score) in html
    assert str(obs.tick) in html
    for alert in obs.alerts:
        assert alert.message in html


# ---------------------------------------------------------------------------
# Properties 2, 17, 18, 23: SessionManager
# ---------------------------------------------------------------------------

from app.config import load_task_config
from app.session_manager import SessionManager
from app.models import ACTION_COSTS, Action, ActionType, KillChainStage

_TASK_CONFIG = load_task_config("tasks/easy.yaml")


def _make_manager() -> SessionManager:
    return SessionManager(task_config=_TASK_CONFIG)


def _block_action(session_id: str, target_ip: str) -> Action:
    return Action(action_type=ActionType.BlockIP, target_ip=target_ip, session_id=session_id)


# --- Property 2: Reset produces a clean initial observation ---

@settings(max_examples=100)
@given(seed=st.integers())
def test_reset_produces_clean_initial_observation(seed: int):
    # Feature: openenv-soc-trilemma, Property 2: Reset produces a clean initial observation
    # Validates: Requirements 1.3, 5.1
    mgr = _make_manager()
    obs = mgr.create_or_reset("prop2", seed=seed)
    assert obs.stage == KillChainStage.Recon
    assert obs.alerts == []
    assert obs.done is False
    assert obs.survival_score == 1.0


# --- Property 17: Successful neutralization terminates the episode ---

@settings(max_examples=100)
@given(seed=st.integers())
def test_successful_neutralization_terminates_episode(seed: int):
    # Feature: openenv-soc-trilemma, Property 17: Successful neutralization terminates the episode
    # Validates: Requirements 5.5
    mgr = _make_manager()
    obs = mgr.create_or_reset("prop17", seed=seed)
    attacker_ip = obs.dpi_data.attacker_ip
    action = _block_action("prop17", attacker_ip)
    result = mgr.step("prop17", action)
    assert result.done is True
    assert result.survival_score > 0.0


# --- Property 18: Observation contains all required fields ---

@settings(max_examples=100)
@given(seed=st.integers())
def test_observation_contains_all_required_fields(seed: int):
    # Feature: openenv-soc-trilemma, Property 18: Observation contains all required fields
    # Validates: Requirements 6.1
    mgr = _make_manager()
    obs = mgr.create_or_reset("prop18", seed=seed)
    assert obs.stage is not None
    assert obs.dpi_data is not None
    assert obs.alerts is not None
    assert obs.survival_score is not None
    assert obs.tick is not None
    assert obs.done is not None
    assert obs.dom is not None and obs.dom != ""


# --- Property 23: max_steps terminates the episode ---

@settings(max_examples=20)
@given(seed=st.integers())
def test_max_steps_terminates_episode(seed: int):
    # Feature: openenv-soc-trilemma, Property 23: max_steps terminates the episode
    # Validates: Requirements 8.3
    mgr = _make_manager()
    obs = mgr.create_or_reset("prop23", seed=seed)
    # Use a decoy IP to avoid a correct block
    decoy_ip = obs.dpi_data.decoy_ips[0]
    action = _block_action("prop23", decoy_ip)

    result = obs
    for _ in range(_TASK_CONFIG.max_steps):
        result = mgr.step("prop23", action)
        if result.done:
            break

    assert result.done is True


# ---------------------------------------------------------------------------
# Properties 3, 7, 8: HTTP endpoint properties
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from app.app import create_app

_test_app = create_app()
_client = TestClient(_test_app)


def _reset_session(session_id: str, seed: int = 42) -> dict:
    resp = _client.post("/reset", json={"seed": seed, "session_id": session_id})
    assert resp.status_code == 200
    return resp.json()


# --- Property 3: Invalid seed rejected with 422 ---

@settings(max_examples=100)
@given(bad_seed=st.one_of(
    st.text(min_size=1, max_size=20),
    st.floats(allow_nan=False, allow_infinity=False),
    st.none(),
    st.lists(st.integers(), min_size=0, max_size=3),
))
def test_invalid_seed_rejected_with_422(bad_seed):
    # Feature: openenv-soc-trilemma, Property 3: Invalid seed rejected with 422
    # Validates: Requirements 1.4
    payload = {"session_id": "prop3_test"}
    if bad_seed is not None:
        payload["seed"] = bad_seed
    resp = _client.post("/reset", json=payload)
    assert resp.status_code == 422


# --- Property 7: Invalid action payload rejected without tick advance ---

@settings(max_examples=100)
@given(seed=st.integers())
def test_invalid_action_payload_rejected_without_tick_advance(seed: int):
    # Feature: openenv-soc-trilemma, Property 7: Invalid action payload rejected without tick advance
    # Validates: Requirements 3.1, 3.2
    session_id = f"prop7_{seed}"
    obs_before = _reset_session(session_id, seed=seed)
    tick_before = obs_before["tick"]

    # Send a malformed action (missing required fields)
    bad_payload = {"session_id": session_id}  # missing action_type and target_ip
    resp = _client.post("/step", json=bad_payload)
    assert resp.status_code == 422

    # Tick must be unchanged
    state_resp = _client.get("/state", params={"session_id": session_id})
    assert state_resp.status_code == 200
    assert state_resp.json()["tick"] == tick_before


# --- Property 8: Tick advances by action cost ---

@settings(max_examples=100)
@given(
    seed=st.integers(),
    action_type=st.sampled_from(list(ActionType)),
)
def test_tick_advances_by_action_cost(seed: int, action_type: ActionType):
    # Feature: openenv-soc-trilemma, Property 8: Tick advances by action cost
    # Validates: Requirements 3.3
    session_id = f"prop8_{seed}_{action_type.value}"
    obs_before = _reset_session(session_id, seed=seed)
    tick_before = obs_before["tick"]
    attacker_ip = obs_before["dpi_data"]["attacker_ip"]
    decoy_ips = obs_before["dpi_data"]["decoy_ips"]

    # Use a decoy IP for non-block actions to avoid termination; use attacker for block
    if action_type == ActionType.BlockIP:
        # Use a decoy to avoid terminating the episode
        target_ip = decoy_ips[0] if decoy_ips else attacker_ip
    else:
        target_ip = decoy_ips[0] if decoy_ips else attacker_ip

    payload = {
        "action_type": action_type.value,
        "target_ip": target_ip,
        "session_id": session_id,
    }
    resp = _client.post("/step", json=payload)
    assert resp.status_code == 200
    tick_after = resp.json()["tick"]
    expected_cost = ACTION_COSTS[action_type]
    assert tick_after == tick_before + expected_cost


# ---------------------------------------------------------------------------
# Property 22: Hard config produces more decoys than easy config
# ---------------------------------------------------------------------------

from app.dpi_loader import load_dpi_template

_EASY_CONFIG = load_task_config("tasks/easy.yaml")
_HARD_CONFIG = load_task_config("tasks/hard.yaml")
_RECON_TEMPLATE = load_dpi_template(KillChainStage.Recon)


@settings(max_examples=100)
@given(seed=st.integers())
def test_hard_config_produces_more_decoys_than_easy_config(seed: int):
    # Feature: openenv-soc-trilemma, Property 22: Hard config produces more decoys than easy config
    # Validates: Requirements 8.2
    engine = SeedEngine()
    easy_assignment = engine.assign_roles(seed, _RECON_TEMPLATE, _EASY_CONFIG.num_decoys)
    hard_assignment = engine.assign_roles(seed, _RECON_TEMPLATE, _HARD_CONFIG.num_decoys)
    assert len(hard_assignment.decoy_ips) > len(easy_assignment.decoy_ips)


# ---------------------------------------------------------------------------
# Property 5: DPI templates contain sufficient IPs for role assignment
# ---------------------------------------------------------------------------

# Strategy: generate arbitrary DPITemplate objects with arbitrary num_decoys
st_arbitrary_ip = st.from_regex(r"10\.0\.\d{1,3}\.\d{1,3}", fullmatch=True)

st_arbitrary_dpi_template = st.builds(
    lambda pool: DPITemplate(
        stage=KillChainStage.Recon,
        entries=[_SAMPLE_ENTRY],
        ip_pool=pool,
    ),
    pool=st.lists(st_arbitrary_ip, min_size=1, max_size=20, unique=True),
)


def test_actual_dpi_templates_have_sufficient_ip_pool():
    """
    **Validates: Requirements 2.3**

    Property 5: DPI templates contain sufficient IPs for role assignment.
    For any DPITemplate, len(ip_pool) >= num_decoys + 1 must hold so the
    SeedEngine can always assign at least one attacker and the configured
    number of decoys.

    Checks all three actual DPI templates against the stricter hard config.
    """
    hard_config = load_task_config("tasks/hard.yaml")
    required = hard_config.num_decoys + 1

    for stage in KillChainStage:
        template = load_dpi_template(stage)
        assert len(template.ip_pool) >= required, (
            f"Stage {stage.value}: ip_pool has {len(template.ip_pool)} IPs "
            f"but hard config requires at least {required} "
            f"(num_decoys={hard_config.num_decoys} + 1 attacker)"
        )


@settings(max_examples=100)
@given(
    template=st_arbitrary_dpi_template,
    num_decoys=st.integers(min_value=0, max_value=15),
)
def test_dpi_template_ip_pool_sufficiency_property(
    template: DPITemplate, num_decoys: int
):
    """
    **Validates: Requirements 2.3**

    Property 5 (generative): For any DPITemplate where len(ip_pool) >= num_decoys + 1,
    the SeedEngine can successfully assign roles without running out of IPs.
    """
    if len(template.ip_pool) < num_decoys + 1:
        # Precondition not met — skip this example
        return

    engine = SeedEngine()
    assignment = engine.assign_roles(seed=42, template=template, num_decoys=num_decoys)

    # Attacker and all decoys must come from the pool
    ip_pool_set = set(template.ip_pool)
    assert assignment.attacker_ip in ip_pool_set
    for ip in assignment.decoy_ips:
        assert ip in ip_pool_set

    # Correct number of decoys assigned
    assert len(assignment.decoy_ips) == num_decoys

    # No overlap between attacker and decoys
    assert assignment.attacker_ip not in assignment.decoy_ips


# ---------------------------------------------------------------------------
# Property 20: WebSocket protocol equivalence
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(seed=st.integers())
def test_websocket_protocol_equivalence(seed: int):
    """
    **Validates: Requirements 7.2**

    Property 20: WebSocket protocol equivalence.
    For any valid reset message sent over the WebSocket endpoint, the response
    payload must be structurally equivalent to the response from the
    corresponding HTTP /reset endpoint given the same seed.
    """
    session_http = f"prop20_http_{seed}"
    session_ws = f"prop20_ws_{seed}"

    # Reset via HTTP
    http_resp = _client.post("/reset", json={"seed": seed, "session_id": session_http}).json()

    # Reset via WebSocket
    with _client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "reset", "seed": seed, "session_id": session_ws})
        ws_resp = ws.receive_json()

    # Structural equivalence on key observation fields
    assert ws_resp["dpi_data"]["attacker_ip"] == http_resp["dpi_data"]["attacker_ip"]
    assert ws_resp["dpi_data"]["decoy_ips"] == http_resp["dpi_data"]["decoy_ips"]
    assert ws_resp["stage"] == http_resp["stage"]
    assert ws_resp["done"] == http_resp["done"]
    assert ws_resp["survival_score"] == http_resp["survival_score"]


# ---------------------------------------------------------------------------
# Property 21: WebSocket final message has done=True
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(seed=st.integers())
def test_websocket_final_message_has_done_true(seed: int):
    """
    **Validates: Requirements 7.4**

    Property 21: WebSocket final message has done=True.
    For any episode that terminates, the last message sent over the WebSocket
    connection must be an Observation with done == True containing the final
    survival_score.
    """
    session_id = f"prop21_{seed}"

    with _client.websocket_connect("/ws") as ws:
        # Reset the episode
        ws.send_json({"type": "reset", "seed": seed, "session_id": session_id})
        obs = ws.receive_json()
        attacker_ip = obs["dpi_data"]["attacker_ip"]

        # Block the attacker IP to terminate the episode immediately
        ws.send_json({
            "type": "step",
            "action_type": "block_ip",
            "target_ip": attacker_ip,
            "session_id": session_id,
        })
        final = ws.receive_json()

    assert final["done"] is True
    assert "survival_score" in final
    assert isinstance(final["survival_score"], float)


# ---------------------------------------------------------------------------
# Property 25: Baseline agent completes without exception
# ---------------------------------------------------------------------------

import random as _random


@settings(max_examples=20, deadline=None)
@given(seed=st.integers())
def test_baseline_agent_completes_without_exception(seed: int):
    """
    **Validates: Requirements 10.2, 10.3**

    Property 25: Baseline agent completes without exception.
    For any integer seed, running the baseline agent against the easy task
    configuration must complete the episode loop (reaching done=True) without
    raising an unhandled exception. The final survival score must be in [0.0, 1.0].
    """
    rng = _random.Random(seed)
    action_types = list(ActionType)
    session_id = f"prop25_{seed}"

    reset_resp = _client.post("/reset", json={"seed": seed, "session_id": session_id})
    assert reset_resp.status_code == 200
    obs = reset_resp.json()

    while not obs["done"]:
        action_type = rng.choice(action_types)
        dpi_data = obs["dpi_data"]
        candidate_ips = [dpi_data["attacker_ip"]] + dpi_data["decoy_ips"]
        target_ip = rng.choice(candidate_ips)

        step_resp = _client.post("/step", json={
            "action_type": action_type.value,
            "target_ip": target_ip,
            "session_id": session_id,
        })
        assert step_resp.status_code == 200
        obs = step_resp.json()

    final_score = obs["survival_score"]
    assert 0.0 <= final_score <= 1.0
