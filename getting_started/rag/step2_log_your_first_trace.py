from galileo import GalileoLogger

import os
import random
import time
import uuid
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.absolute()

# Load .env from the root directory (three levels up from script: rag -> getting_started -> root)
env_path = SCRIPT_DIR.parent.parent / ".env"
load_dotenv(env_path)

MODEL_ALIAS = "gpt-7"

# Get project and logstream names from environment
project_name = os.getenv("GALILEO_PROJECT")
log_stream_name = os.getenv("GALILEO_LOG_STREAM_SANDBOX")
stage_name = os.getenv("GALILEO_PROTECT_STAGE_NAME")

# Initialize logger
logger = GalileoLogger(
    project=project_name,
    log_stream=log_stream_name
)

session_uid = str(uuid.uuid4())[0:5]
nanosecond_epoch_external_id = str(time.time_ns())[0:5]

logger.start_session(
    name=f"Galileo University Session {session_uid}",
    external_id=uuid.uuid4().hex,  # guaranteed unique
)

print(f"Session Started with id {logger.session_id}!")

# Use absolute path based on script location (data is in getting_started/data, one level up from rag/)
csv_path = SCRIPT_DIR.parent / "data" / "mock_logstream_data.csv"
dataframe = pd.read_csv(csv_path)

print("Data Loaded! Starting Loop...")

for idx, row in dataframe.iterrows():
    print(f"Processing row {idx}...")
#    print(row)
    idx =  str(idx+1) + "a"
    context = [row['chunk1'], row['chunk2'], row['chunk3']]

    trace = logger.start_trace(
        input=row['user_input_query'],
        name=f"User Query {idx}",
        duration_ns=random.randint(100000, 200000),
        tags=["galileo-getting-started-user-query"],
        metadata={"last_updated": str(row['last_updated']), "application_id": str(row['application_id'])}
    )

    print(f"Trace started with id {trace.id}!")
    print(f"Trace input: {trace.input}")
    # Add an retriever span to the trace
    logger.add_retriever_span(
        input=row['user_input_query'],
        output=context,
        name=f"Knowledge Base Document Retrieval {idx}",
        duration_ns=random.randint(400000, 500000),
        metadata={"source": "vector_store"}, 
        tags=["galileo-getting-started-kb"],
        status_code=200
    )


    proper_input = (
    row["user_input_query"]
    + "\n\nContext Documents: "
    + ", ".join(context)
    )


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