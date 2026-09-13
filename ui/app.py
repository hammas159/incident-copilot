"""The Streamlit demo the `ui` dependency group declared but never shipped.

Three tabs, one per module: Drain log-template extraction, robust anomaly detection
(a mean/std chart would hide the very spike it's supposed to find), and incident
correlation (many signals across services collapsed into one incident with a named,
checkable cause).

Run: streamlit run ui/app.py
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from copilot.correlate.incident import ChangeEvent, Signal, correlate  # noqa: E402
from copilot.logs.drain import DrainParser  # noqa: E402
from copilot.metrics.anomaly import detect_outliers, detect_seasonal  # noqa: E402

st.set_page_config(page_title="incident-copilot demo", layout="wide")
st.title("incident-copilot")
st.caption(
    "A million log lines, forty simultaneous alarms, reduced to one incident with a suspect."
)

tab_logs, tab_metrics, tab_incident = st.tabs(
    ["Log templates (Drain)", "Anomaly detection", "Incident correlation"]
)

SAMPLE_LOGS = """Connection to db-7 failed after 3021ms
Connection to db-2 failed after 1180ms
Connection to db-9 failed after 902ms
User 8231 logged in from 10.0.0.14
User 4471 logged in from 10.0.0.55
service alpha restarted
service beta restarted
Connection to db-4 failed after 2210ms
Cache miss for key a1b2c3d4-e5f6-7890-abcd-ef1234567890
Cache miss for key 11223344-5566-7788-99aa-bbccddeeff00
Request to /api/v1/orders/1234 took 45ms
Request to /api/v1/orders/5678 took 52ms
Request to /api/v1/orders/9012 took 4821ms
"""

# ---- Tab 1: Drain -----------------------------------------------------------------

with tab_logs:
    st.markdown(
        "Paste raw log lines below. Drain buckets by token count, then compares against "
        "a small number of candidates per bucket — the goal is a few hundred **templates**, "
        "not a million lines nobody can read."
    )
    log_text = st.text_area("Log lines", value=SAMPLE_LOGS, height=220)

    if st.button("Extract templates"):
        parser = DrainParser()
        lines = [line for line in log_text.splitlines() if line.strip()]
        parser.parse(lines)
        templates = parser.templates()
        st.write(f"**{len(lines)} lines &rarr; {len(templates)} templates**")
        for template in templates:
            with st.container(border=True):
                st.code(" ".join(template.tokens), language=None)
                example = template.examples[0]
                st.caption(f"fired {template.count}x &mdash; example: `{example}`")

        st.divider()
        st.subheader("Test an unseen line")
        test_line = st.text_input(
            "New line", value="Connection to db-3 failed after 1500ms", key="test_line"
        )
        if st.button("Match"):
            match = parser.match(test_line)
            if match:
                st.success(f"Matches existing template: `{' '.join(match.tokens)}`")
            else:
                st.warning("No matching template — this shape has never been seen before.")

# ---- Tab 2: anomaly detection -------------------------------------------------------

with tab_metrics:
    st.markdown(
        "A single large spike inflates the mean and standard deviation enough to hide "
        "itself. Robust z-score (median + MAD) is not fooled by the outlier it's looking "
        "for."
    )
    scenario = st.radio(
        "Scenario", ["Latency spike", "Traffic drop (outage)", "Daily seasonal pattern"]
    )

    random.seed(7)
    if scenario == "Latency spike":
        values = [random.gauss(100, 8) for _ in range(48)]
        values[30] = 480.0
        period = None
    elif scenario == "Traffic drop (outage)":
        values = [random.gauss(1000, 50) for _ in range(48)]
        values[30] = 5.0
        period = None
    else:
        values = [
            80 + 40 * (1 if (i % 24) in range(8, 18) else 0) + random.gauss(0, 5) for i in range(72)
        ]
        values[60] = 20.0  # break the pattern once
        period = 24

    threshold = st.slider("z-score threshold", 1.0, 6.0, 3.0, 0.5)
    st.line_chart(values)

    outliers = detect_outliers(values, threshold=threshold, series=scenario)
    st.write(f"**Robust z-score:** {len(outliers)} anomaly(ies) found")
    for a in outliers:
        st.write(
            f"- index {a.index}: value={a.value:.1f}, score={a.score}, direction={a.direction}"
        )

    if period:
        seasonal = detect_seasonal(values, period=period, threshold=threshold, series=scenario)
        st.write(f"**Seasonal comparison (period={period}):** {len(seasonal)} anomaly(ies) found")
        for a in seasonal:
            st.write(
                f"- index {a.index}: value={a.value:.1f}, score={a.score}, direction={a.direction}"
            )

# ---- Tab 3: incident correlation ---------------------------------------------------

with tab_incident:
    st.markdown(
        "One deploy can produce a latency spike, an error-rate spike and forty log "
        "templates firing at once. Correlation groups signals that happened together and "
        "finds a change that preceded them — a lead an operator can check, not a verdict."
    )

    now = time.time()
    if st.button("Simulate a correlated incident", type="primary"):
        deploy = ChangeEvent(
            at=now - 200, kind="deploy", description="checkout-service v2.3.1", service="checkout"
        )
        signals = [
            Signal(at=now, service="checkout", kind="metric", detail="latency p99 high", score=8.2),
            Signal(
                at=now + 10,
                service="checkout",
                kind="log",
                detail="Connection to db-<*> failed after <*>ms",
                score=6.0,
            ),
            Signal(
                at=now + 20, service="payments", kind="metric", detail="error rate high", score=7.1
            ),
            Signal(
                at=now + 3000, service="search", kind="metric", detail="unrelated blip", score=3.5
            ),
        ]
        incidents = correlate(signals, changes=[deploy])
        st.write(f"**{len(signals)} raw signals &rarr; {len(incidents)} incident(s)**")
        for incident in incidents:
            summary = incident.summary()
            severity_color = {"critical": "🔴", "high": "🟠", "medium": "🟡"}[summary["severity"]]
            with st.container(border=True):
                services = ", ".join(summary["services"])
                label = summary["severity"].upper()
                st.write(f"{severity_color} **{label}** — services: {services}")
                causes = ", ".join(summary["causes"]) or "none found in the lookback window"
                st.write(f"Likely cause: {causes}")
                st.write("Top signals:")
                for s in summary["top_signals"]:
                    st.write(f"- {s}")
