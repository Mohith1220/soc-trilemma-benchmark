"""Integration tests for WebSocket endpoint."""
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
# Helpers
# ---------------------------------------------------------------------------

def _get_attacker_ip(client: TestClient, session_id: str, seed: int) -> str:
    """Reset a session and return the attacker IP."""
    resp = client.post("/reset", json={"seed": seed, "session_id": session_id})
    return resp.json()["dpi_data"]["attacker_ip"]


# ---------------------------------------------------------------------------
# Basic message types
# ---------------------------------------------------------------------------

def test_ws_reset_returns_initial_observation(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "reset", "seed": 42, "session_id": "ws_reset_test"})
        data = ws.receive_json()

    assert data["stage"] == "Recon"
    assert data["done"] is False
    assert data["survival_score"] == 0.995
    assert data["tick"] == 0
    assert data["alerts"] == []
    assert data["dom"] != ""


def test_ws_step_advances_tick(client: TestClient) -> None:
    session_id = "ws_step_tick"
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "reset", "seed": 1, "session_id": session_id})
        obs = ws.receive_json()
        decoy_ip = obs["dpi_data"]["decoy_ips"][0]

        ws.send_json({
            "type": "step",
            "action_type": "allow_ip",
            "target_ip": decoy_ip,
            "session_id": session_id,
        })
        obs2 = ws.receive_json()

    assert obs2["tick"] == ACTION_COSTS[ActionType.AllowIP]


def test_ws_state_returns_current_observation(client: TestClient) -> None:
    session_id = "ws_state_test"
    # Create session via HTTP first
    client.post("/reset", json={"seed": 10, "session_id": session_id})

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "state", "session_id": session_id})
        data = ws.receive_json()

    assert data["stage"] == "Recon"
    assert data["tick"] == 0
    assert data["done"] is False


def test_ws_unknown_message_type_returns_error(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "fly_to_moon", "session_id": "ws_unknown"})
        data = ws.receive_json()

    assert "error" in data
    assert "fly_to_moon" in data["error"]


# ---------------------------------------------------------------------------
# Full episode over WebSocket
# ---------------------------------------------------------------------------

def test_ws_full_episode_reset_step_done(client: TestClient) -> None:
    """Reset → step with correct block → done=True."""
    session_id = "ws_full_episode"
    attacker_ip = _get_attacker_ip(client, session_id + "_probe", seed=7)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "reset", "seed": 7, "session_id": session_id})
        obs = ws.receive_json()
        assert obs["done"] is False

        # Block the attacker to end the episode
        ws.send_json({
            "type": "step",
            "action_type": "block_ip",
            "target_ip": obs["dpi_data"]["attacker_ip"],
            "session_id": session_id,
        })
        final_obs = ws.receive_json()

    assert final_obs["done"] is True
    assert final_obs["survival_score"] > 0.0


def test_ws_final_message_has_done_true(client: TestClient) -> None:
    """The last message sent before connection closes must have done=True."""
    session_id = "ws_done_final"

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "reset", "seed": 99, "session_id": session_id})
        obs = ws.receive_json()
        attacker_ip = obs["dpi_data"]["attacker_ip"]

        ws.send_json({
            "type": "step",
            "action_type": "block_ip",
            "target_ip": attacker_ip,
            "session_id": session_id,
        })
        final = ws.receive_json()

    assert final["done"] is True


def test_ws_episode_via_max_steps(client: TestClient) -> None:
    """Episode terminates with done=True when max_steps is reached."""
    session_id = "ws_max_steps"

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "reset", "seed": 42, "session_id": session_id})
        obs = ws.receive_json()

        done = False
        for _ in range(200):
            decoy_ip = obs["dpi_data"]["decoy_ips"][0]
            ws.send_json({
                "type": "step",
                "action_type": "allow_ip",
                "target_ip": decoy_ip,
                "session_id": session_id,
            })
            obs = ws.receive_json()
            if obs.get("done"):
                done = True
                break

    assert done, "Episode should terminate within 200 steps"


# ---------------------------------------------------------------------------
# Protocol equivalence with HTTP
# ---------------------------------------------------------------------------

def test_ws_reset_equivalent_to_http(client: TestClient) -> None:
    """WS reset response is structurally equivalent to HTTP /reset."""
    http_resp = client.post("/reset", json={"seed": 55, "session_id": "equiv_http"}).json()

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "reset", "seed": 55, "session_id": "equiv_ws"})
        ws_resp = ws.receive_json()

    # Same attacker_ip and decoy_ips for same seed
    assert ws_resp["dpi_data"]["attacker_ip"] == http_resp["dpi_data"]["attacker_ip"]
    assert ws_resp["dpi_data"]["decoy_ips"] == http_resp["dpi_data"]["decoy_ips"]
    assert ws_resp["stage"] == http_resp["stage"]
    assert ws_resp["done"] == http_resp["done"]
    assert ws_resp["survival_score"] == http_resp["survival_score"]
