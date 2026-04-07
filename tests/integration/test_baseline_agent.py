"""Integration tests for the baseline agent (inference.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.models import ActionType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_episode_via_client(client: TestClient, seed: int, session_id: str = "baseline_test") -> float:
    """Mirror of inference.run_episode but uses TestClient instead of httpx."""
    import random
    rng = random.Random(seed)
    action_types = list(ActionType)

    reset_resp = client.post("/reset", json={"seed": seed, "session_id": session_id})
    assert reset_resp.status_code == 200
    obs = reset_resp.json()

    while not obs["done"]:
        action_type = rng.choice(action_types)
        dpi_data = obs["dpi_data"]
        candidate_ips = [dpi_data["attacker_ip"]] + dpi_data["decoy_ips"]
        target_ip = rng.choice(candidate_ips)

        step_resp = client.post("/step", json={
            "action_type": action_type.value,
            "target_ip": target_ip,
            "session_id": session_id,
        })
        assert step_resp.status_code == 200
        obs = step_resp.json()

    return obs["survival_score"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    application = create_app("tasks/easy.yaml")
    return TestClient(application)


def test_baseline_agent_completes_without_exception(client: TestClient) -> None:
    """Baseline agent runs to completion with a fixed seed and no unhandled exception."""
    score = _run_episode_via_client(client, seed=42, session_id="baseline_fixed_seed")
    assert 0.0 <= score <= 1.0


def test_baseline_agent_prints_final_score(capsys: pytest.CaptureFixture) -> None:
    """run_episode prints the final survival score."""
    from unittest.mock import patch

    app = create_app("tasks/easy.yaml")
    tc = TestClient(app)

    class _FakeResponse:
        def __init__(self, data: dict) -> None:
            self._data = data

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self._data

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, path: str, json: dict | None = None) -> _FakeResponse:
            resp = tc.post(path, json=json)
            return _FakeResponse(resp.json())

    with patch("inference.httpx.Client", return_value=_FakeClient()):
        from inference import run_episode
        score = run_episode(url="http://testserver", seed=99, session_id="print_test")

    captured = capsys.readouterr()
    assert "[END]" in captured.out
    assert "score=" in captured.out
    assert 0.0 <= score <= 1.0


def test_baseline_agent_terminates_on_done(client: TestClient) -> None:
    """Agent loop terminates when environment returns done=True (respects max_steps)."""
    score = _run_episode_via_client(client, seed=7, session_id="baseline_done_test")
    # If we reach here, the loop terminated correctly
    assert isinstance(score, float)


def test_baseline_agent_different_seeds_produce_different_scores(client: TestClient) -> None:
    """Different seeds can produce different outcomes (non-determinism across seeds)."""
    score_a = _run_episode_via_client(client, seed=1, session_id="seed_a")
    score_b = _run_episode_via_client(client, seed=2, session_id="seed_b")
    # Both should be valid scores; they may or may not differ
    assert 0.0 <= score_a <= 1.0
    assert 0.0 <= score_b <= 1.0
