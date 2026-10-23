
import json
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

ROOT = Path(__file__).resolve().parents[1]
PAGES_FILE = ROOT / "data" / "processed" / "handbook_pages.json"
DB_DIR = ROOT / "data" / "chroma_db"
COLLECTION = "iisc_academic_regulations"

def main():
    if not PAGES_FILE.exists():
        raise FileNotFoundError(
            f"Extract the handbook first: {PAGES_FILE}"
        )

    pages = json.loads(PAGES_FILE.read_text(encoding="utf-8"))

    documents = []
    for item in pages:
        text = item["text"].strip()
        if not text:
            continue

        documents.append(
            Document(
                page_content=text,
                metadata={
                    "source": "UG-HandBook-25-26.pdf",
                    "pdf_page": item["page"],
                    "printed_page": max(1, item["page"] - 3),
                    "chapter": "Chapter 8"
                    if "CHAPTER 8" in text.upper()
                    else "General regulations",
                },
            )
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)

    print(f"Pages with text: {len(documents)}")
    print(f"Chunks to index: {len(chunks)}")

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

    DB_DIR.mkdir(parents=True, exist_ok=True)

    # Stable IDs make repeated indexing idempotent.
    ids = []
    for i, chunk in enumerate(chunks):
        page = chunk.metadata["pdf_page"]
        chunk.metadata["chunk_id"] = f"handbook-{page}-{i}"
        ids.append(chunk.metadata["chunk_id"])

    client = chromadb.PersistentClient(path=str(DB_DIR))

    # Rebuild only this project's collection on each initial indexing run.
    # We will replace this with versioned incremental updates later.
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass

    store = Chroma(
        client=client,
        collection_name=COLLECTION,
        embedding_function=embeddings,
    )

    batch_size = 64
    for start in range(0, len(chunks), batch_size):
        store.add_documents(
            documents=chunks[start:start + batch_size],
            ids=ids[start:start + batch_size],
        )

    print(f"Indexed chunks: {len(chunks)}")
    print(f"Database: {DB_DIR}")
    print(f"Collection: {COLLECTION}")

    query = (
        "What is the minimum attendance requirement and "
        "when can attendance shortage be condoned on medical grounds?"
    )

    results = store.similarity_search_with_score(query, k=5)

    print("\n--- RETRIEVAL TEST ---")
    for rank, (doc, score) in enumerate(results, start=1):
        print(
            f"\n[{rank}] PDF page {doc.metadata['pdf_page']} "
            f"| distance={score:.4f}"
        )
        print(doc.page_content[:1200])

if __name__ == "__main__":
    main()
