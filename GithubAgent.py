from PyQt6.QtCore import pyqtSignal
import os
import json
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from tools import *
from Helper import *
load_dotenv(override=True)

PLANNER_PROMPT = get_promot("planner_agent")
WORKER_PROMPT = get_promot("worker_agent")
SYNTHESIZER_PROMPT = get_promot("synthesizer_agent")
GLOBAL_PROMPT = get_promot("global_restrictions")

def show_text(text, signal:pyqtSignal = None, override = False):
    """Show the text in the right format in the right place.
    if you connect this to my ui, it would show the correct things in the correct QWidgets
    if not, it would print you in the terminal

    Args:
        text (str): text
        signal (pyqtSignal, optional): connection to my ui. Defaults to None.
        override (bool, optional): if it prints it in the terminal, should it start new line or not. Defaults to False.
    """
    if not signal:
        if override:
            print(text)
            return
        print(text, end="", flush=True)
        return
    signal.emit(text)

def planner_agent(user_input, thinking_signal:pyqtSignal = None):
    """Planner agent, agent that gets its system prompt and users input prompt and with reasoning and the right tools
    decides how to create the ultimate plan for the worker agents so in the end the user will get what he ask to

    This function gets user_input with the restrictions prompt, (And if the UI connected then thinking signal from the ui)
    it connects with the right tools, and runs the right LLM using langchain_ollama.
    It streams the thought process of the agent, verifies that every tool has been done correctly
    and in the end returns plan list to preform users input task.

    Args:
        user_input (string): Users prompt + restrictions prompt
        thinking_signal (pyqtSignal, optional): Connection to the UI. Defaults to None.

    Returns:
        list: list of the plan
    """
    planner_tools = [list_repositories, check_repo_visibility, list_branches, list_repo_files]
    planner_llm = ChatOllama(
        model=os.getenv("MODEL"), 
        reasoning=True,
        repeat_penalty=1.15,
        temperature=0.3,
        max_tokens=4000,
    ).bind_tools(planner_tools)

    planner_messages = [SystemMessage(content=PLANNER_PROMPT), HumanMessage(content=user_input)]
    planner_res = None
    for chunk in planner_llm.stream(planner_messages):
        reasoning = chunk.additional_kwargs.get("reasoning_content", "")
        if reasoning:
            show_text(f"{reasoning}", thinking_signal, False)
        if chunk.content:
            show_text(f"{chunk.content}", thinking_signal, False)
            
        if planner_res is None:
            planner_res = chunk
        else:
            planner_res += chunk
            
    while planner_res.tool_calls:
        planner_messages.append(planner_res)
        for tool_call in planner_res.tool_calls:
            show_text(f"\n🤖 AI ACTION Requested: {tool_call['name']}({tool_call['args']})", thinking_signal, False)
            tool_name = tool_call["name"]
            tool_func = next((t for t in planner_tools if t.name == tool_name), None)
            
            if tool_func:
                try:
                    tool_output = tool_func.invoke(tool_call["args"])
                    planner_messages.append(ToolMessage(
                        content=str(tool_output), 
                        tool_call_id=tool_call["id"]
                    ))
                    show_text(f"\n🔧 [Tool '{tool_name}' completed successfully]", thinking_signal, False)
                except Exception as e:
                    show_text(f"\n  ⚠️ Error running {tool_name}: {e}", thinking_signal, False)
                    planner_messages.append(ToolMessage(
                        content=f"Error executing {tool_name}: {str(e)}", 
                        tool_call_id=tool_call["id"]
                    ))
            else:
                show_text(f"\n  ⚠️ Warning: Agent tried to use non-existent tool '{tool_name}'\n", thinking_signal, False)
                planner_messages.append(ToolMessage(
                    content=f"Error: Tool '{tool_name}' is not available.",
                    tool_call_id=tool_call["id"]
                ))   
        show_text("\n🚀 Planner processing tool results (Streaming View)...\n", thinking_signal, False)
        planner_res = None
        for chunk in planner_llm.stream(planner_messages):
            reasoning = chunk.additional_kwargs.get("reasoning_content", "")
            if reasoning:
                show_text(f"{reasoning}", thinking_signal, False)
            if chunk.content:
                show_text(f"{chunk.content}", thinking_signal, False)
                
            if planner_res is None:
                planner_res = chunk
            else:
                planner_res += chunk
        
    raw_plan = planner_res.content.strip().replace("```json", "").replace("```", "")
    try:
        execution_plan = json.loads(raw_plan)
    except json.JSONDecodeError as e:
        show_text(f"\n  ⚠️ Error: The Planner failed to output valid JSON ({e}). Halting.", thinking_signal, False)
        execution_plan = []
        
    if not execution_plan:
        show_text("  ⚠️ The Planner could not find any repositories matching your request.\n  🛑 Halting execution gracefully.", thinking_signal, False)
        return True, None
    return False, execution_plan      

def workers_agent(execution_plan, thinking_signal:pyqtSignal = None, processing_signal:pyqtSignal = None):
    """Worker agent, gets one plan prompt, worker system prompt and tools that he can access to, 
    then he runs to create the right answer for this plan.
    
    This function gets list of execution plan, (And if the UI connected then thinking signal and processing signal from the ui)
    for each plan he creates worker agent that gets connected to the right tools, prompt input and llm and runs it
    It streams the thought expiriance of the agent, verifies that every tool has been done correctly
    and in the end returns list of each worker notes.

    Args:
        execution_plan (list): plan list
        thinking_signal (pyqtSignal, optional): Connection to the UI. Defaults to None.
        processing_signal (pyqtSignal, optional): Connection to the UI. Defaults to None.

    Returns:
        list: list of workers notes
    """
    worker_token_budget = max(300 ,int(6000 / len(execution_plan)))
    worker_notes = []
    worker_llm = ChatOllama(
        model=os.getenv("MODEL"), 
        reasoning=False,
        repeat_penalty=1.15,
        temperature=0.2,      
        num_predict=worker_token_budget,
        num_ctx = 8192     
    )

    for index, task in enumerate(execution_plan):
        repo_name = task.get("repo")
        action = task.get("action")
        mode = task.get("mode", "shallow")
        instruction = task.get("instruction", "Summarize the architecture and strengths/weaknesses.")
        target_files = task.get("target_files", " ")
        
        show_text(f"🔄 Step 2.[{index + 1}]: Processing {repo_name} ({action})...", processing_signal, True)
        show_text(f"\n🔄 Step 2.[{index + 1}]: Processing {repo_name} ({action})...", thinking_signal, False)
        show_text(f"\n  📥 Cloning {repo_name}...", thinking_signal, False)
        clone_res = clone_repository.invoke({"repo_url_or_name": repo_name})    
        if "Error" in clone_res:
            show_text(f"\n  ❌ Skipping due to clone error: {clone_res}", thinking_signal, False)
            continue
        
        show_text(f"\n  📦 Running Repomix file packager...", thinking_signal, False)
        local_path = clone_res.split("'")[1]
        analysis_data = summarize_and_analyzes_cloned_repo.invoke({
            "repo_clone_folder": local_path, 
            "mode": mode,
            "target_files": target_files
        })
        
        show_text(f"\n  🧠 Worker Agent analyzing codebase...\n", thinking_signal, False)
        worker_instruction = f"INSTRUCTION: {instruction}\n\nExecute this instruction on the following codebase data:\n\n{analysis_data}"
        worker_message = [
            SystemMessage(content=WORKER_PROMPT),
            HumanMessage(content=worker_instruction)
        ]
        worker_res_content = ""
        for chunk in worker_llm.stream(worker_message):
            reasoning = chunk.additional_kwargs.get("reasoning_content", "")
            if reasoning:
                show_text(reasoning, thinking_signal, False)
            if chunk.content:
                show_text(chunk.content, thinking_signal, False)
                worker_res_content += chunk.content
                
        show_text(f"\n  🧹 Cleaning up temporary directory...\n", thinking_signal, False)
        delete_all_repository_folders.invoke({"dummy_input": ""})
        worker_notes.append(f"### Insights for {repo_name}\n{worker_res_content}\n")
    return worker_notes

def synthesizer_agent(user_prompt, worker_notes, thinking_signal:pyqtSignal = None, outputing_signal:pyqtSignal = None):
    """Synthesize agent gets users prompt with restrictions prompt, with addition to all worker agents notes and run full reasoning behind
    how to answer to the user with so the user would be satisfied by the answer
    
    This function gets users prompt with restrictions prompt, with addition to all worker agents notes  (And if the UI connected then thinking signal and outputing_signal from the ui)
    It then runs this agent with the right LLM using langchain, shows the stream output of this agent thought process
    and returns his answer to users task
    

    Args:
        user_prompt (string): users prompt with restrictions prompt
        worker_notes (list): list of all worker agents notes
        thinking_signal (pyqtSignal, optional): Connection to the UI. Defaults to None.
        outputing_signal (pyqtSignal, optional): Connection to the UI. Defaults to None.

    Returns:
        string: output of the synthesizer agent
    """
    synthesizer_llm = ChatOllama(
        model=os.getenv("MODEL"), 
        reasoning=True,
        temperature=0.3,
        repeat_penalty=1.15
    )
    
    workers_summary = "\n".join(worker_notes)
    synthesizer_message = [
        SystemMessage(content=SYNTHESIZER_PROMPT),
        HumanMessage(content=f"Original Request: {user_prompt}\n\nWorker Evaluations:\n{workers_summary}")
    ]
    synthesizer_report = ""
    for chunk in synthesizer_llm.stream(synthesizer_message):
        reasoning = chunk.additional_kwargs.get("reasoning_content", "")
        if reasoning:
            show_text(f"{reasoning}", thinking_signal, False)
        if chunk.content:
            show_text(f"{chunk.content}", outputing_signal, False)
            synthesizer_report += chunk.content
    return synthesizer_report
   
def run_full_agent(user_prompt:str, thinking_signal:pyqtSignal = None, processing_signal:pyqtSignal = None, outputing_signal:pyqtSignal = None):
    """This function runs the full agentflow, from the planner to the worker and in the end the synthesizer
    each time it shows in what step in the process it is in (for the user)
    if the planner agent sees that he cant build plan for this request, he stops this process before getting into the other agents
    

    Args:
        user_prompt (str): user request
        thinking_signal (pyqtSignal, optional): Connection to the UI. Defaults to None.
        processing_signal (pyqtSignal, optional): Connection to the UI. Defaults to None.
        outputing_signal (pyqtSignal, optional): Connection to the UI. Defaults to None.

    Raises:
        Exception: planner agent sees that he cant build plan for this request

    Returns:
        string: output of the agent
    """
    # --- Planner ---
    show_text("🚀 Step 1: Running Planner Agent to discover targets...", processing_signal, True)
    show_text("🚀 Step 1: Running Planner Agent to discover targets...\n", thinking_signal, False)
    stop, execution_plan = planner_agent(user_prompt + "\n" + GLOBAL_PROMPT, thinking_signal)
    if stop:
        raise Exception("Something went wrong.")
        
    # --- Workers --- 
    show_text(f"📋 Plan generated successfully", processing_signal, True)
    show_text(f"\n📋 Plan generated successfully\n", thinking_signal, False)
    worker_notes = workers_agent(execution_plan, thinking_signal, processing_signal)
    
    # --- Synthesizer ---
    show_text("✍️ Step 3: Synthesizer Agent compiling final Markdown document...", processing_signal, True)
    show_text("\n✍️ Step 3: Synthesizer Agent compiling final Markdown document...\n", thinking_signal, False)
    synthesizer_report = synthesizer_agent(user_prompt + "\n" + GLOBAL_PROMPT, worker_notes, thinking_signal, outputing_signal)
    
    # --- Finished ---
    show_text("✨ Finished! Check ANSWER.md for the complete evaluation.", processing_signal, True)
    return synthesizer_report

def get_prompts_list():
    """Returns list of all local paths to each prompt used in this agent
    for my UI

    Returns:
        list: all local paths to each prompt used in this agent
    """
    return [
        r"prompts\global_restrictions.txt",
        r"prompts\planner_agent.txt",
        r"prompts\synthesizer_agent.txt",
        r"prompts\worker_agent.txt",
    ]

def get_models_name():
    """Return models name used in this agent
    for my UI

    Returns:
        str: models name
    """
    return os.getenv("MODEL")

if __name__ == "__main__":
    """If this agent is called directly as a standalone script"""
    user_input = str(input("Enter your input: "))
    print(f"Model: {os.getenv('MODEL')}")
    synthesizer_report = run_full_agent(user_input)
    with open("ANSWER.md", "w", encoding="utf-8") as file:
        file.write(synthesizer_report)
    
