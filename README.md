# Galileo University

This repository demonstrates how to log to Galileo using the Python SDK. We also have a [TypeScript SDK](https://v2docs.galileo.ai/) and can integrate with any language through our [APIs](https://v2docs.galileo.ai/).

## Quick Start

**Requirements:** Python 3.12 or greater must be installed.

### Automated Setup (Recommended)

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
```

## Tutorials

Go into the `getting_started/rag/` folder. This contains steps 1-4 of a typical engineering workflow using Galileo:

| Script | Purpose |
| --- | --- |
| `step1_get_started.py` | Enable metrics and create Protect stage |
| `step2_log_your_first_trace.py` | Log your first trace |
| `step3a_create_dataset_from_csv.py` | Create dataset for experiments |
| `step3b_run_your_first_experiment.py` | Run experiment with CI/CD thresholds |
| `step4_run_with_protect.py` | Log traces with Protect enforcement |

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

**Agentic workflows** (optional): See `getting_started/agentic-workflows/` for agentic workflow examples. Step 5 logs an agent workflow with LangGraph. Check out our agent graph to quickly understand a workflow.

## Resources

- [Galileo Documentation](https://v2docs.galileo.ai/)
- [Sessions Overview](https://v2docs.galileo.ai/concepts/logging/sessions/sessions-overview)
