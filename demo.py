"""Forty alerts in, one incident out.

    python demo.py

Builds a realistic alert storm -- one bad deploy that cascades across three
services -- and runs the real correlator over it. No network, no model.
"""

import random
import sys

sys.path.insert(0, "src")

from copilot.correlate.incident import ChangeEvent, Signal, correlate

T = 1_726_500_000.0  # a fixed wall-clock second, so the output is reproducible

# One deploy, then the blast radius: checkout errors, then the two services behind it.
CASCADE = [
    ("checkout", "metric", "error_rate 0.4% -> 11.2%", 9.4, 60),
    ("checkout", "log", "NullPointerException in PaymentClient", 6.1, 62),
    ("checkout", "metric", "p99 latency 180ms -> 4200ms", 7.8, 75),
    ("payments", "metric", "connection_pool_exhausted", 8.2, 90),
    ("payments", "log", "timeout awaiting connection", 5.5, 95),
    ("ledger", "metric", "write_queue_depth 12 -> 3100", 6.9, 120),
]

signals = []
for service, kind, detail, score, offset in CASCADE:
    signals.append(Signal(at=T + offset, service=service, kind=kind, detail=detail, score=score))

# Thirty-four more that are ordinary background noise. Spacing matters: correlation is
# transitive within window_seconds, so a drip steadier than the window would chain into
# one incident no matter which services it touched. Real background noise is sparser and
# irregular, so this uses a fixed-seed jitter well beyond the 300s window.
rng = random.Random(7)
noise_at = T - 36_000
for i in range(34):
    noise_at += rng.uniform(600, 1400)
    signals.append(
        Signal(
            at=noise_at,
            service=["search", "email", "cdn", "auth"][i % 4],
            kind="metric" if i % 2 else "log",
            detail=f"routine fluctuation #{i}",
            score=2.1 + (i % 5) * 0.2,
        )
    )

changes = [
    ChangeEvent(at=T + 30, kind="deploy", description="checkout v4.12.0", service="checkout"),
    ChangeEvent(at=T - 5400, kind="config", description="cdn cache ttl 300->600", service="cdn"),
]

print("INPUT")
print(f"   {len(signals)} alerts across {len({s.service for s in signals})} services")
print(f"   {len(changes)} change events in the lookback window")
print()

incidents = correlate(signals, changes)

grouped = [i for i in incidents if len(i.signals) > 1]
singletons = [i for i in incidents if len(i.signals) == 1]

print("OUTPUT")
print(
    f"   {len(signals)} alerts -> {len(grouped)} correlated incident, "
    f"{len(singletons)} unrelated singletons"
)
print()
for inc in sorted(grouped, key=lambda i: -len(i.signals)):
    print(
        f"   severity={inc.severity}   {len(inc.signals)} alerts   "
        f"services={', '.join(inc.services)}"
    )
    for s in sorted(inc.signals, key=lambda x: x.at):
        print(f"      +{int(s.at - T):>4}s  {s.service:9} {s.kind:6} {s.detail}")
    for c in inc.causes:
        print(f"      SUSPECT   {c.kind}: {c.description}  ({int(c.at - T):+d}s)")
    print()
print(f"   The other {len(singletons)} alerts stayed separate. They are background noise,")
print("   and nothing in the correlator was told which was which.")
