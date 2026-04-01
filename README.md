---
title: SOC Trilemma Benchmark
emoji: 🛡️
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
license: mit
short_description: 3-stage Cyber Kill Chain RL environment for agentic SOC triage
---

# 🛡️ SOC Trilemma Benchmark

[![Tests](https://img.shields.io/badge/tests-114%20passing-brightgreen)]()
[![OpenEnv](https://img.shields.io/badge/openenv%20validate-6%2F6-blue)]()
[![Determinism](https://img.shields.io/badge/seed%2042-0.2000%20locked-brightgreen)]()
[![Tasks](https://img.shields.io/badge/tasks-4%20difficulties-orange)]()
[![MCP](https://img.shields.io/badge/MCP-4%20tools-purple)]()
[![Python](https://img.shields.io/badge/python-3.11-blue)]()
[![Docker](https://img.shields.io/badge/docker-UID%201000-green)]()
[![HF Space](https://img.shields.io/badge/HF%20Space-live-yellow)]()

> A research-grade RL environment where an agent plays a SOC analyst navigating the **Security Trilemma**: stop the attack, don't break the company, and do it before time runs out.
> Built for the Meta PyTorch Foundation OpenEnv Hackathon 2026.

---

## The Problem: Why Standard Security Agents Fail

Most security automation fails not because it lacks tools — but because it lacks **business context**. An agent that blocks every suspicious IP will stop the attacker, but it will also take down the Finance database, the mail server, and the HR system.

This environment models the **Security Trilemma** — a three-way tension no single greedy strategy can solve:

| Dimension | Pressure |
|---|---|
| **Security** | Neutralize a 3-stage Kill Chain before tick 60 |
| **Agility** | Every action costs ticks — slow agents fail too |
| **Stability** | Wrong blocks trigger SLA bleed — Finance is 15× more costly than Guest WiFi |

### The MDP Formulation

The environment is a **Partially Observable Markov Decision Process (POMDP)**:

- Observations are **masked** — the agent sees generic traffic until it pays a tick cost for forensic depth
- Rewards are shaped by **SLA Bleed** — a persistent per-tick penalty that mimics real-world downtime costs
- Transitions are **adversarial** — the environment reacts to the agent's probes, forcing stealth and precision over brute-force scanning

### Kill Chain Progression

```
Recon            Lateral Movement      Exfiltration
(ticks 0–20)     (ticks 21–40)         (ticks 41–60)
     │                 │                     │
     └─────────────────┴─────────────────────┘
                       ↓
                tick > 60 → done=True, penalty=−1.0
```

---

## Technical Innovations

### 1. Tiered Asset Valuation — Reward Shaping

Every IP in the network is assigned a business tier at reset via `random.Random(seed)`, making tier distribution fully deterministic and reproducible. Blocking the wrong IP triggers a **persistent score bleed every tick** until `resolve_outage` is called:

| Tier | Asset Examples | Bleed / tick |
|---|---|---|
| CRITICAL | Finance DB, Domain Controller | −0.15 |
| INTERNAL | Mail Server, HR System | −0.05 |
| LOW | Guest WiFi, Dev Sandbox | −0.01 |

A false positive on a CRITICAL asset is **15× more damaging** than on a LOW asset. This forces the agent to reason about *which* IP to investigate, not just *whether* to act.

### 2. Adversarial Pivoting — Reasoning Over Pattern Matching

During the Lateral Movement stage (ticks 21–40), if the agent queries the attacker IP, the attacker **detects the probe and moves to a backup IP**. This happens once per episode and invalidates static pattern matching:

```
agent calls query_dpi(attacker_ip) during Lateral Movement
    → alert: "PIVOT DETECTED — attacker moved from X to Y"
    → agent must re-investigate from scratch
```

This proves the environment requires **multi-step reasoning**, not memorization.

### 3. Forensic Masking — Partial Observability

All 12 IPs show `"Standard Traffic"` by default. The agent must spend **5 ticks** on `query_dpi` to reveal whether an IP is malicious. This creates a fundamental trade-off:

> *Investigate and spend time, or guess and risk a false positive?*

---

## Proof of Stability

### Numerical Determinism

Every episode is fully reproducible. `random.Random(seed)` controls attacker assignment, decoy selection, business tier distribution, and pivot destination. **Same seed always produces the same score.**

Verified across 3 independent runs — cold start, warm state, and server restart:

| Seed | Score | Cold Start | Warm State | After Restart |
|---|---|---|---|---|
| 1 | 0.2000 | ✅ | ✅ | ✅ |
| 7 | 0.0000 | ✅ | ✅ | ✅ |
| 42 | 0.2000 | ✅ | ✅ | ✅ |
| 99 | 0.0000 | ✅ | ✅ | ✅ |

### Hardening

- **Atomic State Locking** — `asyncio.Lock` per session prevents race conditions under concurrent load
- **LRU Session Eviction** — `OrderedDict`-based cap at 100 sessions, oldest evicted automatically
- **Adversarial Suite** — dedicated test suite probing concurrent resets, mid-episode restarts, and SLA bleed edge cases
- **114 tests passing** — unit, integration, property-based (Hypothesis), and WebSocket lifecycle

### Hybrid Reward Function — Shock + Bleed Model

All mutations apply to a `survival_score` initialised at `1.0`, clamped to `[0.0, 1.0]` after every step:

| Event | Score Delta | Notes |
|---|---|---|
| Correct `block_ip` | **+0.20** | Episode ends immediately, `done=True` |
| Incorrect `block_ip` | **−0.10** | Instant shock; outage created, bleed starts |
| Active outage (per tick) | **−tier_penalty × tick_cost** | Persists until `resolve_outage` is called |
| `resolve_outage` | 0.00 | Stops bleed; no score recovery |
| `query_dpi` / `wait` | 0.00 | No direct score change; tick cost still consumed |
| Tick > 60 (timeout) | **−1.00** | Terminal failure — data exfiltrated |

```python
# From soc_grader.py — exact implementation
def _clamp(score: float) -> float:
    return round(max(0.0, min(1.0, score)), 8)
```

---

## Task Difficulties

Four task configurations covering the full difficulty spectrum — all validated to produce scores in `[0.0, 1.0]`:

| Task | Decoys | Penalty Rate | Max Steps | Time Budget (R/L/E) |
|---|---|---|---|---|
| `easy.yaml` | 2 | 0.05 / tick | 100 | 30 / 25 / 20 |
| `medium.yaml` | 4 | 0.10 / tick | 85 | 25 / 20 / 15 |
| `hard.yaml` | 4 | 0.10 / tick | 75 | 20 / 15 / 12 |
| `expert.yaml` | 6 | 0.20 / tick | 60 | 15 / 12 / 10 |

Expert mode: 6 decoys, 4× the penalty rate of easy, and a tick budget that matches the hard deadline — no margin for error.

---

## Integration Specification

### MCP (Model Context Protocol) — JSON-RPC 2.0

The environment exposes a full MCP tool surface for LLM agents. Compliant with the OpenEnv validator's `tools/list` discovery requirement:

```bash
curl -X POST http://localhost:7860/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

| Tool | Cost | Effect |
|---|---|---|
| `query_dpi` | 5 ticks | Reveals payload for a target IP |
| `block_ip` | 3 ticks | Blocks IP — correct ends episode, wrong starts bleed |
| `resolve_outage` | 3 ticks | Stops SLA bleed for a wrongly blocked IP |
| `wait` | 1 tick | Observe without acting |

### API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/reset` | POST | Start a new episode `{"seed": 42, "session_id": "..."}` |
| `/step` | POST | Submit an action |
| `/state` | GET | Read current observation |
| `/mcp` | POST | JSON-RPC 2.0 tool discovery |
| `/schema` | GET | Pydantic-validated Action / Observation schemas |
| `/health` | GET | Liveness probe — returns `{"status": "healthy"}` |
| `/metadata` | GET | Environment name, version, tasks |
| `/web` | GET | Interactive SIEM dashboard |
| `/docs` | GET | Swagger UI |

### Action / Observation Schema

```json
// Action
{
  "action_type": "block_ip | query_dpi | resolve_outage | wait",
  "target_ip": "10.0.0.5",
  "session_id": "agent-run-1"
}

// Observation
{
  "stage": "Recon | Lateral_Movement | Exfiltration",
  "tick": 12,
  "survival_score": 0.85,
  "done": false,
  "dpi_data": { "entries": [...], "attacker_ip": "10.0.0.5" },
  "alerts": [{ "tick": 10, "severity": "critical", "message": "..." }]
}
```

---

## Quick Start

```bash
# Install and run
pip install -r requirements.txt
uvicorn app.app:app --host 0.0.0.0 --port 7860

# Random policy baseline (determinism audit)
python inference.py --url http://localhost:7860 --seed 42
# → Mode: random policy
# → Final Survival Score: 0.2000

# LLM policy (OpenAI-compatible — set env vars first)
export API_BASE_URL=https://your-hf-space.hf.space
export MODEL_NAME=meta-llama/Llama-3-70b-instruct
export HF_TOKEN=hf_...
python inference.py --url http://localhost:7860 --seed 42

# Docker
docker build -t soc-trilemma .
docker run -p 7860:7860 soc-trilemma

# Validate
openenv validate .
openenv validate --url http://localhost:7860
```

---

## Environment Variables

Required by the OpenEnv validator — injected at runtime:

| Variable | Description |
|---|---|
| `API_BASE_URL` | API endpoint for the LLM (e.g. your HF Space URL) |
| `MODEL_NAME` | Model identifier (e.g. `meta-llama/Llama-3-70b-instruct`) |
| `HF_TOKEN` | Hugging Face API key |

`inference.py` auto-detects: if all three are set it uses the OpenAI client; otherwise falls back to the seeded random policy for determinism validation.

---

## Verification

```
openenv validate .                            → [OK] 6/6 criteria passed
openenv validate --url http://localhost:7860  → passed: true
pytest tests/ -q                              → 114 passed
python pre_submit_check.py                    → [VERDICT]: ENVIRONMENT LOCKED
Deterministic Replay Audit (3 runs)           → seeds 1, 7, 42, 99 identical across all runs
```

---

## Project Structure

```
app/
  app.py             FastAPI server — HTTP, WebSocket, MCP, SIEM dashboard
  session_manager.py Episode state, pivot logic, tier assignment, asyncio.Lock
  soc_grader.py      Tiered SLA penalties and hybrid reward function
  models.py          Pydantic v2 Action / Observation models
  kill_chain.py      3-stage FSM (Recon → Lateral → Exfil)
  seed_engine.py     Deterministic role assignment
  config.py          Task YAML loader and validator
  dpi_loader.py      DPI template loader per stage

tasks/
  easy.yaml          2 decoys, 0.05 penalty rate, 100 max steps
  medium.yaml        4 decoys, 0.10 penalty rate, 85 max steps
  hard.yaml          4 decoys, 0.10 penalty rate, 75 max steps
  expert.yaml        6 decoys, 0.20 penalty rate, 60 max steps

tests/
  unit/              Component-level tests (kill chain, grader, session, seed)
  integration/       Full HTTP + WebSocket episode lifecycle
  property/          25 Hypothesis correctness properties
  adversarial_suite  Concurrent load, race condition, and bleed edge cases

data/
  dpi_recon.json           DPI templates for Recon stage
  dpi_lateral_movement.json DPI templates for Lateral Movement stage
  dpi_exfiltration.json    DPI templates for Exfiltration stage

server/app.py        uvicorn entry point
inference.py         Dual-mode agent: OpenAI client (LLM) or seeded random policy
openenv.yaml         OpenEnv manifest — name, version, 4 tasks, scoring config
Dockerfile           UID 1000, HEALTHCHECK, port 7860, HF Spaces ready
```

---

## Submission Statement

SOC Trilemma Benchmark codifies **business risk into the reward function**. It tests not just whether an agent can stop an attack, but whether it can do so without breaking the company. The three interlocking mechanics — tiered asset valuation, adversarial pivoting, and forensic masking — create an irreducible tension that bridges the gap between cybersecurity operations and AI research.

Validated for 100% numerical determinism and MCP compliance. Baseline agent (Seed 42) scores 0.2000, confirming non-trivial adversarial mechanics.

*Built for the Meta PyTorch Foundation OpenEnv Hackathon 2026.*
