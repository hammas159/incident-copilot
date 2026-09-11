"""Turn signals into incidents.

An incident is not an alert. One deploy produces a latency spike, an error-rate spike,
a queue-depth spike and forty log templates firing at once - and paging someone four
times about one event is how alert fatigue starts.

Correlation here is temporal and causal, in that order: group signals that happened
together, then look for a change that preceded them. Both are deliberately simple and
explainable. An operator woken at 3am needs to see *why* the system thinks these things
are related, and a correlation they cannot check is one they will not trust.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..metrics.anomaly import Anomaly


@dataclass
class ChangeEvent:
    """A deploy, config change, feature flag, or scaling action."""

    at: float
    kind: str
    description: str
    service: str = ""


@dataclass
class Signal:
    at: float
    service: str
    kind: str  # "metric" | "log"
    detail: str
    score: float = 0.0


@dataclass
class Incident:
    signals: list[Signal] = field(default_factory=list)
    causes: list[ChangeEvent] = field(default_factory=list)

    @property
    def started_at(self) -> float:
        return min(s.at for s in self.signals) if self.signals else 0.0

    @property
    def services(self) -> list[str]:
        return sorted({s.service for s in self.signals})

    @property
    def severity(self) -> str:
        """From breadth and strength, not from a hand-set label.

        Breadth matters more than strength: one metric at 10 sigma on one service is
        usually that service; three services moving together is usually infrastructure.
        """
        if len(self.services) >= 3:
            return "critical"
        peak = max((s.score for s in self.signals), default=0.0)
        if len(self.services) >= 2 or peak >= 6:
            return "high"
        return "medium"

    def summary(self) -> dict:
        return {
            "started_at": self.started_at,
            "services": self.services,
            "signals": len(self.signals),
            "severity": self.severity,
            "causes": [f"{c.kind}: {c.description}" for c in self.causes],
            "top_signals": [
                f"{s.service}: {s.detail} (score {s.score:.1f})"
                for s in sorted(self.signals, key=lambda s: -s.score)[:5]
            ],
        }


def correlate(
    signals: list[Signal],
    changes: list[ChangeEvent] | None = None,
    *,
    window_seconds: float = 300.0,
    lookback_seconds: float = 1800.0,
) -> list[Incident]:
    """Group signals into incidents and attach the changes that preceded them."""
    if not signals:
        return []

    ordered = sorted(signals, key=lambda s: s.at)
    incidents: list[Incident] = []
    current = Incident(signals=[ordered[0]])

    for signal in ordered[1:]:
        # Gap-based, not fixed-bucket: a fixed window splits one incident in two
        # whenever it happens to straddle a boundary.
        if signal.at - current.signals[-1].at <= window_seconds:
            current.signals.append(signal)
        else:
            incidents.append(current)
            current = Incident(signals=[signal])
    incidents.append(current)

    for incident in incidents:
        start = incident.started_at
        incident.causes = [
            c
            for c in (changes or [])
            # Only changes *before* the onset. A change after it is a response, and
            # presenting it as a cause sends the investigation backwards.
            if start - lookback_seconds <= c.at <= start
            and (not c.service or c.service in incident.services)
        ]
        incident.causes.sort(key=lambda c: -c.at)  # most recent first

    return incidents


def signals_from_anomalies(
    anomalies: list[Anomaly], *, service: str, timestamps: list[float] | None = None
) -> list[Signal]:
    return [
        Signal(
            at=timestamps[a.index] if timestamps and a.index < len(timestamps) else time.time(),
            service=service,
            kind="metric",
            detail=f"{a.series} {a.direction} ({a.detector})",
            score=a.score,
        )
        for a in anomalies
    ]
