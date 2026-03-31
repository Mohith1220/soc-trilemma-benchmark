"""KillChain FSM: manages stage progression through Recon → LateralMovement → Exfiltration."""
from __future__ import annotations

from typing import Optional

from app.models import DPISnapshot, DPITemplate, KillChainStage
from app.seed_engine import RoleAssignment

# Ordered stage progression
_STAGE_ORDER = [
    KillChainStage.Recon,
    KillChainStage.LateralMovement,
    KillChainStage.Exfiltration,
]


class KillChain:
    """Finite state machine for kill-chain stage progression."""

    def __init__(self) -> None:
        self.stage: KillChainStage = KillChainStage.Recon
        self.tick: int = 0
        self.stage_tick_start: int = 0
        self.dpi_snapshot: Optional[DPISnapshot] = None

    def advance_tick(self, cost: int) -> None:
        """Increment the tick counter by cost."""
        self.tick += cost

    def should_advance_stage(self, stage_budgets: dict[KillChainStage, int]) -> bool:
        """Return True if the time spent in the current stage has met or exceeded its budget."""
        elapsed = self.tick - self.stage_tick_start
        return elapsed >= stage_budgets[self.stage]

    def advance_stage(self) -> Optional[KillChainStage]:
        """Move to the next stage. Returns the new stage, or None if already terminal."""
        current_index = _STAGE_ORDER.index(self.stage)
        next_index = current_index + 1
        if next_index >= len(_STAGE_ORDER):
            return None
        self.stage = _STAGE_ORDER[next_index]
        self.stage_tick_start = self.tick
        return self.stage

    def is_terminal(self) -> bool:
        """Return True if the FSM is at the last stage (Exfiltration)."""
        return self.stage == KillChainStage.Exfiltration

    def load_stage_template(self, template: DPITemplate, role: RoleAssignment) -> None:
        """Build a DPISnapshot from the template and role assignment, store it."""
        self.dpi_snapshot = DPISnapshot(
            stage=template.stage,
            entries=template.entries,
            attacker_ip=role.attacker_ip,
            decoy_ips=role.decoy_ips,
        )
