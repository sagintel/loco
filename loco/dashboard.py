import os
import re
import psutil
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import json

from loco.config import config
from loco.engine import engine
from loco.rag import rag_index
from loco.agent import load_skills

logger = logging.getLogger("loco.dashboard")
router = APIRouter(prefix="/api")

# Pydantic Schemas
class ConfigUpdateSchema(BaseModel):
    ollama_url: Optional[str] = None
    reasoning_model: Optional[str] = None
    coding_model: Optional[str] = None
    enable_cascade: Optional[bool] = None
    enable_rag: Optional[bool] = None
    rag_chunk_size: Optional[int] = None
    rag_overlap: Optional[int] = None
    rag_top_k: Optional[int] = None
    system_prompt: Optional[str] = None
    workspace_dir: Optional[str] = None
    gateway_mode: Optional[str] = None
    runner_type: Optional[str] = None

class PullModelSchema(BaseModel):
    name: str

class ApprovalSchema(BaseModel):
    req_id: str
    approved: bool

class SkillCreateSchema(BaseModel):
    id: str
    title: str
    description: str
    instructions: str

class ModelDownloadSchema(BaseModel):
    model_id: str

class ModelStartSchema(BaseModel):
    filename: str

class AddFileSchema(BaseModel):
    filename: str
    content: str

class AddUrlSchema(BaseModel):
    url: str

# 1. System Health Status
@router.get("/status")
async def get_status():
    ollama_up = await engine.check_status()
    rag_stats = rag_index.get_stats()
    
    # Check if native runner is active instead of Ollama
    runner_active = False
    if config.get("runner_type") == "native":
        from loco.runner import native_runner
        runner_active = await native_runner.check_runner_health()
        
    # Fetch system metrics
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        ram_usage = ram.percent
        ram_free_gb = round(ram.available / (1024 ** 3), 2)
        ram_total_gb = round(ram.total / (1024 ** 3), 2)
    except Exception:
        cpu_usage = 0
        ram_usage = 0
        ram_free_gb = 0
        ram_total_gb = 8 # default fallback

    is_online = (ollama_up and config.get("runner_type") == "ollama") or (runner_active and config.get("runner_type") == "native")

    return {
        "ollama_status": "online" if is_online else "offline",
        "cpu_usage_percent": cpu_usage,
        "ram_usage_percent": ram_usage,
        "ram_free_gb": ram_free_gb,
        "ram_total_gb": ram_total_gb,
        "rag_stats": rag_stats,
        "workspace_dir": config.workspace_dir
    }

# 2. Get / Set Configurations
@router.get("/config")
def get_configuration():
    return config.data

@router.post("/config")
def update_configuration(payload: ConfigUpdateSchema):
    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    config.update(update_data)
    return {"status": "success", "config": config.data}

# 3. Model Management (Ollama Proxy)
@router.get("/models")
async def get_models():
    models = await engine.list_models()
    return {"models": models}

@router.post("/models/pull")
async def pull_model(payload: PullModelSchema):
    """Start pulling a model from Ollama and stream output back via SSE."""
    async def generator():
        async for chunk in engine.pull_model_stream(payload.name):
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: {\"status\": \"complete\"}\n\n"
        
    return StreamingResponse(generator(), media_type="text/event-stream")

# 4. RAG Operations
@router.post("/rag/index")
async def trigger_rag_indexing():
    workspace = config.workspace_dir
    if not workspace or not os.path.exists(workspace):
        raise HTTPException(status_code=400, detail="Invalid workspace directory configured.")
        
    logger.info(f"Triggering manual RAG scan on workspace: {workspace}")
    
    try:
        stats = await rag_index.scan_and_index(workspace)
        return {"status": "success", "results": stats}
    except Exception as e:
        logger.error(f"RAG scan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rag/clear")
def clear_rag_index():
    rag_index.clear_index()
    return {"status": "success", "message": "RAG database cleared."}

@router.get("/rag/search")
async def search_rag(query: str, limit: int = 5):
    if not query:
        return {"results": []}
    results = await rag_index.search(query, top_k=limit)
    clean_results = []
    for r in results:
        clean_results.append({
            "file_path": r["file_path"],
            "filename": os.path.basename(r["file_path"]),
            "content": r["content"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "score": round(r["score"], 4)
        })
    return {"results": clean_results}

@router.post("/rag/add_file")
async def add_file_to_rag(payload: AddFileSchema):
    try:
        res = await rag_index.index_custom_content(payload.filename, payload.content)
        if res.get("status") == "success":
            return res
        raise HTTPException(status_code=500, detail=res.get("message", "Unknown error indexing file."))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def clean_html(html_content: str) -> str:
    html_content = re.sub(r'<(script|style)\b[^>]*>([\s\S]*?)</\1>', ' ', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<!--[\s\S]*?-->', ' ', html_content)
    html_content = re.sub(r'<[^>]*>', ' ', html_content)
    html_content = (html_content
                    .replace("&amp;", "&")
                    .replace("&quot;", '"')
                    .replace("&#x27;", "'")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&nbsp;", " "))
    html_content = re.sub(r'\s+', ' ', html_content)
    return html_content.strip()

@router.post("/rag/add_url")
async def add_url_to_rag(payload: AddUrlSchema):
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL format. Must start with http:// or https://")
    import httpx
    import re
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, follow_redirects=True)
            if res.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Failed to fetch webpage. HTTP {res.status_code}")
            
            text = clean_html(res.text)
            if len(text) < 20:
                raise HTTPException(status_code=400, detail="Scraped webpage content is empty or too short.")
            
            domain = url.split("//")[-1].split("/")[0]
            
            index_res = await rag_index.index_custom_content(domain, text)
            if index_res.get("status") == "success":
                return index_res
            raise HTTPException(status_code=500, detail=index_res.get("message", "Failed to index scraped content."))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 5. Developer Skills
@router.get("/skills")
def get_skills():
    skills = load_skills()
    return {"skills": skills}

@router.post("/skills/sync")
async def sync_skills():
    from loco.agent import sync_anthropic_skills
    result = await sync_anthropic_skills()
    return result

@router.post("/skills/create")
def create_skill(payload: SkillCreateSchema):
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    os.makedirs(skills_dir, exist_ok=True)
    file_path = os.path.join(skills_dir, f"{payload.id}.md")
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# Skill: {payload.title}\n")
            f.write(f"Description: {payload.description}\n\n")
            f.write(payload.instructions)
        return {"status": "success", "message": f"Skill '{payload.title}' created successfully."}
    except Exception as e:
        logger.error(f"Failed to write skill: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 6. Human-in-the-Loop Approval Callback
@router.post("/chat/approve")
def approve_command(payload: ApprovalSchema):
    from loco.agent import approval_manager
    approval_manager.resolve_request(payload.req_id, payload.approved)
    return {"status": "success", "message": f"Approval request {payload.req_id} resolved: {payload.approved}."}

# 7. Native Llama.cpp Runner Controls
@router.get("/runner/status")
async def get_runner_status():
    from loco.runner import native_runner
    is_installed = native_runner.is_installed()
    is_running = await native_runner.check_runner_health()
    downloaded = native_runner.get_downloaded_models()
    return {
        "is_installed": is_installed,
        "is_running": is_running,
        "downloaded_models": downloaded
    }

@router.get("/runner/check_compatibility")
def check_runner_compatibility(model_id: str):
    from loco.runner import check_model_compatibility
    res = check_model_compatibility(model_id)
    return res

@router.post("/runner/install")
def install_runner():
    from loco.runner import native_runner
    async def generator():
        async for chunk in native_runner.download_binaries():
            yield f"data: {json.dumps(chunk)}\n\n"
    return StreamingResponse(generator(), media_type="text/event-stream")

@router.post("/runner/download_model")
def download_native_model(payload: ModelDownloadSchema):
    from loco.runner import native_runner
    async def generator():
        async for chunk in native_runner.download_gguf_model(payload.model_id):
            yield f"data: {json.dumps(chunk)}\n\n"
    return StreamingResponse(generator(), media_type="text/event-stream")

@router.post("/runner/start")
def start_native_runner(payload: ModelStartSchema):
    from loco.runner import native_runner
    success = native_runner.start_server(payload.filename)
    if success:
        return {"status": "success", "message": f"Native server launched with model {payload.filename}."}
    raise HTTPException(status_code=500, detail="Failed to launch native server. Confirm model exists and port is free.")

@router.post("/runner/stop")
def stop_native_runner():
    from loco.runner import native_runner
    native_runner.stop_server()
    return {"status": "success", "message": "Native server stopped."}
