"""Step 6: End-to-end metric-calculation smoke test.

    1. Configure - enable the metrics we want to verify on the dev log stream.
    2. Submit    - log a small batch of RAG traces, tagged with a unique run id.
    3. Poll      - fetch those traces via the traces search API
                   (POST /projects/{project_id}/traces/search).
    4. Verify    - confirm Galileo scored every enabled metric within a timeout;
                   print the scores and exit non-zero if it didn't.

This is self-contained: it enables the metrics, submits the data, and verifies
the results without any manual log inspection.

It can verify LLM-as-judge metrics, Luna (SLM) metrics, or both at once - see
GALILEO_SMOKE_TEST_METRICS below.

Note on how scores are keyed: Galileo stores each metric's value on the trace
under the metric's *scorer id* (e.g. "<scorer_id>_multijudge_average" for
LLM-judge, "<scorer_id>_average" for Luna), not the friendly metric name. Older
versions key by name instead. The resolver probes both, id first, and guards
against an LLM-judge metric accidentally reading its Luna sibling's value.

Configuration (optional, via .env - see .env.template):
    GALILEO_SMOKE_TEST_METRICS            Which family: llm|luna|both  (default llm)
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

# Metric families this smoke test can enable and verify. LLM-judge and Luna
# (SLM) variants are separate scorers, so either family - or both together -
# can be verified in one run. (correctness has no Luna variant; completeness
# is its closest Luna counterpart.)
LLM_JUDGE_METRICS = [
    GalileoMetrics.context_adherence,
    GalileoMetrics.context_relevance,
    GalileoMetrics.correctness,
]
LUNA_METRICS = [
    GalileoMetrics.context_adherence_luna,
    GalileoMetrics.context_relevance_luna,
    GalileoMetrics.completeness_luna,
]
_METRIC_SETS = {
    "llm": LLM_JUDGE_METRICS,
    "luna": LUNA_METRICS,
    "both": LLM_JUDGE_METRICS + LUNA_METRICS,
}

# GALILEO_SMOKE_TEST_METRICS selects which family to run: "llm", "luna", "both".
METRIC_SET = (os.getenv("GALILEO_SMOKE_TEST_METRICS") or "llm").lower()
if METRIC_SET not in _METRIC_SETS:
    print(f"⚠️  GALILEO_SMOKE_TEST_METRICS='{METRIC_SET}' unknown; using 'llm'.")
    METRIC_SET = "llm"
METRICS = _METRIC_SETS[METRIC_SET]
# Use the enum member name (stable snake identifier that matches the on-trace
# metric keys), not .value - on some SDK versions .value is a display label
# like "Context Adherence (SLM)", which won't match the trace keys.
EXPECTED_METRICS = [metric.name for metric in METRICS]

MODEL_ALIAS = "gpt-5"

# Statuses that indicate a metric finished computing (vs. pending / error).
_OK_STATUSES = {"success", "roll_up", "computed", "done"}
# A metric's scalar value is published under its key plus one of these suffixes
# (the trace-level aggregate). Order = preference.
_SCALAR_SUFFIXES = ("@average", "_multijudge_average", "_average")

# Some metrics surface on the trace under a different internal scorer name than
# their enum value. Map enum value -> the on-trace key(s) to also try. Extend
# this if GALILEO_SMOKE_TEST_DEBUG=1 shows a metric keyed under another name.
METRIC_KEY_ALIASES = {
    "completeness_luna": ["rag_nli_completeness"],
}


# ---------------------------------------------------------------------------
# Metric resolution
# ---------------------------------------------------------------------------
#
# How metric values are keyed on a trace varies by Galileo version, family, and
# metric, so for each metric we build a short list of candidate keys and read
# them exactly:
#
#   - By scorer id when available (newer, id-keyed deployments).
#   - By the metric's name, plus any alias in METRIC_KEY_ALIASES.
#
# For each candidate we look for a scalar (key + a _SCALAR_SUFFIXES suffix, or
# the bare key), then fall back to the "<key>_status" field for metrics that
# report completion without a single scalar. Exact-key reads mean an LLM-judge
# metric can't accidentally pick up its Luna sibling's value. Run with
# GALILEO_SMOKE_TEST_DEBUG=1 to print the exact keys on a trace.

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
                scorer.name: str(scorer.id)
                for scorer in Scorers().list()
                if getattr(scorer, "name", None) in wanted
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


def candidate_keys(name: str) -> list:
    """On-trace keys to try for a metric: its scorer id (if any), then its name
    and any known aliases."""
    keys = [name, *METRIC_KEY_ALIASES.get(name, [])]
    scorer_id = scorer_ids().get(name)
    if scorer_id:
        keys.insert(0, scorer_id)
    return keys


def resolve_metric(scores: dict, name: str):
    """Return (computed, value) for one metric on one trace.

    ``value`` is a float when the metric publishes a scalar score, or None when
    it finished computing but exposes no single scalar (status only).
    """
    for key in candidate_keys(name):
        # Scalar value: "<key>@average" / "<key>_..._average" or the bare key.
        for suffix in _SCALAR_SUFFIXES:
            scalar = _numeric(scores.get(f"{key}{suffix}"))
            if scalar is not None:
                return True, float(scalar)
        scalar = _numeric(scores.get(key))
        if scalar is not None:
            return True, float(scalar)

        # No scalar we recognize: trust the metric's completion status.
        if str(scores.get(f"{key}_status", "")).lower() in _OK_STATUSES:
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


def metric_family(name: str) -> str:
    return "Luna (SLM)" if name.endswith("_luna") else "LLM-judge"


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
        our_traces = [record for record in (getattr(response, "records", None) or [])
                      if run_tag in (getattr(record, "tags", None) or [])]

        # On the first batch that has any metrics, optionally reveal the key
        # shape so version differences are easy to diagnose.
        if DEBUG and not dumped_debug:
            for record in our_traces:
                if raw_metrics(record):
                    debug_dump_metric_keys(record)
                    dumped_debug = True
                    break

        scored = [record for record in our_traces if is_fully_scored(record)]

        if len(scored) >= MIN_SCORED_TRACES:
            print(f"✅ {len(scored)}/{len(our_traces)} trace(s) fully scored after {elapsed}s.")
            return scored

        print(f"   {len(our_traces)} found, {len(scored)} fully scored... "
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
    last_family = None
    for metric in EXPECTED_METRICS:
        family = metric_family(metric)
        if family != last_family:
            print(f"[{family}]")
            last_family = family
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
    print(f"Metric family: {METRIC_SET}")
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
    # (by scorer id, then by name) inside the resolver.
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
