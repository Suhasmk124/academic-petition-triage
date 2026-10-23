
from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "data" / "chroma_db"

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

store = Chroma(
    collection_name="iisc_academic_regulations",
    persist_directory=str(DB_DIR),
    embedding_function=embeddings,
)

queries = [
    "What is the minimum attendance percentage and what happens below it?",
    "How can attendance shortage be condoned for medical reasons?",
    "What medical certificate and application deadline are required?",
]

for query in queries:
    print("\n" + "=" * 80)
    print("QUERY:", query)

    results = store.similarity_search(query, k=3)

    for rank, doc in enumerate(results, start=1):
        print(
            f"\n[{rank}] PDF page {doc.metadata.get('pdf_page')} "
            f"| {doc.metadata.get('source')}"
        )
        print(doc.page_content[:900])
