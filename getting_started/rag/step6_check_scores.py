"""Step 6: End-to-end metric-calculation smoke test.

    1. Configure - enable the metrics we want to verify on the dev log stream.
    2. Submit    - log a small batch of RAG traces, tagged with a unique run id.
    3. Poll      - fetch those traces via the traces search API
                   (POST /projects/{project_id}/traces/search).
    4. Verify    - confirm Galileo scored every enabled metric within a timeout;
                   print the scores and exit non-zero if it didn't.

This is self-contained: it enables the metrics, submits the data, and verifies
the results without any manual log inspection.

Note on how scores are keyed: Galileo stores LLM-judge metric values on each
trace under the *scorer id* (e.g. "<scorer_id>_multijudge_average"), not the
friendly metric name. So we look up each metric's scorer id first and use that
to read its value. Retriever metrics such as chunk_attribution_utilization are
keyed by name instead (e.g. "chunk_attribution_utilization_gpt_status").

Configuration (optional, via .env - see .env.template):
    GALILEO_METRIC_TIMEOUT_SECONDS        Max wait for metrics       (default 180)
    GALILEO_METRIC_POLL_INTERVAL_SECONDS  Seconds between polls       (default 10)
    GALILEO_SMOKE_TEST_NUM_TRACES         Test traces to submit      (default 3)
    GALILEO_METRIC_MIN_SCORED_TRACES      Scored traces to pass  (default: submitted)
"""

import os
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

from galileo import GalileoLogger
from galileo.log_streams import enable_metrics, get_log_stream
from galileo.projects import get_project
from galileo.schema.metrics import GalileoMetrics
from galileo.scorers import Scorers
from galileo.search import get_traces

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.absolute()
load_dotenv(SCRIPT_DIR.parent.parent / ".env")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"⚠️  {name}='{raw}' is not an int; using default {default}.")
        return default


PROJECT_NAME = os.getenv("GALILEO_PROJECT")
LOG_STREAM_NAME = os.getenv("GALILEO_LOG_STREAM_DEV")

TIMEOUT_SECONDS = _env_int("GALILEO_METRIC_TIMEOUT_SECONDS", 180)
POLL_INTERVAL_SECONDS = _env_int("GALILEO_METRIC_POLL_INTERVAL_SECONDS", 10)
NUM_TRACES = _env_int("GALILEO_SMOKE_TEST_NUM_TRACES", 3)
MIN_SCORED_TRACES = _env_int("GALILEO_METRIC_MIN_SCORED_TRACES", NUM_TRACES)
DEBUG = bool(os.getenv("GALILEO_SMOKE_TEST_DEBUG"))

# Metrics this smoke test enables on the log stream and then verifies.
METRICS = [
    GalileoMetrics.context_adherence,
    GalileoMetrics.context_relevance,
    GalileoMetrics.correctness,
]
EXPECTED_METRICS = [m.value for m in METRICS]

MODEL_ALIAS = "gpt-5"

# Statuses that indicate a metric finished computing (vs. pending / error).
_OK_STATUSES = {"success", "roll_up", "computed", "done"}
# Suffix for LLM-judge scalar values (used with both scorer-id and name keys).
_JUDGE_VALUE_SUFFIX = "_multijudge_average"


# ---------------------------------------------------------------------------
# Metric resolution
# ---------------------------------------------------------------------------
#
# How metric values are keyed on a trace changed across Galileo versions, so we
# probe several patterns instead of hard-coding one:
#
#   - Newer versions key LLM-judge metrics by the metric's *scorer id*, e.g.
#     "<scorer_id>_multijudge_average".
#   - Older versions key them by the friendly *name*, e.g. "context_adherence"
#     or "context_adherence_multijudge_average".
#   - Some metrics expose a status rather than a single scalar.
#
# We look up scorer ids lazily and only if a name-based match fails, so older /
# name-keyed deployments never pay the (slower) scorer-listing call. To see
# exactly how your version keys metrics, run with GALILEO_SMOKE_TEST_DEBUG=1.

_scorer_ids_cache: Optional[dict] = None


def scorer_ids() -> dict:
    """Best-effort {metric_name: scorer_id} map, cached and lazily loaded.

    Returns an empty map (name-based lookup only) if scorer listing is not
    available on this SDK/server version.
    """
    global _scorer_ids_cache
    if _scorer_ids_cache is None:
        try:
            wanted = set(EXPECTED_METRICS)
            _scorer_ids_cache = {
                s.name: str(s.id)
                for s in Scorers().list()
                if getattr(s, "name", None) in wanted
            }
        except Exception as exc:  # noqa: BLE001 - fall back to name-based lookup
            print(f"⚠️  Could not list scorer ids ({exc}); using name-based lookup.")
            _scorer_ids_cache = {}
    return _scorer_ids_cache


def raw_metrics(record) -> dict:
    """The flat metric-name -> value map Galileo attaches to a trace record."""
    metrics = getattr(record, "metrics", None)
    return dict(getattr(metrics, "additional_properties", None) or {})


def _numeric(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def resolve_metric(scores: dict, name: str):
    """Return (computed, value) for one metric on one trace, version-tolerant.

    ``value`` is a float when the metric produces a scalar score, or None when
    it computed but exposes no single scalar (e.g. chunk attribution).
    """
    # 1. Name-based scalar (older versions): "context_adherence" or
    #    "context_adherence_multijudge_average".
    for key in (name, f"{name}{_JUDGE_VALUE_SUFFIX}"):
        v = _numeric(scores.get(key))
        if v is not None:
            return True, float(v)

    # 2. Scorer-id-based scalar (newer versions): "<scorer_id>_multijudge_average".
    sid = scorer_ids().get(name)
    if sid:
        for key in (f"{sid}{_JUDGE_VALUE_SUFFIX}", sid):
            v = _numeric(scores.get(key))
            if v is not None:
                return True, float(v)

    # 3. Computed but no clean scalar: a success status under the name or id
    #    prefix (e.g. "<metric>_gpt_status").
    prefixes = tuple(p for p in (name, sid) if p)
    for key, value in scores.items():
        if key.startswith(prefixes) and key.endswith("_status"):
            if str(value).lower() in _OK_STATUSES:
                return True, None

    return False, None


def trace_results(record) -> dict:
    """Return {metric_name: (computed, value)} for a trace."""
    scores = raw_metrics(record)
    return {name: resolve_metric(scores, name) for name in EXPECTED_METRICS}


def is_fully_scored(record) -> bool:
    return all(computed for computed, _ in trace_results(record).values())


def debug_dump_metric_keys(record) -> None:
    """Print the metric keys on a trace, to reveal how this stack keys metrics."""
    keys = sorted(raw_metrics(record).keys())
    print("\n[debug] metric keys on trace:")
    for key in keys:
        print(f"    {key}")
    print(f"[debug] resolved scorer ids: {scorer_ids()}\n")


def fmt(value) -> str:
    if value is None:
        return "computed"
    return f"{value:.3f}"


# ---------------------------------------------------------------------------
# 2. Submit test data
# ---------------------------------------------------------------------------

def submit_test_traces(run_tag: str) -> int:
    print(f"Submitting {NUM_TRACES} test trace(s) to '{LOG_STREAM_NAME}'...")

    csv_path = SCRIPT_DIR.parent / "data" / "mock_logstream_data.csv"
    rows = pd.read_csv(csv_path).head(NUM_TRACES)

    logger = GalileoLogger(project=PROJECT_NAME, log_stream=LOG_STREAM_NAME)
    logger.start_session(name=f"Metric Smoke Test {run_tag}", external_id=uuid.uuid4().hex)

    for idx, row in rows.iterrows():
        context = [row["chunk1"], row["chunk2"], row["chunk3"]]
        logger.start_trace(
            input=row["user_input_query"],
            name=f"Smoke Test Query {idx + 1}",
            tags=[run_tag, "metric-smoke-test"],
        )
        logger.add_retriever_span(
            input=row["user_input_query"],
            output=context,
            name="Knowledge Base Document Retrieval",
            duration_ns=random.randint(400_000, 500_000),
            status_code=200,
        )
        logger.add_llm_span(
            input=row["user_input_query"] + "\n\nContext Documents: " + ", ".join(context),
            output=row["ai_response"],
            model=MODEL_ALIAS,
            name="LLM Call",
            duration_ns=random.randint(1_000_000, 2_000_000),
            status_code=200,
        )
        logger.conclude(output=row["ai_response"], status_code=200, conclude_all=False)
        logger.clear_session(conclude_all=False)

    logger.flush()
    print(f"✅ Submitted {len(rows)} trace(s) tagged '{run_tag}'.")
    return len(rows)


# ---------------------------------------------------------------------------
# 3 & 4. Poll for metrics and verify within the timeout
# ---------------------------------------------------------------------------

def poll_for_scored_traces(project_id: str, log_stream_id: str, run_tag: str) -> list:
    """Poll the traces search API until our tagged traces are fully scored."""
    print(
        f"\nPolling for metrics (timeout {TIMEOUT_SECONDS}s, "
        f"every {POLL_INTERVAL_SECONDS}s, need >= {MIN_SCORED_TRACES} fully scored)..."
    )

    elapsed = 0
    dumped_debug = False
    while elapsed < TIMEOUT_SECONDS:
        response = get_traces(project_id=project_id, log_stream_id=log_stream_id, limit=100)
        ours = [r for r in (getattr(response, "records", None) or [])
                if run_tag in (getattr(r, "tags", None) or [])]

        # On the first batch that has any metrics, optionally reveal the key
        # shape so version differences are easy to diagnose.
        if DEBUG and not dumped_debug:
            for record in ours:
                if raw_metrics(record):
                    debug_dump_metric_keys(record)
                    dumped_debug = True
                    break

        scored = [r for r in ours if is_fully_scored(r)]

        if len(scored) >= MIN_SCORED_TRACES:
            print(f"✅ {len(scored)}/{len(ours)} trace(s) fully scored after {elapsed}s.")
            return scored

        print(f"   {len(ours)} found, {len(scored)} fully scored... "
              f"({elapsed}s/{TIMEOUT_SECONDS}s)")
        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

    print(f"❌ Timed out: fewer than {MIN_SCORED_TRACES} trace(s) fully scored "
          f"in {TIMEOUT_SECONDS}s.")
    return []


def print_scores(records: list) -> None:
    print("\nScores")
    print("-" * 48)
    totals: dict = {}
    for record in records:
        results = trace_results(record)
        print(f"\n{getattr(record, 'name', None) or 'trace'}:")
        for metric in EXPECTED_METRICS:
            computed, value = results[metric]
            status = fmt(value) if computed else "MISSING"
            print(f"  {metric}: {status}")
            if computed and value is not None:
                totals.setdefault(metric, []).append(value)

    print("\nAverages")
    print("-" * 48)
    for metric in EXPECTED_METRICS:
        values = totals.get(metric)
        if values:
            print(f"  {metric}: {sum(values) / len(values):.3f} (n={len(values)})")
        else:
            print(f"  {metric}: computed (no scalar value)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    if not PROJECT_NAME or not LOG_STREAM_NAME:
        print("❌ GALILEO_PROJECT and GALILEO_LOG_STREAM_DEV must be set in .env.")
        return 1

    project = get_project(name=PROJECT_NAME)
    if project is None:
        print(f"❌ Project '{PROJECT_NAME}' not found.")
        return 1

    log_stream = get_log_stream(name=LOG_STREAM_NAME, project_name=PROJECT_NAME)
    if log_stream is None:
        print(f"❌ Log stream '{LOG_STREAM_NAME}' not found.")
        return 1

    print(f"Project: {PROJECT_NAME} ({project.id})")
    print(f"Log stream: {LOG_STREAM_NAME} ({log_stream.id})\n")

    # 1. Enable the metrics we are about to verify.
    print(f"Enabling metrics: {', '.join(EXPECTED_METRICS)}...")
    try:
        enable_metrics(
            log_stream_name=LOG_STREAM_NAME,
            project_name=PROJECT_NAME,
            metrics=METRICS,
        )
    except Exception as exc:  # noqa: BLE001 - surface config failures clearly
        print(f"❌ Could not enable metrics: {exc}")
        return 1
    print("✅ Metrics enabled.\n")

    # 2. Submit test data.
    run_tag = f"smoke-{uuid.uuid4().hex[:8]}"
    submit_test_traces(run_tag)

    # 3 & 4. Poll and verify. Metric values are resolved version-tolerantly
    # (by name, then by scorer id) inside the resolver.
    try:
        scored = poll_for_scored_traces(project.id, log_stream.id, run_tag)
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user.")
        return 130

    if not scored:
        print("\n❌ SMOKE TEST FAILED: metrics were not calculated in time.")
        return 1

    print_scores(scored)
    print("\n✅ SMOKE TEST PASSED: metrics were calculated end-to-end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
