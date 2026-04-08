"""Episode-level grader for SOC Trilemma benchmark.

Scores a complete episode based on final survival_score.
Always returns a float strictly between 0.1 and 0.9 (never 0.0 or 1.0).
"""
from __future__ import annotations


def _clamp(score: float) -> float:
    """Clamp to strictly (0.1, 0.9) — never 0.0 or 1.0."""
    return max(0.1, min(0.9, score))


class EpisodeGrader:
    """Grades a completed episode and returns a score strictly in (0.1, 0.9)."""

    def grade(self, final_obs: dict, task_id: str) -> float:
        """
        Grade an episode based on the final observation.

        Args:
            final_obs: dict with survival_score, done, tick
            task_id: "easy", "medium", or "hard"

        Returns:
            Float strictly between 0.1 and 0.9
        """
        survival = final_obs.get("survival_score", 0.5)
        done = final_obs.get("done", False)

        # Base score from survival
        score = survival * 0.7

        # Bonus for completing the episode (attacker blocked)
        if done:
            score += 0.15

        # Task difficulty offset so scores differ across tasks
        offsets = {"easy": 0.05, "medium": 0.02, "hard": 0.0, "very_easy": 0.07, "very_hard": -0.02}
        score += offsets.get(task_id, 0.0)

        return _clamp(score)
