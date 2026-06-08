import os
import time
import threading
import logging
import asyncio
from typing import Optional
from loco.config import config
from loco.rag import rag_index

logger = logging.getLogger("loco.watcher")

class WorkspaceWatcher:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.last_scan_time = 0
        self.is_scanning = False

    def start(self):
        """Start the background file watcher thread."""
        if self.thread and self.thread.is_alive():
            return
            
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_watcher, name="LocoWatcher", daemon=True)
        self.thread.start()
        logger.info("Background workspace watcher thread started.")

    def stop(self):
        """Stop the background watcher."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
            logger.info("Workspace watcher thread stopped.")

    def _run_watcher(self):
        """Periodic polling execution loop running inside the daemon thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while not self.stop_event.is_set():
            # Wait for 5 seconds
            for _ in range(50):
                if self.stop_event.is_set():
                    break
                time.sleep(0.1)
                
            if self.stop_event.is_set():
                break
                
            workspace = config.workspace_dir
            if not workspace or not os.path.exists(workspace):
                continue
                
            if self.is_scanning:
                continue
                
            # Perform incremental scan check
            try:
                self.is_scanning = True
                # Run the async scan inside the thread's event loop
                stats = loop.run_until_complete(rag_index.scan_and_index(workspace))
                
                # Log only if actual changes occurred to prevent console spam
                files_indexed = stats.get("files_indexed", 0)
                chunks_added = stats.get("chunks_added", 0)
                
                if files_indexed > 0 or chunks_added > 0:
                    logger.info(
                        f"[Watcher RAG Auto-Sync] Automatically indexed {files_indexed} modified files "
                        f"({chunks_added} chunks added)."
                    )
            except Exception as e:
                logger.error(f"Error in background workspace watcher scan: {e}")
            finally:
                self.is_scanning = False
                
        loop.close()

# Global Watcher Instance
watcher = WorkspaceWatcher()
