from __future__ import annotations

import yaml

from app.exceptions import ConfigurationError
from app.models import KillChainStage, TaskConfig


def load_task_config(path: str) -> TaskConfig:
    """Load and validate a TaskConfig from a YAML file.

    Raises:
        ConfigurationError: If the file is missing, unreadable, or contains
            invalid/missing fields.
    """
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigurationError(f"Task config file not found: {path}")
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Failed to parse YAML at {path}: {exc}")

    if not isinstance(data, dict):
        raise ConfigurationError(f"Task config at {path} must be a YAML mapping")

    required_fields = {"max_steps", "stage_time_budgets", "sla_penalty_rate", "num_decoys"}
    missing = required_fields - data.keys()
    if missing:
        raise ConfigurationError(
            f"Task config at {path} is missing required fields: {sorted(missing)}"
        )

    sla_penalty_rate = data["sla_penalty_rate"]
    if not isinstance(sla_penalty_rate, (int, float)) or sla_penalty_rate < 0:
        raise ConfigurationError(
            f"sla_penalty_rate must be a non-negative number, got: {sla_penalty_rate!r}"
        )

    num_decoys = data["num_decoys"]
    if not isinstance(num_decoys, int) or num_decoys < 2:
        raise ConfigurationError(
            f"num_decoys must be an integer >= 2, got: {num_decoys!r}"
        )

    stage_time_budgets = data.get("stage_time_budgets")
    if not isinstance(stage_time_budgets, dict):
        raise ConfigurationError(
            f"stage_time_budgets must be a mapping, got: {type(stage_time_budgets).__name__}"
        )

    required_stages = {stage.value for stage in KillChainStage}
    provided_stages = set(stage_time_budgets.keys())
    missing_stages = required_stages - provided_stages
    if missing_stages:
        raise ConfigurationError(
            f"stage_time_budgets is missing entries for stages: {sorted(missing_stages)}"
        )

    # Normalise stage keys to KillChainStage enum values
    normalised_budgets: dict[KillChainStage, int] = {}
    for key, value in stage_time_budgets.items():
        try:
            stage = KillChainStage(key)
        except ValueError:
            raise ConfigurationError(
                f"Unknown stage key in stage_time_budgets: {key!r}"
            )
        if not isinstance(value, int) or value <= 0:
            raise ConfigurationError(
                f"stage_time_budgets[{key!r}] must be a positive integer, got: {value!r}"
            )
        normalised_budgets[stage] = value

    try:
        return TaskConfig(
            max_steps=data["max_steps"],
            stage_time_budgets=normalised_budgets,
            sla_penalty_rate=float(sla_penalty_rate),
            num_decoys=num_decoys,
        )
    except Exception as exc:
        raise ConfigurationError(f"Invalid task config at {path}: {exc}") from exc
