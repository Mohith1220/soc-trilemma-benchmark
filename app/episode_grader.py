"""Episode-level grader for SOC Trilemma benchmark.

Trajectory-aware scoring that rewards:
- Efficiency: blocking the attacker in fewer steps
- Forensic discipline: querying before blocking (no false positives)
- SLA management: resolving outages quickly
- Survival: maintaining high survival_score throughout

Always returns a float strictly in (0.11, 0.89).
"""
from __future__ import annotations


def _clamp(score: float) -> float:
    """Clamp to strictly (0.11, 0.89) — well within (0, 1), never at boundaries."""
    return max(0.11, min(0.89, score))


# Max steps per task — used to compute efficiency bonus
_TASK_MAX_STEPS = {
    "easy":   100,
    "medium": 85,
    "hard":   75,
    "expert": 60,
}

# Difficulty offsets — harder tasks start with lower base
_TASK_OFFSETS = {
    "easy":   0.05,
    "medium": 0.02,
    "hard":   0.00,
    "expert": -0.03,
}


class EpisodeGrader:
    """
    Trajectory-aware episode grader.

    Scoring components:
      1. Survival component  (40%) — final survival_score reflects SLA discipline
      2. Completion bonus    (20%) — attacker blocked before timeout
      3. Efficiency bonus    (20%) — faster resolution = higher score
      4. Forensic bonus      (10%) — queried before blocking (no false positives)
      5. Difficulty offset   (10%) — task-specific calibration

    All components sum to a value clamped strictly in (0.11, 0.89).
    """

    def grade(self, final_obs: dict, task_id: str) -> float:
        """
        Grade an episode using trajectory-aware scoring.

        Args:
            final_obs: dict with keys:
                - survival_score: float — final survival score
                - done: bool — True if attacker was blocked (not timeout)
                - tick: int — final tick count
                - steps: int (optional) — number of steps taken
                - queried_before_block: bool (optional) — True if agent used query_dpi
                - false_positives: int (optional) — number of wrong blocks
            task_id: "easy", "medium", "hard", or "expert"

        Returns:
            Float strictly in (0.11, 0.89)
        """
        survival   = final_obs.get("survival_score", 0.5)
        done       = final_obs.get("done", False)
        tick       = final_obs.get("tick", 60)
        steps      = final_obs.get("steps", 50)
        queried    = final_obs.get("queried_before_block", False)
        false_pos  = final_obs.get("false_positives", 0)

        max_steps  = _TASK_MAX_STEPS.get(task_id, 75)
        offset     = _TASK_OFFSETS.get(task_id, 0.0)

        # 1. Survival component (40%) — reflects SLA discipline throughout episode
        survival_component = survival * 0.40

        # 2. Completion bonus (20%) — attacker blocked before tick 60
        completion_bonus = 0.20 if done else 0.0

        # 3. Efficiency bonus (20%) — reward faster resolution
        #    Full bonus if done in ≤30% of max steps, scales down linearly
        if done and max_steps > 0:
            efficiency_ratio = 1.0 - (steps / max_steps)
            efficiency_bonus = max(0.0, efficiency_ratio) * 0.20
        else:
            efficiency_bonus = 0.0

        # 4. Forensic bonus (10%) — reward querying before blocking
        #    Penalize false positives (wrong blocks)
        forensic_bonus = 0.10 if queried else 0.0
        false_positive_penalty = min(0.08, false_pos * 0.04)  # cap at -0.08
        forensic_component = max(0.0, forensic_bonus - false_positive_penalty)

        # 5. Difficulty offset (10%) — task calibration
        difficulty_component = offset * 0.10 / 0.05  # normalize to ~0.10 range

        raw = (
            survival_component
            + completion_bonus
            + efficiency_bonus
            + forensic_component
            + difficulty_component
        )

        return _clamp(raw)
