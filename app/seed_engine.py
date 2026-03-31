"""SeedEngine: deterministic IP role assignment using a seeded RNG."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.models import DPITemplate


@dataclass
class RoleAssignment:
    attacker_ip: str
    decoy_ips: list[str] = field(default_factory=list)


class SeedEngine:
    def assign_roles(
        self, seed: int, template: DPITemplate, num_decoys: int
    ) -> RoleAssignment:
        """Shuffle ip_pool with a seeded RNG and pick attacker + decoys."""
        rng = random.Random(seed)
        pool = list(template.ip_pool)
        rng.shuffle(pool)
        attacker_ip = pool[0]
        decoy_ips = pool[1 : 1 + num_decoys]
        return RoleAssignment(attacker_ip=attacker_ip, decoy_ips=decoy_ips)
