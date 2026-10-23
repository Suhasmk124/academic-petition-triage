
from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.tools import tool

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "data" / "chroma_db"
COLLECTION = "iisc_academic_regulations"

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

store = Chroma(
    collection_name=COLLECTION,
    persist_directory=str(DB_DIR),
    embedding_function=embeddings,
)


@tool
def search_regulations(query: str) -> str:
    """Search the academic handbook and return potentially relevant regulation passages."""

    results = store.similarity_search_with_score(query, k=8)

    # Chroma returns distances: lower means closer, not higher confidence.
    # This threshold is a provisional retrieval filter, not proof of relevance.
    max_distance = 1.15

    passages = []

    for doc, distance in results:
        if distance > max_distance:
            continue

        text = doc.page_content.strip()
        if not text:
            continue

        page = doc.metadata.get("pdf_page", "unknown")
        source = doc.metadata.get("source", "unknown")

        passages.append(
            f"Source: {source}\n"
            f"PDF page: {page}\n"
            f"Retrieved distance: {distance:.4f}\n"
            f"Passage:\n{text}"
        )

    if not passages:
        return (
            "NO_SUFFICIENT_EVIDENCE: No passages passed the provisional "
            "retrieval filter. Do not invent a regulation; retry with a "
            "different query or refer the petition for human review."
        )

    return "\n\n" + ("\n" + "-" * 60 + "\n").join(passages)


if __name__ == "__main__":
    queries = [
        "What is the minimum attendance percentage and what happens below it?",
        "How can attendance shortage be condoned for medical reasons?",
        "What medical certificate and application deadline are required?",
    ]

    for query in queries:
        print("\n" + "=" * 80)
        print("QUERY:", query)
        print(search_regulations.invoke({"query": query}))
