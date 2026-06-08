import os
import re
import json
import logging
import asyncio
import subprocess
import httpx
import time
from typing import List, Dict, Any, AsyncGenerator, Tuple, Optional
from loco.config import config
from loco.engine import engine
from loco.rag import rag_index

logger = logging.getLogger("loco.agent")

# --- Human-In-The-Loop (HITL) Approval Manager ---

class ApprovalManager:
    def __init__(self):
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}

    def create_request(self, req_id: str, tool_name: str, arguments: Dict[str, Any]) -> asyncio.Event:
        event = asyncio.Event()
        self.pending_approvals[req_id] = {
            "tool_name": tool_name,
            "arguments": arguments,
            "event": event,
            "approved": False,
            "resolved": False
        }
        logger.info(f"[HITL] Created approval request {req_id} for tool '{tool_name}'")
        return event

    def resolve_request(self, req_id: str, approved: bool):
        if req_id in self.pending_approvals:
            self.pending_approvals[req_id]["approved"] = approved
            self.pending_approvals[req_id]["resolved"] = True
            self.pending_approvals[req_id]["event"].set()
            logger.info(f"[HITL] Resolved approval request {req_id}: approved={approved}")
        else:
            logger.warning(f"[HITL] Attempted to resolve non-existent request {req_id}")

approval_manager = ApprovalManager()


# --- Skills & Dynamic Tools Manager ---

def load_skills() -> List[Dict[str, Any]]:
    """Scan the skills directory and load all Markdown skill files (including YAML frontmatter format)."""
    skills = []
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    
    if not os.path.exists(skills_dir):
        os.makedirs(skills_dir, exist_ok=True)
        return skills
        
    for file in os.listdir(skills_dir):
        if file.endswith(".md"):
            file_path = os.path.join(skills_dir, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                title = None
                description = None
                
                # Check for YAML frontmatter
                yaml_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
                if yaml_match:
                    yaml_content = yaml_match.group(1)
                    name_match = re.search(r"^name:\s*(.*)$", yaml_content, re.MULTILINE)
                    desc_match = re.search(r"^description:\s*(.*)$", yaml_content, re.MULTILINE)
                    if name_match:
                        title = name_match.group(1).strip()
                    if desc_match:
                        description = desc_match.group(1).strip()
                
                # Fallback to standard # Skill: formatting if not parsed from frontmatter
                if not title:
                    title_match = re.search(r"^# Skill:\s*(.*)$", content, re.MULTILINE)
                    title = title_match.group(1).strip() if title_match else file[:-3]
                if not description:
                    desc_match = re.search(r"^Description:\s*(.*)$", content, re.MULTILINE)
                    description = desc_match.group(1).strip() if desc_match else "Custom developer skill."
                
                skills.append({
                    "id": file[:-3],
                    "title": title,
                    "description": description,
                    "instructions": content
                })
            except Exception as e:
                logger.error(f"Error loading skill file {file}: {e}")
                
    return skills

SKILL_KEYWORDS = {
    "unit_test": [
        "test", "unittest", "pytest", "jest", "unit test", "spec", "assert",
        "vitest", "coverage", "test case", "test suite", "edge case", "boundary",
        "regression", "mock", "stub", "fixture", "test coverage", "tdd",
        "test driven", "integration test", "write tests", "add tests"
    ],
    "code_review": [
        "review", "audit", "code review", "static analysis", "pr review",
        "code quality", "find bugs", "bug hunt", "security audit", "vulnerability",
        "code smell", "tech debt", "technical debt", "refactor review", "inspect",
        "verify code", "check code", "validate code", "correctness", "logic error",
        "race condition", "injection", "xss", "sql injection"
    ],
    "optimize": [
        "optimize", "perf", "performance", "speed up", "refactor", "latency",
        "complexity", "bottleneck", "slow", "memory leak", "cache", "profiling",
        "benchmark", "throughput", "scalability", "n+1", "big-o", "o(n)",
        "reduce memory", "faster", "efficient"
    ],
    "frontend-design": ["frontend", "css", "html", "react", "vue", "landing page", "dashboard", "style", "ui", "ux", "beautify", "layout"],
    "webapp-testing": ["webapp testing", "e2e", "playwright", "cypress", "web test", "selenium"],
    "pptx": ["powerpoint", "pptx", "slide", "presentation"],
    "docx": ["word document", "docx", "document design"],
    "xlsx": ["excel", "xlsx", "spreadsheet", "sheet"],
    "pdf": ["pdf", "report pdf", "generate pdf"],
    "mcp-builder": ["mcp", "model context protocol", "mcp server"],
    "algorithmic-art": ["art", "canvas art", "creative layout", "p5.js", "creative coding"],
    "theme-factory": ["theme", "color palette", "styling system", "design system"],
    "doc-coauthoring": ["coauthor", "co-author", "collaborate document", "write documentation"],
    "brand-guidelines": ["brand", "color guide", "logo style", "typography guide"],
    "canvas-design": ["canvas", "vector art", "svg path", "drawing canvas"],
    "claude-api": ["claude api", "anthropic api", "messages api"],
    "internal-comms": ["announcement", "internal comms", "email template", "newsletter"],
    "skill-creator": ["create skill", "new skill", "define skill", "agent skill"],
    "slack-gif-creator": ["slack gif", "gif creator", "animated gif"],
    "web-artifacts-builder": ["artifacts", "artifact builder", "web app component"]
}

def detect_skills(prompt: str) -> Optional[Dict[str, Any]]:
    """Determine if a prompt matches a specific developer skill based on keywords."""
    skills = load_skills()
    prompt_lower = prompt.lower()
    
    best_skill = None
    max_hits = 0
    
    for skill in skills:
        skill_id = skill["id"]
        keywords = SKILL_KEYWORDS.get(skill_id, [skill_id.replace("-", " ")])
        
        hits = 0
        for kw in keywords:
            if kw in prompt_lower:
                hits += 1
                
        if hits > max_hits:
            max_hits = hits
            best_skill = skill
            
    return best_skill

async def sync_anthropic_skills() -> Dict[str, Any]:
    """Download all official skills from the Anthropic repository and cache them locally."""
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    os.makedirs(skills_dir, exist_ok=True)
    
    skills_to_download = list(SKILL_KEYWORDS.keys())
    # Skip native/built-in ones
    for native in ["unit_test", "code_review", "optimize"]:
        if native in skills_to_download:
            skills_to_download.remove(native)
            
    downloaded = []
    failed = []
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        for skill_name in skills_to_download:
            url = f"https://raw.githubusercontent.com/anthropics/skills/main/skills/{skill_name}/SKILL.md"
            dest_path = os.path.join(skills_dir, f"{skill_name}.md")
            try:
                res = await client.get(url, follow_redirects=True)
                if res.status_code == 200:
                    with open(dest_path, "w", encoding="utf-8") as f:
                        f.write(res.text)
                    downloaded.append(skill_name)
                    logger.info(f"Successfully synced skill: {skill_name}")
                else:
                    failed.append((skill_name, f"HTTP {res.status_code}"))
            except Exception as e:
                failed.append((skill_name, str(e)))
                logger.error(f"Failed to sync skill {skill_name}: {e}")
                
    return {
        "status": "success" if not failed else "partial_success",
        "downloaded": downloaded,
        "failed": failed
    }


# --- Web Search Tool (DuckDuckGo Lite Parser) ---

async def perform_web_search(query: str) -> str:
    url = "https://lite.duckduckgo.com/lite/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    data = {"q": query}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, data=data, headers=headers)
            if response.status_code != 200:
                return f"Web search failed: HTTP {response.status_code}"
            
            html = response.text
            snippets = re.findall(r'<td class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)
            titles = re.findall(r'<a[^>]*class="result-link"[^>]*>(.*?)</a>', html, re.DOTALL)
            
            if not snippets:
                return "No search results found."
                
            results_text = []
            for i in range(min(5, len(snippets))):
                title = re.sub(r'<[^>]+>', '', titles[i]).strip() if i < len(titles) else "Result"
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                snippet = snippet.replace("&amp;", "&").replace("&quot;", '"').replace("&#x27;", "'").replace("&lt;", "<").replace("&gt;", ">")
                results_text.append(f"[{i+1}] {title}\n    {snippet}")
                
            return "\n\n".join(results_text)
    except Exception as e:
        logger.error(f"Error during DuckDuckGo search: {e}")
        return f"Web search error: {e}"

def get_project_summary() -> str:
    workspace_dir = config.workspace_dir
    if not os.path.exists(workspace_dir):
        return "Workspace directory not found."
    summary = [f"Project Directory: {workspace_dir}"]
    config_files = ["package.json", "requirements.txt", "pyproject.toml", "cargo.toml", "go.mod", "docker-compose.yml", "config.json", "app.json"]
    found_configs = []
    for f in config_files:
        if os.path.exists(os.path.join(workspace_dir, f)):
            found_configs.append(f)
    summary.append(f"Configuration Files Found: {', '.join(found_configs) if found_configs else 'None'}")
    try:
        items = os.listdir(workspace_dir)
        dirs = [d for d in items if os.path.isdir(os.path.join(workspace_dir, d)) and d not in [".git", "__pycache__", ".venv", "node_modules"]]
        files = [f for f in items if os.path.isfile(os.path.join(workspace_dir, f))]
        summary.append(f"Top-level directories: {', '.join(dirs[:10])}")
        summary.append(f"Top-level files: {', '.join(files[:10])}")
        for f in found_configs:
            try:
                with open(os.path.join(workspace_dir, f), "r", encoding="utf-8") as f_ptr:
                    content = f_ptr.read()
                    summary.append(f"\n--- {f} ---\n" + content[:1000] + ("...\n[Truncated]" if len(content) > 1000 else ""))
            except: pass
    except Exception as e:
        summary.append(f"Error reading directory: {e}")
    return "\n".join(summary)


# --- Command Execution ---

def execute_command_safely(cmd: str) -> str:
    forbidden_tokens = ["rm ", "del ", "format", "mkfs", "shutdown", "wget", "curl", "ssh", "ftp"]
    for token in forbidden_tokens:
        if token in cmd.lower():
            return f"Error: Command rejected due to unsafe token '{token}'."
            
    workspace_dir = config.workspace_dir
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10.0
        )
        output = result.stdout + result.stderr
        if not output.strip():
            return "Command ran successfully with no output."
        return output[:2000]
    except subprocess.TimeoutExpired:
        return "Error: Command timed out (10s limit)."
    except Exception as e:
        return f"Error executing command: {str(e)}"


# --- Tools Operations ---
import shutil

def resolve_safe_path(rel_path: str) -> Optional[str]:
    workspace_dir = config.workspace_dir
    full_path = os.path.abspath(os.path.join(workspace_dir, rel_path))
    if not full_path.startswith(os.path.abspath(workspace_dir)):
        return None
    return full_path

async def call_tool(name: str, arguments: Dict[str, Any]) -> str:
    workspace_dir = config.workspace_dir
    
    if name == "read_file":
        rel_path = arguments.get("path", "")
        full_path = resolve_safe_path(rel_path)
        if not full_path: return "Error: Access denied. Path escapes workspace boundary."
        if not os.path.exists(full_path): return f"Error: File '{rel_path}' not found."
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return f"--- FILE CONTENT: {rel_path} ---\n{content}"
        except Exception as e: return f"Error reading file: {e}"
            
    elif name == "write_file":
        rel_path = arguments.get("path", "")
        content = arguments.get("content", "")
        full_path = resolve_safe_path(rel_path)
        if not full_path: return "Error: Access denied. Path escapes workspace boundary."
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote file: {rel_path}"
        except Exception as e: return f"Error writing file: {e}"
            
    elif name == "list_directory":
        rel_path = arguments.get("path", "")
        full_path = resolve_safe_path(rel_path)
        if not full_path: return "Error: Access denied. Path escapes workspace boundary."
        if not os.path.exists(full_path): return f"Error: Directory '{rel_path}' not found."
        try:
            items = os.listdir(full_path)
            items = [item for item in items if item not in [".git", "__pycache__", ".venv", "node_modules"]]
            return f"Directory listing for '{rel_path}':\n" + "\n".join(items)
        except Exception as e: return f"Error listing directory: {e}"
            
    elif name == "web_search":
        query = arguments.get("query", "")
        return await perform_web_search(query)
        
    elif name == "run_command":
        cmd = arguments.get("command", "")
        return execute_command_safely(cmd)
        
    elif name == "analyze_project":
        return get_project_summary()
        
    elif name == "search_codebase":
        query = arguments.get("query", "")
        results = await rag_index.search(query, top_k=10)
        if not results:
            return "No results found."
        output = []
        for r in results:
            output.append(f"--- {r['file_path']} (Lines {r['start_line']}-{r['end_line']}) ---\n{r['content']}")
        return "\n\n".join(output)
        
    elif name == "delete_file":
        rel_path = arguments.get("path", "")
        full_path = resolve_safe_path(rel_path)
        if not full_path: return "Error: Access denied. Path escapes workspace boundary."
        try:
            if os.path.exists(full_path):
                if os.path.isdir(full_path): shutil.rmtree(full_path)
                else: os.remove(full_path)
                return f"Successfully deleted {rel_path}"
            return f"Error: File '{rel_path}' not found."
        except Exception as e: return f"Error deleting file: {e}"
        
    elif name == "move_file":
        src = arguments.get("source", "")
        dest = arguments.get("destination", "")
        full_src = resolve_safe_path(src)
        full_dest = resolve_safe_path(dest)
        if not full_src or not full_dest: return "Error: Access denied. Path escapes workspace."
        try:
            os.makedirs(os.path.dirname(full_dest), exist_ok=True)
            shutil.move(full_src, full_dest)
            return f"Successfully moved {src} to {dest}"
        except Exception as e: return f"Error moving file: {e}"

    elif name == "copy_file":
        src = arguments.get("source", "")
        dest = arguments.get("destination", "")
        full_src = resolve_safe_path(src)
        full_dest = resolve_safe_path(dest)
        if not full_src or not full_dest: return "Error: Access denied. Path escapes workspace."
        try:
            os.makedirs(os.path.dirname(full_dest), exist_ok=True)
            if os.path.isdir(full_src): shutil.copytree(full_src, full_dest)
            else: shutil.copy2(full_src, full_dest)
            return f"Successfully copied {src} to {dest}"
        except Exception as e: return f"Error copying file: {e}"

    elif name == "create_directory":
        rel_path = arguments.get("path", "")
        full_path = resolve_safe_path(rel_path)
        if not full_path: return "Error: Access denied. Path escapes workspace boundary."
        try:
            os.makedirs(full_path, exist_ok=True)
            return f"Successfully created directory: {rel_path}"
        except Exception as e: return f"Error creating directory: {e}"

    return f"Error: Tool '{name}' is not supported."


# --- OpenAI Response Streaming Format ---

def format_openai_chunk(content: str, model: str, finish_reason: Optional[str] = None, extra_delta: Optional[Dict[str, Any]] = None) -> str:
    delta = {"content": content} if content else {}
    if extra_delta:
        for k, v in extra_delta.items():
            delta[k] = v
            
    chunk = {
        "id": "chatcmpl-loco",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason
            }
        ]
    }
    return f"data: {json.dumps(chunk)}\n\n"


# --- ReAct Agent Loop Parser ---

def parse_react_action(text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Parse action string blocks from ReAct outputs:
    Action: tool_name
    Arguments: {"arg": "value"}
    """
    action_match = re.search(r"Action:\s*(\w+)", text)
    args_match = re.search(r"Arguments:\s*({.*?})", text, re.DOTALL)
    
    if action_match and args_match:
        tool_name = action_match.group(1).strip()
        try:
            arguments = json.loads(args_match.group(1).strip())
            return tool_name, arguments
        except json.JSONDecodeError:
            # Try parsing key-values if JSON parsing fails directly
            raw_args = args_match.group(1).strip()
            # Simple fallback regex parser for basic strings
            arg_map = {}
            for k, v in re.findall(r'"(\w+)":\s*"([^"]+)"', raw_args):
                arg_map[k] = v
            return tool_name, arg_map
            
    return None


# --- Core Agent Chat Completions Router ---

async def compress_context(messages: List[Dict[str, str]]) -> str:
    """Summarizes old conversation history using the LLM to free up context window."""
    if not messages: return ""
    prompt = "Summarize the following conversation history to capture the core intent, key decisions, and completed tasks. Keep it concise but retain technical context.\n\n"
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if len(content) > 1000: content = content[:1000] + "... [Truncated]"
        prompt += f"[{role.upper()}]:\n{content}\n\n"
        
    summary_messages = [{"role": "user", "content": prompt}]
    summary = ""
    async for chunk in engine.generate_chat_stream(config.reasoning_model, summary_messages):
        if "error" not in chunk:
            summary += chunk.get("message", {}).get("content", "")
    return summary.strip()

async def execute_agent_chat(
    messages: List[Dict[str, str]],
    stream: bool = True
) -> AsyncGenerator[str, None]:
    
    is_up = await engine.check_status()
    if not is_up:
        yield format_openai_chunk(
            "**[LocoEngine ERROR]** Local model engine (Ollama) is not running.\n"
            "Please ensure Ollama is active or configure the Native runner.",
            "loco-error",
            "stop"
        )
        yield "data: [DONE]\n\n"
        return

    # Extract user prompt
    user_query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_query = msg.get("content", "")
            break

    # 1. RAG context query
    rag_context = ""
    if config.enable_rag and user_query:
        search_results = await rag_index.search(user_query, top_k=config.get("rag_top_k", 5))
        if search_results:
            rag_context_blocks = []
            for r in search_results:
                filename = os.path.basename(r["file_path"])
                rag_context_blocks.append(
                    f"--- FILE: {filename} (Lines {r['start_line']}-{r['end_line']}) ---\n"
                    f"{r['content']}\n"
                )
            rag_context = "\n".join(rag_context_blocks)

    # 2. Dynamic Skill checks
    matched_skill_prompt = ""
    if user_query:
        skill = detect_skills(user_query)
        if skill:
            matched_skill_prompt = f"\n\n[Skill Guidelines: {skill['title']}]\n{skill['instructions']}"

    # Build base instruction sets
    base_system = config.get("system_prompt")
    if rag_context:
        base_system += f"\n\nUse the following relevant file chunks from the user's workspace as source context:\n```\n{rag_context}\n```"
    if matched_skill_prompt:
        base_system += matched_skill_prompt

    # Project Discovery & Workflow guidelines for high-level understanding
    base_system += (
        "\n\n[PROJECT DISCOVERY & SYSTEM DESIGN GUIDELINES]\n"
        "To understand the system design, architecture, dataflow, and workflows of this project:\n"
        "1. **Config Discovery**: Locate and read configuration files first (e.g. config.json, package.json, requirements.txt, app.json, settings.json) to understand how the project is configured and structured.\n"
        "2. **Tools-First Investigation**: In AGENT mode, before modifying code, use tools to search and read file structures first to map symbols, functions, and files.\n"
        "3. **Trace Dataflow**: Follow imports and exports to see how data moves from interfaces/routes to databases and logic components.\n"
        "4. **Human-In-The-Loop Command Safety**: Since shell commands require user approval before execution, write a detailed Thought explaining exactly what the command does so the user can make an informed decision.\n"
        "5. **Dynamic Skills**: Apply loaded skill rules (e.g. unit tests, reviews, or optimizations) when performing code edits.\n"
        "6. **Library Research**: ALWAYS perform thorough research (e.g. via web_search or read_file) before proposing or installing any third-party libraries. You MUST understand why that specific tool is the best fit for the system design and security context before adopting it."
    )

    # Extract dynamic gateway operation mode (Code Mode vs Plan Mode vs Agent Mode)
    mode = config.get("gateway_mode", "code")  # default is code mode
    
    logger.info(f"Executing request in gateway mode: {mode}")

    # Adjust instructions based on mode
    if mode == "plan":
        base_system += (
            "\n\n[MODE: PLAN MODE]\n"
            "You MUST plan the whole task first. Outline a step-by-step checklist of actions "
            "as a markdown checklist using `- [ ]`. Do not write code blocks or modify any files yet. "
            "Explain what you plan to accomplish, and ask the user for approval to execute."
        )
    elif mode == "agent":
        base_system += (
            "\n\n[MODE: AGENT MODE - ReAct Autonomous Loop]\n"
            "You are working in an autonomous loop. You can use tools to gather information or modify files.\n"
            "Available tools:\n"
            "1. `read_file(path: string)`: Read workspace file content.\n"
            "2. `write_file(path: string, content: string)`: Write/create code files in workspace.\n"
            "3. `list_directory(path: string)`: List files and folders in workspace.\n"
            "4. `web_search(query: string)`: Search the web for syntax or documentation.\n"
            "5. `run_command(command: string)`: Run command lines (like compiling, running test suites).\n"
            "6. `analyze_project()`: Get a high-level summary of the codebase structure and configurations.\n"
            "7. `search_codebase(query: string)`: Perform a hybrid semantic/keyword search across the entire codebase.\n"
            "8. `delete_file(path: string)`: Delete a file or folder from the workspace.\n"
            "9. `move_file(source: string, destination: string)`: Move or rename a file or folder.\n"
            "10. `copy_file(source: string, destination: string)`: Copy a file or folder.\n"
            "11. `create_directory(path: string)`: Create a new empty folder.\n\n"
            "For each step, you MUST respond exactly in the following format:\n"
            "Thought: <your reasoning step>\n"
            "Action: <tool_name>\n"
            "Arguments: {\"<arg_name>\": \"<arg_val>\"}\n\n"
            "After receiving the Tool Observation, continue your thought loop. When the task is complete, respond with:\n"
            "Thought: <finished analysis>\n"
            "Final Answer: <your final complete response to the user>\n"
        )
    else:
        # Default Code Mode
        base_system += "\n\n[MODE: CODE MODE]\nDirectly implement the requested changes and answer the task."

    # Format initial messages list
    working_messages = []
    has_system = False
    
    # Cascade Memory Management
    user_assistant_msgs = [m for m in messages if m.get("role") != "system"]
    cascade_summary = ""
    if len(user_assistant_msgs) > 12:
        recent_msgs = user_assistant_msgs[-6:]
        old_msgs = user_assistant_msgs[:-6]
        logger.info(f"Context window large ({len(user_assistant_msgs)} msgs). Compressing older messages via Cascade...")
        cascade_summary = await compress_context(old_msgs)
        messages = [m for m in messages if m.get("role") == "system"] + recent_msgs
        if cascade_summary:
            base_system += f"\n\n[CASCADED MEMORY CONTEXT]\n{cascade_summary}"
            
    for msg in messages:
        if msg.get("role") == "system":
            working_messages.append({"role": "system", "content": base_system})
            has_system = True
        else:
            working_messages.append(msg)
    if not has_system:
        working_messages.insert(0, {"role": "system", "content": base_system})

    reasoning_model = config.reasoning_model
    coding_model = config.coding_model

    # --- Mode Executions ---

    if mode == "agent":
        # Autonomous ReAct Tool-Calling loop
        max_agent_turns = 5
        agent_turn = 0
        req_id = "req-" + str(int(time.time()))
        
        while agent_turn < max_agent_turns:
            agent_turn += 1
            logger.info(f"Agent Loop Turn {agent_turn}/{max_agent_turns}")
            
            accumulated_response = []
            
            # Call Ollama using the coding model for ReAct loop
            async for chunk in engine.generate_chat_stream(coding_model, working_messages):
                if "error" in chunk:
                    yield format_openai_chunk(f"\n[Agent Error]: {chunk['error']}\n", coding_model)
                    yield "data: [DONE]\n\n"
                    return
                
                content = chunk.get("message", {}).get("content", "")
                if content:
                    accumulated_response.append(content)
                    # Stream raw thoughts back to user playground
                    yield format_openai_chunk(content, coding_model)
            
            full_text = "".join(accumulated_response)
            
            # Check if final answer is provided
            if "Final Answer:" in full_text:
                logger.info("Agent found Final Answer. Stopping loop.")
                break
                
            # Parse action
            action_data = parse_react_action(full_text)
            if not action_data:
                # If the model didn't format an action or final answer, fallback and terminate to prevent loops
                logger.warning("Agent did not output standard Action block. Exiting loop.")
                yield format_openai_chunk("\n\n*Agent terminated loop: no further action required.*", coding_model)
                break
                
            tool_name, tool_args = action_data
            logger.info(f"Agent requested tool: {tool_name} with args: {tool_args}")
            
            tool_result = ""
            
            # Human-In-The-Loop: Request permissions for run_command and delete_file
            if tool_name in ["run_command", "delete_file"]:
                cmd_str = tool_args.get("command", "") if tool_name == "run_command" else f"Delete: {tool_args.get('path', '')}"
                yield format_openai_chunk(
                    f"\n\n**[LocoEngine Approval Required]** Agent wants to execute destructive action:\n"
                    f"```bash\n{cmd_str}\n```\n",
                    coding_model,
                    extra_delta={
                        "approval_required": True,
                        "tool": tool_name,
                        "req_id": req_id,
                        "command": cmd_str
                    }
                )
                
                # Register approval wait event
                event = approval_manager.create_request(req_id, tool_name, tool_args)
                
                # Await user dashboard callback approval
                logger.info(f"Awaiting user approval for command: '{cmd_str}'...")
                await event.wait()
                
                # Check user action
                req_status = approval_manager.pending_approvals.get(req_id, {})
                approved = req_status.get("approved", False)
                
                # Clean up
                if req_id in approval_manager.pending_approvals:
                    del approval_manager.pending_approvals[req_id]
                    
                if not approved:
                    tool_result = "Observation: Command execution rejected by user. Please try another approach."
                    yield format_openai_chunk("\n*Command rejected by user.*\n", coding_model)
                else:
                    yield format_openai_chunk("\n*Command approved. Executing...*\n", coding_model)
                    raw_out = await call_tool(tool_name, tool_args)
                    tool_result = f"Observation: {raw_out}"
            else:
                # Read-only tools or write-file (allow without prompt for automation, 
                # but run_command is blocked strictly)
                raw_out = await call_tool(tool_name, tool_args)
                tool_result = f"Observation: {raw_out}"
                
            logger.info(f"Tool observation collected: {tool_result[:150]}...")
            
            # Append interaction to assistant messages history
            working_messages.append({"role": "assistant", "content": full_text})
            working_messages.append({"role": "user", "content": tool_result})
            
            # Stream observation back to playground console
            yield format_openai_chunk(f"\n\n*Observation:*\n```\n{tool_result}\n```\n\n", coding_model)

    else:
        # Code Mode or Plan Mode (which is treated as direct inference with tailored prompts)
        if config.enable_cascade:
            # Cascade Mode
            yield format_openai_chunk("<think>\n", coding_model)
            accumulated_thoughts = []
            is_thinking = True
            
            async for chunk in engine.generate_chat_stream(reasoning_model, working_messages):
                if "error" in chunk:
                    yield format_openai_chunk(f"\n[Reasoning Error]: {chunk['error']}\n", coding_model)
                    break
                    
                delta_content = chunk.get("message", {}).get("content", "")
                if not delta_content:
                    continue
                    
                if "</think>" in delta_content:
                    is_thinking = False
                    parts = delta_content.split("</think>")
                    accumulated_thoughts.append(parts[0])
                    yield format_openai_chunk(parts[0], coding_model)
                    break
                    
                accumulated_thoughts.append(delta_content)
                yield format_openai_chunk(delta_content, coding_model)
                
            full_thought = "".join(accumulated_thoughts).replace("<think>", "").replace("</think>", "").strip()
            
            yield format_openai_chunk("\n</think>\n\n", coding_model)
            
            # Inject thinking step context into coder messages
            coding_messages = working_messages.copy()
            coding_messages.append({
                "role": "assistant",
                "content": f"<think>\n{full_thought}\n</think>"
            })
            
            async for chunk in engine.generate_chat_stream(coding_model, coding_messages):
                if "error" in chunk:
                    yield format_openai_chunk(f"\n[Coding Error]: {chunk['error']}\n", coding_model)
                    break
                
                delta_content = chunk.get("message", {}).get("content", "")
                if delta_content:
                    yield format_openai_chunk(delta_content, coding_model)
        else:
            # Standard single call
            async for chunk in engine.generate_chat_stream(coding_model, working_messages):
                if "error" in chunk:
                    yield format_openai_chunk(f"\n[Inference Error]: {chunk['error']}\n", coding_model)
                    break
                
                delta_content = chunk.get("message", {}).get("content", "")
                if delta_content:
                    yield format_openai_chunk(delta_content, coding_model)

    yield format_openai_chunk("", coding_model, "stop")
    yield "data: [DONE]\n\n"
