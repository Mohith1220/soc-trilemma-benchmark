#!/usr/bin/env python3
"""SOC Trilemma inference script.

Emits structured stdout logs in the mandatory format:
  [START] task=<task_name> env=<benchmark> model=<model_name>
  [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
  [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>
"""
from __future__ import annotations

import argparse
import os
import random
import sys

from app.config import load_task_config
from app.episode_grader import EpisodeGrader
from app.models import Action, ActionType
from app.session_manager import SessionManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_BASE_URL = os.getenv("API_BASE_URL", "")
MODEL_NAME   = os.getenv("MODEL_NAME", "random-baseline")
HF_TOKEN     = os.getenv("HF_TOKEN", "")

BENCHMARK = "soc-trilemma"
MAX_STEPS = 50

TASK_CONFIGS = {
    "easy":   "tasks/easy.yaml",
    "medium": "tasks/medium.yaml",
    "hard":   "tasks/hard.yaml",
}

_ACTION_TYPES = list(ActionType)

# ---------------------------------------------------------------------------
# Mandatory log helpers
# ---------------------------------------------------------------------------

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: str | None) -> None:
    error_str = error if error else "null"
    done_str  = "true" if done else "false"
    print(
        f"[STEP]  step={step} action={action} reward={reward:.2f} "
        f"done={done_str} error={error_str}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: list[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    success_str = "true" if success else "false"
    print(
        f"[END]   success={success_str} steps={steps} score={score:.2f} "
        f"rewards={rewards_str}",
        flush=True,
    )

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def random_policy(obs, rng: random.Random, session_id: str) -> Action:
    action_type = rng.choice(_ACTION_TYPES)
    candidate_ips = [e.src_ip for e in obs.dpi_data.entries]
    target_ip = rng.choice(candidate_ips)
    return Action(action_type=action_type, target_ip=target_ip, session_id=session_id)

# ---------------------------------------------------------------------------
# Episode runner
# ---------------------------------------------------------------------------

def run_episode(task_id: str, seed: int = 42) -> float:
    """Run one episode, emit [START]/[STEP]/[END] logs, return grader_score."""
    config_path  = TASK_CONFIGS[task_id]
    task_config  = load_task_config(config_path)
    session_mgr  = SessionManager(task_config=task_config)
    grader       = EpisodeGrader()
    session_id   = f"inference_{task_id}_{seed}"
    rng          = random.Random(seed)

    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    obs        = session_mgr.create_or_reset(session_id, seed=seed)
    prev_score = obs.survival_score
    step       = 0
    rewards: list[float] = []
    success    = False
    score      = 0.0

    try:
        while not obs.done and step < MAX_STEPS:
            action  = random_policy(obs, rng, session_id)
            obs     = session_mgr.step(session_id, action)

            raw_reward  = obs.survival_score - prev_score
            prev_score  = obs.survival_score
            step       += 1
            # Normalize to strictly (0, 1): map [-1,1] -> [0.01, 0.99]
            reward = max(0.01, min(0.99, (raw_reward + 1.0) / 2.0))
            rewards.append(reward)

            log_step(
                step=step,
                action=f"{action.action_type.value}({action.target_ip})",
                reward=reward,
                done=obs.done,
                error=None,
            )

        final_obs_dict = {
            "survival_score": obs.survival_score,
            "done": obs.done,
            "tick": obs.tick,
        }
        score   = grader.grade(final_obs_dict, task_id)
        success = score > 0.0

    except Exception as exc:
        log_step(step=step + 1, action="error", reward=0.0, done=True, error=str(exc))
        score   = 0.11  # minimum valid score — never 0.0
        success = False

    log_end(success=success, steps=step, score=score, rewards=rewards)
    return score

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SOC Trilemma inference script")
    parser.add_argument("--seed", type=int, default=int(os.getenv("TASK_SEED", "42")))
    args = parser.parse_args()
    seed = args.seed

    for task_id in ["easy", "medium", "hard"]:
        run_episode(task_id, seed=seed)

    sys.exit(0)


if __name__ == "__main__":
    main()
