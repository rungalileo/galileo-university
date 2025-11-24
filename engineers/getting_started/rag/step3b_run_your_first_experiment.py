import os
import time
from pathlib import Path

from dotenv import load_dotenv

from galileo.experiments import run_experiment, get_experiment
from galileo.datasets import get_dataset
from galileo.schema.metrics import GalileoScorers
from galileo.prompts import create_prompt
from galileo import Message, MessageRole

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.absolute()

# Load .env from the root directory (three levels up from script: rag -> getting_started -> engineers -> root)
env_path = SCRIPT_DIR.parent.parent.parent / ".env"
load_dotenv(env_path)

# Get project name from environment
project_name = os.getenv("GALILEO_PROJECT")

########################################################
# Step 1: Get the dataset (created via create_dataset_from_csv.py)
########################################################

dataset_name = "ds-hallucination-ci-cd-check-context-adherence"
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

print("\nCreating prompt template...")
# Note: In production, you'd include context from your RAG retrieval
# For this example, we use the input directly. Context is stored in metadata.
prompt_template = create_prompt(
    name="rag-application-prompt-abc",
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
print("✅ Prompt template created")

########################################################
# Step 4: Run the experiment with metrics
########################################################

print("\n" + "="*60)
print("Running Experiment...")
print("="*60)

experiment_name = "Galileo Getting Started RAG Experiment"
metrics = [
    GalileoScorers.ground_truth_adherence,  
    GalileoScorers.context_adherence, 
    GalileoScorers.context_relevance,
    GalileoScorers.completeness,
    GalileoScorers.correctness
]

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

# Define thresholds for CI/CD
THRESHOLDS = {
    "ground_truth_adherence": 0.75,  # 75% adherence to ground truth
    "context_adherence": 0.7,        # 70% context adherence
    "context_relevance": 0.7,        # 70% context relevance
    "completeness": 0.7,            # 70% completeness
    "correctness": 0.7,             # 70% correctness
}

# Poll for metrics to be calculated
max_wait_time = 60  # 1 minute
poll_interval = 10   # Check every 10 seconds (less verbose)
elapsed_time = 0
last_status = None

print("Waiting for metrics to be calculated...")
print("(Press Ctrl+C to stop early)")

try:
    while elapsed_time < max_wait_time:
        # Reload the experiment to check for metrics
        experiment = get_experiment(experiment_name=actual_experiment_name, project_name=project_name)
        
        # Check experiment status first
        if hasattr(experiment, 'status') and experiment.status:
            # Handle ExperimentStatus enum or string
            status_value = experiment.status.value if hasattr(experiment.status, 'value') else str(experiment.status)
            status_lower = status_value.lower() if isinstance(status_value, str) else str(status_value).lower()
            
            if status_lower in ['failed', 'error', 'cancelled']:
                print(f"\n❌ Experiment status: {status_value}")
                print("Experiment failed or was cancelled. Exiting.")
                exit(1)
        
        # Check if aggregate_metrics are available
        all_metrics_ready = True
        if experiment.aggregate_metrics is None:
            all_metrics_ready = False
        else:
            # Check if all expected metrics are calculated
            for metric in metrics:
                metric_name = metric.value
                average_metric_key = f"average_{metric_name}"
                if average_metric_key not in experiment.aggregate_metrics:
                    all_metrics_ready = False
                    break
        
        if all_metrics_ready:
            print("\n✅ All metrics calculated!")
            break
        
        # Only print every 30 seconds to reduce verbosity
        current_status = None
        if hasattr(experiment, 'status') and experiment.status:
            # Handle ExperimentStatus enum or string
            current_status = experiment.status.value if hasattr(experiment.status, 'value') else str(experiment.status)
        
        should_print = (elapsed_time % 30 == 0) or (last_status != current_status)
        
        if should_print:
            status_msg = f" (status: {current_status})" if current_status else ""
            print(f"   Waiting for metrics... ({elapsed_time}s/{max_wait_time}s){status_msg}")
            last_status = current_status
        
        time.sleep(poll_interval)
        elapsed_time += poll_interval
    else:
        print("\n❌ Experiment timed out waiting for metrics!")
        print("   You can check the experiment status in the Galileo console.")
        exit(1)
except KeyboardInterrupt:
    print("\n\n⚠️  Polling interrupted by user.")
    print("   Experiment is still running. Check results in Galileo console.")
    exit(130)  # Standard exit code for Ctrl+C

# Get metric results from aggregate_metrics
print("\n" + "="*60)
print("Experiment Results:")
print("="*60)

all_passed = True

# Check each metric against thresholds
for metric in metrics:
    metric_name = metric.value
    average_metric_key = f"average_{metric_name}"
    
    if experiment.aggregate_metrics and average_metric_key in experiment.aggregate_metrics:
        avg_score = experiment.aggregate_metrics[average_metric_key]
        threshold = THRESHOLDS.get(metric_name, 0.0)
        
        # For hallucination, lower is better (inverted check)
        if metric_name == "hallucination":
            passed = avg_score <= threshold
        else:
            passed = avg_score >= threshold
        
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {metric_name}: {avg_score:.3f} (threshold: {threshold:.3f})")
        
        if not passed:
            all_passed = False
    else:
        print(f"⚠️  {metric_name}: No results available")
        all_passed = False

print("\n" + "="*60)
if all_passed:
    print("✅ ALL METRICS PASSED THRESHOLDS - CI/CD CHECK PASSED")
    print("="*60)
    exit(0)
else:
    print("❌ SOME METRICS FAILED THRESHOLDS - CI/CD CHECK FAILED")
    print("="*60)
    exit(1)
