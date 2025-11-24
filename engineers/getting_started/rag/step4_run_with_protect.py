import os
import random
import time
import uuid
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from galileo import GalileoLogger
from galileo.protect import invoke_protect
from galileo_core.schemas.protect.payload import Payload
from galileo_core.schemas.protect.execution_status import (
    ExecutionStatus
)

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.absolute()

# Load .env from the root directory (three levels up from script: rag -> getting_started -> engineers -> root)
env_path = SCRIPT_DIR.parent.parent.parent / ".env"
load_dotenv(env_path)

MODEL_ALIAS = "gpt-7"

# Get project, logstream, and stage names from environment
project_name = os.getenv("GALILEO_PROJECT")
log_stream_name = os.getenv("GALILEO_LOG_STREAM_DEV")
stage_name = os.getenv("GALILEO_PROTECT_STAGE_NAME")

from galileo.stages import get_protect_stage

# Check if stage exists
stage = get_protect_stage(stage_name=stage_name, project_name=project_name)

if stage is None:
    print(f"⚠️ Stage '{stage_name}' not found in project '{project_name}'. Please create the stage first.")
    exit(1)


# Initialize logger
logger = GalileoLogger(
    project=project_name,
    log_stream=log_stream_name
)

session_uid = str(uuid.uuid4())[0:5]
nanosecond_epoch_external_id = str(time.time_ns())[0:5]
logger.start_session(name=f"Galileo University Session {session_uid}", external_id=str(nanosecond_epoch_external_id))
print("Session Started!")

# Use absolute path based on script location
# Use absolute path based on script location (data is in getting_started/data, one level up from rag/)
csv_path = SCRIPT_DIR.parent / "data" / "mock_logstream_data.csv"
dataframe = pd.read_csv(csv_path)

print("Data Loaded! Starting Loop...")

for idx, row in dataframe.iterrows():
    print(f"Processing row {idx}...")
    print(row)
    idx =  str(idx+1) + "a"
    context = [row['chunk1'], row['chunk2'], row['chunk3']]
    
    # Start trace
    trace = logger.start_trace(
        input=row['user_input_query'],
        name=f"User Query {idx}",
        tags=["galileo-getting-started-user-query"],
        metadata={
            "last_updated": str(row['last_updated']),
            "application_id": str(row['application_id'])
        }
    )
    
    # Run Protect check on user input
    print(f"Running Protect check on input...")
    protect_payload = Payload(input=row['user_input_query'])
    protect_response = invoke_protect(
        payload=protect_payload,
        stage_name=stage_name,
        project_name=project_name
    )

    # Optional logging step for educational purposes
    if protect_response.ruleset_results[0]['status'] == ExecutionStatus.triggered:
        print("🛡️ Galileo Protect has blocked sensitive data from being processed.")
        continue

    else:
        # Log protect invocation using add_protect_span
        logger.add_protect_span(
            payload=protect_payload,
            response=protect_response,
            tags=["protect", "pii-detection"]
        )

        # Add an retriever span to the trace (only if protect passed)
        logger.add_retriever_span(
            input=row['user_input_query'],
            output=context,
            name=f"Knowledge Base Document Retrieval {idx}",
            duration_ns=random.randint(400000, 500000),
            metadata={"source": "vector_store"}, 
            tags=["galileo-getting-started-kb"],
            status_code=200
        )

        proper_input = row['user_input_query'] + f"\n\n Context Documents: {" ,".join(context)}"

        # Add an LLM span to the trace
        logger.add_llm_span(
            input=proper_input,
            output=row['ai_response'],
            model=MODEL_ALIAS,
            name=f"LLM Call {idx}",
            duration_ns=random.randint(1000000, 2000000),
            tags=["galileo-getting-started-llm-call"],  # Optional tags
            num_input_tokens=len((row['user_input_query']+str(context)).split()),
            num_output_tokens=len(row['ai_response'].split()),
            total_tokens=len((row['user_input_query']+str(context)).split())+len(row['ai_response'].split()),
            temperature=0.8675309,
            status_code=200,
            time_to_first_token_ns=1000000,
            metadata={"reference_output": str(row['reference_output']), "hallucination": str(row['hallucination'])}
        )

        # Conclude the trace with the final output
        logger.conclude(
            output=row['ai_response'],
            duration_ns=random.randint(1000, 2000),
            status_code=200,
            conclude_all=False
        )

        logger.clear_session(conclude_all=False)

        # Flush the trace to Galileo
        logger.flush()

print("Completed! Check Galileo Console for results.")