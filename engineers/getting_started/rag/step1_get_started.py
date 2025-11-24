from galileo import GalileoLogger
from galileo.log_streams import enable_metrics
from galileo.schema.metrics import GalileoScorers
from galileo.stages import create_protect_stage, get_protect_stage
from galileo_core.schemas.protect.action import OverrideAction
from galileo_core.schemas.protect.rule import Rule, RuleOperator
from galileo_core.schemas.protect.ruleset import Ruleset
from galileo_core.schemas.protect.stage import StageType

import os
from pathlib import Path

from dotenv import load_dotenv

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.absolute()

# Load .env from the root directory (three levels up from script: rag -> getting_started -> engineers -> root)
env_path = SCRIPT_DIR.parent.parent.parent / ".env"
load_dotenv(env_path)

# Get project, logstreams, and stage names from environment
project_name = os.getenv("GALILEO_PROJECT")
log_stream_sandbox = os.getenv("GALILEO_LOG_STREAM_SANDBOX")
log_stream_dev = os.getenv("GALILEO_LOG_STREAM_DEV")
stage_name = os.getenv("GALILEO_PROTECT_STAGE_NAME")

# Initialize logger (using sandbox as default)
logger_sandbox = GalileoLogger(
    project=project_name,
    log_stream=log_stream_sandbox
)

logger_dev = GalileoLogger(
    project=project_name,
    log_stream=log_stream_dev
)

# Enable metrics for both logstreams: context adherence, tool selection quality, and chunk attribution utilization
metrics_to_enable = [
    GalileoScorers.context_adherence, # RAG
    GalileoScorers.chunk_attribution_utilization, # RAG
    GalileoScorers.context_relevance, # RAG
    GalileoScorers.completeness, # RAG
    GalileoScorers.correctness # RAG
]

# Enable metrics for sandbox logstream
if log_stream_sandbox:
    print(f"Enabling metrics for logstream '{log_stream_sandbox}' (sandbox) in project '{project_name}'...")
    local_metrics_sandbox = enable_metrics(
        log_stream_name=log_stream_sandbox,
        project_name=project_name,
        metrics=metrics_to_enable
    )
    print(f"✅ Metrics enabled for sandbox logstream: context_adherence, chunk_attribution_utilization, context_relevance, completeness, correctness")

# Enable metrics for dev logstream
if log_stream_dev:
    print(f"Enabling metrics for logstream '{log_stream_dev}' (dev) in project '{project_name}'...")
    local_metrics_dev = enable_metrics(
        log_stream_name=log_stream_dev,
        project_name=project_name,
        metrics=metrics_to_enable
    )
    print(f"✅ Metrics enabled for dev logstream: context_adherence, tool_selection_quality, chunk_attribution_utilization")

########################################################
# Create Protect Stage for PII detection
########################################################

print(f"\nCreating Protect stage '{stage_name}'...")
rule = Rule(
    metric=GalileoScorers.input_pii,
    operator=RuleOperator.any,
    target_value=["ssn", "address", "email", "phone number"]
)

# Create OverrideAction to block with a message when PII is detected
blocking_action = OverrideAction(
    choices=["🛡️ Galileo Protect has blocked sensitive data from being processed. Please remove PII and try again."]
)

ruleset = Ruleset(
    rules=[rule],
    action=blocking_action
)

stage = create_protect_stage(
    name=stage_name,
    project_name=project_name,
    stage_type=StageType.central,
    prioritized_rulesets=[ruleset],
    description="Test the input for PII."
)

protected_stage = get_protect_stage(
    stage_name=stage_name,
    project_name=project_name
)

print(f"✅ Stage created successfully with ID: {protected_stage.id}")