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
from typing import Any

import httpx

from app.models import ActionType

# ---------------------------------------------------------------------------
# Env-var configuration (injected by the OpenEnv validator at runtime)
# ---------------------------------------------------------------------------
HF_TOKEN: str | None = os.getenv("HF_TOKEN")                          # NO default — ever
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://mohith1220-soc-trilemma-benchmark.hf.space")
MODEL_NAME: str = os.getenv("MODEL_NAME", "meta-llama/Llama-3.3-70B-Instruct")

BENCHMARK: str = "soc-trilemma-benchmark"

_EPSILON = 0.005


def _clamp_score(score: float) -> float:
    """Mirror soc_grader epsilon clamp so [END] score matches grader output."""
    return round(max(_EPSILON, min(1.0 - _EPSILON, score)), 4)

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
    from openai import OpenAI

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


def run_episode(url: str, seed: int, session_id: str = "baseline", task_id: str = "easy") -> float:
    """Run one episode against the environment server.

    Returns:
        Final survival score as a float.
    """
    rng = random.Random(seed)
    action_types = list(ActionType)

    n: int = 0
    score: float = 0.0
    success: bool = False
    rewards_list: list[float] = []
    prev_score: float = 1.0

    print(f"[START] task={task_id} env={BENCHMARK} model={MODEL_NAME}", flush=True)

    try:
        with httpx.Client(base_url=url, timeout=30.0) as client:
            reset_resp = client.post("/reset", json={"seed": seed, "session_id": session_id})
            reset_resp.raise_for_status()
            obs: dict[str, Any] = reset_resp.json()
            prev_score = obs["survival_score"]

            while not obs["done"]:
                error_msg: str | None = None
                action_str: str = ""

                try:
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

                    step_resp = client.post("/step", json=action)
                    step_resp.raise_for_status()
                    obs = step_resp.json()

                except Exception as exc:
                    error_msg = str(exc)

                n += 1
                reward = round(obs["survival_score"] - prev_score, 8)
                prev_score = obs["survival_score"]
                rewards_list.append(reward)
                done = obs["done"]

                print(
                    f"[STEP] step={n} action={action_str} reward={reward:.4f} "
                    f"done={str(done).lower()} error={error_msg or 'null'}",
                    flush=True,
                )


                if error_msg:
                    break

            score = obs["survival_score"]
            success = obs["done"]

    except Exception as exc:
        error_msg = str(exc)
        print(f"[STEP] step={n} action= reward=0.0000 done=false error={error_msg}", flush=True)

    clamped_score = _clamp_score(score)
    print(
        f"[END] success={str(success).lower()} steps={n} score={clamped_score:.4f} "
        f"rewards={','.join(f'{r:.4f}' for r in rewards_list)}",
        flush=True,
    )
    return clamped_score


def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline agent for OpenEnv SOC Trilemma")
    parser.add_argument("--url", default="http://localhost:7860", help="Base URL of the environment server")
    parser.add_argument("--seed", type=int, default=42, help="Integer seed for the episode")
    parser.add_argument("--task", default="easy", help="Task ID for structured logging")
    args = parser.parse_args()

    mode = f"LLM ({MODEL_NAME} @ {API_BASE_URL})" if _LLM_MODE else "random policy"
    print(f"Mode: {mode}", flush=True)
    run_episode(url=args.url, seed=args.seed, task_id=args.task)


if __name__ == "__main__":
    main()
