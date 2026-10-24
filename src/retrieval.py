"""Bounded hybrid retrieval with exact source citations; no eligibility decision."""
import hashlib
import json
import math
import re
from runtime_config import embedding_model, chroma_path, collection_name
from collections import Counter
from functools import lru_cache
from pathlib import Path

from langchain_core.tools import tool

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = collection_name()
MODEL = embedding_model()
STOP = set('a an the is are was were be been of for to from in on at by and or with what which when how can may must should my i me it its this that does do have has as all about required requirement requirements handbook student students please say says'.split())


def tokens(text):
    return [w for w in re.findall(r'[a-z0-9]+', text.lower()) if w not in STOP]


def normal(text):
    return ' '.join(text.split())


@lru_cache(maxsize=1)
def resources():
    import chromadb
    from langchain_huggingface import HuggingFaceEmbeddings
    client = chromadb.PersistentClient(path=str(chroma_path()))
    try:
        collection = client.get_collection(COLLECTION)
    except Exception as exc:
        raise RuntimeError('Build the v2 index using python src/index_corpus.py --apply first.') from exc
    if (collection.metadata or {}).get('embedding_model') != MODEL:
        raise RuntimeError('Index embedding model does not match retrieval configuration.')
    embedding = HuggingFaceEmbeddings(model_name=MODEL)
    return collection, embedding


@lru_cache(maxsize=1)
def source_pages():
    items = json.loads((ROOT / 'data/processed/handbook_pages.json').read_text(encoding='utf-8'))
    return {int(p['page']): p['text'] for p in items}


def validate_record(record):
    """Check offsets and page hash against the local extracted source; fail closed."""
    m = record['metadata']
    page = source_pages().get(m['pdf_page'], '')
    if hashlib.sha256(page.encode('utf-8')).hexdigest() != m['page_text_sha256']:
        raise ValueError('Index/source mismatch: re-index the corpus.')
    if page[m['char_start']:m['char_end']] != record['text']:
        raise ValueError('Indexed text does not match its cited source offsets.')
    if 'parent_text' in m and page[m['parent_char_start']:m['parent_char_end']] != m['parent_text']:
        raise ValueError('Indexed parent context does not match its cited source offsets.')


def read_records(collection):
    data = collection.get(include=['documents', 'metadatas'])
    return {identifier: {'id': identifier, 'text': text, 'metadata': metadata}
            for identifier, text, metadata in zip(data['ids'], data['documents'], data['metadatas'])}


def lexical_rank(query, records):
    terms = set(tokens(query))
    documents = {key: Counter(tokens(r['text'])) for key, r in records.items()}
    lengths = {key: sum(count.values()) for key, count in documents.items()}
    average = sum(lengths.values()) / max(1, len(lengths)) or 1
    frequencies = Counter(term for count in documents.values() for term in count)
    scores = {}
    for key, count in documents.items():
        score = 0.0
        for term in terms:
            tf = count[term]
            if tf:
                idf = math.log(1 + (len(documents) - frequencies[term] + .5) / (frequencies[term] + .5))
                score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * lengths[key] / average))
        if score:
            scores[key] = score
    return sorted(scores, key=lambda key: (-scores[key], key))[:24]


def citation(record):
    m = record['metadata']
    section = m['section'] or None
    clause = m['clause_id'] or None
    kind = m.get('clause_label_kind', '')
    # Generated bullet ordinals are locators, not numbering printed in the PDF.
    if kind.startswith('generated'):
        label = f"Section {section}; {kind.replace('_', ' ')}: {clause}"
    else:
        label = f"Clause {clause}" if clause else 'Section not yet reviewed'
    return dict(evidence_id=record['id'], source=m['source'], title=m['handbook_title'],
                version=m['handbook_version'], chapter=m['chapter'] or None,
                section=section, clause_id=clause, locator_kind=kind or None, locator_label=label,
                pdf_page=m['pdf_page'], printed_page=m['printed_page'] or None,
                printed_page_verified=m['printed_page_verified'],
                citation_metadata_verified=m['citation_metadata_verified'],
                char_start=m['char_start'], char_end=m['char_end'],
                page_text_sha256=m['page_text_sha256'], exact_quote=record['text'],
                source_note=m.get('source_note', ''))


def retrieve(query, limit=4):
    if not query.strip() or len(query) > 4000:
        raise ValueError('Query must contain 1-4000 characters.')
    collection, embedding = resources()
    records = read_records(collection)
    if not records:
        raise RuntimeError('The v2 index is empty.')
    lexical = lexical_rank(query, records)
    # A conservative lexical gate handles empty/no-overlap queries only. It is not
    # an out-of-corpus classifier; semantic relevance still requires human/agent review.
    if not lexical:
        return dict(status='NO_SUFFICIENT_EVIDENCE', passages=[],
                    reason='No non-stopword query terms matched the indexed corpus.')
    vector = collection.query(query_embeddings=[embedding.embed_query(query)],
                              n_results=min(24, len(records)), include=['distances'])
    semantic = vector['ids'][0]
    distances = dict(zip(semantic, vector['distances'][0]))
    scores = Counter()
    for ranking in (lexical, semantic):
        for rank, key in enumerate(ranking, 1):
            scores[key] += 1 / (60 + rank)
    ranked = sorted(scores, key=lambda key: (-scores[key], key))
    passages, seen_groups, seen_pages = [], set(), set()
    # Prefer reviewed clauses among hybrid candidates; preserve generic search
    # coverage when there is no reviewed candidate for the query.
    reviewed = [key for key in ranked if records[key]['metadata']['citation_metadata_verified']
                and set(tokens(query)).intersection(tokens(records[key]['text']))]
    order = reviewed + [key for key in ranked if key not in reviewed]
    for key in order:
        record = records[key]
        m = record['metadata']
        group = (m['pdf_page'], m['section']) if m['citation_metadata_verified'] else (key, '')
        if group in seen_groups or (not m['citation_metadata_verified'] and m['pdf_page'] in seen_pages):
            continue
        siblings = [r for r in records.values() if r['metadata']['citation_metadata_verified']
                    and r['metadata']['pdf_page'] == m['pdf_page'] and r['metadata']['section'] == m['section']] if m['citation_metadata_verified'] else [record]
        siblings.sort(key=lambda r: r['metadata']['char_start'])
        for sibling in siblings:
            validate_record(sibling)
        passages.append(dict(matched_evidence_id=key, hybrid_rank_score=scores[key],
                             vector_distance=distances.get(key),
                             context=m.get('parent_text', record['text']),
                             citations=[citation(r) for r in siblings]))
        seen_groups.add(group)
        seen_pages.add(m['pdf_page'])
        if len(passages) >= min(max(limit, 1), 4):
            break
    return dict(status='CANDIDATES_RETRIEVED', collection=COLLECTION,
                notice='Source-text checks do not prove claim entailment or eligibility. Distances are not confidence. Human review is required.',
                passages=passages)


@tool
def search_regulations(query: str) -> str:
    """Search handbook candidates and return complete reviewed clause context and citations."""
    try:
        return json.dumps(retrieve(query), ensure_ascii=False)
    except (RuntimeError, ValueError) as exc:
        return json.dumps(dict(status='NO_SUFFICIENT_EVIDENCE', reason=str(exc), passages=[]))


@tool
def fetch_exact_clause(clause_id: str) -> str:
    """Fetch a reviewed clause by its exact locator ID, including generated locator labels."""
    collection, _ = resources()
    records = read_records(collection)
    matches = [r for r in records.values() if r['metadata']['clause_id'] == clause_id
               and r['metadata']['citation_metadata_verified']]
    for record in matches:
        validate_record(record)
    return json.dumps(dict(status='FOUND' if matches else 'NO_SUFFICIENT_EVIDENCE',
                           citations=[citation(r) for r in matches]), ensure_ascii=False)


@tool
def verify_source_quote(evidence_id: str, quote: str) -> str:
    """Check an exact quotation's presence in a source-validated evidence record; not entailment."""
    collection, _ = resources()
    record = read_records(collection).get(evidence_id)
    if record is None:
        return json.dumps(dict(quote_supported=False, reason='Unknown evidence ID', claim_entailment_checked=False))
    try:
        validate_record(record)
    except ValueError as exc:
        return json.dumps(dict(quote_supported=False, reason=str(exc), claim_entailment_checked=False))
    supported = bool(normal(quote)) and normal(quote) in normal(record['text'])
    return json.dumps(dict(quote_supported=supported, evidence_id=evidence_id,
                           comparison='Exact substring after whitespace normalization only',
                           claim_entailment_checked=False))


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    for query in ['minimum attendance percentage and consequences',
                  'medical attendance condonation certificate and application deadline',
                  'missed terminal examination medical leave deadline',
                  'X grade retest deadline summer term']:
        result = retrieve(query)
        print('\nQUERY:', query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
