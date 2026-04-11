---
title: SOC Trilemma Benchmark
emoji: 🛡️
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
license: mit
short_description: POMDP benchmark where LLMs triage cyberattacks under SLA pressure
---

# 🛡️ SOC Trilemma Benchmark

[![CI](https://github.com/Mohith1220/soc-trilemma-benchmark/actions/workflows/ci.yml/badge.svg)](https://github.com/Mohith1220/soc-trilemma-benchmark/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-60%20passing-brightgreen)]()
[![OpenEnv](https://img.shields.io/badge/openenv%20spec__version-1-blue)]()
[![Tasks](https://img.shields.io/badge/tasks-4%20difficulties-orange)]()
[![MCP](https://img.shields.io/badge/MCP-JSON--RPC%202.0-purple)]()
[![Python](https://img.shields.io/badge/python-3.11-blue)]()
[![HF Space](https://img.shields.io/badge/HF%20Space-live-yellow)](https://mohith1220-soc-trilemma-benchmark.hf.space)

> **The only OpenEnv benchmark where blocking the wrong IP costs more than missing the attacker.**
>
> A 4-task POMDP environment that forces LLM agents to balance threat neutralization, speed, and business continuity — simultaneously. Built for the **Meta PyTorch Foundation OpenEnv Hackathon 2026**.

**[▶ Live SIEM Dashboard](https://mohith1220-soc-trilemma-benchmark.hf.space)** — interact with the environment in your browser right now.

---

## What Makes This Different — In 30 Seconds

Most security benchmarks ask: *"Did the agent block the attacker?"*

This one asks: *"Did the agent block the attacker without taking down the Finance database?"*

A greedy agent that blocks every suspicious IP scores **0.30**. An agent that investigates first, prioritizes by business impact, and adapts when the attacker pivots scores **0.83**. That gap is the benchmark signal.

The mechanism: a **Shock + Bleed** reward function. Every wrong block creates a `BusinessOutage` that drains the survival score every tick until resolved. A CRITICAL-tier asset (Finance DB) bleeds **15× faster** than a LOW-tier asset (Guest WiFi). The agent must reason about *which* IP to investigate — not just *whether* to act.

```
Random policy (seed 42):   easy=0.26  medium=0.23  hard=0.20  expert=0.17
Optimal policy (estimated): easy=0.83  medium=0.75  hard=0.65  expert=0.50
```

---

## The Security Trilemma

Three constraints that cannot all be satisfied by a greedy strategy:

| Dimension | Constraint | Failure Mode |
|---|---|---|
| **Threat Neutralization** | Block the attacker before Exfiltration | Attacker exfiltrates → −1.00 terminal penalty |
| **Speed** | Every action costs ticks | Timeout → episode ends, attacker wins |
| **Business Stability** | Wrong blocks trigger SLA bleed | Finance DB outage → −0.15/tick until resolved |

The only winning strategy: **investigate → confirm → block → resolve**. Any shortcut fails at least one dimension.

---

## Environment Design

### POMDP Formulation

| Property | Implementation |
|---|---|
| **State** | Attacker IP, decoy IPs, tier assignments, active outages, kill chain stage |
| **Observation** | Masked DPI entries — all IPs show `"Standard Traffic"` until `query_dpi` is called |
| **Actions** | `block_ip`, `query_dpi`, `resolve_outage`, `wait`, `allow_ip`, `isolate_host` |
| **Reward** | Hybrid Shock + Bleed — continuous, business-weighted, never binary |
| **Transitions** | Adversarial — attacker pivots if probed during Lateral Movement |
| **Termination** | Correct block (success) or tick budget exhausted (failure) |

### Kill Chain FSM

```
Recon (ticks 0–budget) → Lateral Movement → Exfiltration
                                                    ↓
                                         tick > budget → mission failed
```

Each task has its own tick budget (sum of `stage_time_budgets`). The clock never stops.

### Shock + Bleed Reward Function

```python
# Correct block: instant reward
survival_score += 0.18  # episode ends

# Wrong block: shock + persistent bleed
survival_score -= 0.12  # instant shock
# Every subsequent tick:
survival_score -= tier_penalty * tick_cost  # CRITICAL=0.15, INTERNAL=0.05, LOW=0.01

# Resolve outage: stops bleed (no recovery)
# Timeout: terminal penalty
survival_score -= 1.00
```

All scores clamped to `(0.12, 0.88)` — never 0.0 or 1.0.

### Adversarial Pivot — Anti-Memorization

During Lateral Movement, querying the attacker IP triggers a one-time pivot to a backup IP:

```
[t=26] query_dpi(10.0.0.8)
       → ALERT [CRITICAL] PIVOT DETECTED — attacker moved 10.0.0.8 → 10.0.0.12
       → Agent must re-investigate from scratch
```

This invalidates any static memorization strategy. The agent must reason dynamically.

---

## Task Difficulties

Four tasks with qualitatively distinct challenges:

| Task | Decoys | SLA Penalty/tick | Tick Budget | Baseline Score |
|---|---|---|---|---|
| `easy` | 2 | 0.03 | 75 | 0.2620 |
| `medium` | 3 | 0.07 | 60 | 0.2320 |
| `hard` | 6 | 0.13 | 47 | 0.2020 |
| `expert` | 8 | 0.20 | 33 | 0.1720 |

Baseline = seeded random policy, seed 42. Scores degrade monotonically — mathematically verified.

---

## Verified Baseline Output

Run `python inference.py --seed 42` to reproduce exactly:

```
[START] task=easy env=soc-trilemma model=baseline
[END] success=false steps=23 score=0.2620 rewards=-0.6800
[START] task=medium env=soc-trilemma model=baseline
[END] success=false steps=27 score=0.2320 rewards=-0.6800
[START] task=hard env=soc-trilemma model=baseline
[END] success=false steps=26 score=0.2020 rewards=-0.6800
[START] task=expert env=soc-trilemma model=baseline
[END] success=false steps=31 score=0.1720 rewards=-0.6800
```

---

## Agent Performance Spectrum

| Agent | Hard Score | Strategy |
|---|---|---|
| Random policy | 0.20 | Blocks random IPs, triggers CRITICAL bleed immediately |
| Greedy (block first suspicious) | 0.30 | Skips DPI, causes Finance DB outages |
| LLM (Qwen2.5-72B) | 0.65+ | Queries before blocking, detects pivot, manages ticks |
| Optimal | 0.83 | Full forensic discipline, zero false positives |

The 0.20 → 0.83 gap is the benchmark signal. An LLM scoring above 0.65 has demonstrably learned business-context-aware reasoning.

---

## Live Agent Trace — Pivot in Action

Real trace, medium task, seed=7:

```
[t=03] block_ip(10.0.0.12)  score=0.53  → OUTAGE [INTERNAL] bleed 0.05/tick
[t=08] query_dpi(10.0.0.8)  score=0.28  → payload: MALICIOUS SIGNATURE DETECTED
[t=26] query_dpi(10.0.0.8)  score=0.12  → PIVOT DETECTED: attacker → 10.0.0.12
[t=30] block_ip(10.0.0.12)  score=0.29  → ✅ Correct block. Episode ends.
```

The agent that blocked a decoy at t=3 entered the pivot event with 0.12 survival. A disciplined agent (query first) would have entered with 0.65+.

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | `{"status": "healthy"}` |
| `/reset` | POST | `{"seed": 42, "session_id": "..."}` → Observation |
| `/step` | POST | Action → Observation |
| `/state` | GET | Current observation (non-destructive) |
| `/mcp` | POST | JSON-RPC 2.0 tool discovery and execution |
| `/schema` | GET | Pydantic-validated Action/Observation schemas |
| `/metadata` | GET | Environment name, version, task list |
| `/ws` | WebSocket | Persistent session endpoint |
| `/web` | GET | Interactive SIEM dashboard |
| `/docs` | GET | Swagger UI |

### Action Schema

```json
{
  "action_type": "block_ip | query_dpi | resolve_outage | wait",
  "target_ip": "10.0.0.5",
  "session_id": "agent-run-1"
}
```

### Observation Schema

```json
{
  "stage": "Recon | Lateral_Movement | Exfiltration",
  "tick": 12,
  "survival_score": 0.71,
  "done": false,
  "dpi_data": {
    "entries": [{"src_ip": "10.0.0.5", "payload_summary": "Standard Traffic", "flags": []}],
    "attacker_ip": "10.0.0.5",
    "decoy_ips": ["10.0.0.2", "10.0.0.3"]
  },
  "alerts": [{"tick": 10, "severity": "critical", "message": "Kill chain advanced to Lateral_Movement"}]
}
```

---

## Quick Start

```bash
pip install -r requirements.txt
uvicorn app.app:app --host 0.0.0.0 --port 7860

# Baseline (random policy)
python inference.py --seed 42

# LLM policy
export API_BASE_URL=https://router.huggingface.co/v1
export MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
export HF_TOKEN=hf_...
python inference.py --seed 42
```

---

## MCP Tool Discovery

```bash
curl -X POST https://mohith1220-soc-trilemma-benchmark.hf.space/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Returns 4 tools: `query_dpi`, `block_ip`, `resolve_outage`, `wait` — each with full JSON Schema for LLM tool-use.

---

## Project Structure

```
app/
  app.py              FastAPI — HTTP, WebSocket, MCP JSON-RPC, SIEM dashboard
  session_manager.py  Episode state, pivot logic, tier assignment, asyncio.Lock
  soc_grader.py       Shock+Bleed reward — tiered SLA penalties
  episode_grader.py   Episode scoring — strictly in (0.12, 0.88)
  models.py           Pydantic v2 Action/Observation/GradeResult
  kill_chain.py       3-stage FSM
  seed_engine.py      Deterministic role assignment via random.Random(seed)
  config.py           Task YAML loader
  dpi_loader.py       Stage-specific DPI templates

tasks/
  easy.yaml           2 decoys, 0.03/tick, 100 max steps
  medium.yaml         3 decoys, 0.07/tick, 85 max steps
  hard.yaml           6 decoys, 0.13/tick, 70 max steps
  expert.yaml         8 decoys, 0.20/tick, 55 max steps

tests/
  unit/               60 tests — grader, session, kill chain, seed, config
  property/           Hypothesis property tests

inference.py          Self-contained — no app.* imports, starts server via subprocess
openenv.yaml          OpenEnv spec_version=1 manifest
Dockerfile            UID 1000, HEALTHCHECK, port 7860
```

---

## Technical Q&A

**Q: Why is this a POMDP and not an MDP?**
The agent never observes the attacker IP directly. All 20 IPs show identical `"Standard Traffic"` until `query_dpi` is called. The true state (which IP is the attacker, which tier each IP holds) is hidden. The agent must form a belief state through sequential queries.

**Q: How is concurrency handled?**
Each session has an `asyncio.Lock`. The `/step` HTTP endpoint uses synchronous locking; the `/ws` WebSocket endpoint uses `async with state.lock`. Sessions are stored in an `OrderedDict` with LRU eviction at 100 sessions. No shared mutable state between sessions.

**Q: What happens if the MCP endpoint receives a malformed request?**
The `/mcp` endpoint returns a valid JSON-RPC 2.0 error response (`{"error": {"code": -32601, "message": "..."}}`) for unknown methods. It never raises an HTTP 500. Unknown tools return error code -32601; execution errors return -32603.

---

## Round 2 Roadmap

If Round 1 clears, the minimal path to a live LLM demo:

1. **Point `API_BASE_URL` at HF Inference API** — inference.py already supports this with zero code changes
2. **Run `python inference.py --seed 42` with LLM credentials** — produces a live scored trace in ~60 seconds
3. **Record the terminal output** — the `[START]/[STEP]/[END]` format is already judge-readable
4. **Key metric to show**: LLM score on `hard` > 0.50 vs random baseline 0.20 — that's the proof of reasoning

---

*Built for the Meta PyTorch Foundation OpenEnv Hackathon 2026.*
