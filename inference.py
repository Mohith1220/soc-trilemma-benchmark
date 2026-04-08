"""Baseline agent for OpenEnv SOC Trilemma.

Supports two modes:
  1. LLM mode  — set API_BASE_URL, MODEL_NAME, HF_TOKEN to use an OpenAI-compatible
                 chat model as the decision-maker.
  2. Random mode — fallback when env vars are absent; uses a seeded random policy
                   (deterministic, used for numerical validation).

Usage:
    # Random policy (determinism audit)
    python inference.py --url http://localhost:7860 --seed 42

    # LLM policy (validator / HF Spaces)
    API_BASE_URL=https://... MODEL_NAME=meta-llama/... HF_TOKEN=hf_... \\
        python inference.py --url http://localhost:7860 --seed 42
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from typing import Any

import httpx
from openai import OpenAI

from app.models import ActionType

# ---------------------------------------------------------------------------
# Env-var configuration (injected by the OpenEnv validator at runtime)
# ---------------------------------------------------------------------------
HF_TOKEN: str | None = os.getenv("HF_TOKEN")                          # NO default — ever
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://mohith1220-soc-trilemma-benchmark.hf.space")
MODEL_NAME: str = os.getenv("MODEL_NAME", "meta-llama/Llama-3.3-70B-Instruct")

BENCHMARK: str = "soc-trilemma-benchmark"
MAX_TOTAL_REWARD: float = 1.0  # Maximum possible cumulative reward
SUCCESS_SCORE_THRESHOLD: float = 0.5  # Threshold for success


def _clamp_score(score: float) -> float:
    """Clamp score to strictly between 0 and 1 (never exactly 0.0 or 1.0)."""
    epsilon = 0.0001
    if score <= 0:
        return epsilon
    elif score >= 1.0:
        return 1.0 - epsilon
    else:
        return max(epsilon, min(1.0 - epsilon, score))


_LLM_MODE = bool(HF_TOKEN and API_BASE_URL and MODEL_NAME)

_SYSTEM_PROMPT = """\
You are a SOC analyst agent operating inside the SOC Trilemma RL environment.
Your goal: identify and block the attacker IP before tick 60 without causing
business outages on legitimate assets.

At each step you receive a JSON observation and must respond with a single JSON
action object — no prose, no markdown, just the JSON.

Action schema:
{
  "action_type": "block_ip" | "query_dpi" | "resolve_outage" | "wait",
  "target_ip": "<IPv4>",
  "session_id": "<session_id>"
}

Strategy hints:
- Use query_dpi (costs 5 ticks) to reveal whether an IP is malicious before blocking.
- block_ip on the wrong IP creates a business outage that bleeds survival score every tick.
- resolve_outage stops the bleed but costs 3 ticks.
- CRITICAL-tier assets bleed 0.15/tick — avoid false positives on them.
"""


def _llm_action(obs: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Ask the LLM for the next action given the current observation."""
    client = OpenAI(
        base_url=f"{API_BASE_URL}/v1",
        api_key=HF_TOKEN,
    )

    user_msg = json.dumps({
        "stage": obs["stage"],
        "tick": obs["tick"],
        "survival_score": obs["survival_score"],
        "dpi_entries": [
            {"ip": e["src_ip"], "payload": e["payload_summary"]}
            for e in obs["dpi_data"]["entries"]
        ],
        "alerts": [a["message"] for a in obs.get("alerts", [])[-3:]],
        "session_id": session_id,
    })

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
        max_tokens=128,
    )

    raw = response.choices[0].message.content or ""
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    action = json.loads(raw)
    action["session_id"] = session_id
    return action


def wait_for_server(url: str, timeout: int = 60) -> bool:
    """Wait for the environment server to become ready. Returns True if ready, False if timeout."""
    print(f"Waiting for server at {url}/health...", flush=True)
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            resp = httpx.get(f"{url}/health", timeout=5.0)
            if resp.status_code == 200:
                print("Server is ready!", flush=True)
                return True
        except Exception:
            pass
        time.sleep(1)
    print(f"Error: Server did not start within {timeout} seconds.", flush=True)
    return False


def log_start(task: str, env: str, model: str) -> None:
    """Log the start of an episode."""
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: str | None) -> None:
    """Log a single step."""
    print(
        f"[STEP] step={step} action={action} reward={reward:.4f} "
        f"done={str(done).lower()} error={error or 'null'}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    """Log the end of an episode."""
    rewards_str = ','.join(f'{r:.4f}' for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.4f} "
        f"rewards={rewards_str}",
        flush=True,
    )


def run_episode(url: str, seed: int, session_id: str = "baseline", task_id: str = "easy") -> float:
    """Run one episode against the environment server.

    Returns:
        Final normalized score as a float strictly between 0 and 1.
    """
    rng = random.Random(seed)
    action_types = list(ActionType)

    steps_taken: int = 0
    score: float = 0.5  # Default safe score
    success: bool = False
    rewards: list[float] = []
    prev_survival_score: float = 0.9

    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    try:
        with httpx.Client(base_url=url, timeout=30.0) as client:
            # Reset environment
            reset_resp = client.post("/reset", json={"seed": seed, "session_id": session_id})
            reset_resp.raise_for_status()
            obs: dict[str, Any] = reset_resp.json()
            prev_survival_score = obs["survival_score"]

            # Episode loop
            while not obs["done"]:
                error_msg: str | None = None
                action_str: str = ""

                try:
                    # Get action
                    if _LLM_MODE:
                        action = _llm_action(obs, session_id)
                    else:
                        action_type = rng.choice(action_types)
                        candidate_ips = [e["src_ip"] for e in obs["dpi_data"]["entries"]]
                        target_ip = rng.choice(candidate_ips)
                        action = {
                            "action_type": action_type.value,
                            "target_ip": target_ip,
                            "session_id": session_id,
                        }

                    action_str = f"{action['action_type']}('{action['target_ip']}')"

                    # Execute step
                    step_resp = client.post("/step", json=action)
                    step_resp.raise_for_status()
                    obs = step_resp.json()

                except Exception as exc:
                    error_msg = str(exc)
                    obs["done"] = True  # Force termination on error

                # Calculate reward as change in survival score
                current_survival_score = obs.get("survival_score", prev_survival_score)
                raw_reward = current_survival_score - prev_survival_score
                
                # Clamp reward to strictly (0, 1) range
                reward = _clamp_score(raw_reward + 0.5)  # Shift to positive range
                
                prev_survival_score = current_survival_score
                rewards.append(reward)
                steps_taken += 1
                done = obs.get("done", False)

                log_step(step=steps_taken, action=action_str, reward=reward, done=done, error=error_msg)

                if error_msg or done:
                    break

            # Calculate final score as normalized sum of rewards
            total_reward = sum(rewards)
            if MAX_TOTAL_REWARD > 0:
                score = total_reward / (MAX_TOTAL_REWARD * max(1, steps_taken))
            else:
                score = 0.5
            
            # Clamp final score to strictly (0, 1)
            score = _clamp_score(score)
            success = score >= SUCCESS_SCORE_THRESHOLD

    except Exception as exc:
        error_msg = str(exc)
        log_step(step=steps_taken, action="", reward=0.5, done=False, error=error_msg)
        score = _clamp_score(0.5)
        success = False

    log_end(success=success, steps=steps_taken, score=score, rewards=rewards)
    return score


def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline agent for OpenEnv SOC Trilemma")
    parser.add_argument("--url", default=os.getenv("ENV_URL", "http://localhost:7860"), help="Base URL of the environment server")
    parser.add_argument("--seed", type=int, default=int(os.getenv("TASK_SEED", "42")), help="Integer seed for the episode")
    parser.add_argument("--task", default="easy", help="Task ID for structured logging")
    args = parser.parse_args()

    # Validator injects TASK_NAME as env var — takes priority over --task CLI arg
    task_id = os.getenv("TASK_NAME") or os.getenv("TASK") or args.task

    mode = f"LLM ({MODEL_NAME} @ {API_BASE_URL})" if _LLM_MODE else "random policy"
    print(f"Mode: {mode}", flush=True)
    
    # Try to wait for the server. If it fails, print safe fallback and exit cleanly
    server_ready = wait_for_server(args.url)
    if not server_ready:
        log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)
        log_step(step=0, action="", reward=0.5, done=False, error="timeout")
        log_end(success=False, steps=0, score=0.5, rewards=[])
        return
    
    # If ready, run the actual episode
    run_episode(url=args.url, seed=args.seed, session_id="baseline", task_id=task_id)


if __name__ == "__main__":
    main()
