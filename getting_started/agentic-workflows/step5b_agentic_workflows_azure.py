"""
LangGraph Agent - Getting Started with Agentic Workflows (Azure OpenAI)

This script demonstrates how to build a LangGraph agent with:
- Tool usage (agentic workflows)
- RAG support (optional)
- Galileo Protect integration
- Galileo observability via GalileoCallback
- Azure OpenAI integration

Environment variables required:
- AZURE_OPENAI_ENDPOINT: Your Azure OpenAI endpoint (e.g., https://your-resource.openai.azure.com/)
- AZURE_OPENAI_API_KEY: Your Azure OpenAI API key
- AZURE_OPENAI_DEPLOYMENT_NAME: Your Azure OpenAI deployment name (NOT the model name!)
  This is the name you gave your deployment in Azure Portal (e.g., "my-gpt4-deployment")
  It may be different from the underlying model name (e.g., "gpt-4o-mini")
- AZURE_OPENAI_API_VERSION: API version (e.g., 2024-02-15-preview, optional, defaults to 2024-02-15-preview)
"""

import os
import time
import uuid
from pathlib import Path
from typing import Optional, List

from dotenv import load_dotenv

from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.graph import START, END, StateGraph, MessagesState
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from galileo.handlers.langchain import GalileoCallback
from galileo.handlers.langchain.tool import ProtectTool
from galileo.stages import get_protect_stage
from galileo_core.schemas.protect.execution_status import ExecutionStatus
from galileo_core.schemas.protect.response import Response
from galileo import GalileoLogger

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.absolute()

# Load .env from the root directory (three levels up from script: agentic-workflows -> getting_started -> root)
env_path = SCRIPT_DIR.parent.parent / ".env"
load_dotenv(env_path)

# Get project and stage names from environment
project_name = os.getenv("GALILEO_PROJECT")
log_stream_name = os.getenv("GALILEO_LOG_STREAM_DEV") + "-agent"
stage_name = os.getenv("GALILEO_PROTECT_STAGE_NAME")

# Azure OpenAI configuration
azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")  # Required - no default
azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# Define the state for our graph using MessagesState
class State(MessagesState):
    protect_triggered: bool  # Track if Protect was triggered


def create_sample_tools() -> List[StructuredTool]:
    """Create sample tools for the agent to use"""
    
    def get_weather(location: str) -> str:
        """Get the current weather for a location.
        
        Args:
            location: The city or location to get weather for
            
        Returns:
            A string describing the weather
        """
        # Simulated weather data
        weather_data = {
            "san francisco": "Sunny, 72°F",
            "new york": "Cloudy, 65°F",
            "london": "Rainy, 55°F",
            "tokyo": "Clear, 75°F"
        }
        location_lower = location.lower()
        return weather_data.get(location_lower, f"Weather for {location}: Partly cloudy, 68°F")
    
    def calculate(expression: str) -> str:
        """Evaluate a mathematical expression.
        
        Args:
            expression: A mathematical expression to evaluate (e.g., "2 + 2", "10 * 5")
            
        Returns:
            The result of the calculation
        """
        try:
            # Simple and safe evaluation (in production, use a proper math parser)
            result = eval(expression)
            return f"Result: {result}"
        except Exception as e:
            return f"Error calculating: {str(e)}"
    
    def search_knowledge_base(query: str) -> str:
        """Search the knowledge base for information.
        
        Args:
            query: The search query
            
        Returns:
            Relevant information from the knowledge base
        """
        # Simulated knowledge base
        kb_data = {
            "password reset": "To reset your password, go to Settings > Security > Reset Password",
            "account": "Your account information can be found in the Account Settings page",
            "billing": "Billing information is available in the Billing section of your account"
        }
        query_lower = query.lower()
        for key, value in kb_data.items():
            if key in query_lower:
                return value
        return f"Information about '{query}': Please contact support for more details."
    
    # Create StructuredTools from functions
    tools = [
        StructuredTool.from_function(
            func=get_weather,
            name="get_weather",
            description="Get the current weather for a location"
        ),
        StructuredTool.from_function(
            func=calculate,
            name="calculate",
            description="Evaluate a mathematical expression"
        ),
        StructuredTool.from_function(
            func=search_knowledge_base,
            name="search_knowledge_base",
            description="Search the knowledge base for information"
        )
    ]
    
    return tools


def build_langgraph_agent(
    tools: List[StructuredTool],
    system_prompt: str,
    protect_stage_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> CompiledStateGraph:
    """Build a LangGraph agent with Protect integration using Azure OpenAI"""
    
    # Validate Azure configuration
    if not azure_endpoint or not azure_api_key:
        raise ValueError(
            "Azure OpenAI configuration missing. Please set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY environment variables."
        )
    if not azure_deployment:
        raise ValueError(
            "AZURE_OPENAI_DEPLOYMENT_NAME is required. This should be the name of your deployment "
            "in Azure Portal (not the model name). For example, if you created a deployment called "
            "'my-gpt4' for the gpt-4o-mini model, set AZURE_OPENAI_DEPLOYMENT_NAME=my-gpt4"
        )
    
    # Format the Azure endpoint for LangChain
    # Azure endpoint should be: https://your-resource.openai.azure.com
    # LangChain needs: https://your-resource.openai.azure.com/openai/v1/
    endpoint = azure_endpoint.rstrip('/')
    if not endpoint.endswith('/openai/v1'):
        if endpoint.endswith('/openai'):
            base_url = f"{endpoint}/v1"
        else:
            base_url = f"{endpoint}/openai/v1"
    else:
        base_url = endpoint
    
    # Create the LLM with Azure OpenAI configuration
    # Use base_url and api_key directly (LangChain supports Azure via base_url)
    llm = ChatOpenAI(
        model=azure_deployment,
        base_url=base_url,
        api_key=azure_api_key,
        temperature=0.7,
        name="Galileo Assistant (Azure)"
    ).bind_tools(tools)
    
    protect_enabled = protect_stage_id is not None
    
    def protect_check_node(state: State) -> State:
        """Check for harmful content before processing"""
        if not protect_enabled:
            # IMPORTANT: don't touch messages; just signal no protect
            return {"protect_triggered": False}
        
        latest_message = None
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                latest_message = msg.content
                break
        
        if not latest_message:
            return {"protect_triggered": False}
        
        protect_tool = ProtectTool(stage_id=protect_stage_id)
        response_json = protect_tool.invoke({"input": latest_message})
        response = Response.model_validate_json(response_json)
        
        if response.status == ExecutionStatus.triggered:
            override_msg = AIMessage(content=response.text)
            return {
                # override the message history: just the block message
                "messages": [override_msg],
                "protect_triggered": True,
            }
        
        # Not triggered -> DO NOT touch messages, only flag
        return {"protect_triggered": False}
    
    def invoke_chatbot(state: State) -> State:
        """Invoke the LLM with system prompt, letting LangGraph handle message aggregation."""
        messages = state["messages"]

        # Add system prompt once, at the front, if it's not already there
        if system_prompt and not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=system_prompt)] + messages

        # Call the LLM with the full message history
        ai_message = llm.invoke(messages)

        # Return only the new AI message; MessagesState appends it to the history
        return {"messages": [ai_message]}
    
    def route_after_protect(state: State) -> str:
        """Route after protect check - skip to END if triggered"""
        if state.get("protect_triggered", False):
            return END
        return "chatbot"
    
    # Build the graph
    graph_builder = StateGraph(State)
    
    # Add nodes
    graph_builder.add_node("protect_check", protect_check_node)
    graph_builder.add_node("chatbot", invoke_chatbot)
    tool_node = ToolNode(tools=tools)
    graph_builder.add_node("tools", tool_node)
    
    # Add edges
    graph_builder.add_edge(START, "protect_check")
    graph_builder.add_conditional_edges("protect_check", route_after_protect)
    graph_builder.add_conditional_edges("chatbot", tools_condition)
    graph_builder.add_edge("tools", "chatbot")
    
    return graph_builder.compile()


def main():
    """Main function to run the LangGraph agent with Azure OpenAI"""
    
    print("="*60)
    print("LangGraph Agent - Getting Started (Azure OpenAI)")
    print("="*60)
    
    # Validate Azure configuration
    if not azure_endpoint:
        print("❌ Error: AZURE_OPENAI_ENDPOINT environment variable is not set")
        print("   Set it to your Azure OpenAI endpoint (e.g., https://your-resource.openai.azure.com/)")
        return
    if not azure_api_key:
        print("❌ Error: AZURE_OPENAI_API_KEY environment variable is not set")
        print("   Set it to your Azure OpenAI API key")
        return
    if not azure_deployment:
        print("❌ Error: AZURE_OPENAI_DEPLOYMENT_NAME environment variable is not set")
        print("   This should be the NAME of your deployment in Azure Portal, not the model name.")
        print("   Example: If you created a deployment called 'my-gpt4' for the gpt-4o-mini model,")
        print("   set AZURE_OPENAI_DEPLOYMENT_NAME=my-gpt4")
        return
    
    print(f"✅ Azure OpenAI Endpoint: {azure_endpoint}")
    print(f"✅ Azure OpenAI Deployment Name: '{azure_deployment}'")
    print(f"   (Note: This is your deployment name, not the model name)")
    print(f"   ⚠️  If you see an error about 'Unknown model', check that this matches")
    print(f"      the exact deployment name in your Azure Portal (case-sensitive)")
    print(f"   💡 Common mistake: Using model name like 'gpt-4.1-mini' instead of deployment name")
    print(f"✅ Azure OpenAI API Version: {azure_api_version}")
    
    # Get or create session ID
    session_id = str(uuid.uuid4())
    print(f"Session ID: {session_id}")
    
    # Check if Protect stage exists
    protect_stage_id = None
    if stage_name:
        try:
            stage = get_protect_stage(stage_name=stage_name, project_name=project_name)
            if stage:
                protect_stage_id = stage.id
                print(f"✅ Protect enabled with stage: {stage_name} (ID: {protect_stage_id})")
            else:
                print(f"⚠️  Protect stage '{stage_name}' not found. Running without Protect.")
        except Exception as e:
            print(f"⚠️  Error getting Protect stage: {e}. Running without Protect.")
    
    # Create tools
    print("\nCreating tools...")
    tools = create_sample_tools()
    print(f"✅ Created {len(tools)} tools: {[tool.name for tool in tools]}")
    
    # System prompt
    system_prompt = """You are a helpful assistant that can use tools to help users.
You have access to tools for:
- Getting weather information
- Performing calculations
- Searching the knowledge base

Use tools when appropriate to provide accurate and helpful responses."""
    
    # Build the graph
    print("\nBuilding LangGraph agent...")
    try:
        graph = build_langgraph_agent(
            tools=tools,
            system_prompt=system_prompt,
            protect_stage_id=protect_stage_id,
            session_id=session_id
        )
        print("✅ Graph built successfully")
    except Exception as e:
        print(f"❌ Error building graph: {e}")
        return
    
    # Create config with GalileoCallback for observability
    # GalileoCallback needs project and log_stream to log traces
    galileo_logger = GalileoLogger(project=project_name, log_stream=log_stream_name)
    nanosecond_epoch_external_id = str(time.time_ns())[-5]
    galileo_logger.start_session(name=f"Agentic Workflows Session (Azure) {nanosecond_epoch_external_id}", external_id=str(session_id[-5:]))
    galileo_callback = GalileoCallback(galileo_logger=galileo_logger,
                                       start_new_trace=False)
    
    config = {
        "configurable": {"thread_id": session_id},
        "callbacks": [galileo_callback]
    }
    
    print(f"✅ GalileoCallback configured for project: {project_name}, logstream: {log_stream_name}")
    
    # Example queries
    test_queries = [
        "What's the weather in San Francisco?",
        "Calculate 25 * 4 + 10",
        "How do I reset my password?",
        "What's 2 + 2?",
    ]
    
    print("\n" + "="*60)
    print("Running Test Queries")
    print("="*60)
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n[Query {i}] {query}")
        print("-" * 60)
        
        # Start a new trace with the query as input (not the full state)
        trace = galileo_logger.start_trace(input=query)
        
        # Create initial state
        initial_state = {
            "messages": [HumanMessage(content=query)]
        }
        
        # Invoke the graph
        try:
            result = graph.invoke(initial_state, config)
            
            # Get the last AIMessage (skip ToolMessages) - extract just the content
            response_content = ""
            if result["messages"]:
                # Find the last AIMessage in the messages array
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage):
                        response_content = msg.content
                        print(f"Response: {response_content}")
                        break
                else:
                    # If no AIMessage found, use the last message's string representation
                    last_message = result["messages"][-1]
                    response_content = str(last_message)
                    print(f"Response: {response_content}")
            
            # Conclude the trace with just the content string (not the full JSON)
            # This should override whatever the callback may have logged
            galileo_logger.conclude(output=response_content, conclude_all=False)
            
            # Flush to ensure the output is persisted
            galileo_logger.flush()
            
            # Check if Protect was triggered
            if result.get("protect_triggered", False):
                print("🛡️  Protect was triggered - input was blocked")
        
        except Exception as e:
            error_str = str(e)
            print(f"❌ Error: {error_str}")
            
            # Provide helpful guidance for common Azure OpenAI errors
            if "unknown_model" in error_str.lower() or "unavailable_model" in error_str.lower():
                print("\n" + "="*60)
                print("🔍 Azure OpenAI Model Error - Troubleshooting:")
                print("="*60)
                print(f"1. Your deployment name is: '{azure_deployment}'")
                print("2. This must match EXACTLY (case-sensitive) the deployment name in Azure Portal")
                print("3. Common issues:")
                print("   - Typo in model name (e.g., 'gpt-4.1-mini' should be 'gpt-4o-mini')")
                print("   - Deployment name doesn't match what's in Azure Portal")
                print("   - Deployment was deleted or doesn't exist")
                print("\nTo fix:")
                print("1. Go to Azure Portal > Your OpenAI Resource > Deployments")
                print("2. Find your deployment and copy its EXACT name")
                print("3. Update AZURE_OPENAI_DEPLOYMENT_NAME in your .env file")
                print("="*60 + "\n")
            
            import traceback
            traceback.print_exc()
            # Conclude trace with error
            galileo_logger.conclude(output=f"Error: {str(e)}", conclude_all=False)
        
        # Small delay between queries
        time.sleep(1)
    
    print("\n" + "="*60)
    print("✅ Completed! Check Galileo Console for traces and metrics.")
    print("="*60)


if __name__ == "__main__":
    main()

