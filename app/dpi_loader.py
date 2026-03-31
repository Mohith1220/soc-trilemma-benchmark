from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.exceptions import TemplateLoadError
from app.models import DPITemplate, KillChainStage

# Map each stage to its data file name
_STAGE_FILE_MAP: dict[KillChainStage, str] = {
    KillChainStage.Recon: "dpi_recon.json",
    KillChainStage.LateralMovement: "dpi_lateral_movement.json",
    KillChainStage.Exfiltration: "dpi_exfiltration.json",
}

_DATA_DIR = Path(__file__).parent.parent / "data"


def load_dpi_template(stage: KillChainStage) -> DPITemplate:
    """Load a DPI template JSON file for the given kill-chain stage.

    Raises:
        TemplateLoadError: if the file is missing or the JSON is malformed /
                           fails Pydantic validation.
    """
    filename = _STAGE_FILE_MAP[stage]
    path = _DATA_DIR / filename

    if not path.exists():
        raise TemplateLoadError(f"DPI template file not found: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateLoadError(f"Failed to read/parse DPI template '{path}': {exc}") from exc

    try:
        return DPITemplate.model_validate(data)
    except ValidationError as exc:
        raise TemplateLoadError(f"DPI template '{path}' failed validation: {exc}") from exc
