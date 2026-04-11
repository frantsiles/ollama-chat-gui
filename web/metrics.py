"""Métricas ligeras de rendimiento para el agente (en memoria).

No requiere dependencias externas. Guarda las últimas 200 solicitudes
en un deque y expone un resumen agregado vía MetricsCollector.summary().
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List


@dataclass
class RequestMetric:
    """Métrica de una solicitud individual."""

    session_id: str
    mode: str
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    steps: int = 0
    prompt_chars: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    status: str = "running"  # running | completed | cancelled | awaiting_approval | error | max_steps

    # ------------------------------------------------------------------ helpers

    @property
    def duration_ms(self) -> float:
        """Duración en ms (usa tiempo actual si todavía está en ejecución)."""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def finish(self, status: str) -> None:
        self.end_time = time.time()
        self.status = status


class MetricsCollector:
    """
    Colector global de métricas (últimas 200 solicitudes).

    Uso típico:
        metric = MetricsCollector.start(session_id, mode)
        metric.prompt_chars = len(content)
        # ... al terminar ...
        metric.finish(response.status)
    """

    _metrics: Deque[RequestMetric] = deque(maxlen=200)

    @classmethod
    def start(cls, session_id: str, mode: str) -> RequestMetric:
        """Registra el inicio de una solicitud y devuelve su métrica."""
        m = RequestMetric(session_id=session_id, mode=mode)
        cls._metrics.append(m)
        return m

    @classmethod
    def summary(cls) -> Dict[str, Any]:
        """Devuelve un resumen agregado de las métricas registradas."""
        all_m: List[RequestMetric] = list(cls._metrics)
        running = [m for m in all_m if m.status == "running"]
        done = [m for m in all_m if m.status != "running"]

        if not done:
            return {
                "total_requests": 0,
                "running": len(running),
            }

        durations = [m.duration_ms for m in done]
        n = len(done)

        return {
            "total_requests": n,
            "running": len(running),
            "avg_duration_ms": round(sum(durations) / n, 1),
            "max_duration_ms": round(max(durations), 1),
            "min_duration_ms": round(min(durations), 1),
            "error_rate": round(
                sum(1 for m in done if m.status == "error") / n, 3
            ),
            "cancellation_rate": round(
                sum(1 for m in done if m.status == "cancelled") / n, 3
            ),
            "by_mode": {
                mode: sum(1 for m in done if m.mode == mode)
                for mode in ("chat", "agent", "plan")
            },
            "avg_steps_agent": round(
                sum(m.steps for m in done if m.mode == "agent")
                / max(1, sum(1 for m in done if m.mode == "agent")),
                1,
            ),
            "avg_prompt_chars": round(sum(m.prompt_chars for m in done) / n),
            "recent": [
                {
                    "session_id": m.session_id[:8],
                    "mode": m.mode,
                    "status": m.status,
                    "duration_ms": round(m.duration_ms, 1),
                    "steps": m.steps,
                }
                for m in list(reversed(done))[:10]  # últimas 10
            ],
        }
