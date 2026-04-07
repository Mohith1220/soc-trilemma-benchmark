"""Integration tests for FastAPI HTTP endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.models import ACTION_COSTS, ActionType


@pytest.fixture(scope="module")
def client() -> TestClient:
    application = create_app()
    return TestClient(application)


# ---------------------------------------------------------------------------
# /reset
# ---------------------------------------------------------------------------

def test_reset_returns_initial_observation(client: TestClient) -> None:
    resp = client.post("/reset", json={"seed": 42, "session_id": "test_reset"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "Recon"
    assert data["alerts"] == []
    assert data["done"] is False
    assert data["survival_score"] == 0.995
    assert data["tick"] == 0
    assert data["dom"] != ""


def test_reset_missing_seed_uses_default(client: TestClient) -> None:
    # seed is Optional with default=42, so omitting it is valid and returns 200
    resp = client.post("/reset", json={"session_id": "no_seed"})
    assert resp.status_code == 200
    assert resp.json()["survival_score"] == 0.995


def test_reset_non_integer_seed_returns_422(client: TestClient) -> None:
    resp = client.post("/reset", json={"seed": "not_an_int", "session_id": "bad_seed"})
    assert resp.status_code == 422


def test_reset_float_seed_returns_422(client: TestClient) -> None:
    resp = client.post("/reset", json={"seed": 3.14, "session_id": "float_seed"})
    assert resp.status_code == 422


def test_reset_same_seed_deterministic(client: TestClient) -> None:
    r1 = client.post("/reset", json={"seed": 99, "session_id": "det1"}).json()
    r2 = client.post("/reset", json={"seed": 99, "session_id": "det2"}).json()
    assert r1["dpi_data"]["attacker_ip"] == r2["dpi_data"]["attacker_ip"]
    assert r1["dpi_data"]["decoy_ips"] == r2["dpi_data"]["decoy_ips"]


# ---------------------------------------------------------------------------
# /step
# ---------------------------------------------------------------------------

def test_step_advances_tick(client: TestClient) -> None:
    client.post("/reset", json={"seed": 1, "session_id": "step_tick"})
    obs = client.get("/state", params={"session_id": "step_tick"}).json()
    decoy_ip = obs["dpi_data"]["decoy_ips"][0]

    resp = client.post("/step", json={
        "action_type": "allow_ip",
        "target_ip": decoy_ip,
        "session_id": "step_tick",
    })
    assert resp.status_code == 200
    assert resp.json()["tick"] == ACTION_COSTS[ActionType.AllowIP]


def test_step_missing_action_type_returns_422(client: TestClient) -> None:
    client.post("/reset", json={"seed": 2, "session_id": "step_422"})
    resp = client.post("/step", json={
        "target_ip": "10.0.0.1",
        "session_id": "step_422",
    })
    assert resp.status_code == 422


def test_step_missing_target_ip_returns_422(client: TestClient) -> None:
    client.post("/reset", json={"seed": 3, "session_id": "step_422b"})
    resp = client.post("/step", json={
        "action_type": "block_ip",
        "session_id": "step_422b",
    })
    assert resp.status_code == 422


def test_step_invalid_action_type_returns_422(client: TestClient) -> None:
    client.post("/reset", json={"seed": 4, "session_id": "step_422c"})
    resp = client.post("/step", json={
        "action_type": "nuke_everything",
        "target_ip": "10.0.0.1",
        "session_id": "step_422c",
    })
    assert resp.status_code == 422


def test_step_invalid_ip_returns_422(client: TestClient) -> None:
    client.post("/reset", json={"seed": 5, "session_id": "step_422d"})
    resp = client.post("/step", json={
        "action_type": "block_ip",
        "target_ip": "not_an_ip",
        "session_id": "step_422d",
    })
    assert resp.status_code == 422


def test_step_unknown_session_returns_404(client: TestClient) -> None:
    resp = client.post("/step", json={
        "action_type": "block_ip",
        "target_ip": "10.0.0.1",
        "session_id": "nonexistent_session_xyz",
    })
    assert resp.status_code == 404


def test_step_correct_block_terminates_episode(client: TestClient) -> None:
    client.post("/reset", json={"seed": 7, "session_id": "correct_block"})
    obs = client.get("/state", params={"session_id": "correct_block"}).json()
    attacker_ip = obs["dpi_data"]["attacker_ip"]

    resp = client.post("/step", json={
        "action_type": "block_ip",
        "target_ip": attacker_ip,
        "session_id": "correct_block",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["done"] is True
    assert data["survival_score"] > 0.0


# ---------------------------------------------------------------------------
# /state
# ---------------------------------------------------------------------------

def test_state_returns_current_observation(client: TestClient) -> None:
    client.post("/reset", json={"seed": 10, "session_id": "state_test"})
    resp = client.get("/state", params={"session_id": "state_test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "Recon"
    assert data["tick"] == 0
    assert data["done"] is False


def test_state_unknown_session_returns_404(client: TestClient) -> None:
    resp = client.get("/state", params={"session_id": "ghost_session_abc"})
    assert resp.status_code == 404


def test_state_reflects_step_changes(client: TestClient) -> None:
    client.post("/reset", json={"seed": 11, "session_id": "state_step"})
    obs = client.get("/state", params={"session_id": "state_step"}).json()
    decoy_ip = obs["dpi_data"]["decoy_ips"][0]

    client.post("/step", json={
        "action_type": "allow_ip",
        "target_ip": decoy_ip,
        "session_id": "state_step",
    })
    state_after = client.get("/state", params={"session_id": "state_step"}).json()
    assert state_after["tick"] == ACTION_COSTS[ActionType.AllowIP]


# ---------------------------------------------------------------------------
# Full episode lifecycle
# ---------------------------------------------------------------------------

def test_full_episode_lifecycle(client: TestClient) -> None:
    """Reset → step loop using decoy IPs → eventually done via max_steps."""
    session_id = "lifecycle_test"
    resp = client.post("/reset", json={"seed": 42, "session_id": session_id})
    assert resp.status_code == 200
    obs = resp.json()
    assert obs["done"] is False

    done = False
    max_iterations = 200  # safety cap
    for _ in range(max_iterations):
        decoy_ip = obs["dpi_data"]["decoy_ips"][0]
        step_resp = client.post("/step", json={
            "action_type": "allow_ip",
            "target_ip": decoy_ip,
            "session_id": session_id,
        })
        assert step_resp.status_code == 200
        obs = step_resp.json()
        if obs["done"]:
            done = True
            break

    assert done, "Episode should have terminated within max_iterations"
    assert "survival_score" in obs
    assert "stage" in obs
