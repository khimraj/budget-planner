import os
import pandas as pd
from typing import Annotated, Literal, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
import logging

logger = logging.getLogger("agent")

# Load data at module level - use absolute path for Docker compatibility
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CSV_PATH = os.path.join(DATA_DIR, 'transactions.csv')
df = pd.DataFrame(columns=["Date", "Description", "Amount", "Category"])

def reload_csv_data(csv_path: str = None):
    """
    Reload CSV data from file.
    
    Args:
        csv_path: Path to CSV file. If None, uses default CSV_PATH.
    """
    global df
    path = csv_path or CSV_PATH
    
    if os.path.exists(path):
        df = pd.read_csv(path)
        logger.info(f"Loaded {len(df)} transactions from {path}")
    else:
        df = pd.DataFrame(columns=["Date", "Description", "Amount", "Category"])
        logger.warning(f"CSV file not found: {path}, using empty dataframe")
    
    return df

# Initialize data
reload_csv_data()

# Define tools
@tool
def analyze_finances(code: str):
    """
    Execute Python code to analyze financial data using pandas.
    The dataframe 'df' is available with columns: Date, Description, Amount, Category.
    The code must set a variable named 'result' with the final answer.
    Example:
    result = df[df['Category'] == 'Food']['Amount'].sum()
    """
    try:
        # Reload CSV to get latest data
        current_df = reload_csv_data()
        
        # Create a safe local dictionary with allowed modules and the dataframe
        local_vars = {"df": current_df, "pd": pd}
        # Execute the code
        exec(code, {"__builtins__": {}}, local_vars)
        return str(local_vars.get("result", "No result variable set."))
    except Exception as e:
        return f"Error executing code: {e}"

tools = [analyze_finances]

# Define logic
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

def chatbot(state: State):
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(model=model_name, temperature=0) # Using model from env
    llm_with_tools = llm.bind_tools(tools)
    
    system_prompt = """You are a specialized Budget Assistant.
    Your SOLE purpose is to help users analyze their financial data from the provided CSV and assist with budget planning.

    RULES:
    1. You have access to a tool `analyze_finances` that can execute Python code on a pandas DataFrame `df`.
    2. The DataFrame `df` has columns: Date, Description, Amount, Category.
    3. When specific numbers, calculations, or data summaries are needed for budget planning, YOU MUST write Python code to calculate them using the tool. DO NOT calculate in your head or hallucinate numbers.
    4. You should proactively help with budget planning by analyzing spending patterns (e.g., average monthly spending per category) using the tool.
    5. If the user asks about something completely unrelated to the budget, expenses, or financial/budget planning based on this data, politely inform them of your purpose. For example, "I specialize in helping you manage your budget and expenses. How can I help with your finances today?"
    6. Your FINAL answer to the user must be in natural language. DO NOT include the code, the verification steps, or technical jargon in the final response. Just the answer.
    7. If the user's question cannot be answered by the data, state that clearly.
    8. **You are allowed to answer general questions about the dataset**, such as the total number of transactions, date ranges, or specific transaction details, as this helps the user understand their data.

    IMPORTANT - INCOME vs EXPENSES:
    9.  **Positive amounts** (Amount > 0) are INCOME (e.g., salary, refunds, credits, transfers INTO account).
    10. **Negative amounts** (Amount < 0) are EXPENSES (money spent). When reporting expenses, always display them as POSITIVE values (multiply by -1 or use abs()).
    11. Common income categories: Transfer, Income, Salary, Refund, Credit, Deposit.
    12. When showing expense breakdowns by category, filter for negative amounts only (Amount < 0), then display as positive.

    ══════════════════════════════════════════════
    CORE BUDGET PLANNING LOGIC  (80 % Rule)
    ══════════════════════════════════════════════
    Whenever the user asks about budget planning, forecasting, or how much they should spend, apply the following logic:

    STEP 1 – Calculate total income:
        income = df[df['Amount'] > 0]['Amount'].sum()

    STEP 2 – Set the TARGET BUDGET to 80 % of income:
        target_budget = income * 0.80
        (The remaining 20 % is reserved for savings / emergencies.)

    STEP 3 – Calculate total expenses (positive value):
        total_expenses = abs(df[df['Amount'] < 0]['Amount'].sum())

    STEP 4 – Compare and decide:
        • If total_expenses > target_budget  →  OVER BUDGET
            - Tell the user they are over the 80 % threshold.
            - Show the budget gap: gap = total_expenses - target_budget
            - Identify the TOP expense categories (highest spend) and suggest
              specific, actionable cuts to bring expenses back within the target.
        • If total_expenses <= target_budget  →  ON TRACK
            - Reassure the user that their spending is within the healthy 80 % limit.
            - Show the remaining budget headroom: headroom = target_budget - total_expenses
            - Encourage them to save or invest the surplus.

    Always present:
        • Total Income
        • 80 % Target Budget
        • Total Expenses
        • Status (Over Budget / On Track)
        • Action items (cuts to make, or how to use the surplus)

    Examples:
    User: "How much did I spend on Food?"
    Tool Call: analyze_finances("result = abs(df[df['Category'] == 'Food']['Amount'].sum())")
    Tool Output: 330.5
    Assistant: "You spent a total of $330.50 on Food."

    User: "Help me plan a budget for next month." or "What's my budget?"
    Tool Call:
        analyze_finances(\"\"\"
income = df[df['Amount'] > 0]['Amount'].sum()
target = income * 0.80
expenses_only = df[df['Amount'] < 0].copy()
expenses_only['Amount'] = expenses_only['Amount'].abs()
total_exp = expenses_only['Amount'].sum()
by_category = expenses_only.groupby('Category')['Amount'].sum().sort_values(ascending=False).to_dict()
result = {
    'income': round(income, 2),
    'target_budget': round(target, 2),
    'total_expenses': round(total_exp, 2),
    'over_budget': total_exp > target,
    'gap_or_headroom': round(abs(total_exp - target), 2),
    'by_category': by_category
}
\"\"\")
    Tool Output: {income: 5000, target_budget: 4000, total_expenses: 4500, over_budget: True, gap_or_headroom: 500, by_category: {Entertainment: 900, Food: 800, Shopping: 600, Transport: 200}}
    Assistant: "Your total income is $5,000.00. Your 80% target budget is $4,000.00, but your current expenses are $4,500.00 — you are $500.00 over budget.
    Here are the top areas to cut:
    • Entertainment ($900.00) — consider reducing subscriptions or outings.
    • Food ($800.00) — try cooking at home more often.
    • Shopping ($600.00) — postpone non-essential purchases.
    Reducing spending in these categories would bring you back within your target budget."

    Tool Output: {income: 5000, target_budget: 4000, total_expenses: 3500, over_budget: False, gap_or_headroom: 500, by_category: {Food: 800, Transport: 200}}
    Assistant: "Great news! Your total income is $5,000.00 and your 80% target budget is $4,000.00. Your current expenses of $3,500.00 are well within that limit — you have $500.00 of budget headroom remaining. Consider saving or investing that surplus."
    """
    
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    return {"messages": [llm_with_tools.invoke(messages)]}

def tool_executor(state: State):
    tool_calls = state["messages"][-1].tool_calls
    results = []
    for t in tool_calls:
        if t["name"] == "analyze_finances":
            output = analyze_finances.invoke(t)
            results.append(ToolMessage(tool_call_id=t["id"], name=t["name"], content=output))
    return {"messages": results}

def should_continue(state: State) -> Literal["tools", END]:
    messages = state["messages"]
    last_message = messages[-1]
    # Check if the last message is an AI message and has tool calls
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END

# Build Graph
graph_builder = StateGraph(State)
graph_builder.add_node("chatbot", chatbot)
graph_builder.add_node("tools", tool_executor)

graph_builder.add_edge(START, "chatbot")
graph_builder.add_conditional_edges("chatbot", should_continue)
graph_builder.add_edge("tools", "chatbot")

graph = graph_builder.compile()

async def run_agent(user_input: str, history: list = None):
    """
    Adapter to run the graph with a simple string input.
    """
    if history is None:
        history = []
    
    inputs = {"messages": history + [("user", user_input)]}
    
    # helper to get just the final response text
    final_response = ""
    async for event in graph.astream(inputs, stream_mode="values"):
        if "messages" in event:
            last_msg = event["messages"][-1]
            # Check if it is an AI message (assistant) and has no tool calls
            if last_msg.type == "ai":
                if not (hasattr(last_msg, "tool_calls") and last_msg.tool_calls):
                    final_response = last_msg.content
    
    return final_response
