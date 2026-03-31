"""PrettyPrinter: serializes DPITemplate to JSON and Observation to HTML."""
from __future__ import annotations

from app.models import DPITemplate, Observation

_MALICIOUS = "MALICIOUS SIGNATURE DETECTED"


class PrettyPrinter:
    def dpi_template_to_json(self, template: DPITemplate) -> str:
        return template.model_dump_json(indent=2)

    def observation_to_html(self, obs: Observation) -> str:
        """Render a TailwindCSS SIEM dashboard. Malicious payloads are highlighted in red."""
        alerts_html = "".join(
            f'<li class="text-sm text-yellow-300">[{a.severity.upper()}] tick={a.tick} — {a.message}</li>'
            for a in obs.alerts
        ) or '<li class="text-sm text-gray-500">No alerts</li>'

        rows = ""
        for entry in obs.dpi_data.entries:
            is_malicious = entry.payload_summary == _MALICIOUS
            row_class = "bg-red-900 text-red-200" if is_malicious else "text-gray-300"
            flag_str = ", ".join(entry.flags) if entry.flags else "—"
            rows += (
                f'<tr class="{row_class}">'
                f'<td class="px-2 py-1 font-mono">{entry.src_ip}</td>'
                f'<td class="px-2 py-1">{entry.protocol}</td>'
                f'<td class="px-2 py-1">{entry.payload_summary}</td>'
                f'<td class="px-2 py-1 text-xs text-gray-500">{flag_str}</td>'
                f'</tr>'
            )

        stage_colors = {
            "Recon": "text-blue-400",
            "Lateral_Movement": "text-yellow-400",
            "Exfiltration": "text-red-400",
        }
        stage_color = stage_colors.get(obs.stage.value, "text-white")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>SOC Trilemma — SIEM Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-950 text-white p-6 font-mono">
  <div class="max-w-3xl mx-auto space-y-4">
    <h1 class="text-2xl font-bold">SOC Trilemma — SIEM Dashboard</h1>

    <div class="grid grid-cols-4 gap-3">
      <div class="bg-gray-800 rounded p-3">
        <div class="text-xs text-gray-400">Stage</div>
        <div class="text-lg font-bold {stage_color}">{obs.stage.value}</div>
      </div>
      <div class="bg-gray-800 rounded p-3">
        <div class="text-xs text-gray-400">Tick</div>
        <div class="text-lg font-bold">{obs.tick} / 60</div>
      </div>
      <div class="bg-gray-800 rounded p-3">
        <div class="text-xs text-gray-400">Survival Score</div>
        <div class="text-lg font-bold text-green-400" data-score="{obs.survival_score}">{obs.survival_score:.4f}</div>
      </div>
      <div class="bg-gray-800 rounded p-3">
        <div class="text-xs text-gray-400">Done</div>
        <div class="text-lg font-bold">{obs.done}</div>
      </div>
    </div>

    <div class="bg-gray-800 rounded p-4">
      <h2 class="font-semibold mb-2 text-gray-300">DPI Log
        <span class="text-xs text-gray-500 ml-2">(use query_dpi to reveal payloads)</span>
      </h2>
      <table class="w-full text-sm">
        <thead><tr class="text-gray-500 text-xs">
          <th class="px-2 py-1 text-left">Source IP</th>
          <th class="px-2 py-1 text-left">Protocol</th>
          <th class="px-2 py-1 text-left">Payload</th>
          <th class="px-2 py-1 text-left">Flags</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>

    <div class="bg-gray-800 rounded p-4">
      <h2 class="font-semibold mb-2 text-gray-300">Alerts</h2>
      <ul class="space-y-1">{alerts_html}</ul>
    </div>
  </div>
</body>
</html>"""

    render_dashboard = observation_to_html
