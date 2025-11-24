"""
LangGraph Agent - Getting Started with Agentic Workflows

This script demonstrates how to build a LangGraph agent with:
- Tool usage (agentic workflows)
- RAG support (optional)
- Galileo Protect integration
- Galileo observability via GalileoCallback
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

# Load .env from the root directory (three levels up from script: agentic-workflows -> getting_started -> engineers -> root)
env_path = SCRIPT_DIR.parent.parent.parent / ".env"
load_dotenv(env_path)

# Get project and stage names from environment
project_name = os.getenv("GALILEO_PROJECT")
log_stream_name = os.getenv("GALILEO_LOG_STREAM_DEV") + "-agent"
stage_name = os.getenv("GALILEO_PROTECT_STAGE_NAME")

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
    """Build a LangGraph agent with Protect integration"""
    
    # Create the LLM with tools
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.7,
        name="Galileo Assistant"
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
    """Main function to run the LangGraph agent"""
    
    print("="*60)
    print("LangGraph Agent - Getting Started")
    print("="*60)
    
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
    graph = build_langgraph_agent(
        tools=tools,
        system_prompt=system_prompt,
        protect_stage_id=protect_stage_id,
        session_id=session_id
    )
    print("✅ Graph built successfully")
    
    # Create config with GalileoCallback for observability
    # GalileoCallback needs project and log_stream to log traces
    galileo_logger = GalileoLogger(project=project_name, log_stream=log_stream_name)
    nanosecond_epoch_external_id = str(time.time_ns())[0:5]
    galileo_logger.start_session(name=f"Agentic Workflows Session {session_id[-4]}", external_id=str(nanosecond_epoch_external_id))
    galileo_callback = GalileoCallback(galileo_logger=galileo_logger,
                                       start_new_trace=True)
    
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
        
        # Create initial state
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "protect_triggered": False
        }
        
        # Invoke the graph
        try:
            result = graph.invoke(initial_state, config)
            
            # Get the last message
            if result["messages"]:
                last_message = result["messages"][-1]
                if isinstance(last_message, AIMessage):
                    print(f"Response: {last_message.content}")
                else:
                    print(f"Response: {last_message}")
            
            # Check if Protect was triggered
            if result.get("protect_triggered", False):
                print("🛡️  Protect was triggered - input was blocked")
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        # Small delay between queries
        time.sleep(1)
    
    print("\n" + "="*60)
    print("✅ Completed! Check Galileo Console for traces and metrics.")
    print("="*60)


if __name__ == "__main__":
    main()

