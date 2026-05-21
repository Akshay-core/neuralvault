# Akshay-core
__author__ = "Akshay-core"

# FILE: app/ingestion/pdf_loader.py
import hashlib
from pathlib import Path
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger("pdf_loader")


def extract_text_from_pdf(file_path: str) -> Optional[str]:
    try:
        import pypdf
        text_parts = []
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        return "\n".join(text_parts)
    except ImportError:
        logger.warning("pypdf not installed, trying pdfminer")
    except Exception as e:
        logger.error(f"pypdf failed on {file_path}: {e}")

    try:
        from pdfminer.high_level import extract_text
        return extract_text(file_path)
    except Exception as e:
        logger.error(f"pdfminer failed: {e}")
        return None


def file_hash(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
