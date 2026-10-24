"""Environment-owned deployment configuration; never log secret values."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env',override=False,encoding='utf-8-sig')


def secret():
    path = os.getenv('TRIAGE_API_KEY_FILE')
    return Path(path).read_text(encoding='utf-8').strip() if path else os.getenv('TRIAGE_API_KEY', '')


def embedding_model():
    return os.getenv('EMBEDDING_MODEL') or 'sentence-transformers/all-MiniLM-L6-v2'


def chroma_path():
    return Path(os.getenv('CHROMA_PATH') or ROOT / 'data/chroma_db')


def collection_name():
    return os.getenv('CHROMA_COLLECTION') or 'iisc_academic_regulations_v2'
