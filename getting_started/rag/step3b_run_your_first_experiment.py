import os
import time
from pathlib import Path

from dotenv import load_dotenv

from galileo.experiments import run_experiment, get_experiment
from galileo.datasets import get_dataset
from galileo_core.schemas.shared.scorers.scorer_name import ScorerName
from galileo.prompts import create_prompt, get_prompt
from galileo.projects import get_project
from galileo import Message, MessageRole

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.absolute()

# Load .env from the root directory (three levels up from script: rag -> getting_started -> root)
env_path = SCRIPT_DIR.parent.parent / ".env"
load_dotenv(env_path)

# Get project name from environment
project_name = os.getenv("GALILEO_PROJECT")

########################################################
# Step 1: Get the dataset (created via create_dataset_from_csv.py)
########################################################

# Read dataset name from file created by step3a
dataset_name_file = SCRIPT_DIR / "dataset_name.txt"
try:
    with open(dataset_name_file, "r") as f:
        dataset_name = f.read().strip()
    print(f"Read dataset name from {dataset_name_file}: '{dataset_name}'")
except FileNotFoundError:
    print(f"❌ Error: Dataset name file not found: {dataset_name_file}")
    print("   Please run step3a_create_dataset_from_csv.py first to create the dataset.")
    exit(1)
except Exception as e:
    print(f"❌ Error reading dataset name file: {e}")
    exit(1)

print(f"Getting dataset '{dataset_name}'...")

try:
    dataset = get_dataset(name=dataset_name, project_name=project_name)
    print(f"✅ Dataset found: {dataset.name} (ID: {dataset.id})")
    # Check if content is available (it might not be loaded by default)
    if dataset.content is not None:
        print(f"   Contains {len(dataset.content)} entries")
    else:
        print(f"   Dataset content will be loaded during experiment")
except Exception as e:
    print(f"❌ Error getting dataset: {e}")
    print("   Please run create_dataset_from_csv.py first to create the dataset.")
    exit(1)

########################################################
# Step 2: Create prompt template for the experiment
# This simulates your RAG application - the experiment will run this
# prompt template with your LLM for each input in the dataset
########################################################

prompt_name = "rag-application-prompt"
print(f"\nFetching prompt '{prompt_name}'...")

try:
    prompt_template = get_prompt(name=prompt_name, project_name=project_name)

    if prompt_template is None:
        print("⚠️ Prompt not found, creating a new one...")
        prompt_template = create_prompt(
            name=prompt_name,
            project_name=project_name,
            template=[
                Message(
                    role=MessageRole.system,
                    content="You are a helpful assistant. Answer the user's question accurately and concisely based on the context provided. Answer in 30 words or less."
                ),
                Message(
                    role=MessageRole.user,
                    content="{{input}}"
                )
            ]
        )
        print("✅ Prompt created and saved in Galileo.")
    else:
        print("✅ Prompt found in Galileo – reusing existing template.")

except Exception as e:
    print(f"❌ Error getting prompt: {e}")
    exit(1)

########################################################
# Step 4: Run the experiment with metrics
########################################################

print("\n" + "="*60)
print("Running Experiment...")
print("="*60)

experiment_name = "Galileo Getting Started RAG Experiment"
metrics = [
    ScorerName.ground_truth_adherence,
    ScorerName.context_adherence,
    ScorerName.context_relevance,
    ScorerName.correctness
]

# Some scorers are published under a renamed key in aggregate_metrics
# (e.g. correctness -> factuality, context_adherence -> groundedness). Map each
# requested scorer to the output key(s) to look for.
METRIC_OUTPUT_ALIASES = {
    "correctness": ["correctness", "factuality"],
    "context_adherence": ["context_adherence", "groundedness"],
    "context_relevance": ["context_relevance"],
    "ground_truth_adherence": ["ground_truth_adherence"],
}


def aggregate_props(experiment):
    """aggregate_metrics is an object whose values live in additional_properties."""
    return getattr(getattr(experiment, "aggregate_metrics", None), "additional_properties", None) or {}


def resolve_average(props, scorer_value):
    """Return (key, value) for a scorer's average, tolerating renamed outputs."""
    for alias in METRIC_OUTPUT_ALIASES.get(scorer_value, [scorer_value]):
        key = f"average_{alias}"
        if key in props:
            return key, props[key]
    return None, None


print(f"Experiment Name: {experiment_name}")
print(f"Metrics: {', '.join([m.value for m in metrics])}")
print(f"Dataset: {dataset.name}")

experiment_response = run_experiment(
    experiment_name,
    dataset=dataset,
    prompt_template=prompt_template,
    metrics=metrics,
    project=project_name,
    experiment_tags={
        "dataset-name": dataset_name,
        "type": "rag-experiment",
        "ci-cd": "true"
    }
)

# Get the actual experiment name (may have timestamp appended)
actual_experiment_name = experiment_response["experiment"].name
print(f"\n✅ Experiment started!")
print(f"Experiment Name: {actual_experiment_name}")
print(f"Experiment ID: {experiment_response['experiment'].id}")

########################################################
# Step 5: Poll results and assert thresholds (for CI/CD)
########################################################

print("\n" + "="*60)
print("Polling Experiment Results...")
print("="*60)

# Define thresholds for CI/CD (keyed by requested scorer name)
THRESHOLDS = {
    "ground_truth_adherence": 0.75,  # 75% adherence to ground truth
    "context_adherence": 0.7,        # 70% context adherence
    "context_relevance": 0.7,        # 70% context relevance
    "correctness": 0.7,             # 70% correctness
}

# Poll for metrics to be calculated
max_wait_time = 180  # scoring can take a couple of minutes
poll_interval = 10   # Check every 10 seconds (less verbose)
elapsed_time = 0

print("Waiting for metrics to be calculated...")
print("(Press Ctrl+C to stop early)")

try:
    while elapsed_time < max_wait_time:
        # Reload the experiment to check for metrics
        experiment = get_experiment(experiment_name=actual_experiment_name, project_name=project_name)

        # Fail fast if the experiment itself errored/cancelled
        status_text = str(getattr(experiment, "status", "")).lower()
        if any(bad in status_text for bad in ("failed", "error", "cancelled")):
            print(f"\n❌ Experiment status: {getattr(experiment, 'status', None)}")
            print("Experiment failed or was cancelled. Exiting.")
            exit(1)

        # Ready when every requested scorer that the platform returns is present.
        props = aggregate_props(experiment)
        resolved = {m.value: resolve_average(props, m.value)[0] for m in metrics}
        found = sum(1 for key in resolved.values() if key is not None)

        if props and found == len(metrics):
            print("\n✅ All metrics calculated!")
            break

        print(f"   Waiting for metrics... ({elapsed_time}s/{max_wait_time}s) "
              f"[{found}/{len(metrics)} available]")
        time.sleep(poll_interval)
        elapsed_time += poll_interval
    else:
        print("\n⚠️  Timed out waiting for all metrics; evaluating what was calculated.")
except KeyboardInterrupt:
    print("\n\n⚠️  Polling interrupted by user.")
    print("   Experiment is still running. Check results in Galileo console.")
    exit(130)  # Standard exit code for Ctrl+C

# Get metric results from aggregate_metrics
print("\n" + "="*60)
print("Experiment Results:")
print("="*60)

experiment = get_experiment(experiment_name=actual_experiment_name, project_name=project_name)
props = aggregate_props(experiment)

all_passed = True
missing = []

# Check each metric against thresholds. Metrics the platform did not return for
# this experiment are reported as skipped (not a hard failure).
for metric in metrics:
    metric_name = metric.value
    resolved_key, avg_score = resolve_average(props, metric_name)

    if resolved_key is not None:
        threshold = THRESHOLDS.get(metric_name, 0.0)
        passed = avg_score >= threshold
        status = "✅ PASS" if passed else "❌ FAIL"
        label = metric_name if resolved_key == f"average_{metric_name}" else f"{metric_name} (as {resolved_key[len('average_'):]})"
        print(f"{status} {label}: {avg_score:.3f} (threshold: {threshold:.3f})")
        if not passed:
            all_passed = False
    else:
        print(f"⏭️  {metric_name}: not returned by the platform for this experiment (skipped)")
        missing.append(metric_name)

print("\n" + "="*60)
if all_passed:
    print("✅ CI/CD CHECK PASSED - all returned metrics met thresholds")
    if missing:
        print(f"   (skipped, not computed for this experiment: {', '.join(missing)})")
    print("="*60)
    exit(0)
else:
    print("❌ CI/CD CHECK FAILED - one or more metrics below threshold")
    print("="*60)
    exit(1)
