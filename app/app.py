"""FastAPI application for OpenEnv SOC Trilemma."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import load_task_config
from app.dpi_loader import load_dpi_template
from app.models import Action, KillChainStage, Observation, ResetRequest
from app.session_manager import SessionManager


def create_app(task_config_path: str = "tasks/easy.yaml") -> FastAPI:
    """Factory function that creates and configures the FastAPI application."""
    task_config = load_task_config(task_config_path)
    for stage in KillChainStage:
        load_dpi_template(stage)

    session_manager = SessionManager(task_config=task_config)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        yield

    application = FastAPI(
        title="OpenEnv SOC Trilemma",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # OpenEnv runtime compliance endpoints
    # ------------------------------------------------------------------

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @application.get("/metadata")
    def metadata() -> dict[str, Any]:
        return {
            "name": "soc-trilemma",
            "description": (
                "A 3-stage Cyber Kill Chain RL environment where an agent acts as a "
                "SOC analyst triaging DPI alerts under SLA pressure."
            ),
            "version": "1.0.0",
            "tasks": ["easy", "hard"],
        }

    @application.get("/schema")
    def schema() -> dict[str, Any]:
        return {
            "action": Action.model_json_schema(),
            "observation": Observation.model_json_schema(),
            "state": Observation.model_json_schema(),
        }

    @application.post("/mcp")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        """JSON-RPC 2.0 MCP endpoint — exposes SOC tools for LLM agents."""
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            body = {}

        method = body.get("method", "")
        req_id = body.get("id", 1)

        if method == "tools/list":
            tools = [
                {
                    "name": "block_ip",
                    "description": (
                        "Block a suspicious IP (cost: 3 ticks). Correct block ends the episode "
                        "with a reward. Incorrect block creates a Business Outage — survival score "
                        "bleeds -0.05 every tick until resolved."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "target_ip": {"type": "string", "description": "IPv4 address to block"},
                            "session_id": {"type": "string", "description": "Active session ID"},
                        },
                        "required": ["target_ip", "session_id"],
                    },
                },
                {
                    "name": "query_dpi",
                    "description": (
                        "Reveal the DPI payload for a target IP (cost: 5 ticks). "
                        "Masked IPs show 'Standard Traffic'. After querying, the attacker IP "
                        "shows 'MALICIOUS SIGNATURE DETECTED'. Use before block_ip to avoid false positives."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "target_ip": {"type": "string", "description": "IPv4 address to inspect"},
                            "session_id": {"type": "string", "description": "Active session ID"},
                        },
                        "required": ["target_ip", "session_id"],
                    },
                },
                {
                    "name": "resolve_outage",
                    "description": (
                        "Resolve an active Business Outage (cost: 3 ticks). "
                        "Stops the SLA penalty bleed for the targeted IP."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "target_ip": {"type": "string", "description": "IPv4 address whose outage to resolve"},
                            "session_id": {"type": "string", "description": "Active session ID"},
                        },
                        "required": ["target_ip", "session_id"],
                    },
                },
                {
                    "name": "wait",
                    "description": "Do nothing for 1 tick. Useful for observing SLA bleed rate.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "target_ip": {"type": "string", "description": "Any IP (ignored)"},
                            "session_id": {"type": "string", "description": "Active session ID"},
                        },
                        "required": ["target_ip", "session_id"],
                    },
                },
            ]
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})

        if method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name", "")
            args = params.get("arguments", {})
            session_id = args.get("session_id", "default")
            target_ip = args.get("target_ip", "")

            action_map = {
                "block_ip": "block_ip",
                "query_dpi": "query_dpi",
                "resolve_outage": "resolve_outage",
                "wait": "wait",
                "allow_ip": "allow_ip",
            }
            if tool_name not in action_map:
                return JSONResponse({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                })
            try:
                action = Action(
                    action_type=action_map[tool_name],
                    target_ip=target_ip,
                    session_id=session_id,
                )
                obs = session_manager.step(session_id, action)
                return JSONResponse({
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": obs.model_dump_json()}],
                        "isError": False,
                    },
                })
            except HTTPException as exc:
                return JSONResponse({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": exc.status_code, "message": exc.detail},
                })
            except Exception as exc:
                return JSONResponse({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32603, "message": str(exc)},
                })

        # Unknown method — return empty result (still valid JSON-RPC 2.0)
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}})

    def _siem_dashboard_html() -> str:
        return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>SOC Trilemma — SIEM Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    .blinking { animation: blink 1s step-start infinite; }
    @keyframes blink { 50% { opacity: 0; } }
  </style>
</head>
<body class="bg-gray-950 text-white font-mono min-h-screen p-6">
  <div class="max-w-4xl mx-auto space-y-5">

    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-green-400">OpenEnv SOC Trilemma</h1>
        <p class="text-xs text-gray-500 mt-1">Meta PyTorch OpenEnv Hackathon 2026 — Interactive SIEM</p>
      </div>
      <span id="status-dot" class="text-xs text-gray-500">● disconnected</span>
    </div>

    <!-- Controls -->
    <div class="bg-gray-900 rounded-lg p-4 space-y-3">
      <div class="flex gap-3 flex-wrap">
        <div class="flex gap-2 items-center">
          <label class="text-xs text-gray-400">Seed</label>
          <input id="seed-input" type="number" value="42"
            class="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-24 text-white"/>
        </div>
        <button onclick="doReset()"
          class="bg-green-700 hover:bg-green-600 text-white text-sm px-4 py-1 rounded">
          ▶ Reset Episode
        </button>
        <button onclick="doStep('wait')"
          class="bg-gray-700 hover:bg-gray-600 text-sm px-3 py-1 rounded">Wait (1t)</button>
      </div>

      <!-- Action row -->
      <div class="flex gap-2 flex-wrap items-center">
        <input id="target-ip" type="text" placeholder="Target IP (e.g. 10.0.0.5)"
          class="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm w-44 text-white"/>
        <button onclick="doStep('query_dpi')"
          class="bg-blue-700 hover:bg-blue-600 text-sm px-3 py-1 rounded">Query DPI (5t)</button>
        <button onclick="doStep('block_ip')"
          class="bg-red-700 hover:bg-red-600 text-sm px-3 py-1 rounded">Block IP (3t)</button>
        <button onclick="doStep('resolve_outage')"
          class="bg-yellow-700 hover:bg-yellow-600 text-sm px-3 py-1 rounded">Resolve Outage (3t)</button>
      </div>
    </div>

    <!-- Stats bar -->
    <div class="grid grid-cols-4 gap-3" id="stats-bar">
      <div class="bg-gray-900 rounded p-3">
        <div class="text-xs text-gray-500">Stage</div>
        <div id="stat-stage" class="text-lg font-bold text-blue-400">—</div>
      </div>
      <div class="bg-gray-900 rounded p-3">
        <div class="text-xs text-gray-500">Tick</div>
        <div id="stat-tick" class="text-lg font-bold">— / 60</div>
      </div>
      <div class="bg-gray-900 rounded p-3">
        <div class="text-xs text-gray-500">Survival Score</div>
        <div id="stat-score" class="text-lg font-bold text-green-400">—</div>
      </div>
      <div class="bg-gray-900 rounded p-3">
        <div class="text-xs text-gray-500">Done</div>
        <div id="stat-done" class="text-lg font-bold">—</div>
      </div>
    </div>

    <!-- DPI Log -->
    <div class="bg-gray-900 rounded-lg p-4">
      <h2 class="text-sm font-semibold text-gray-300 mb-2">
        DPI Log
        <span class="text-xs text-gray-600 ml-2">— use Query DPI to reveal payloads</span>
      </h2>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="text-gray-600 border-b border-gray-800">
              <th class="text-left px-2 py-1">Source IP</th>
              <th class="text-left px-2 py-1">Protocol</th>
              <th class="text-left px-2 py-1">Payload</th>
              <th class="text-left px-2 py-1">Flags</th>
            </tr>
          </thead>
          <tbody id="dpi-table"></tbody>
        </table>
      </div>
    </div>

    <!-- Alerts -->
    <div class="bg-gray-900 rounded-lg p-4">
      <h2 class="text-sm font-semibold text-gray-300 mb-2">Alert Feed</h2>
      <ul id="alert-list" class="space-y-1 text-xs max-h-48 overflow-y-auto"></ul>
    </div>

    <!-- API quick-ref -->
    <div class="bg-gray-900 rounded-lg p-4 text-xs text-gray-500 grid grid-cols-2 gap-1">
      <span>POST <span class="text-green-500">/reset</span> — new episode</span>
      <span>POST <span class="text-green-500">/step</span> — submit action</span>
      <span>POST <span class="text-green-500">/mcp</span> — JSON-RPC 2.0 tools</span>
      <span>GET  <span class="text-green-500">/schema</span> — action/obs schemas</span>
      <span>GET  <span class="text-green-500">/health</span> — liveness probe</span>
      <span>GET  <span class="text-green-500">/docs</span> — Swagger UI</span>
    </div>
  </div>

<script>
const SESSION = "web-dashboard";
let lastObs = null;

function setStatus(msg, color="text-gray-400") {
  const el = document.getElementById("status-dot");
  el.textContent = "● " + msg;
  el.className = "text-xs " + color;
}

function updateUI(obs) {
  lastObs = obs;
  const stageColors = {
    "Recon": "text-blue-400",
    "Lateral_Movement": "text-yellow-400",
    "Exfiltration": "text-red-400"
  };
  document.getElementById("stat-stage").textContent = obs.stage;
  document.getElementById("stat-stage").className = "text-lg font-bold " + (stageColors[obs.stage] || "text-white");
  document.getElementById("stat-tick").textContent = obs.tick + " / 60";
  const score = obs.survival_score.toFixed(4);
  const scoreEl = document.getElementById("stat-score");
  scoreEl.textContent = score;
  scoreEl.className = "text-lg font-bold " + (obs.survival_score > 0.6 ? "text-green-400" : obs.survival_score > 0.3 ? "text-yellow-400" : "text-red-400");
  document.getElementById("stat-done").textContent = obs.done ? "✓ Done" : "Running";
  document.getElementById("stat-done").className = "text-lg font-bold " + (obs.done ? "text-green-400" : "text-gray-300");

  // DPI table
  const tbody = document.getElementById("dpi-table");
  tbody.innerHTML = "";
  for (const e of obs.dpi_data.entries) {
    const isMalicious = e.payload_summary === "MALICIOUS SIGNATURE DETECTED";
    const tr = document.createElement("tr");
    tr.className = isMalicious
      ? "bg-red-950 text-red-300 border-b border-red-900"
      : "border-b border-gray-800 text-gray-300 hover:bg-gray-800 cursor-pointer";
    tr.innerHTML = `
      <td class="px-2 py-1 font-mono">${e.src_ip}</td>
      <td class="px-2 py-1">${e.protocol}</td>
      <td class="px-2 py-1 ${isMalicious ? 'font-bold' : ''}">${e.payload_summary}</td>
      <td class="px-2 py-1 text-gray-600">${e.flags.join(", ") || "—"}</td>`;
    tr.onclick = () => { document.getElementById("target-ip").value = e.src_ip; };
    tbody.appendChild(tr);
  }

  // Alerts (newest first)
  const ul = document.getElementById("alert-list");
  ul.innerHTML = "";
  const alerts = [...obs.alerts].reverse();
  if (alerts.length === 0) {
    ul.innerHTML = '<li class="text-gray-600">No alerts yet</li>';
  }
  for (const a of alerts) {
    const colors = { info: "text-blue-400", warning: "text-yellow-400", critical: "text-red-400" };
    const li = document.createElement("li");
    li.className = colors[a.severity] || "text-gray-400";
    li.textContent = `[t=${a.tick}] [${a.severity.toUpperCase()}] ${a.message}`;
    ul.appendChild(li);
  }
}

async function doReset() {
  const seed = parseInt(document.getElementById("seed-input").value) || 42;
  setStatus("resetting...", "text-yellow-400");
  try {
    const r = await fetch("/reset", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({seed, session_id: SESSION})
    });
    const obs = await r.json();
    updateUI(obs);
    setStatus("connected — seed=" + seed, "text-green-400");
  } catch(e) { setStatus("error: " + e.message, "text-red-400"); }
}

async function doStep(actionType) {
  if (!lastObs) { alert("Reset first"); return; }
  const targetIp = document.getElementById("target-ip").value.trim() || lastObs.dpi_data.attacker_ip;
  setStatus("stepping...", "text-yellow-400");
  try {
    const r = await fetch("/step", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action_type: actionType, target_ip: targetIp, session_id: SESSION})
    });
    const obs = await r.json();
    if (obs.detail) { setStatus("error: " + obs.detail, "text-red-400"); return; }
    updateUI(obs);
    setStatus("tick=" + obs.tick + " score=" + obs.survival_score.toFixed(3), "text-green-400");
  } catch(e) { setStatus("error: " + e.message, "text-red-400"); }
}

// Auto-reset on load
doReset();
</script>
</body>
</html>"""

    @application.get("/", response_class=HTMLResponse)
    def dashboard_root() -> HTMLResponse:
        return HTMLResponse(_siem_dashboard_html())

    @application.get("/web", response_class=HTMLResponse)
    def dashboard_web() -> HTMLResponse:
        """Interactive SIEM dashboard — alias for / (satisfies OpenEnv /web requirement)."""
        return HTMLResponse(_siem_dashboard_html())

    # ------------------------------------------------------------------
    # Core simulation endpoints
    # ------------------------------------------------------------------

    @application.post("/reset", response_model=Observation)
    def reset(request: Optional[ResetRequest] = None) -> Observation:
        if request is None:
            request = ResetRequest(seed=42, session_id="default")
        session_id = request.session_id or "default"
        seed = request.seed if request.seed is not None else 42
        return session_manager.create_or_reset(session_id, seed=seed)

    @application.post("/step", response_model=Observation)
    def step(action: Action) -> Observation:
        try:
            return session_manager.step(action.session_id, action)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @application.get("/state", response_model=Observation)
    def state(session_id: str = Query(...)) -> Observation:
        try:
            return session_manager.get_state(session_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @application.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                session_id = data.get("session_id", "default")

                if msg_type == "reset":
                    seed = data.get("seed")
                    if seed is None or not isinstance(seed, int):
                        await websocket.send_json({"error": "Invalid or missing seed"})
                        await websocket.close()
                        return
                    obs = session_manager.create_or_reset(session_id, seed=seed)
                    await websocket.send_json(obs.model_dump())

                elif msg_type == "step":
                    try:
                        action = Action(
                            action_type=data["action_type"],
                            target_ip=data["target_ip"],
                            session_id=session_id,
                        )
                    except Exception as exc:
                        await websocket.send_json({"error": str(exc)})
                        await websocket.close()
                        return
                    try:
                        obs = await session_manager.async_step(session_id, action)
                    except HTTPException as exc:
                        await websocket.send_json({"error": exc.detail})
                        await websocket.close()
                        return
                    await websocket.send_json(obs.model_dump())
                    if obs.done:
                        await websocket.close()
                        return

                elif msg_type == "state":
                    try:
                        obs = session_manager.get_state(session_id)
                    except HTTPException as exc:
                        await websocket.send_json({"error": exc.detail})
                        await websocket.close()
                        return
                    await websocket.send_json(obs.model_dump())

                else:
                    await websocket.send_json({"error": f"Unknown message type: {msg_type}"})
                    await websocket.close()
                    return

        except WebSocketDisconnect:
            sess = session_manager._sessions.get(session_id)
            if sess is not None:
                sess.suspended_at = time.time()

    return application


# Module-level app instance for uvicorn
app = create_app()
