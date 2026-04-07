"""Unit tests for SessionManager."""
import pytest
from fastapi import HTTPException

from app.config import load_task_config
from app.models import ACTION_COSTS, Action, ActionType, KillChainStage
from app.session_manager import SessionManager

TASK_CONFIG = load_task_config("tasks/easy.yaml")


def _make_manager() -> SessionManager:
    return SessionManager(task_config=TASK_CONFIG)


def _block_action(session_id: str, target_ip: str) -> Action:
    return Action(action_type=ActionType.BlockIP, target_ip=target_ip, session_id=session_id)


# ---------------------------------------------------------------------------
# Test: 404 on missing session_id
# ---------------------------------------------------------------------------

def test_step_raises_404_for_unknown_session():
    mgr = _make_manager()
    action = _block_action("ghost", "10.0.0.1")
    with pytest.raises(HTTPException) as exc_info:
        mgr.step("ghost", action)
    assert exc_info.value.status_code == 404


def test_get_state_raises_404_for_unknown_session():
    mgr = _make_manager()
    with pytest.raises(HTTPException) as exc_info:
        mgr.get_state("ghost")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Test: reset produces clean initial observation
# ---------------------------------------------------------------------------

def test_reset_produces_clean_observation():
    mgr = _make_manager()
    obs = mgr.create_or_reset("s1", seed=42)
    assert obs.stage == KillChainStage.Recon
    assert obs.alerts == []
    assert obs.done is False
    assert obs.survival_score == 0.9
    assert obs.tick == 0
    assert obs.dom != ""


# ---------------------------------------------------------------------------
# Test: correct block terminates episode (done=True)
# ---------------------------------------------------------------------------

def test_correct_block_terminates_episode():
    mgr = _make_manager()
    obs = mgr.create_or_reset("s2", seed=42)
    attacker_ip = obs.dpi_data.attacker_ip

    action = _block_action("s2", attacker_ip)
    result = mgr.step("s2", action)
    assert result.done is True
    assert result.survival_score > 0.0


# ---------------------------------------------------------------------------
# Test: max_steps terminates episode
# ---------------------------------------------------------------------------

def test_max_steps_terminates_episode():
    mgr = _make_manager()
    obs = mgr.create_or_reset("s3", seed=99)
    # Use a decoy IP so we never get a correct block
    decoy_ip = obs.dpi_data.decoy_ips[0]
    action = _block_action("s3", decoy_ip)

    result = obs
    for _ in range(TASK_CONFIG.max_steps):
        result = mgr.step("s3", action)
        if result.done:
            break

    assert result.done is True


# ---------------------------------------------------------------------------
# Test: full reset → step → done flow
# ---------------------------------------------------------------------------

def test_full_episode_flow():
    mgr = _make_manager()
    obs = mgr.create_or_reset("s4", seed=7)
    assert obs.stage == KillChainStage.Recon
    assert not obs.done

    attacker_ip = obs.dpi_data.attacker_ip
    action = _block_action("s4", attacker_ip)
    result = mgr.step("s4", action)

    assert result.done is True
    assert result.tick > 0
    assert result.dom != ""


# ---------------------------------------------------------------------------
# Test: reset of existing session clears state
# ---------------------------------------------------------------------------

def test_reset_clears_existing_session():
    mgr = _make_manager()
    obs1 = mgr.create_or_reset("s5", seed=1)
    attacker_ip = obs1.dpi_data.attacker_ip
    # Take a step to dirty the state
    mgr.step("s5", _block_action("s5", attacker_ip))

    # Reset with a new seed
    obs2 = mgr.create_or_reset("s5", seed=2)
    assert obs2.stage == KillChainStage.Recon
    assert obs2.alerts == []
    assert obs2.survival_score == 0.9
    assert obs2.tick == 0
    assert obs2.done is False
