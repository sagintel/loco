import httpx
import json
import logging
import asyncio
from typing import List, Dict, Any, AsyncGenerator, Optional
from loco.config import config

logger = logging.getLogger("loco.engine")

class OllamaClient:
    def __init__(self):
        pass

    @property
    def base_url(self) -> str:
        """Dynamically resolve base URL depending on active runner type settings."""
        if config.get("runner_type") == "native":
            return f"http://127.0.0.1:11435/v1"
        return f"{config.ollama_url}/v1"

    async def check_status(self) -> bool:
        """Check if active runner server is running and healthy."""
        url = f"{self.base_url}/models"
        # Fallback check for root url if /v1/models isn't directly responding
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url)
                return response.status_code == 200
        except Exception:
            # Fallback root check
            try:
                root_url = "http://127.0.0.1:11435/health" if config.get("runner_type") == "native" else config.ollama_url
                async with httpx.AsyncClient(timeout=1.0) as client:
                    response = await client.get(root_url)
                    return response.status_code == 200
            except Exception:
                return False

    async def list_models(self) -> List[Dict[str, Any]]:
        """List locally available models by querying standard OpenAI models endpoint."""
        url = f"{self.base_url}/models"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    # Format standard OpenAI models list
                    models_list = data.get("data", [])
                    return [{"name": m.get("id")} for m in models_list]
                return []
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []

    async def pull_model_stream(self, model_name: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Pull a model from Ollama library (only supported when runner type is 'ollama')."""
        if config.get("runner_type") == "native":
            yield {"status": "error", "message": "Pulling model from Ollama registry is not supported in native GGUF mode."}
            return
            
        ollama_base = config.ollama_url
        url = f"{ollama_base}/api/pull"
        payload = {"name": model_name, "stream": True}
        
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        yield {"status": "error", "message": f"HTTP error {response.status_code}"}
                        return
                    
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            yield data
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Error pulling model {model_name}: {e}")
            yield {"status": "error", "message": str(e)}

    async def generate_embedding(self, text: str, model_name: str = "nomic-embed-text") -> Optional[List[float]]:
        """Generate embedding vector using standard OpenAI compatible endpoint, with Ollama native API fallbacks."""
        url = f"{self.base_url}/embeddings"
        
        # If native runner is active, let's use the running GGUF model for embeddings 
        # (native llama-server uses the loaded model as its embedder)
        active_model = model_name
        if config.get("runner_type") == "native":
            # Just grab the active model ID from config, since llama-server doesn't require a specific embedding model parameter
            active_model = config.coding_model
            
        payload = {"model": active_model, "input": text}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. Try standard OpenAI compatible endpoint
                try:
                    response = await client.post(url, json=payload)
                    if response.status_code == 200:
                        res_data = response.json()
                        data_list = res_data.get("data", [])
                        if data_list:
                            return data_list[0].get("embedding")
                except Exception as e:
                    logger.warning(f"OpenAI embedding endpoint failed: {e}")

                # 2. Try with fallback coding model on standard OpenAI endpoint if Ollama
                if config.get("runner_type") == "ollama" and active_model != config.coding_model:
                    try:
                        fallback_model = config.coding_model
                        logger.warning(f"Embedding failed for '{model_name}'. Trying OpenAI compatible fallback with '{fallback_model}'...")
                        fallback_payload = {"model": fallback_model, "input": text}
                        response = await client.post(url, json=fallback_payload)
                        if response.status_code == 200:
                            res_data = response.json()
                            data_list = res_data.get("data", [])
                            if data_list:
                                return data_list[0].get("embedding")
                    except Exception as e:
                        logger.warning(f"OpenAI fallback embedding failed: {e}")

                # 3. Try Ollama native /api/embed if in Ollama mode
                if config.get("runner_type") == "ollama":
                    try:
                        logger.info("Trying Ollama native /api/embed fallback...")
                        native_url = f"{config.ollama_url}/api/embed"
                        # /api/embed takes {"model": model, "input": text}
                        native_payload = {"model": active_model, "input": text}
                        response = await client.post(native_url, json=native_payload)
                        if response.status_code == 200:
                            res_data = response.json()
                            embeddings = res_data.get("embeddings", [])
                            if embeddings:
                                return embeddings[0]
                    except Exception as e:
                        logger.warning(f"Ollama native /api/embed failed: {e}")

                    # 4. Try Ollama native legacy /api/embeddings if in Ollama mode
                    try:
                        logger.info("Trying Ollama native legacy /api/embeddings fallback...")
                        legacy_url = f"{config.ollama_url}/api/embeddings"
                        # /api/embeddings takes {"model": model, "prompt": text}
                        legacy_payload = {"model": active_model, "prompt": text}
                        response = await client.post(legacy_url, json=legacy_payload)
                        if response.status_code == 200:
                            res_data = response.json()
                            embedding = res_data.get("embedding")
                            if embedding:
                                return embedding
                    except Exception as e:
                        logger.warning(f"Ollama legacy /api/embeddings failed: {e}")
                        
                logger.error(f"Failed to generate embedding for model '{active_model}' using any available endpoint.")
                return None
        except Exception as e:
            logger.error(f"Embedding generation error: {e}")
            return None

    async def generate_chat_stream(
        self, 
        model: str, 
        messages: List[Dict[str, str]], 
        options: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream chat completions utilizing standard OpenAI SSE formats."""
        url = f"{self.base_url}/chat/completions"
        
        # Build standard OpenAI chat payload
        payload = {
            "model": model,
            "messages": messages,
            "stream": True
        }
        if options:
            # Format parameters like temperature if supplied
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "max_tokens" in options:
                payload["max_tokens"] = options["max_tokens"]
            
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        err_text = await response.aread()
                        logger.error(f"Engine completions failed: {response.status_code} - {err_text.decode('utf-8', errors='ignore')}")
                        yield {"error": f"HTTP {response.status_code}: {err_text.decode('utf-8')}"}
                        return
                    
                    buffer = ""
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        
                        # Parse standard OpenAI stream SSE data chunks
                        if line.startswith("data: "):
                            clean_data = line[6:].strip()
                            if clean_data == "[DONE]":
                                break
                            try:
                                parsed = json.loads(clean_data)
                                # Translate OpenAI chunk structure to Ollama Client format for the agent:
                                # {"message": {"content": "text"}}
                                choices = parsed.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    yield {"message": {"content": content}}
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error(f"Connection error to engine completion route: {e}")
            yield {"error": f"Connection error: {e}"}

# Global Client Instance
engine = OllamaClient()
