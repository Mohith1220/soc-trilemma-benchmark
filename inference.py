#!/usr/bin/env python3
"""SOC Trilemma inference script."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

from openai import OpenAI

from app.config import load_task_config
from app.episode_grader import EpisodeGrader
from app.models import Action, ActionType
from app.session_manager import SessionManager

# ---------------------------------------------------------------------------
# Credentials — NO defaults, always use what the platform injects
# ---------------------------------------------------------------------------
API_BASE_URL = os.environ.get("API_BASE_URL", "")
MODEL_NAME   = os.environ.get("MODEL_NAME", "")
API_KEY      = os.environ.get("API_KEY", "") or os.environ.get("HF_TOKEN", "")

MAX_STEPS = 50
TASK_CONFIGS = {
    "easy":   "tasks/easy.yaml",
    "medium": "tasks/medium.yaml",
    "hard":   "tasks/hard.yaml",
}
_ACTION_TYPES = list(ActionType)

SYSTEM_PROMPT = """You are a SOC analyst. You will see a list of IP addresses and network data.
Your job is to identify and block the attacker IP address.
Reply with ONLY a JSON object like: {"action": "block_ip", "target_ip": "10.0.0.X"}
Choose the IP most likely to be the attacker based on the DPI data."""


def _get_client():
    """Always create client using platform-injected credentials."""
    if not API_BASE_URL or not API_KEY:
        return None
    try:
        return OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
    except Exception:
        return None


def llm_policy(obs, session_id: str) -> Action | None:
    """Ask LLM to pick an action. Returns None on failure."""
    client = _get_client()
    if client is None:
        return None

    ip_list = [e.src_ip for e in obs.dpi_data.entries]
    dpi_info = [
        {"ip": e.src_ip, "payload": e.payload_summary, "flags": e.flags}
        for e in obs.dpi_data.entries
    ]
    user_msg = json.dumps({
        "stage": obs.stage.value,
        "tick": obs.tick,
        "survival_score": round(obs.survival_score, 4),
        "dpi_data": dpi_info,
    })

    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=64,
            temperature=0.0,
        )
        text = resp.choices[0].message.content.strip()
        parsed = json.loads(text)
        action_str = parsed.get("action", "block_ip")
        target_ip  = parsed.get("target_ip", "")
        if target_ip in ip_list:
            action_type = ActionType(action_str) if action_str in [a.value for a in ActionType] else ActionType.BlockIP
            return Action(action_type=action_type, target_ip=target_ip, session_id=session_id)
    except Exception:
        pass
    return None


def random_policy(obs, rng: random.Random, session_id: str) -> Action:
    action_type = rng.choice(_ACTION_TYPES)
    target_ip   = rng.choice([e.src_ip for e in obs.dpi_data.entries])
    return Action(action_type=action_type, target_ip=target_ip, session_id=session_id)


def run_episode(task_id: str, seed: int = 42) -> float:
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
            # Try LLM first, fall back to random
            action = llm_policy(obs, session_id)
            if action is None:
                action = random_policy(obs, rng, session_id)

            obs        = session_mgr.step(session_id, action)
            reward     = obs.survival_score - prev_score
            prev_score = obs.survival_score
            step      += 1
            total_reward += reward
            cumulative   += reward

            done_str   = "true" if obs.done else "false"
            action_str = f"{action.action_type.value}({action.target_ip})"
            sys.stdout.write(
                f"[STEP]  step={step} action={action_str} reward={reward:.4f}"
                f" cumulative_reward={cumulative:.4f} done={done_str}\n"
            )
            sys.stdout.flush()

    except Exception as exc:
        sys.stdout.write(
            f"[STEP]  step={step+1} action=error reward=0.0000"
            f" cumulative_reward={cumulative:.4f} done=true\n"
        )
        sys.stdout.flush()

    grader_score = grader.grade(
        {"survival_score": obs.survival_score, "done": obs.done, "tick": obs.tick},
        task_id,
    )

    sys.stdout.write(
        f"[END]   task={task_id} score={grader_score:.4f}"
        f" steps={step} total_reward={total_reward:.4f}\n"
    )
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
