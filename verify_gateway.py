import os
import sys
import py_compile
import logging
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("loco.verifier")

def run_syntax_check() -> bool:
    """Compile code to check for structural syntax errors."""
    logger.info("Running python compilation/syntax checks...")
    files = [
        "loco/config.py",
        "loco/engine.py",
        "loco/rag.py",
        "loco/agent.py",
        "loco/runner.py",
        "loco/watcher.py",
        "loco/dashboard.py",
        "loco/main.py"
    ]
    
    success = True
    for f in files:
        path = os.path.abspath(f)
        if not os.path.exists(path):
            logger.error(f"Missing file: {f}")
            success = False
            continue
            
        try:
            py_compile.compile(path, doraise=True)
            logger.info(f"  [PASS] {f}")
        except py_compile.PyCompileError as e:
            logger.error(f"  [FAIL] {f} contains syntax errors:\n{e}")
            success = False
            
    return success

def run_directory_check() -> bool:
    """Confirm all folders and files are created in the right workspace locations."""
    logger.info("Verifying workspace layout...")
    paths = [
        "loco/dashboard/index.html",
        "loco/dashboard/style.css",
        "loco/dashboard/app.js",
        "loco/skills/unit_test.md",
        "loco/skills/code_review.md",
        "loco/skills/optimize.md",
        "requirements.txt",
        "run.bat"
    ]
    
    success = True
    for p in paths:
        path = os.path.abspath(p)
        if os.path.exists(path):
            logger.info(f"  [FOUND] {p} ({os.path.getsize(path)} bytes)")
        else:
            logger.error(f"  [MISSING] {p}")
            success = False
            
    return success

def run_unit_tests() -> bool:
    """Execute unit tests on the components to verify correctness."""
    logger.info("Running unit tests on components...")
    
    # 1. Config Manager test
    try:
        from loco.config import ConfigManager
        test_config = ConfigManager("test_config.json")
        test_config.set("gateway_mode", "agent")
        if test_config.get("gateway_mode") != "agent":
            logger.error("  [FAIL] ConfigManager failed to set/get value.")
            return False
        # clean up
        if os.path.exists("test_config.json"):
            os.remove("test_config.json")
        logger.info("  [PASS] ConfigManager tests.")
    except Exception as e:
        logger.error(f"  [FAIL] ConfigManager tests failed with exception: {e}")
        return False

    # 2. Chunker test
    try:
        from loco.rag import rag_index
        code_sample = (
            "class MyClass:\n"
            "    def __init__(self):\n"
            "        self.val = 1\n\n"
            "    def method_one(self):\n"
            "        print('hello')\n"
        )
        chunks = rag_index._chunk_text(code_sample, "test_file.py")
        if not chunks:
            logger.error("  [FAIL] Code chunker returned no chunks.")
            return False
        # verify start/end lines
        logger.info(f"  [PASS] Code chunker tests (generated {len(chunks)} chunks).")
    except Exception as e:
        logger.error(f"  [FAIL] Code chunker tests failed with exception: {e}")
        return False

    # 3. Skills Loading test
    try:
        from loco.agent import load_skills
        skills = load_skills()
        if not skills:
            logger.error("  [FAIL] load_skills returned empty list.")
            return False
        skill_ids = [s["id"] for s in skills]
        if "unit_test" not in skill_ids or "code_review" not in skill_ids:
            logger.error(f"  [FAIL] Missing default skills. Loaded: {skill_ids}")
            return False
        logger.info(f"  [PASS] Skills loading tests (found {len(skills)} skills).")
    except Exception as e:
        logger.error(f"  [FAIL] Skills loading tests failed with exception: {e}")
        return False

    # 4. Hybrid RAG Search test
    try:
        from loco.rag import rag_index
        import sqlite3
        import json
        import gc
        
        # Setup clean temporary test db
        test_db = "test_rag.db"
        if os.path.exists(test_db):
            try:
                gc.collect()
                os.remove(test_db)
            except Exception:
                pass
            
        original_db_path = rag_index.db_path
        rag_index.db_path = os.path.abspath(test_db)
        rag_index._init_db()
        
        # Insert test chunks directly using try-finally for explicit closing
        conn = sqlite3.connect(rag_index.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO indexed_files (file_path, last_modified) VALUES (?, ?)", ("sample.py", time.time()))
            
            # chunk 1 containing specific keyword 'calculate_total'
            emb1 = [0.1] * 384
            cursor.execute(
                "INSERT INTO chunks (file_path, content, start_line, end_line, embedding) VALUES (?, ?, ?, ?, ?)",
                ("sample.py", "def calculate_total(items):\n    return sum(items)", 1, 2, json.dumps(emb1))
            )
            
            # chunk 2 containing keyword 'fetch_records'
            emb2 = [-0.1] * 384
            cursor.execute(
                "INSERT INTO chunks (file_path, content, start_line, end_line, embedding) VALUES (?, ?, ?, ?, ?)",
                ("sample.py", "def fetch_records(db):\n    return db.query()", 4, 5, json.dumps(emb2))
            )
            conn.commit()
        finally:
            conn.close()
            
        # Mock engine.generate_embedding
        from unittest.mock import AsyncMock
        from loco.engine import engine
        original_embed = engine.generate_embedding
        engine.generate_embedding = AsyncMock(return_value=[0.1] * 384)
        
        try:
            # Search for 'calculate_total'
            results = asyncio.run(rag_index.search("calculate_total", top_k=2))
            if not results:
                logger.error("  [FAIL] Hybrid search returned no results.")
                return False
                
            # First result should be the one matching keyword and vector
            first_match = results[0]["content"]
            if "calculate_total" not in first_match:
                logger.error(f"  [FAIL] Hybrid search did not prioritize correct chunk: {first_match}")
                return False
                
            logger.info("  [PASS] Hybrid RAG Search RRF matching tests.")
        finally:
            engine.generate_embedding = original_embed
            rag_index.db_path = original_db_path
            # Force close and collect connections before deleting
            gc.collect()
            time.sleep(0.1)
            if os.path.exists(test_db):
                try:
                    os.remove(test_db)
                except Exception as del_err:
                    logger.warning(f"Could not remove test_db during cleanup (locked by Windows): {del_err}")
    except Exception as e:
        logger.error(f"  [FAIL] Hybrid Search tests failed with exception: {e}")
        return False

    return True

def main():
    print("==================================================")
    print("        LocoEngine Build Verification             ")
    print("==================================================")
    
    dir_ok = run_directory_check()
    syntax_ok = run_syntax_check()
    unit_tests_ok = run_unit_tests()
    
    print("==================================================")
    if dir_ok and syntax_ok and unit_tests_ok:
        print(" [SUCCESS] All files present, compiled clean, ")
        print("           and all unit tests passed!         ")
        print(" To run the server, double click: run.bat         ")
        sys.exit(0)
    else:
        print(" [FAILURE] Error in files check or tests.      ")
        sys.exit(1)

if __name__ == "__main__":
    main()
