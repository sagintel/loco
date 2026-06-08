import os
import sys
import httpx
import json
import logging
import zipfile
import asyncio
import subprocess
import shutil
from typing import AsyncGenerator, Optional, Dict, Any
from loco.config import config

logger = logging.getLogger("loco.runner")

BIN_DIR = os.path.join(os.path.dirname(__file__), "bin")
os.makedirs(BIN_DIR, exist_ok=True)

# Hardware Gating Specifications
MODEL_REQUIREMENTS = {
    "qwen2.5-coder:1.5b": {"min_ram": 4.0, "min_vram": 0.0, "min_disk": 2.0},
    "deepseek-r1:1.5b": {"min_ram": 4.0, "min_vram": 0.0, "min_disk": 2.0},
    "llama3.2:3b": {"min_ram": 8.0, "min_vram": 0.0, "min_disk": 4.0},
    "nemotron-mini:4b": {"min_ram": 8.0, "min_vram": 0.0, "min_disk": 5.0}
}

def get_gpu_vram() -> float:
    """Returns total NVIDIA GPU VRAM in GB, or 0.0 if not available."""
    try:
        nvsmi_path = "nvidia-smi"
        if os.path.exists("C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe"):
            nvsmi_path = "C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe"
            
        import subprocess
        res = subprocess.run(
            [nvsmi_path, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2.0
        )
        if res.returncode == 0:
            lines = res.stdout.strip().split("\n")
            if lines and lines[0].strip().isdigit():
                return float(lines[0].strip()) / 1024.0
    except Exception:
        pass
    return 0.0

def get_system_ram() -> float:
    """Returns system RAM in GB."""
    import psutil
    try:
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return 8.0

def get_free_disk_space(path: str) -> float:
    """Returns free disk space in GB at the given path."""
    import shutil
    try:
        return shutil.disk_usage(path).free / (1024 ** 3)
    except Exception:
        return 10.0

def check_model_compatibility(model_id: str, dest_dir: str = BIN_DIR) -> Dict[str, Any]:
    """Verify if the host machine has sufficient CPU RAM, GPU VRAM, and Disk space for the model."""
    reqs = MODEL_REQUIREMENTS.get(model_id.lower())
    if not reqs:
        return {"compatible": True, "reasons": [], "metrics": {}}
        
    ram = get_system_ram()
    vram = get_gpu_vram()
    disk = get_free_disk_space(dest_dir)
    
    compatible = True
    reasons = []
    
    if disk < reqs["min_disk"]:
        compatible = False
        reasons.append(f"Insufficient disk space. Required: {reqs['min_disk']} GB, Available: {disk:.2f} GB.")
        
    has_enough_ram = ram >= reqs["min_ram"]
    has_enough_vram = False
    
    if vram > 0.0:
        target_vram = reqs["min_vram"] if reqs["min_vram"] > 0.0 else max(2.0, reqs["min_ram"] * 0.7)
        if vram >= target_vram:
            has_enough_vram = True
            
    if not has_enough_ram and not has_enough_vram:
        compatible = False
        if vram > 0.0:
            reasons.append(
                f"Insufficient memory. Need either {reqs['min_ram']} GB System RAM or "
                f"{reqs['min_vram'] if reqs['min_vram'] > 0 else '70% of RAM'} GB GPU VRAM. "
                f"Your system: RAM={ram:.2f} GB, VRAM={vram:.2f} GB."
            )
        else:
            reasons.append(
                f"Insufficient System RAM. Required: {reqs['min_ram']} GB, Available: {ram:.2f} GB."
            )
            
    return {
        "compatible": compatible,
        "reasons": reasons,
        "metrics": {
            "ram_gb": round(ram, 2),
            "vram_gb": round(vram, 2),
            "disk_gb": round(disk, 2)
        },
        "requirements": reqs
    }

class NativeRunner:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.port = 11435  # Native runner port (Ollama uses 11434)
        self.download_tasks = {}

    @property
    def server_path(self) -> str:
        return os.path.join(BIN_DIR, "llama-server.exe")

    @property
    def dll_path(self) -> str:
        return os.path.join(BIN_DIR, "llama.dll")

    def is_installed(self) -> bool:
        """Check if llama-server.exe and llama.dll are available locally."""
        return os.path.exists(self.server_path) and os.path.exists(self.dll_path)

    async def check_runner_health(self) -> bool:
        """Verify if native llama-server is running and responding on port 11435."""
        if not self.process or self.process.poll() is not None:
            return False
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                response = await client.get(f"http://localhost:{self.port}/health")
                return response.status_code == 200
        except Exception:
            return False

    async def download_binaries(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Query GitHub Releases API, find Windows AVX2 binaries, download and extract them."""
        github_url = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
        headers = {"User-Agent": "LocoEngine-Gateway"}
        
        yield {"status": "fetching_api", "message": "Querying latest llama.cpp releases from GitHub..."}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(github_url, headers=headers)
                if res.status_code != 200:
                    yield {"status": "error", "message": f"GitHub API error: HTTP {res.status_code}"}
                    return
                
                release_data = res.json()
                assets = release_data.get("assets", [])
                
                # Find Win AVX2 x64 or generic Windows binary zip
                target_asset = None
                for asset in assets:
                    name = asset.get("name", "").lower()
                    if "win" in name and "x64" in name and (".zip" in name):
                        # Prioritize AVX2
                        if "avx2" in name:
                            target_asset = asset
                            break
                        # Fallback to general zip if AVX2 not matched immediately
                        if not target_asset:
                            target_asset = asset
                            
                if not target_asset:
                    yield {"status": "error", "message": "Could not find compatible Windows x64 binary in release assets."}
                    return
                
                download_url = target_asset["browser_download_url"]
                asset_size = target_asset["size"]
                asset_name = target_asset["name"]
                
                yield {"status": "downloading", "message": f"Downloading {asset_name}...", "total": asset_size, "completed": 0}
                
                zip_dest = os.path.join(BIN_DIR, "llama_bin.zip")
                
                # Download zip file in streams
                completed_bytes = 0
                async with client.stream("GET", download_url, follow_redirects=True) as stream:
                    if stream.status_code != 200:
                        yield {"status": "error", "message": f"Failed to download asset: HTTP {stream.status_code}"}
                        return
                        
                    with open(zip_dest, "wb") as f:
                        async for chunk in stream.iter_bytes(chunk_size=16384):
                            f.write(chunk)
                            completed_bytes += len(chunk)
                            yield {
                                "status": "downloading", 
                                "message": f"Downloading binaries...", 
                                "total": asset_size, 
                                "completed": completed_bytes
                            }
                            
                # Unzip files
                yield {"status": "extracting", "message": "Extracting binaries..."}
                extract_temp = os.path.join(BIN_DIR, "temp_extract")
                os.makedirs(extract_temp, exist_ok=True)
                
                with zipfile.ZipFile(zip_dest, 'r') as zip_ref:
                    zip_ref.extractall(extract_temp)
                
                # Move llama-server.exe and llama.dll to BIN_DIR
                found_exe = False
                found_dll = False
                for root, dirs, files in os.walk(extract_temp):
                    for file in files:
                        if file.lower() == "llama-server.exe":
                            shutil.move(os.path.join(root, file), self.server_path)
                            found_exe = True
                        elif file.lower() == "llama.dll":
                            shutil.move(os.path.join(root, file), self.dll_path)
                            found_dll = True
                            
                # Cleanup temp files
                shutil.rmtree(extract_temp, ignore_errors=True)
                if os.path.exists(zip_dest):
                    os.remove(zip_dest)
                    
                if found_exe and found_dll:
                    # Grant executable permissions just in case
                    try:
                        os.chmod(self.server_path, 0o755)
                    except Exception:
                        pass
                    yield {"status": "complete", "message": "llama.cpp binaries installed successfully!"}
                else:
                    yield {"status": "error", "message": "Binaries extracted but 'llama-server.exe' or 'llama.dll' was missing."}
                    
        except Exception as e:
            logger.error(f"Error installing native binaries: {e}")
            yield {"status": "error", "message": f"Installation failed: {str(e)}"}

    async def download_gguf_model(self, model_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Download GGUF models directly from Hugging Face resolving URLs."""
        # Check model hardware compatibility first
        comp = check_model_compatibility(model_id)
        if not comp["compatible"]:
            reasons_str = " ".join(comp["reasons"])
            yield {"status": "error", "message": f"Hardware Gating: {reasons_str}"}
            return

        # Simple mapper for standard model GGUFs
        model_urls = {
            "qwen2.5-coder:1.5b": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
            "deepseek-r1:1.5b": "https://huggingface.co/lmstudio-community/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
            "llama3.2:3b": "https://huggingface.co/Bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "nemotron-mini:4b": "https://huggingface.co/bartowski/Nemotron-Mini-4B-Instruct-GGUF/resolve/main/Nemotron-Mini-4B-Instruct-Q4_K_M.gguf"
        }
        
        url = model_urls.get(model_id.lower())
        if not url:
            yield {"status": "error", "message": f"Unknown GGUF model download source for '{model_id}'."}
            return
            
        filename = url.split("/")[-1]
        dest_path = os.path.join(BIN_DIR, filename)
        
        # If model is already downloaded, skip
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 100 * 1024 * 1024:
            yield {"status": "complete", "message": f"Model {model_id} already exists.", "filename": filename}
            return
            
        yield {"status": "downloading", "message": f"Initiating Hugging Face download for {filename}...", "total": 0, "completed": 0}
        
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url, follow_redirects=True) as stream:
                    if stream.status_code != 200:
                        yield {"status": "error", "message": f"HTTP resolve failed: HTTP {stream.status_code}"}
                        return
                    
                    total_bytes = int(stream.headers.get("content-length", 0))
                    completed_bytes = 0
                    
                    with open(dest_path, "wb") as f:
                        async for chunk in stream.iter_bytes(chunk_size=65536):
                            f.write(chunk)
                            completed_bytes += len(chunk)
                            yield {
                                "status": "downloading",
                                "message": f"Downloading GGUF file...",
                                "total": total_bytes,
                                "completed": completed_bytes
                            }
                            
            yield {"status": "complete", "message": f"GGUF model downloaded to {dest_path}", "filename": filename}
        except Exception as e:
            logger.error(f"GGUF download failed: {e}")
            if os.path.exists(dest_path):
                os.remove(dest_path)
            yield {"status": "error", "message": f"Download failed: {str(e)}"}

    def get_downloaded_models(self) -> list:
        """Scan BIN_DIR for downloaded .gguf models."""
        models = []
        if not os.path.exists(BIN_DIR):
            return models
        for file in os.listdir(BIN_DIR):
            if file.endswith(".gguf"):
                path = os.path.join(BIN_DIR, file)
                models.append({
                    "name": file,
                    "path": path,
                    "size_bytes": os.path.getsize(path)
                })
        return models

    def start_server(self, model_filename: str) -> bool:
        """Launch the llama-server.exe process with CPU threading configurations."""
        self.stop_server()
        
        model_path = os.path.join(BIN_DIR, model_filename)
        if not os.path.exists(model_path):
            logger.error(f"Model GGUF not found: {model_path}")
            return False
            
        if not self.is_installed():
            logger.error("llama-server.exe binary is not installed.")
            return False

        # Detect optimal thread bindings
        import psutil
        try:
            cores = psutil.cpu_count(logical=False) or 4
            # Set threads to physical cores to maximize speed while preventing overheating
            threads = max(1, cores)
        except Exception:
            threads = 4
            
        cmd = [
            self.server_path,
            "-m", model_path,
            "-c", "4096",
            "--port", str(self.port),
            "-t", str(threads),
            "--host", "127.0.0.1",
            "--embedding"
        ]
        
        logger.info(f"Launching native runner subprocess: {' '.join(cmd)}")
        try:
            # Start process in background
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=BIN_DIR,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return True
        except Exception as e:
            logger.error(f"Failed to start llama-server subprocess: {e}")
            return False

    def stop_server(self):
        """Terminate the native background server process."""
        if self.process:
            logger.info("Terminating native llama-server subprocess...")
            self.process.terminate()
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                logger.warning("Subprocess did not terminate; forcing kill...")
                self.process.kill()
            self.process = None

# Global Native Runner Instance
native_runner = NativeRunner()
