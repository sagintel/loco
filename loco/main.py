import os
import uvicorn
import logging
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import json

from loco.config import config
from loco.dashboard import router as dashboard_router
from loco.agent import execute_agent_chat
from loco.engine import engine
from loco.rag import rag_index
from loco.watcher import watcher
from loco.runner import native_runner

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("loco.main")

app = FastAPI(
    title="LocoEngine local AI Gateway",
    description="Intelligent Local AI Proxy, Cascade Router, and RAG server.",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Admin Dashboard Router
app.include_router(dashboard_router)

# Mount Dashboard Frontend Assets
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "dashboard")
if os.path.exists(DASHBOARD_DIR):
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR), name="dashboard")
else:
    logger.warning(f"Dashboard directory not found at: {DASHBOARD_DIR}")

# Root route serves the dashboard index.html
@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    index_file = os.path.join(DASHBOARD_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return """
    <html>
        <head><title>LocoEngine Server</title></head>
        <body style="font-family: sans-serif; background: #0b0c10; color: #c5c6c7; text-align: center; padding-top: 100px;">
            <h1>LocoEngine Gateway</h1>
            <p>Admin dashboard files not found under <code>loco/dashboard</code>. The API is active.</p>
            <p>API Endpoint: <code>http://localhost:8000/v1/chat/completions</code></p>
        </body>
    </html>
    """

# --- OpenAI Compatible Endpoints ---

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    OpenAI-compatible /v1/chat/completions endpoint.
    Passes messages to the agent completion routine.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
        
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    
    if not messages:
        raise HTTPException(status_code=400, detail="Missing required field 'messages'.")
        
    logger.info(f"Received completion request: {len(messages)} messages, stream={stream}")
    
    # Execute the agent loop (handles RAG, Cascade, Skills, and Tool execution)
    if stream:
        generator = execute_agent_chat(messages, stream=True)
        return StreamingResponse(generator, media_type="text/event-stream")
    else:
        # Non-streaming mode: collect chunks into a single response
        full_content = ""
        model_name = config.coding_model
        async for chunk_line in execute_agent_chat(messages, stream=True):
            if chunk_line.startswith("data: ") and not chunk_line.strip() == "data: [DONE]":
                try:
                    data = json.loads(chunk_line[6:])
                    delta = data["choices"][0]["delta"]
                    if "content" in delta:
                        full_content += delta["content"]
                except Exception:
                    continue
                    
        return {
            "id": "chatcmpl-loco",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": -1,
                "completion_tokens": -1,
                "total_tokens": -1
            }
        }

@app.get("/v1/models")
async def list_openai_models():
    """
    OpenAI-compatible /v1/models endpoint.
    Retrieves models from Ollama and formats them according to OpenAI standards.
    """
    engine_models = await engine.list_models()
    
    formatted_models = []
    if not engine_models:
        formatted_models = [
            {"id": "deepseek-r1:1.5b", "object": "model", "created": 1700000000, "owned_by": "engine"},
            {"id": "qwen2.5-coder:1.5b", "object": "model", "created": 1700000000, "owned_by": "engine"},
            {"id": "qwen2.5-coder:7b", "object": "model", "created": 1700000000, "owned_by": "engine"}
        ]
    else:
        for m in engine_models:
            name = m.get("name")
            formatted_models.append({
                "id": name,
                "object": "model",
                "created": 1700000000,
                "owned_by": "engine"
            })
            
    return {
        "object": "list",
        "data": formatted_models
    }

# Background task for initial indexing
async def initial_index():
    workspace = config.workspace_dir
    logger.info(f"System boot: scanning workspace files at {workspace} in background...")
    try:
        await asyncio.sleep(2.0) # Give server time to boot completely
        stats = await rag_index.scan_and_index(workspace)
        logger.info(f"Boot Scan Complete: {stats.get('chunks_added', 0)} chunks loaded from {stats.get('files_scanned', 0)} files.")
    except Exception as e:
        logger.error(f"Error during startup indexing: {e}")

@app.on_event("startup")
def on_startup():
    # Start the RAG background watcher daemon
    watcher.start()
    
    # Run the initial indexer in background task loop
    asyncio.create_task(initial_index())

@app.on_event("shutdown")
def on_shutdown():
    logger.info("Server shutdown initiated. Cleaning up daemon threads and subprocesses...")
    watcher.stop()
    native_runner.stop_server()

if __name__ == "__main__":
    # ASCII Header
    print(r"""
     _       ____   _____ ____  _____ _   _  ____ ___ _   _ _____ 
    | |     / __ \ / ____/ __ \|  ___| \ | |/ ___|_ _| \ | |  ___|
    | |    | |  | | |   | |  | | |__ |  \| | |  _  | ||  \| | |__  
    | |___ | |__| | |___| |__| | |___| |\  | |_| | | || |\  | |___ 
    |_____| \____/ \_____\____/|_____|_| \_|\____|___|_| \_|_____|
                                                     
               LOCAL LLM GATEWAY & AI AGENT GATEWAY
    """)
    print("==============================================================")
    print(f" * Server running on: http://{config.host}:{config.port}")
    print(f" * Web Dashboard:     http://{config.host}:{config.port}/")
    print(f" * OpenAI Endpoint:   http://{config.host}:{config.port}/v1")
    print(f" * Active Workspace:  {config.workspace_dir}")
    print("==============================================================")
    
    uvicorn.run(
        "loco.main:app", 
        host=config.host, 
        port=config.port, 
        log_level="info", 
        reload=False
    )
