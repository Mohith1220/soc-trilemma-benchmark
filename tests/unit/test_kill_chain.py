"""Unit tests for KillChain FSM."""
import pytest

from app.kill_chain import KillChain
from app.models import DPIEntry, DPISnapshot, DPITemplate, KillChainStage
from app.seed_engine import RoleAssignment

_BUDGETS = {
    KillChainStage.Recon: 30,
    KillChainStage.LateralMovement: 25,
    KillChainStage.Exfiltration: 20,
}


def test_initialization():
    """KillChain starts at Recon with tick=0 and stage_tick_start=0."""
    kc = KillChain()
    assert kc.stage == KillChainStage.Recon
    assert kc.tick == 0
    assert kc.stage_tick_start == 0
    assert kc.dpi_snapshot is None


def test_advance_tick():
    kc = KillChain()
    kc.advance_tick(5)
    assert kc.tick == 5
    kc.advance_tick(3)
    assert kc.tick == 8


def test_should_advance_stage_false_before_budget():
    kc = KillChain()
    kc.advance_tick(29)
    assert kc.should_advance_stage(_BUDGETS) is False


def test_should_advance_stage_true_at_budget():
    kc = KillChain()
    kc.advance_tick(30)
    assert kc.should_advance_stage(_BUDGETS) is True


def test_should_advance_stage_true_after_budget():
    kc = KillChain()
    kc.advance_tick(50)
    assert kc.should_advance_stage(_BUDGETS) is True


def test_stage_transition_sequence():
    """Recon → LateralMovement → Exfiltration → None."""
    kc = KillChain()
    assert kc.stage == KillChainStage.Recon

    result = kc.advance_stage()
    assert result == KillChainStage.LateralMovement
    assert kc.stage == KillChainStage.LateralMovement

    result = kc.advance_stage()
    assert result == KillChainStage.Exfiltration
    assert kc.stage == KillChainStage.Exfiltration

    result = kc.advance_stage()
    assert result is None
    assert kc.stage == KillChainStage.Exfiltration  # stays at last stage


def test_advance_stage_updates_stage_tick_start():
    kc = KillChain()
    kc.advance_tick(10)
    kc.advance_stage()
    assert kc.stage_tick_start == 10


def test_is_terminal_false_at_recon():
    kc = KillChain()
    assert kc.is_terminal() is False


def test_is_terminal_false_at_lateral_movement():
    kc = KillChain()
    kc.advance_stage()
    assert kc.is_terminal() is False


def test_is_terminal_true_at_exfiltration():
    kc = KillChain()
    kc.advance_stage()
    kc.advance_stage()
    assert kc.is_terminal() is True


def test_load_stage_template():
    kc = KillChain()
    entry = DPIEntry(
        src_ip="10.0.0.1",
        dst_ip="10.0.0.2",
        protocol="TCP",
        payload_summary="test",
        flags=[],
    )
    template = DPITemplate(
        stage=KillChainStage.Recon,
        entries=[entry],
        ip_pool=["10.0.0.1", "10.0.0.2", "10.0.0.3"],
    )
    role = RoleAssignment(attacker_ip="10.0.0.1", decoy_ips=["10.0.0.2"])
    kc.load_stage_template(template, role)

    assert kc.dpi_snapshot is not None
    assert kc.dpi_snapshot.attacker_ip == "10.0.0.1"
    assert kc.dpi_snapshot.decoy_ips == ["10.0.0.2"]
    assert kc.dpi_snapshot.stage == KillChainStage.Recon
