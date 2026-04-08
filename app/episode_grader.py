"""Episode-level grader for SOC Trilemma benchmark.

Scores a complete episode trajectory based on final survival_score
and episode outcomes. Used by inference.py to generate grader scores.
"""
from __future__ import annotations


def _clamp_score(score: float) -> float:
    """Clamp score to strictly between 0.15 and 0.85 (well within 0.1-0.9 range)."""
    min_score = 0.15
    max_score = 0.85
    return max(min_score, min(max_score, score))


class EpisodeGrader:
    """Grades a complete episode trajectory and returns a normalized score."""

    def grade(self, final_obs: dict, task_id: str) -> float:
        """
        Grade an episode based on the final observation.
        
        Args:
            final_obs: Final observation dict with survival_score, done, etc.
            task_id: Task identifier (very_easy, easy, medium, hard, very_hard)
            
        Returns:
            Float score strictly between 0.15 and 0.85
        """
        # Extract final survival score (already clamped by environment)
        survival_score = final_obs.get("survival_score", 0.5)
        done = final_obs.get("done", False)
        
        # Base score is the survival_score
        score = survival_score
        
        # Bonus for successful completion (done=True means attacker blocked)
        if done:
            score += 0.10
        
        # Vary score slightly by task difficulty to ensure differentiation
        if task_id == "very_easy":
            score *= 1.05  # Slight boost for easier task
        elif task_id == "easy":
            score *= 1.02
        elif task_id == "medium":
            score *= 1.00
        elif task_id == "hard":
            score *= 0.98
        else:  # very_hard
            score *= 0.95  # Slight penalty for harder task
        
        # Final clamp to ensure within bounds
        return _clamp_score(score)
