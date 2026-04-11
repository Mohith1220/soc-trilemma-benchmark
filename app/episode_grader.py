"""Episode-level grader for SOC Trilemma benchmark.

Always returns a float strictly in (0.12, 0.88) — never 0.0 or 1.0.
Scores are differentiated across tasks even when survival hits the floor.
"""
from __future__ import annotations


def _clamp(score: float) -> float:
    """Clamp to strictly (0.12, 0.88)."""
    return max(0.12, min(0.88, score))


# Per-task base scores — guarantees differentiation even at survival floor
_TASK_BASE = {"easy": 0.22, "medium": 0.19, "hard": 0.16, "expert": 0.13}
_TASK_MAX_STEPS = {"easy": 100, "medium": 85, "hard": 70, "expert": 55}


class EpisodeGrader:
    """Grades a completed episode. Returns float strictly in (0.12, 0.88)."""

    def grade(self, final_obs: dict, task_id: str) -> float:
        survival  = final_obs.get("survival_score", 0.5)
        done      = final_obs.get("done", False)   # True = attacker blocked
        steps     = final_obs.get("steps", 50)
        queried   = final_obs.get("queried_before_block", False)
        false_pos = final_obs.get("false_positives", 0)

        base      = _TASK_BASE.get(task_id, 0.16)
        max_steps = _TASK_MAX_STEPS.get(task_id, 75)

        # Base score guarantees per-task differentiation
        score = base

        # Survival contribution (scales 0 → +0.35 as survival goes 0 → 1)
        score += survival * 0.35

        # Completion bonus — attacker actually blocked
        if done:
            score += 0.20
            # Efficiency: faster block = more bonus (up to +0.10)
            if max_steps > 0:
                score += max(0.0, 1.0 - steps / max_steps) * 0.10

        # Forensic discipline bonus
        if queried:
            score += 0.05

        # False positive penalty
        score -= min(0.06, false_pos * 0.03)

        return _clamp(score)
