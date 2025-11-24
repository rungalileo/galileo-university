# Galileo University - Getting Started

This repository contains step-by-step tutorials for getting started with Galileo observability, metrics, and protect features.

## What is a Trace?

A trace represents a single execution path through your application, showing how data flows from input through various components (retrievers, LLMs, tools) to the final output.

Learn more: https://v2docs.galileo.ai/concepts/logging/sessions/sessions-overview

## Prerequisites

- Python 3.7+
- Galileo API Key
- Galileo Project and Log Stream names

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Or install individually:
```bash
pip install galileo pandas python-dotenv
```

### 2. Configure Environment Variables

Create a `.env` file in the root directory with the following:

```env
GALILEO_API_KEY=your_api_key_here
GALILEO_PROJECT=your_project_name
GALILEO_LOG_STREAM_SANDBOX=sandbox
GALILEO_LOG_STREAM_DEV=dev
GALILEO_PROTECT_STAGE_NAME=Galileo Getting Started Protect PII Stage
```

## Step-by-Step Tutorials

All tutorials are located in `engineers/getting_started/rag/`:

### Step 1: Get Started (`step1_get_started.py`)

**What it does:**
- Enables metrics for both sandbox and dev logstreams:
  - Context Adherence (RAG)
  - Chunk Attribution Utilization (RAG)
  - Context Relevance (RAG)
  - Completeness (RAG)
  - Correctness (RAG)
- Creates a Protect stage for PII detection with blocking action

**Run it:**
```bash
cd engineers/getting_started/rag
python3 step1_get_started.py
```

**What you'll see:**
- Metrics enabled for both logstreams
- A Protect stage created for blocking PII

### Step 2: Log Your First Trace (`step2_log_your_first_trace.py`)

**What it does:**
- Reads sample data from CSV
- Logs traces with retriever and LLM spans
- Demonstrates basic trace logging with context documents

**Run it:**
```bash
cd engineers/getting_started/rag
python3 step2_log_your_first_trace.py
```

**What you'll see:**
- Traces logged to the sandbox logstream
- Each trace includes:
  - User query
  - Knowledge base document retrieval span
  - LLM call span with context documents and token counts

### Step 3a: Create Dataset from CSV (`step3a_create_dataset_from_csv.py`)

**What it does:**
- Reads `mock_logstream_data.csv`
- Maps columns to dataset format:
  - `user_input_query` + context documents → `input`
  - `reference_output` → `output` (ground truth)
  - `ai_response`, `chunk1-3`, `application_id`, `hallucination` → `metadata`
- Creates a Galileo dataset for experiments

**Run it:**
```bash
cd engineers/getting_started/rag
python3 step3a_create_dataset_from_csv.py
```

**What you'll see:**
- Dataset created in Galileo
- Dataset ID and name for use in experiments

### Step 3b: Run Your First Experiment (`step3b_run_your_first_experiment.py`)

**What it does:**
- Gets the dataset created in Step 3a
- Creates a prompt template for the RAG application
- Runs an experiment with multiple metrics:
  - Ground Truth Adherence
  - Context Adherence
  - Context Relevance
  - Completeness
  - Correctness
- Polls for results and asserts thresholds for CI/CD

**Run it:**
```bash
cd engineers/getting_started/rag
python3 step3b_run_your_first_experiment.py
```

**What you'll see:**
- Experiment starts running
- Polling for metrics calculation (up to 1 minute)
- Results checked against thresholds
- Exit code 0 if all pass, 1 if any fail (for CI/CD)

**CI/CD Integration:**
- The script exits with code 0 if all metrics pass thresholds
- Exits with code 1 if metrics fail or errors occur
- Can be integrated into CI/CD pipelines as a quality gate

### Step 4: Run with Protect (`step4_run_with_protect.py`)

**What it does:**
- Logs traces with Protect guardrails integrated
- Uses `add_protect_span` to log protect invocations
- Blocks inputs that contain PII before processing

**Run it:**
```bash
cd engineers/getting_started/rag
python3 step4_run_with_protect.py
```

**What you'll see:**
- Protect checks run before processing each trace
- Inputs with PII are blocked
- Protect invocations logged as protect spans

## Project Structure

```
galileo-university/
├── .env                          # Environment variables (not in git)
├── .gitignore                    # Git ignore file
├── README.md                     # This file
├── requirements.txt              # Python dependencies
└── engineers/
    └── getting_started/
        ├── data/
        │   └── mock_logstream_data.csv  # Sample data
        └── rag/
            ├── step1_get_started.py              # Setup metrics and protect
            ├── step2_log_your_first_trace.py     # Basic trace logging
            ├── step3a_create_dataset_from_csv.py  # Create dataset from CSV
            ├── step3b_run_your_first_experiment.py  # Run experiments
            └── step4_run_with_protect.py         # Protect integration
```

## Metrics Enabled

The following metrics are enabled for both sandbox and dev logstreams:

- **Context Adherence** (RAG): Measures how well the LLM response adheres to the provided context
- **Chunk Attribution Utilization** (RAG): Identifies which chunks/documents were used to construct the answer
- **Context Relevance** (RAG): Evaluates how relevant the retrieved context is to the query
- **Completeness** (RAG): Measures how complete the answer is relative to the query
- **Correctness** (RAG): Measures factual correctness of the response

## Experiment Metrics

Experiments use the following metrics with thresholds:

- **Ground Truth Adherence**: 75% threshold (compares output to reference_output)
- **Context Adherence**: 70% threshold
- **Context Relevance**: 70% threshold
- **Completeness**: 70% threshold
- **Correctness**: 70% threshold

## Protect Stage

A Protect stage is created with:
- **Metric**: Input PII detection
- **Action**: Override (blocks with a message when PII is detected)
- **Target Values**: ssn, address, email, phone number

## Dataset Format

The dataset is created from CSV with the following mapping:

- **Input**: `user_input_query` + context documents (chunk1, chunk2, chunk3)
- **Output**: `reference_output` (used as ground truth for metrics)
- **Metadata**: `ai_response`, `chunk1-3`, `application_id`, `hallucination`, `last_updated`

## Troubleshooting

### Error: "ModuleNotFoundError: No module named 'galileo'"
- **Solution**: Run `pip install galileo pandas python-dotenv`

### Error: "GALILEO_PROJECT environment variable not set"
- **Solution**: Check that your `.env` file exists in the root directory and contains `GALILEO_PROJECT=your_project_name`

### Error: "Project/Logstream does not exist"
- **Solution**: Create the project and logstreams in your Galileo console first

### Error: "FileNotFoundError: data/mock_logstream_data.csv"
- **Solution**: Make sure you're running the script from the `rag/` directory, and the data folder is in `getting_started/data/`

### Error: "Dataset not found"
- **Solution**: Run `step3a_create_dataset_from_csv.py` first to create the dataset

### Experiment polling takes too long
- **Solution**: The script polls for up to 1 minute. You can press Ctrl+C to stop early and check results in the Galileo console

## CI/CD Integration

The experiment script (`step3b_run_your_first_experiment.py`) is designed for CI/CD:

1. **Exit Codes**:
   - `0` = All metrics passed thresholds (CI/CD passes)
   - `1` = Metrics failed or errors occurred (CI/CD fails)
   - `130` = Interrupted by user (Ctrl+C)

2. **Usage in CI/CD**:
   ```bash
   python3 step3b_run_your_first_experiment.py
   if [ $? -eq 0 ]; then
       echo "Quality checks passed!"
   else
       echo "Quality checks failed!"
       exit 1
   fi
   ```

3. **Customization**:
   - Adjust thresholds in the `THRESHOLDS` dictionary
   - Modify metrics in the `metrics` list
   - Change `max_wait_time` for polling duration

## Next Steps

After completing these steps:
1. Check your **Galileo Console** to see the logged traces
2. Explore the **metrics** computed for your traces
3. Review **Protect** guardrail results
4. Run **experiments** to validate quality metrics
5. Integrate experiments into your **CI/CD pipeline**

## Resources

- [Galileo Documentation](https://v2docs.galileo.ai/)
- [Sessions Overview](https://v2docs.galileo.ai/concepts/logging/sessions/sessions-overview)
- [Experiments Guide](https://v2docs.galileo.ai/sdk-api/experiments/running-experiments-in-unit-tests)
