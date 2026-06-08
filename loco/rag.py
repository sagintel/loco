import os
import sqlite3
import threading
import json
import math
import logging
import time
import re
from typing import List, Dict, Any, Tuple, Optional
from loco.config import config
from loco.engine import engine

logger = logging.getLogger("loco.rag")

# Folders to completely ignore during workspace scanning
IGNORE_DIRS = {
    ".git", ".svn", ".venv", "venv", "env", "node_modules", 
    "__pycache__", ".idea", ".vscode", "dist", "build", "out",
    "bin", "obj", ".gemini"
}

# Text extensions we support
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", 
    ".json", ".md", ".txt", ".sh", ".bat", ".yaml", ".yml",
    ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".sql", ".properties", ".ini"
}

class RAGIndex:
    def __init__(self, fallback_db_path: str = "rag_store.db"):
        self.fallback_db_path = os.path.abspath(fallback_db_path)
        self._custom_db_path = None
        self._scan_lock = threading.Lock()
        self._initialized_db_paths = set()
        self._init_db()

    @property
    def db_path(self) -> str:
        if self._custom_db_path:
            return self._custom_db_path
        if config.workspace_dir and os.path.exists(config.workspace_dir):
            loco_dir = os.path.join(config.workspace_dir, ".loco")
            os.makedirs(loco_dir, exist_ok=True)
            return os.path.join(loco_dir, "rag_store.db")
        return self.fallback_db_path

    @db_path.setter
    def db_path(self, value: Optional[str]):
        if value:
            self._custom_db_path = os.path.abspath(value)
        else:
            self._custom_db_path = None

    def _get_connection(self) -> sqlite3.Connection:
        current_path = self.db_path
        conn = sqlite3.connect(current_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        
        # Check if we have initialized this db path in this session
        if current_path not in self._initialized_db_paths:
            self._initialized_db_paths.add(current_path)
            self._create_tables(conn)
            
        return conn

    def _create_tables(self, conn: sqlite3.Connection):
        """Create database tables on the given connection."""
        try:
            cursor = conn.cursor()
            # Table for file tracking (to support incremental updates)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS indexed_files (
                    file_path TEXT PRIMARY KEY,
                    last_modified REAL,
                    file_hash TEXT
                )
            """)
            # Table for document chunks
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT,
                    content TEXT,
                    start_line INTEGER,
                    end_line INTEGER,
                    embedding TEXT, -- JSON serialized list of floats
                    FOREIGN KEY (file_path) REFERENCES indexed_files(file_path) ON DELETE CASCADE
                )
            """)
            conn.commit()
        except Exception as e:
            logger.error(f"Error creating RAG DB tables: {e}")

    def _init_db(self):
        """Initialize SQLite database for indexing."""
        try:
            with self._get_connection() as conn:
                pass
        except Exception as e:
            logger.error(f"Error initializing SQLite RAG DB: {e}")

    def clear_index(self):
        """Clears all indexed data."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM chunks")
                cursor.execute("DELETE FROM indexed_files")
                conn.commit()
            logger.info("RAG Index successfully cleared.")
        except Exception as e:
            logger.error(f"Error clearing database: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Return indexing statistics."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM indexed_files")
                total_files = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM chunks")
                total_chunks = cursor.fetchone()[0]
                
                return {
                    "total_files": total_files,
                    "total_chunks": total_chunks,
                    "db_size_bytes": os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {"total_files": 0, "total_chunks": 0, "db_size_bytes": 0}

    def _chunk_text(self, text: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Split document text into chunks, using simple code-aware rules 
        for classes and functions if applicable.
        """
        ext = os.path.splitext(file_path)[1].lower()
        lines = text.splitlines(keepends=True)
        chunks = []
        
        chunk_size = config.get("rag_chunk_size", 1000)
        overlap = config.get("rag_overlap", 150)
        
        # Helper: standard chunker based on window character size
        def standard_chunker():
            current_chunk = []
            current_len = 0
            start_line = 1
            
            for line_idx, line in enumerate(lines, 1):
                current_chunk.append(line)
                current_len += len(line)
                
                if current_len >= chunk_size:
                    chunk_content = "".join(current_chunk)
                    chunks.append({
                        "content": chunk_content.strip(),
                        "start_line": start_line,
                        "end_line": line_idx
                    })
                    
                    # Keep overlap lines
                    overlap_len = 0
                    overlap_chunk = []
                    overlap_start = line_idx
                    
                    # Backtrack to build the overlap
                    for i in range(len(current_chunk) - 1, -1, -1):
                        l = current_chunk[i]
                        overlap_chunk.insert(0, l)
                        overlap_len += len(l)
                        overlap_start -= 1
                        if overlap_len >= overlap:
                            break
                            
                    current_chunk = overlap_chunk
                    current_len = overlap_len
                    start_line = max(1, overlap_start + 1)
            
            if current_chunk:
                chunks.append({
                    "content": "".join(current_chunk).strip(),
                    "start_line": start_line,
                    "end_line": len(lines)
                })

        # Smart chunking for code (Python/JS/C++...)
        # We try to keep blocks together (split on double newlines or classes/functions)
        if ext in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cpp", ".c", ".h"}:
            current_block = []
            current_len = 0
            start_line = 1
            
            for line_idx, line in enumerate(lines, 1):
                # Detect logical break points in code: class def, function def, or empty lines
                is_break = False
                cleaned_line = line.strip()
                
                if ext == ".py":
                    is_break = cleaned_line.startswith(("class ", "def "))
                elif ext in {".js", ".ts", ".tsx", ".jsx", ".java", ".cpp", ".c", ".go", ".rs"}:
                    is_break = cleaned_line.startswith(("class ", "function ", "const ", "let ", "func ", "pub func ", "fn ", "struct ", "interface "))
                
                # If we hit a logical code boundary and we have accumulated enough content, save chunk
                if is_break and current_len > (chunk_size // 2):
                    chunks.append({
                        "content": "".join(current_block).strip(),
                        "start_line": start_line,
                        "end_line": line_idx - 1
                    })
                    current_block = []
                    current_len = 0
                    start_line = line_idx
                
                current_block.append(line)
                current_len += len(line)
                
                # Fallback to hard limit if block gets too big
                if current_len >= chunk_size:
                    chunks.append({
                        "content": "".join(current_block).strip(),
                        "start_line": start_line,
                        "end_line": line_idx
                    })
                    
                    # Simple overlap window
                    overlap_lines = current_block[-5:] if len(current_block) > 5 else current_block
                    current_block = list(overlap_lines)
                    current_len = sum(len(l) for l in current_block)
                    start_line = max(1, line_idx - len(current_block) + 1)
                    
            if current_block:
                chunks.append({
                    "content": "".join(current_block).strip(),
                    "start_line": start_line,
                    "end_line": len(lines)
                })
        else:
            standard_chunker()
            
        return [c for c in chunks if len(c["content"]) > 10]

    async def scan_and_index(self, root_dir: str, progress_callback=None) -> Dict[str, Any]:
        """
        Scan workspace directory recursively, find modified files,
        chunk them, request embeddings, and save to SQLite.
        """
        if not self._scan_lock.acquire(blocking=False):
            logger.info("Scan skipped: another scan is already in progress.")
            return {"status": "skipped", "message": "Scan already in progress"}
            
        try:
            start_time = time.time()
            root_dir = os.path.abspath(root_dir)
            
            if not os.path.exists(root_dir):
                return {"status": "error", "message": f"Workspace directory {root_dir} does not exist"}

            files_to_index = []
        
            # 1. Walk directory and filter files
            for root, dirs, files in os.walk(root_dir):
                # Prune directory search
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        file_path = os.path.join(root, file)
                        try:
                            mtime = os.path.getmtime(file_path)
                            files_to_index.append((file_path, mtime))
                        except OSError:
                            continue
            
            # 2. Check SQLite for modified files (incremental indexing)
            modified_files = []
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for file_path, mtime in files_to_index:
                    cursor.execute("SELECT last_modified FROM indexed_files WHERE file_path = ?", (file_path,))
                    row = cursor.fetchone()
                    if row is None or row[0] < mtime:
                        modified_files.append((file_path, mtime))
                        
            total_modified = len(modified_files)
            logger.info(f"RAG Scan: found {len(files_to_index)} files, {total_modified} need re-indexing.")
            
            # 3. Process modified files
            indexed_count = 0
            chunks_added = 0
            errors = 0
            
            for idx, (file_path, mtime) in enumerate(modified_files):
                if progress_callback:
                    progress_callback(idx + 1, total_modified, file_path)
                    
                try:
                    # Read content
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    
                    # Chunk content
                    chunks = self._chunk_text(content, file_path)
                    
                    # Generate embeddings and store
                    with self._get_connection() as conn:
                        cursor = conn.cursor()
                        
                        # Delete old chunks for this file
                        cursor.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
                        # Delete from indexed files if exists
                        cursor.execute("DELETE FROM indexed_files WHERE file_path = ?", (file_path,))
                        
                        # Insert file metadata
                        cursor.execute("INSERT OR REPLACE INTO indexed_files (file_path, last_modified) VALUES (?, ?)", (file_path, mtime))
                        
                        # Generate embeddings for each chunk
                        for chunk in chunks:
                            # Call Ollama for embedding vector
                            embedding = await engine.generate_embedding(chunk["content"])
                            if embedding is not None:
                                cursor.execute(
                                    "INSERT INTO chunks (file_path, content, start_line, end_line, embedding) VALUES (?, ?, ?, ?, ?)",
                                    (file_path, chunk["content"], chunk["start_line"], chunk["end_line"], json.dumps(embedding))
                                )
                                chunks_added += 1
                            else:
                                # Graceful degradation: insert without embedding
                                cursor.execute(
                                    "INSERT INTO chunks (file_path, content, start_line, end_line) VALUES (?, ?, ?, ?)",
                                    (file_path, chunk["content"], chunk["start_line"], chunk["end_line"])
                                )
                                chunks_added += 1
                                
                        conn.commit()
                    indexed_count += 1
                    
                except Exception as e:
                    logger.error(f"Error indexing file {file_path}: {e}")
                    errors += 1
                    
            duration = time.time() - start_time
            
            result = {
                "status": "success",
                "files_scanned": len(files_to_index),
                "files_indexed": indexed_count,
                "chunks_added": chunks_added,
                "errors": errors,
                "duration_seconds": round(duration, 2)
            }
            
            return result
        finally:
            self._scan_lock.release()

    async def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Hybrid search combining semantic vector cosine similarity and keyword matches,
        fusing rankings using Reciprocal Rank Fusion (RRF).
        """
        if not query.strip():
            return []

        # 1. Fetch all chunks from SQLite
        all_chunks = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT file_path, content, start_line, end_line, embedding FROM chunks")
                rows = cursor.fetchall()
                for file_path, content, start_line, end_line, emb_str in rows:
                    all_chunks.append({
                        "file_path": file_path,
                        "content": content,
                        "start_line": start_line,
                        "end_line": end_line,
                        "embedding": json.loads(emb_str) if emb_str else None
                    })
        except Exception as e:
            logger.error(f"Failed to read chunks for search: {e}")
            return []

        if not all_chunks:
            return []

        # 2. Part A: Vector Cosine Similarity Search
        vector_results = []
        query_vector = await engine.generate_embedding(query)
        
        if query_vector:
            def cosine_similarity(v1, v2):
                dot = sum(a * b for a, b in zip(v1, v2))
                norm1 = math.sqrt(sum(a * a for a in v1))
                norm2 = math.sqrt(sum(b * b for b in v2))
                if norm1 == 0 or norm2 == 0:
                    return 0.0
                return dot / (norm1 * norm2)

            for chunk in all_chunks:
                if chunk["embedding"] and len(chunk["embedding"]) == len(query_vector):
                    score = cosine_similarity(query_vector, chunk["embedding"])
                    vector_results.append((chunk, score))
            
            # Sort descending by vector score
            vector_results.sort(key=lambda x: x[1], reverse=True)

        # 3. Part B: Keyword Density Search
        keyword_results = []
        # Simple query term extractor: split by non-alphanumeric, filter small/empty words
        query_terms = [t.lower() for t in re.split(r'\W+', query) if len(t) >= 2]
        
        if query_terms:
            for chunk in all_chunks:
                content_lower = chunk["content"].lower()
                # Score = sum of term frequencies in chunk
                score = 0
                for term in query_terms:
                    score += content_lower.count(term)
                if score > 0:
                    keyword_results.append((chunk, score))
            
            # Sort descending by keyword density score
            keyword_results.sort(key=lambda x: x[1], reverse=True)

        # 4. Part C: Reciprocal Rank Fusion (RRF)
        # RRF Score = 1 / (60 + VectorRank) + 1 / (60 + KeywordRank)
        rrf_scores = {}
        
        # Build maps of chunk key -> rank
        vector_ranks = {}
        for rank, (chunk, _) in enumerate(vector_results, 1):
            key = (chunk["file_path"], chunk["start_line"], chunk["end_line"])
            vector_ranks[key] = rank
            
        keyword_ranks = {}
        for rank, (chunk, _) in enumerate(keyword_results, 1):
            key = (chunk["file_path"], chunk["start_line"], chunk["end_line"])
            keyword_ranks[key] = rank

        # Compute RRF for chunks present in top candidates
        candidates = list(vector_ranks.keys()) + list(keyword_ranks.keys())
        # Make unique keys
        unique_keys = set(candidates)
        
        # Lookup map for chunk objects
        chunk_lookup = {}
        for chunk in all_chunks:
            key = (chunk["file_path"], chunk["start_line"], chunk["end_line"])
            chunk_lookup[key] = chunk

        fused_results = []
        for key in unique_keys:
            v_rank = vector_ranks.get(key, 9999) # If not ranked, treat as very low rank
            k_rank = keyword_ranks.get(key, 9999)
            
            rrf_score = (1.0 / (60.0 + v_rank)) + (1.0 / (60.0 + k_rank))
            
            # Formulate a composite score for display (scaled to looks like a standard percentage/ratio)
            display_score = round(rrf_score * 30.0, 4) # Max RRF for top 1 in both is 2 * (1/61) ~ 0.032, scaled to ~0.98
            
            chunk_obj = chunk_lookup[key]
            fused_results.append({
                "file_path": chunk_obj["file_path"],
                "content": chunk_obj["content"],
                "start_line": chunk_obj["start_line"],
                "end_line": chunk_obj["end_line"],
                "score": display_score
            })

        # Sort by RRF score descending
        fused_results.sort(key=lambda x: x["score"], reverse=True)
        return fused_results[:top_k]

    async def index_custom_content(self, name: str, content: str) -> Dict[str, Any]:
        """Index a specific piece of custom content (file upload or URL text) directly into RAG."""
        start_time = time.time()
        file_path = f"custom_index/{name}"
        
        chunks = self._chunk_text(content, file_path)
        chunks_added = 0
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Delete any old chunks for this identifier
                cursor.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
                cursor.execute("DELETE FROM indexed_files WHERE file_path = ?", (file_path,))
                
                # Insert metadata record
                cursor.execute("INSERT OR REPLACE INTO indexed_files (file_path, last_modified) VALUES (?, ?)", (file_path, time.time()))
                
                # Insert chunks with embeddings
                for chunk in chunks:
                    embedding = await engine.generate_embedding(chunk["content"])
                    if embedding is not None:
                        cursor.execute(
                            "INSERT INTO chunks (file_path, content, start_line, end_line, embedding) VALUES (?, ?, ?, ?, ?)",
                            (file_path, chunk["content"], chunk["start_line"], chunk["end_line"], json.dumps(embedding))
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO chunks (file_path, content, start_line, end_line) VALUES (?, ?, ?, ?)",
                            (file_path, chunk["content"], chunk["start_line"], chunk["end_line"])
                        )
                    chunks_added += 1
                conn.commit()
                
            return {
                "status": "success",
                "file_path": file_path,
                "chunks_added": chunks_added,
                "duration_seconds": round(time.time() - start_time, 2)
            }
        except Exception as e:
            logger.error(f"Failed to index custom content '{name}': {e}")
            return {"status": "error", "message": str(e)}

# Global database instance
rag_index = RAGIndex()
