"""Container-only incremental corpus initialization and reproducible vector baseline."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from index_corpus import main
from ingest import ingest
ingest(apply=True)
sys.argv = ['index_corpus.py','--apply']
main()
from retrieval import resources
import chromadb
from runtime_config import chroma_path
collection,_ = resources()
client = chromadb.PersistentClient(path=str(chroma_path()))
legacy = client.get_or_create_collection('iisc_academic_regulations')
if not legacy.count():
    data = collection.get(where={'citation_metadata_verified':False},include=['documents','metadatas','embeddings'])
    legacy.upsert(ids=data['ids'],documents=data['documents'],metadatas=data['metadatas'],embeddings=data['embeddings'])
print('Corpus and baseline are ready.')
