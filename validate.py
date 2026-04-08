#!/usr/bin/env python3
"""SOC Trilemma validation script — checks environment correctness."""
import sys
from app.config import load_task_config
from app.session_manager import SessionManager
from app.episode_grader import EpisodeGrader

CHECKS = []

def check(name):
    """Decorator to register a check function."""
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


@check("grader_returns_valid_range_for_all_tasks")
def check_grader_range():
    """Verify grader returns scores in (0, 1) for all 5 tasks."""
    grader = EpisodeGrader()
    
    for task_id in ("very_easy", "easy", "medium", "hard", "very_hard"):
        # Create a mock final observation
        final_obs = {
            "survival_score": 0.65,
            "done": True,
            "stage": "Exfiltration",
            "tick": 50,
            "max_ticks": 100,
        }
        
        score = grader.grade(final_obs, task_id)
        
        assert isinstance(score, float), (
            f"Grader.grade() must return float for task '{task_id}', "
            f"got {type(score).__name__}"
        )
        assert 0.0 < score < 1.0, (
            f"Grader score must be strictly between 0 and 1 for task '{task_id}': {score}"
        )
        assert score != 0.0 and score != 1.0, (
            f"Grader score must NOT be exactly 0.0 or 1.0 for task '{task_id}': {score}"
        )
        print(f"  ✓ {task_id}: score={score:.4f} (valid)")


@check("grader_scores_vary_by_task")
def check_grader_variation():
    """Verify grader produces different scores for different tasks."""
    grader = EpisodeGrader()
    
    # Same final observation for all tasks
    final_obs = {
        "survival_score": 0.65,
        "done": True,
        "stage": "Exfiltration",
        "tick": 50,
        "max_ticks": 100,
    }
    
    scores = {}
    for task_id in ("very_easy", "easy", "medium", "hard", "very_hard"):
        scores[task_id] = grader.grade(final_obs, task_id)
    
    # Check that not all scores are the same
    unique_scores = set(scores.values())
    assert len(unique_scores) > 1, (
        f"Grader must produce different scores for different tasks, "
        f"but all tasks got the same score: {scores}"
    )
    print(f"  ✓ Scores vary by task: {scores}")


@check("session_manager_reset_works")
def check_session_manager():
    """Verify SessionManager can reset and produce valid observations."""
    task_config = load_task_config("tasks/easy.yaml")
    mgr = SessionManager(task_config=task_config)
    
    obs = mgr.create_or_reset("test_session", seed=42)
    
    assert isinstance(obs.survival_score, float), "survival_score must be float"
    assert 0.0 < obs.survival_score < 1.0, (
        f"Initial survival_score must be strictly between 0 and 1: {obs.survival_score}"
    )
    assert obs.survival_score != 0.0 and obs.survival_score != 1.0, (
        f"Initial survival_score must NOT be exactly 0.0 or 1.0: {obs.survival_score}"
    )
    assert obs.done is False, "Initial observation must have done=False"
    assert obs.tick == 0, "Initial observation must have tick=0"
    
    print(f"  ✓ SessionManager reset OK (survival_score={obs.survival_score:.4f})")


@check("all_task_configs_load")
def check_task_configs():
    """Verify all 5 task configs load successfully."""
    for task_id in ("very_easy", "easy", "medium", "hard", "very_hard"):
        config = load_task_config(f"tasks/{task_id}.yaml")
        assert config.max_steps > 0, f"{task_id}: max_steps must be positive"
        assert 0.0 < config.sla_penalty_rate < 1.0, (
            f"{task_id}: sla_penalty_rate must be in (0, 1)"
        )
        print(f"  ✓ {task_id}.yaml loaded (max_steps={config.max_steps}, penalty={config.sla_penalty_rate})")


def main():
    print("=" * 60)
    print("SOC Trilemma Validation")
    print("=" * 60)
    print()
    
    for name, fn in CHECKS:
        print(f"Running: {name}")
        try:
            fn()
        except AssertionError as e:
            print(f"  ✗ FAIL [{name}]: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"  ✗ FAIL [{name}]: Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    print()
    print("=" * 60)
    print("All validation checks passed!")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
