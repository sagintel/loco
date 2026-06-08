import os
import json
import logging
from typing import Dict, Any, List

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("loco.config")

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8000,
    "ollama_url": "http://localhost:11434",
    "reasoning_model": "deepseek-r1:1.5b",
    "coding_model": "qwen2.5-coder:1.5b",
    "enable_cascade": True,
    "enable_rag": True,
    "rag_chunk_size": 1000,
    "rag_overlap": 150,
    "rag_top_k": 5,
    "system_prompt": "You are a professional software AI engineer. Provide high-quality, optimal code, utilizing step-by-step reasoning where applicable.",
    "workspace_dir": "",
    "active_skills": ["unit_test", "code_review", "optimize"],
    "gateway_mode": "code",
    "runner_type": "ollama"
}

class ConfigManager:
    def __init__(self, config_path: str = "config.json"):
        # Put config in the workspace directory or script directory
        self.config_path = os.path.abspath(config_path)
        self.data = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                    # Merge loaded keys to support updates
                    for k, v in loaded_data.items():
                        self.data[k] = v
                logger.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                logger.error(f"Error reading configuration file: {e}. Using defaults.")
        else:
            self.save()

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
            logger.info(f"Saved configuration to {self.config_path}")
        except Exception as e:
            logger.error(f"Error saving configuration file: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any):
        self.data[key] = value
        self.save()

    def update(self, items: Dict[str, Any]):
        for k, v in items.items():
            self.data[k] = v
        self.save()

    @property
    def host(self) -> str:
        return self.get("host")

    @property
    def port(self) -> int:
        return self.get("port")

    @property
    def ollama_url(self) -> str:
        return self.get("ollama_url")

    @property
    def reasoning_model(self) -> str:
        return self.get("reasoning_model")

    @property
    def coding_model(self) -> str:
        return self.get("coding_model")

    @property
    def enable_cascade(self) -> bool:
        return self.get("enable_cascade")

    @property
    def enable_rag(self) -> bool:
        return self.get("enable_rag")

    @property
    def workspace_dir(self) -> str:
        # Default workspace dir is current working dir of the script
        ws = self.get("workspace_dir")
        if not ws:
            ws = os.path.dirname(self.config_path)
            # Just fallback to current directory
            if not ws or ws == "":
                ws = os.getcwd()
        return os.path.abspath(ws)

# Global configuration instance
config = ConfigManager()
