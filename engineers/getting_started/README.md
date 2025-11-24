# Galileo University (Quick Guide)

**Install**
```bash
pip install -r requirements.txt
```

**Env (`.env`)**
```env
GALILEO_API_KEY=...
GALILEO_PROJECT=...
GALILEO_LOG_STREAM_SANDBOX=sandbox
GALILEO_LOG_STREAM_DEV=dev
GALILEO_PROTECT_STAGE_NAME=Protect PII Stage
```

**Scripts** (run from `engineers/getting_started/rag/`)
| Script | Purpose |
| --- | --- |
| `step1_get_started.py` | enable metrics + create Protect stage |
| `step2_log_your_first_trace.py` | log traces from CSV |
| `step3a_create_dataset_from_csv.py` | create Galileo dataset |
| `step3b_run_your_first_experiment.py` | run CI-style experiment |
| `step4_run_with_protect.py` | log traces with Protect enforcement |

**Usage**
```bash
cd engineers/getting_started/rag
python3 step2_log_your_first_trace.py   # example
```

Check the Galileo console afterward for traces, metrics, experiments, and Protect events.

