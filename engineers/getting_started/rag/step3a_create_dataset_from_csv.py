import os
import json
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from galileo.datasets import create_dataset

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.absolute()

# Load .env from the root directory (three levels up from script: rag -> getting_started -> engineers -> root)
env_path = SCRIPT_DIR.parent.parent.parent / ".env"
load_dotenv(env_path)

# Get project name from environment
project_name = os.getenv("GALILEO_PROJECT")

# Read the CSV file
csv_path = SCRIPT_DIR.parent / "data" / "mock_logstream_data.csv"
dataframe = pd.read_csv(csv_path)

print(f"Reading CSV from: {csv_path}")
print(f"Found {len(dataframe)} rows")

# Convert CSV to dataset format with proper column mapping:
# user_input_query + context documents → input (matching step2_log_your_first_trace.py)
# reference_output → output (for ground truth metrics)
# ai_response, chunk1-3, application_id, hallucination → metadata
dataset_content = []
for idx, row in dataframe.iterrows():
    # Build context from chunks (matching step2)
    context = [row['chunk1'], row['chunk2'], row['chunk3']]
    
    # Format input to match step2: user_query + context documents
    # This matches: proper_input = row['user_input_query'] + f"\n\n Context Documents: {" ,".join(context)}"
    input_text = row['user_input_query'] + f"\n\n Context Documents: {', '.join(context)}"
    
    # Map reference_output → output (for ground truth metrics)
    reference_output = row['reference_output']
    
    # Map ai_response, chunk1-3, application_id, hallucination → metadata
    metadata = {
        "original ai_response": str(row['ai_response']),
        "hallucination": str(row['hallucination']),
        "last_updated": str(row['last_updated'])
    }
    
    # Create dataset entry
    dataset_entry = {
        "input": input_text,
        "output": reference_output,  # This is the ground truth for metrics. The golden correct answer.
        "metadata": metadata
    }
    
    dataset_content.append(dataset_entry)

# Create the dataset in Galileo
dataset_name = "ds-hallucination-ci-cd-check-context-adherence"
print(f"\nCreating dataset '{dataset_name}' in project '{project_name}'...")
print(f"Dataset will contain {len(dataset_content)} entries")

dataset = create_dataset(
    name=dataset_name,
    content=dataset_content,
    project_name=project_name
)

print(f"✅ Dataset created successfully!")
print(f"Dataset ID: {dataset.id}")
print(f"Dataset Name: {dataset.name}")
print(f"\nYou can now use this dataset in experiments!")

