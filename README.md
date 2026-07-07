# Galileo University

This repository demonstrates how to log to Galileo using the Python SDK. We also have a [TypeScript SDK](https://v2docs.galileo.ai/) and can integrate with any language through our [APIs](https://v2docs.galileo.ai/).

## Quick Start

**Requirements:** Python 3.12 or greater must be installed.

### Automated Setup (Recommended)

There is an automated setup script that supports macOS, Linux, and Windows on WSL terminal. If you are using Windows without WSL, follow to the manual setup instructions below.

Run the setup script to automatically create a virtual environment, install dependencies, and configure your environment:

```bash
./setup.sh
```

After running the script, activate the virtual environment:

```bash
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

Then edit the `.env` file with your Galileo credentials (the script creates it from a template if it doesn't exist).

### Manual Setup (Alternative)

If you prefer to set up manually:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Configure `.env` file:**
```env
GALILEO_API_KEY=your_api_key_here
GALILEO_PROJECT=your_project_name
GALILEO_LOG_STREAM_SANDBOX=sandbox
GALILEO_LOG_STREAM_DEV=dev
GALILEO_PROTECT_STAGE_NAME=Galileo Getting Started Protect PII Stage

(optional)
OPENAI_API_KEY=key
other model api keys as needed
```

## Tutorials


### Smoke Testing & Logging Your First Trace and Experiment
Steps 1-4 can be used as a Galileo environment smoke test and/or to quickly populate your first logstream and experiment.

Go into the `getting_started/rag/` folder. This contains steps 1-4 of a typical engineering workflow using Galileo:

| Script | Purpose |
| --- | --- |
| `step1_get_started.py` | Enable metrics and create Protect stage |
| `step2_log_your_first_trace.py` | Log your first trace |
| `step3a_create_dataset_from_csv.py` | Create dataset for experiments |
| `step3b_run_your_first_experiment.py` | Run experiment with CI/CD thresholds |
| `step4_run_with_protect.py` | Log traces with Protect enforcement |
| `step6_check_scores.py` | End-to-end metric-calculation smoke test: submit traces, poll for metrics, fail on timeout |

**Step 1**: Set up your Protect Stage and Enable Metrics. Metrics enabled:
- [Context Adherence](https://v2docs.galileo.ai/)
- [Chunk Attribution Utilization](https://v2docs.galileo.ai/)
- [Context Relevance](https://v2docs.galileo.ai/)
- [Correctness](https://v2docs.galileo.ai/).

**Step 2**: Log your first trace. Optionally, create a custom metric (e.g., prevent legal advice). Use [CLHF](https://v2docs.galileo.ai/) to auto-tune and improve metrics such as custom metrics or context relevance.

**Step 3**: Uses the dataset in `data/`. You can also use [Galileo's synthetic dataset generation](https://v2docs.galileo.ai/) to quickly create more data.

Stay organized among teams by storing prompts in our [prompt storage](https://v2docs.galileo.ai/).

**Step 3b**: Demonstrates how a ground truth dataset can be applied in your CI/CD pipeline to prevent bad AI code from reaching production.

**Step 4**: Use Protect to block bad input PII queries in real time.

**Step 6**: End-to-end metric-calculation smoke test. It is self-contained: it (1) enables a chosen metric family on the `dev` log stream, (2) submits a small batch of RAG traces tagged with a unique run id, (3) polls the traces search API (`POST /projects/{project_id}/traces/search`) until Galileo has scored every enabled metric on those traces, and (4) verifies they appear within a configurable timeout — printing the scores and exiting non-zero if they don't. This lets the smoke test detect metric-calculation failures without manual log inspection, suitable for lightweight monitoring.

Metric families: set `GALILEO_SMOKE_TEST_METRICS` to `llm` (LLM-as-judge: context adherence, context relevance, correctness), `luna` (Luna/SLM: context adherence, context relevance, completeness), or `both` to verify both families in one run. `correctness` has no Luna variant, so `completeness` stands in for the Luna set.

Note on version differences: how metric values are keyed on a trace changed across Galileo versions and by family. Newer versions key by the metric's *scorer id* (e.g. `<scorer_id>_multijudge_average` for LLM-judge, `<scorer_id>_average` for Luna), while older versions key by *name* (e.g. `context_adherence`). The script is version-tolerant: it tries scorer ids first (unique per variant, so an LLM-judge metric never reads its Luna sibling's value) and falls back to a collision-guarded name lookup. Run with `GALILEO_SMOKE_TEST_DEBUG=1` to print the exact metric-column keys and resolved scorer ids for your version.

Enabling metrics replaces the log stream's scorer configuration with exactly the family you select, so point this at a dedicated smoke-test log stream if you don't want to change an existing stream's metrics.

Configuration (all optional, via `.env` — see `.env.template`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `GALILEO_SMOKE_TEST_METRICS` | `llm` | Metric family to verify: `llm`, `luna`, or `both` |
| `GALILEO_METRIC_TIMEOUT_SECONDS` | `180` | Max seconds to wait for metrics before failing |
| `GALILEO_METRIC_POLL_INTERVAL_SECONDS` | `10` | Seconds between polls |
| `GALILEO_SMOKE_TEST_NUM_TRACES` | `3` | Number of test traces to submit |
| `GALILEO_METRIC_MIN_SCORED_TRACES` | = submitted | Min scored traces required to pass |
| `GALILEO_SMOKE_TEST_DEBUG` | unset | Set to `1` to print how this Galileo version keys metric columns (scorer id vs. name) |

**Agentic workflows** (optional): See `getting_started/agentic-workflows/` for agentic workflow examples. Step 5 logs an agent workflow with LangGraph. Check out our agent graph to quickly understand a workflow.

## Resources

- [Galileo Documentation](https://v2docs.galileo.ai/)
- [Sessions Overview](https://v2docs.galileo.ai/concepts/logging/sessions/sessions-overview)
