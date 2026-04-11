"""Unit tests for load_task_config (Task 2)."""
import os
import textwrap

import pytest

from app.config import load_task_config
from app.exceptions import ConfigurationError
from app.models import KillChainStage


EASY_YAML = os.path.join(os.path.dirname(__file__), "../../tasks/easy.yaml")
HARD_YAML = os.path.join(os.path.dirname(__file__), "../../tasks/hard.yaml")

VALID_YAML = textwrap.dedent("""\
    max_steps: 100
    stage_time_budgets:
      Recon: 30
      Lateral_Movement: 25
      Exfiltration: 20
    sla_penalty_rate: 0.05
    num_decoys: 2
""")


def write_tmp(tmp_path, content: str) -> str:
    p = tmp_path / "task.yaml"
    p.write_text(content)
    return str(p)


# --- Happy-path tests ---

def test_easy_config_loads(tmp_path):
    cfg = load_task_config(EASY_YAML)
    assert cfg.max_steps == 100
    assert cfg.sla_penalty_rate == 0.03
    assert cfg.num_decoys == 2
    assert cfg.stage_time_budgets[KillChainStage.Recon] == 30
    assert cfg.stage_time_budgets[KillChainStage.LateralMovement] == 25
    assert cfg.stage_time_budgets[KillChainStage.Exfiltration] == 20


def test_hard_config_loads():
    cfg = load_task_config(HARD_YAML)
    assert cfg.max_steps == 70
    assert cfg.sla_penalty_rate == 0.13
    assert cfg.num_decoys == 6


def test_hard_has_more_decoys_than_easy():
    easy = load_task_config(EASY_YAML)
    hard = load_task_config(HARD_YAML)
    assert hard.num_decoys > easy.num_decoys


def test_valid_yaml_returns_task_config(tmp_path):
    path = write_tmp(tmp_path, VALID_YAML)
    cfg = load_task_config(path)
    assert cfg.max_steps == 100


# --- Missing field tests ---

def test_missing_max_steps_raises(tmp_path):
    content = textwrap.dedent("""\
        stage_time_budgets:
          Recon: 30
          Lateral_Movement: 25
          Exfiltration: 20
        sla_penalty_rate: 0.05
        num_decoys: 2
    """)
    path = write_tmp(tmp_path, content)
    with pytest.raises(ConfigurationError, match="max_steps"):
        load_task_config(path)


def test_missing_stage_time_budgets_raises(tmp_path):
    content = textwrap.dedent("""\
        max_steps: 100
        sla_penalty_rate: 0.05
        num_decoys: 2
    """)
    path = write_tmp(tmp_path, content)
    with pytest.raises(ConfigurationError, match="stage_time_budgets"):
        load_task_config(path)


def test_missing_sla_penalty_rate_raises(tmp_path):
    content = textwrap.dedent("""\
        max_steps: 100
        stage_time_budgets:
          Recon: 30
          Lateral_Movement: 25
          Exfiltration: 20
        num_decoys: 2
    """)
    path = write_tmp(tmp_path, content)
    with pytest.raises(ConfigurationError, match="sla_penalty_rate"):
        load_task_config(path)


def test_missing_num_decoys_raises(tmp_path):
    content = textwrap.dedent("""\
        max_steps: 100
        stage_time_budgets:
          Recon: 30
          Lateral_Movement: 25
          Exfiltration: 20
        sla_penalty_rate: 0.05
    """)
    path = write_tmp(tmp_path, content)
    with pytest.raises(ConfigurationError, match="num_decoys"):
        load_task_config(path)


# --- Invalid value tests ---

def test_negative_sla_penalty_rate_raises(tmp_path):
    content = VALID_YAML.replace("sla_penalty_rate: 0.05", "sla_penalty_rate: -0.1")
    path = write_tmp(tmp_path, content)
    with pytest.raises(ConfigurationError, match="sla_penalty_rate"):
        load_task_config(path)


def test_num_decoys_less_than_2_raises(tmp_path):
    content = VALID_YAML.replace("num_decoys: 2", "num_decoys: 1")
    path = write_tmp(tmp_path, content)
    with pytest.raises(ConfigurationError, match="num_decoys"):
        load_task_config(path)


def test_missing_stage_in_budgets_raises(tmp_path):
    content = textwrap.dedent("""\
        max_steps: 100
        stage_time_budgets:
          Recon: 30
          Lateral_Movement: 25
        sla_penalty_rate: 0.05
        num_decoys: 2
    """)
    path = write_tmp(tmp_path, content)
    with pytest.raises(ConfigurationError, match="Exfiltration"):
        load_task_config(path)


def test_file_not_found_raises():
    with pytest.raises(ConfigurationError, match="not found"):
        load_task_config("/nonexistent/path/task.yaml")
