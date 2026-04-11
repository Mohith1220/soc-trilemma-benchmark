#!/usr/bin/env python3
"""SOC Trilemma inference script — OpenEnv compliant.

Starts the environment server as a subprocess, runs 4 tasks via HTTP,
outputs [START]/[STEP]/[END] logs parseable by the OpenEnv validator.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time

import httpx
from openai import OpenAI

# ---------------------------------------------------------------------------
# Platform-injected credentials
# ---------------------------------------------------------------------------
API_BASE_URL = os.environ.get("API_BASE_URL", "")
MODEL_NAME   = os.environ.get("MODEL_NAME", "")
API_KEY      = os.environ.get("API_KEY", "") or os.environ.get("HF_TOKEN", "")

# ENV_URL: where the environment server is running
# Validator may inject this; default to localhost
ENV_URL = os.environ.get("ENV_URL", "http://localhost:7860").rstrip("/")

BENCHMARK  = "soc-trilemma"
MAX_STEPS  = 50
TASK_IDS   = ["easy", "medium", "hard", "expert"]

_ACTION_TYPES = [
    "block_ip", "query_dpi", "resolve_outage", "wait", "allow_ip", "isolate_host"
]

SYSTEM_PROMPT = """\
You are a SOC analyst agent. Given a JSON observation, respond with ONE JSON action.
Schema: {"action_type": "block_ip|query_dpi|resolve_outage|wait", "target_ip": "10.0.0.X", "session_id": "..."}
Strategy: use query_dpi to reveal payloads before block_ip. Avoid blocking CRITICAL assets.
Reply with ONLY the JSON object — no prose, no markdown."""


# ---------------------------------------------------------------------------
# LLM policy
# ---------------------------------------------------------------------------
def _get_client() -> OpenAI | None:
    if not (API_BASE_URL and API_KEY):
        return None
    try:
        return OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
    except Exception:
        return None


def llm_action(obs: dict, session_id: str) -> dict | None:
    client = _get_client()
    if client is None:
        return None
    try:
        ip_list = [e["src_ip"] for e in obs["dpi_data"]["entries"]]
        user_msg = json.dumps({
            "stage": obs["stage"],
            "tick": obs["tick"],
            "survival_score": round(obs["survival_score"], 4),
            "dpi_entries": [
                {"ip": e["src_ip"], "payload": e["payload_summary"]}
                for e in obs["dpi_data"]["entries"]
            ],
            "alerts": [a["message"] for a in obs.get("alerts", [])[-3:]],
            "session_id": session_id,
        })
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=80,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        action = json.loads(raw)
        action["session_id"] = session_id
        if action.get("target_ip") in ip_list:
            return action
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Random baseline policy — seed varies per task so actions differ
# ---------------------------------------------------------------------------
def random_action(obs: dict, rng: random.Random, session_id: str) -> dict:
    action_type = rng.choice(_ACTION_TYPES)
    ip_list     = [e["src_ip"] for e in obs["dpi_data"]["entries"]]
    target_ip   = rng.choice(ip_list)
    return {"action_type": action_type, "target_ip": target_ip, "session_id": session_id}


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------
_server_proc: subprocess.Popen | None = None


def start_server() -> bool:
    """Start uvicorn in background if ENV_URL is localhost and server not already up."""
    global _server_proc

    # Check if already running
    if _is_healthy():
        return True

    # Only auto-start if targeting localhost
    if "localhost" not in ENV_URL and "127.0.0.1" not in ENV_URL:
        return False

    print("[INFO] Starting environment server...", flush=True)
    _server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.app:app",
         "--host", "0.0.0.0", "--port", "7860", "--workers", "1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait up to 30s for health
    for _ in range(30):
        time.sleep(1)
        if _is_healthy():
            print("[INFO] Server ready.", flush=True)
            return True

    print("[ERROR] Server failed to start.", flush=True)
    return False


def stop_server() -> None:
    global _server_proc
    if _server_proc is not None:
        _server_proc.terminate()
        _server_proc = None


def _is_healthy() -> bool:
    try:
        r = httpx.get(f"{ENV_URL}/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Episode runner — HTTP against live server
# ---------------------------------------------------------------------------
def run_episode(task_id: str, seed: int) -> float:
    from app.episode_grader import EpisodeGrader
    grader     = EpisodeGrader()
    session_id = f"inf_{task_id}_{seed}"

    # Use task-specific seed so each task gets different IP assignments
    task_seed_offset = {"easy": 0, "medium": 1000, "hard": 2000, "expert": 3000}
    episode_seed = seed + task_seed_offset.get(task_id, 0)

    sys.stdout.write(
        f"[START] task={task_id} env={BENCHMARK}"
        f" model={MODEL_NAME or 'baseline'}\n"
    )
    sys.stdout.flush()

    step             = 0
    cumulative_reward = 0.0
    obs: dict        = {}

    try:
        with httpx.Client(base_url=ENV_URL, timeout=30.0) as client:
            # Reset
            reset_resp = client.post(
                "/reset",
                json={"seed": episode_seed, "session_id": session_id},
            )
            reset_resp.raise_for_status()
            obs = reset_resp.json()

            prev_survival = obs["survival_score"]
            rng = random.Random(episode_seed)

            while not obs.get("done", False) and step < MAX_STEPS:
                error_msg: str | None = None

                # Choose action
                action = llm_action(obs, session_id)
                if action is None:
                    action = random_action(obs, rng, session_id)

                action_str = f"{action['action_type']}({action['target_ip']})"

                try:
                    step_resp = client.post("/step", json=action)
                    step_resp.raise_for_status()
                    obs = step_resp.json()
                except Exception as exc:
                    error_msg = str(exc)[:80]
                    obs["done"] = True

                reward = obs.get("survival_score", prev_survival) - prev_survival
                prev_survival = obs.get("survival_score", prev_survival)
                cumulative_reward += reward
                step += 1

                done_str = "true" if obs.get("done", False) else "false"
                sys.stdout.write(
                    f"[STEP] step={step} action={action_str}"
                    f" reward={reward:.4f} done={done_str}"
                    f" error={error_msg or 'null'}\n"
                )
                sys.stdout.flush()

                if error_msg or obs.get("done", False):
                    break

    except Exception as exc:
        error_msg = str(exc)[:120]
        sys.stdout.write(
            f"[STEP] step={step + 1} action=error reward=0.0000"
            f" done=true error={error_msg}\n"
        )
        sys.stdout.flush()

    # Grade
    attacker_blocked = obs.get("done", False) and any(
        "Attacker exfiltrated" not in a.get("message", "")
        and obs.get("done", False)
        for a in obs.get("alerts", [{}])[-1:]
    )
    # Simpler: done=True AND no "exfiltrated" alert = correct block
    exfiltrated = any(
        "exfiltrated" in a.get("message", "").lower()
        for a in obs.get("alerts", [])
    )
    attacker_blocked = obs.get("done", False) and not exfiltrated

    grader_score = grader.grade(
        {
            "survival_score": obs.get("survival_score", 0.5),
            "done":           attacker_blocked,   # only True if correctly blocked
            "tick":           obs.get("tick", 0),
            "steps":          step,
        },
        task_id,
    )
    grader_score = max(0.001, min(0.999, grader_score))

    success_str = "true" if attacker_blocked else "false"

    sys.stdout.write(
        f"[END] success={success_str} steps={step}"
        f" score={grader_score:.4f}"
        f" rewards={cumulative_reward:.4f}\n"
    )
    sys.stdout.flush()
    return grader_score


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=int(os.getenv("TASK_SEED", "42")))
    args = parser.parse_args()
    seed = args.seed

    server_started = start_server()
    if not server_started:
        print(f"[WARN] Could not reach server at {ENV_URL} — results may be degraded.",
              flush=True)

    results: dict[str, float] = {}
    start_time = time.time()

    try:
        for task_id in TASK_IDS:
            results[task_id] = run_episode(task_id, seed)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        stop_server()

    elapsed = time.time() - start_time
    print("\n=== Summary ===", flush=True)
    for task_id, score in results.items():
        print(f"{task_id}: {score:.4f}", flush=True)
    print(f"Elapsed: {elapsed:.2f}s", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
