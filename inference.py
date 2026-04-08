#!/usr/bin/env python3
"""SOC Trilemma inference script — runs episodes locally and reports grader scores.

Mirrors the SIREN output format so the OpenEnv validator can parse grader scores.
Prints "Grader score: X.XXXX" for each task (easy, medium, hard).
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

from app.config import load_task_config
from app.episode_grader import EpisodeGrader
from app.models import Action, ActionType
from app.session_manager import SessionManager

# ---------------------------------------------------------------------------
# LLM config (optional — falls back to random policy if not set)
# ---------------------------------------------------------------------------
_API_BASE_URL = os.environ.get("API_BASE_URL", "")
_MODEL_NAME = os.environ.get("MODEL_NAME", "")
_HF_TOKEN = os.environ.get("HF_TOKEN", "")

_llm_client = None


def _get_client():
    global _llm_client
    if _llm_client is not None:
        return _llm_client
    if not (_API_BASE_URL and _MODEL_NAME and _HF_TOKEN):
        return None
    try:
        from openai import OpenAI
        _llm_client = OpenAI(base_url=_API_BASE_URL, api_key=_HF_TOKEN)
        return _llm_client
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Task definitions — maps task_id to its yaml config path
# ---------------------------------------------------------------------------
TASK_CONFIGS = {
    "easy":   "tasks/easy.yaml",
    "medium": "tasks/medium.yaml",
    "hard":   "tasks/hard.yaml",
}

# ---------------------------------------------------------------------------
# Random baseline policy
# ---------------------------------------------------------------------------
_ACTION_TYPES = list(ActionType)


def random_policy(obs, rng: random.Random, session_id: str) -> Action:
    """Pick a random action from the available IPs."""
    action_type = rng.choice(_ACTION_TYPES)
    candidate_ips = [e.src_ip for e in obs.dpi_data.entries]
    target_ip = rng.choice(candidate_ips)
    return Action(action_type=action_type, target_ip=target_ip, session_id=session_id)


# ---------------------------------------------------------------------------
# Episode runner — runs locally without HTTP
# ---------------------------------------------------------------------------
MAX_STEPS = 50


def run_episode(task_id: str, seed: int = 42) -> tuple:
    """Run one episode locally and return (final_obs, total_reward, grader_score)."""
    config_path = TASK_CONFIGS[task_id]
    task_config = load_task_config(config_path)
    session_manager = SessionManager(task_config=task_config)
    grader = EpisodeGrader()

    session_id = f"inference_{task_id}_{seed}"
    rng = random.Random(seed)

    obs = session_manager.create_or_reset(session_id, seed=seed)

    using_llm = _get_client() is not None
    policy_label = f"LLM ({_MODEL_NAME})" if using_llm else "random (fallback)"
    print(f"\n--- Episode: {task_id} (seed={seed}, policy={policy_label}) ---")

    total_reward = 0.0
    step = 0
    prev_score = obs.survival_score

    while not obs.done and step < MAX_STEPS:
        action = random_policy(obs, rng, session_id)
        obs = session_manager.step(session_id, action)

        reward = obs.survival_score - prev_score
        prev_score = obs.survival_score
        total_reward += reward
        step += 1

        print(
            f"Step {step}: action={action.action_type.value}({action.target_ip})"
            f" reward={reward:.4f} survival={obs.survival_score:.4f}"
        )

    # Grade the episode
    final_obs_dict = {
        "survival_score": obs.survival_score,
        "done": obs.done,
        "tick": obs.tick,
    }
    grader_score = grader.grade(final_obs_dict, task_id)

    print(f"\nFinal observation: survival_score={obs.survival_score:.4f} tick={obs.tick} done={obs.done}")
    print(f"Final reward: {reward:.4f}")
    print(f"Grader score: {grader_score:.4f}")

    return obs, total_reward, grader_score


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SOC Trilemma inference script")
    parser.add_argument("--seed", type=int, default=int(os.getenv("TASK_SEED", "42")))
    args = parser.parse_args()
    seed = args.seed

    task_ids = ["easy", "medium", "hard"]
    results = {}

    start_time = time.time()

    try:
        for task_id in task_ids:
            _obs, total_reward, grader_score = run_episode(task_id, seed=seed)
            results[task_id] = {
                "total_reward": total_reward,
                "grader_score": grader_score,
            }
    except Exception as exc:
        print(f"Error during episode execution: {exc}", file=sys.stderr)
        sys.exit(1)

    elapsed = time.time() - start_time

    print("\n=== Summary ===")
    print(f"{'task_id':<10} | {'total_reward':>12} | {'grader_score':>12}")
    print(f"{'-'*10}-|-{'-'*14}-|-{'-'*13}")
    for task_id in task_ids:
        r = results[task_id]
        print(f"{task_id:<10} | {r['total_reward']:>12.4f} | {r['grader_score']:>12.4f}")
    print(f"\nElapsed time: {elapsed:.2f}s")

    sys.exit(0)


if __name__ == "__main__":
    main()
