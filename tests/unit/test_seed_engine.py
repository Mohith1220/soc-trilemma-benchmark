"""Unit tests for SeedEngine (Task 4)."""
import random

import pytest

from app.models import DPIEntry, DPITemplate, KillChainStage
from app.seed_engine import RoleAssignment, SeedEngine

_ENTRY = DPIEntry(
    src_ip="10.0.0.1",
    dst_ip="10.0.0.2",
    protocol="TCP",
    payload_summary="test",
    flags=[],
)

_IP_POOL = [
    "10.0.0.1",
    "10.0.0.2",
    "10.0.0.3",
    "10.0.0.4",
    "10.0.0.5",
]

_TEMPLATE = DPITemplate(
    stage=KillChainStage.Recon,
    entries=[_ENTRY],
    ip_pool=_IP_POOL,
)


def _expected_attacker(seed: int, pool: list[str]) -> str:
    """Replicate the SeedEngine shuffle to get the expected attacker IP."""
    rng = random.Random(seed)
    shuffled = list(pool)
    rng.shuffle(shuffled)
    return shuffled[0]


# --- Known seed produces known attacker_ip ---

def test_known_seed_produces_known_attacker_ip():
    engine = SeedEngine()
    seed = 42
    assignment = engine.assign_roles(seed, _TEMPLATE, num_decoys=2)
    expected = _expected_attacker(seed, _IP_POOL)
    assert assignment.attacker_ip == expected


def test_different_seeds_may_produce_different_results():
    engine = SeedEngine()
    results = {engine.assign_roles(s, _TEMPLATE, num_decoys=2).attacker_ip for s in range(20)}
    # With 5 IPs and 20 seeds, we expect more than 1 unique attacker
    assert len(results) > 1


# --- No IP appears in both attacker and decoy roles ---

def test_no_ip_in_both_roles():
    engine = SeedEngine()
    for seed in range(50):
        assignment = engine.assign_roles(seed, _TEMPLATE, num_decoys=2)
        assert assignment.attacker_ip not in assignment.decoy_ips, (
            f"seed={seed}: attacker_ip {assignment.attacker_ip!r} also in decoy_ips"
        )


# --- num_decoys controls the length of decoy_ips ---

@pytest.mark.parametrize("num_decoys", [1, 2, 3, 4])
def test_num_decoys_controls_decoy_length(num_decoys: int):
    engine = SeedEngine()
    assignment = engine.assign_roles(0, _TEMPLATE, num_decoys=num_decoys)
    assert len(assignment.decoy_ips) == num_decoys


def test_zero_decoys_returns_empty_list():
    engine = SeedEngine()
    assignment = engine.assign_roles(0, _TEMPLATE, num_decoys=0)
    assert assignment.decoy_ips == []


# --- RoleAssignment fields ---

def test_role_assignment_has_correct_fields():
    engine = SeedEngine()
    assignment = engine.assign_roles(7, _TEMPLATE, num_decoys=2)
    assert isinstance(assignment, RoleAssignment)
    assert isinstance(assignment.attacker_ip, str)
    assert isinstance(assignment.decoy_ips, list)
    assert all(isinstance(ip, str) for ip in assignment.decoy_ips)
