from PyQt6.QtCore import pyqtSignal
import os
import json
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from tools import *
from Helper import *
load_dotenv()

PLANNER_PROMPT = get_promot("planner_agent")
WORKER_PROMPT = get_promot("worker_agent")
SYNTHESIZER_PROMPT = get_promot("synthesizer_agent")
GLOBAL_PROMPT = get_promot("global_restrictions")

def show_text(text, signal:pyqtSignal = None, override = False):
    if not signal:
        if override:
            print(text)
            return
        print(text, end="", flush=True)
        return
    signal.emit(text)

def planner_agent(user_input, thinking_signal = None):
    planner_tools = [list_repositories, check_repo_visibility, list_branches]
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

def workers_agent(execution_plan, thinking_signal = None, processing_signal = None):
    worker_notes = []
    worker_llm = ChatOllama(
        model=os.getenv("MODEL"), 
        reasoning=False,
        repeat_penalty=1.15,
        temperature=0.2,      
        num_predict=300     
    )

    for index, task in enumerate(execution_plan):
        repo_name = task.get("repo")
        action = task.get("action")
        mode = task.get("mode", "shallow")
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
            "mode": mode
        })
        
        show_text(f"\n  🧠 Worker Agent analyzing codebase...\n", thinking_signal, False)
        worker_instruction = f"Perform action '{action}' on this repository: '{repo_name}'. Here is the packed codebase data:\n\n{analysis_data}"
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

def synthesizer_agent(user_prompt, worker_notes, thinking_signal = None, outputing_signal = None):
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
    
    # --- Saving ---
    show_text("✨ Finished! Check ANSWER.md for the complete evaluation.", processing_signal, True)
    return synthesizer_report

def get_prompts_list():
    return [
        "prompts\global_restrictions.txt",
        "prompts\planner_agent.txt",
        "prompts\synthesizer_agent.txt",
        "prompts\worker_agent.txt",
    ]

def get_models_name():
    return os.getenv("MODEL")

if __name__ == "__main__":
    user_input = str(input("Enter your input: "))
    print(f"Model: {os.getenv('MODEL')}")
    synthesizer_report = run_full_agent(user_input)#"Summarize my 'raytracer' repository and give it a score based on its architecture.")
    with open("ANSWER.md", "w", encoding="utf-8") as file:
        file.write(synthesizer_report)
    
