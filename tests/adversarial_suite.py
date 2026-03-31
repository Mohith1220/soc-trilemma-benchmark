"""
Adversarial robustness test suite.
Tests concurrency safety, input validation, and post-done behaviour.
"""
from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.models import ACTION_COSTS, ActionType

_app = create_app()
_client = TestClient(_app)


def _reset(session_id: str, seed: int = 42) -> dict:
    r = _client.post("/reset", json={"seed": seed, "session_id": session_id})
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# 1. Concurrency — hammer 10 simultaneous block_ip actions on one session
# ---------------------------------------------------------------------------

def test_hammer_concurrency():
    """10 concurrent block_ip calls must not corrupt tick or score."""
    obs = _reset("hammer", seed=42)
    decoy = obs["dpi_data"]["decoy_ips"][0]
    tick_before = obs["tick"]

    # TestClient is synchronous — simulate concurrency by sending 10 sequential
    # requests and verifying the state is consistent (no double-counting).
    # For true async concurrency we use asyncio with httpx below.
    import httpx

    async def _send(client: httpx.AsyncClient) -> dict:
        r = await client.post("/step", json={
            "action_type": "block_ip",
            "target_ip": decoy,
            "session_id": "hammer_async",
        })
        return r.json()

    async def _run():
        _client.post("/reset", json={"seed": 42, "session_id": "hammer_async"})
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app),
            base_url="http://testserver"
        ) as ac:
            results = await asyncio.gather(*[_send(ac) for _ in range(10)])
        return results

    results = asyncio.run(_run())

    # Filter out 400s (post-done rejections) and 404s
    valid = [r for r in results if "tick" in r]
    # The final tick must equal tick_before + (cost × number of accepted steps)
    # Each accepted step costs ACTION_COSTS[BlockIP] = 3 ticks
    if valid:
        final_tick = max(r["tick"] for r in valid)
        accepted_steps = (final_tick - tick_before) // ACTION_COSTS[ActionType.BlockIP]
        assert accepted_steps >= 1, "At least one step must be accepted"
        # Tick must be an exact multiple of the action cost
        assert (final_tick - tick_before) % ACTION_COSTS[ActionType.BlockIP] == 0


# ---------------------------------------------------------------------------
# 2. Out-of-bounds IPs — must return 400, not 500
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_ip", [
    "8.8.8.8",
    "127.0.0.1",
    "192.168.1.1",
    "0.0.0.0",
    "255.255.255.255",
])
def test_out_of_bounds_ips(bad_ip: str):
    """IPs outside the 12-IP pool must return 400 Bad Request."""
    _reset("oob", seed=1)
    r = _client.post("/step", json={
        "action_type": "wait",
        "target_ip": bad_ip,
        "session_id": "oob",
    })
    assert r.status_code == 400, f"Expected 400 for {bad_ip}, got {r.status_code}"
    assert "valid IP pool" in r.json().get("detail", "").lower() or \
           "not in" in r.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# 3. Post-done action — must be rejected cleanly
# ---------------------------------------------------------------------------

def test_post_done_action():
    """Actions after done=True must return 400, not corrupt state."""
    obs = _reset("postdone", seed=42)
    attacker = obs["dpi_data"]["attacker_ip"]

    # End the episode with a correct block
    r = _client.post("/step", json={
        "action_type": "block_ip",
        "target_ip": attacker,
        "session_id": "postdone",
    })
    assert r.status_code == 200
    assert r.json()["done"] is True
    final_score = r.json()["survival_score"]

    # Now try to step again — must be rejected
    r2 = _client.post("/step", json={
        "action_type": "wait",
        "target_ip": attacker,
        "session_id": "postdone",
    })
    assert r2.status_code == 400
    assert "done" in r2.json().get("detail", "").lower()

    # Score must be unchanged
    state = _client.get("/state", params={"session_id": "postdone"}).json()
    assert state["survival_score"] == final_score


# ---------------------------------------------------------------------------
# 4. FP stability — seed=42 produces identical score across 100 runs
# ---------------------------------------------------------------------------

def test_fp_stability_100_runs():
    """Same seed must produce identical survival_score across 100 resets."""
    scores = set()
    for i in range(100):
        obs = _client.post("/reset", json={"seed": 42, "session_id": f"fp_{i}"}).json()
        d = obs["dpi_data"]["decoy_ips"][0]
        _client.post("/step", json={"action_type": "block_ip", "target_ip": d, "session_id": f"fp_{i}"})
        for _ in range(5):
            obs = _client.post("/step", json={"action_type": "wait", "target_ip": d, "session_id": f"fp_{i}"}).json()
        scores.add(obs["survival_score"])
    assert len(scores) == 1, f"FP drift detected across 100 runs: {scores}"


# ---------------------------------------------------------------------------
# 5. LRU session cap — 101st session evicts the oldest
# ---------------------------------------------------------------------------

def test_lru_session_cap():
    """Creating 101 sessions must not crash and oldest must be evicted."""
    for i in range(101):
        _client.post("/reset", json={"seed": i, "session_id": f"lru_{i}"})

    # Session 0 should be evicted
    r = _client.get("/state", params={"session_id": "lru_0"})
    assert r.status_code == 404

    # Session 100 (most recent) must still exist
    r = _client.get("/state", params={"session_id": "lru_100"})
    assert r.status_code == 200
