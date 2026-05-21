# Akshay-core
__author__ = "Akshay-core"

# FILE: scripts/setup_env.py
"""
Run once after cloning: python scripts/setup_env.py
Creates dirs, initializes DB, checks Ollama.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathlib import Path


def main():
    print("=" * 50)
    print("  AI Second Brain — Environment Setup")
    print("=" * 50)

    # Create dirs
    dirs = [
        "data/raw_docs", "data/processed_docs", "data/embeddings",
        "data/vector_index", "data/user_data/sessions",
        "data/user_data/profiles", "logs", "models_cache/downloaded_models",
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
    print("✅ Directories created")

    # Init DB
    from app.database.sqlite_db import init_db
    init_db()
    print("✅ SQLite database initialized")

    # Check Ollama
    from app.models.ollama_client import is_ollama_running, list_available_models
    if is_ollama_running():
        models = list_available_models()
        print(f"✅ Ollama is running. Models: {models or '(none pulled yet)'}")
    else:
        print("⚠️  Ollama not running.")
        print("   Install: curl -fsSL https://ollama.ai/install.sh | sh")
        print("   Start:   ollama serve")
        print("   Pull:    ollama pull phi3:mini")

    # Check sentence-transformers
    try:
        from sentence_transformers import SentenceTransformer
        print("✅ sentence-transformers available")
    except ImportError:
        print("❌ sentence-transformers not installed")
        print("   Run: pip install sentence-transformers")

    # Check faiss
    try:
        import faiss
        print("✅ FAISS available")
    except ImportError:
        print("❌ faiss-cpu not installed")
        print("   Run: pip install faiss-cpu")

    print("\n✅ Setup complete. Run:")
    print("   streamlit run app/ui/streamlit_app.py")
    print("   OR")
    print("   python run.py")


if __name__ == "__main__":
    main()
