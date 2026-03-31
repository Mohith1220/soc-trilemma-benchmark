"""Unit tests for PrettyPrinter."""
import json

import pytest

from app.models import (
    Alert,
    DPIEntry,
    DPISnapshot,
    DPITemplate,
    KillChainStage,
    Observation,
)
from app.pretty_printer import PrettyPrinter


@pytest.fixture
def printer():
    return PrettyPrinter()


@pytest.fixture
def sample_template():
    return DPITemplate(
        stage=KillChainStage.Recon,
        entries=[
            DPIEntry(
                src_ip="10.0.0.1",
                dst_ip="10.0.0.2",
                protocol="TCP",
                payload_summary="SYN scan",
                flags=["SYN"],
            )
        ],
        ip_pool=["10.0.0.1", "10.0.0.2", "10.0.0.3"],
    )


@pytest.fixture
def sample_observation():
    snapshot = DPISnapshot(
        stage=KillChainStage.Recon,
        entries=[
            DPIEntry(
                src_ip="10.0.0.1",
                dst_ip="10.0.0.2",
                protocol="TCP",
                payload_summary="SYN scan",
                flags=["SYN"],
            )
        ],
        attacker_ip="10.0.0.1",
        decoy_ips=["10.0.0.2"],
    )
    return Observation(
        stage=KillChainStage.Recon,
        dpi_data=snapshot,
        alerts=[
            Alert(message="Suspicious scan detected", severity="warning", tick=5),
            Alert(message="High traffic volume", severity="critical", tick=10),
        ],
        survival_score=0.75,
        tick=15,
        done=False,
        dom="",
    )


# --- dpi_template_to_json ---

def test_dpi_template_to_json_is_valid_json(printer, sample_template):
    result = printer.dpi_template_to_json(sample_template)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


def test_dpi_template_to_json_round_trip(printer, sample_template):
    json_str = printer.dpi_template_to_json(sample_template)
    restored = DPITemplate.model_validate_json(json_str)
    assert restored == sample_template


def test_dpi_template_to_json_contains_stage(printer, sample_template):
    json_str = printer.dpi_template_to_json(sample_template)
    assert "Recon" in json_str


def test_dpi_template_to_json_contains_ip_pool(printer, sample_template):
    json_str = printer.dpi_template_to_json(sample_template)
    for ip in sample_template.ip_pool:
        assert ip in json_str


# --- observation_to_html / render_dashboard ---

def test_html_contains_tailwind_cdn(printer, sample_observation):
    html = printer.observation_to_html(sample_observation)
    assert "https://cdn.tailwindcss.com" in html


def test_html_contains_stage(printer, sample_observation):
    html = printer.observation_to_html(sample_observation)
    assert sample_observation.stage.value in html


def test_html_contains_survival_score(printer, sample_observation):
    html = printer.observation_to_html(sample_observation)
    assert str(sample_observation.survival_score) in html


def test_html_contains_tick(printer, sample_observation):
    html = printer.observation_to_html(sample_observation)
    assert str(sample_observation.tick) in html


def test_html_contains_done(printer, sample_observation):
    html = printer.observation_to_html(sample_observation)
    assert str(sample_observation.done) in html


def test_html_contains_all_alert_messages(printer, sample_observation):
    html = printer.observation_to_html(sample_observation)
    for alert in sample_observation.alerts:
        assert alert.message in html


def test_html_no_alerts_shows_placeholder(printer, sample_observation):
    sample_observation.alerts = []
    html = printer.observation_to_html(sample_observation)
    assert "No alerts" in html


def test_render_dashboard_is_alias(printer, sample_observation):
    """render_dashboard must produce the same output as observation_to_html."""
    assert printer.render_dashboard(sample_observation) == printer.observation_to_html(sample_observation)
