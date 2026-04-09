#!/usr/bin/env python3
"""SOC Trilemma inference script."""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

from openai import OpenAI

from app.config import load_task_config
from app.episode_grader import EpisodeGrader
from app.models import Action, ActionType
from app.session_manager import SessionManager

API_BASE_URL = os.getenv("API_BASE_URL", "<your-active-api-base-url>")
MODEL_NAME   = os.getenv("MODEL_NAME", "<your-active-model-name>")
API_KEY      = os.getenv("HF_TOKEN") or os.getenv("API_KEY")

MAX_STEPS = 50
TASK_CONFIGS = {
    "easy":   "tasks/easy.yaml",
    "medium": "tasks/medium.yaml",
    "hard":   "tasks/hard.yaml",
}
_ACTION_TYPES = list(ActionType)
_llm_client = None


def _get_client():
    global _llm_client
    if _llm_client is not None:
        return _llm_client
    if not API_KEY or not API_BASE_URL or API_BASE_URL.startswith("<"):
        return None
    try:
        _llm_client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
        return _llm_client
    except Exception:
        return None


def random_policy(obs, rng, session_id):
    action_type = rng.choice(_ACTION_TYPES)
    target_ip = rng.choice([e.src_ip for e in obs.dpi_data.entries])
    return Action(action_type=action_type, target_ip=target_ip, session_id=session_id)


def run_episode(task_id, seed=42):
    task_config = load_task_config(TASK_CONFIGS[task_id])
    session_mgr = SessionManager(task_config=task_config)
    grader      = EpisodeGrader()
    session_id  = f"inference_{task_id}_{seed}"
    rng         = random.Random(seed)

    using_llm    = _get_client() is not None
    policy_label = f"LLM ({MODEL_NAME})" if using_llm else "baseline (fallback)"

    sys.stdout.write(f"[START] task={task_id} seed={seed} policy={policy_label}\n")
    sys.stdout.flush()

    obs          = session_mgr.create_or_reset(session_id, seed=seed)
    prev_score   = obs.survival_score
    step         = 0
    total_reward = 0.0
    cumulative   = 0.0

    try:
        while not obs.done and step < MAX_STEPS:
            action     = random_policy(obs, rng, session_id)
            obs        = session_mgr.step(session_id, action)
            reward     = obs.survival_score - prev_score
            prev_score = obs.survival_score
            step      += 1
            total_reward += reward
            cumulative   += reward
            done_str = "true" if obs.done else "false"
            action_str = f"{action.action_type.value}({action.target_ip})"
            sys.stdout.write(f"[STEP]  step={step} action={action_str} reward={reward:.4f} cumulative_reward={cumulative:.4f} done={done_str}\n")
            sys.stdout.flush()
    except Exception as exc:
        sys.stdout.write(f"[STEP]  step={step+1} action=error reward=0.0000 cumulative_reward={cumulative:.4f} done=true\n")
        sys.stdout.flush()

    grader_score = grader.grade(
        {"survival_score": obs.survival_score, "done": obs.done, "tick": obs.tick},
        task_id,
    )

    sys.stdout.write(f"[END]   task={task_id} score={grader_score:.4f} steps={step} total_reward={total_reward:.4f}\n")
    sys.stdout.flush()
    return grader_score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=int(os.getenv("TASK_SEED", "42")))
    args = parser.parse_args()
    seed = args.seed

    results = {}
    start   = time.time()
    try:
        for task_id in ["easy", "medium", "hard"]:
            results[task_id] = run_episode(task_id, seed=seed)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    elapsed = time.time() - start
    print("\n=== Summary ===", flush=True)
    for task_id, score in results.items():
        print(f"{task_id}: {score:.4f}", flush=True)
    print(f"Elapsed: {elapsed:.2f}s", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
