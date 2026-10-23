"""Preview first; --apply incrementally writes a separate v2 Chroma collection."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SOURCE = 'UG-HandBook-25-26.pdf'
TITLE = 'Student Information Handbook and Scheme of Instructions: Undergraduate Programmes'
VERSION = '2025-26'
COLLECTION = 'iisc_academic_regulations_v2'
MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
PRINTED = {25: '22', 26: '23', 37: '34'}


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def locate(text, start, end=None):
    match = re.search(start, text, re.M)
    if match is None:
        raise ValueError(f'Source anchor missing: {start}')
    stop = re.search(end, text[match.end():], re.M) if end else None
    if end and stop is None:
        raise ValueError(f'Source end anchor missing: {end}')
    a, b = match.start(), match.end() + stop.start() if stop else len(text)
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return a, b


def record(pages, page, a, b, identifier, **extra):
    text = pages[page][a:b]
    metadata = dict(source=SOURCE, handbook_title=TITLE, handbook_version=VERSION,
                    schema_version='clause-pilot-v2', pdf_page=page,
                    printed_page=PRINTED.get(page, ''), printed_page_verified=page in PRINTED,
                    chapter='', section='', section_title='', clause_id='',
                    citation_metadata_verified=False, char_start=a, char_end=b,
                    page_text_sha256=sha(pages[page]))
    metadata.update(extra)
    metadata['record_sha256'] = sha(json.dumps([text, metadata], sort_keys=True))
    metadata['chunk_id'] = f'ug-2025-26-{identifier}'
    return dict(id=metadata['chunk_id'], text=text, metadata=metadata)


def reviewed(pages):
    # These three section boundaries and page labels were visually checked.
    specs = [
        (25, '5.6', 'Terminal Examination', '5',
         r'^5\.6\s+TERMINAL EXAMINATION', r'^5\.7\s+HANDLING'),
        (26, '5.7(C)', 'X Grade', '5', r'^C\.\s+‘X’ Grade', None),
        (37, '8.1', 'Attendance', '8', r'^8\.1\s+ATTENDANCE', r'^8\.2\s+LEAVE RULES'),
    ]
    rows = []
    for page, section, title, chapter, first, last in specs:
        a, b = locate(pages[page], first, last)
        parent = pages[page][a:b]
        markers = list(re.finditer(r'^[ \t]*(?:[ivxlcdm]+\)|[•\uf0b7])\s*', parent, re.M))
        bounds = [0] + [m.start() for m in markers] + [len(parent)]
        for ordinal, (left, right) in enumerate(zip(bounds, bounds[1:])):
            piece = parent[left:right]
            if not piece.strip() or (ordinal == 0 and section != '5.6'):
                continue
            start = a + left + len(piece) - len(piece.lstrip())
            end = a + right - (len(piece) - len(piece.rstrip()))
            label = 'introduction' if ordinal == 0 else str(ordinal)
            if ordinal and section != '5.7(C)':
                label = re.match(r'([ivxlcdm]+)\)', pages[page][start:end]).group(1)
            note = ''
            if section == '5.6' and ordinal:
                note = ('Source prints Refer Para. 5.5 (C); X Grade heading is 5.7(C). '
                        'Preserve printed reference and flag inconsistency for human review.')
            rows.append(record(pages, page, start, end, f'verified-{section}-{label}',
                               section=section, section_title=title, chapter=chapter,
                               clause_id=f'{section}({label})',
                               clause_label_kind='generated_bullet_ordinal' if section == '5.7(C)' else 'source_label',
                               citation_metadata_verified=True, parent_text=parent,
                               parent_char_start=a, parent_char_end=b, source_note=note))
    # Neighboring exceptions remain distinct from the attendance provision.
    related = [
        (26, '5.7(B)', 'Make-Up Examinations', 'attendance_exclusion',
         r'^[ \t]*\uf0b7\s*If a student secures an F grade due to shortage',
         r'^[ \t]*\uf0b7\s*Students can register'),
        (37, '8.2', 'Leave Rules', 'i', r'^i\)\s+Leave on personal grounds', r'^ii\)'),
        (37, '8.2', 'Leave Rules', 'v', r'^v\)\s+Absence for a period', r'^vi\)'),
    ]
    for page, section, title, label, first, last in related:
        a, b = locate(pages[page], first, last)
        rows.append(record(pages, page, a, b, f'verified-{section}-{label}',
                           section=section, section_title=title, chapter=section.split('.')[0],
                           clause_id=f'{section}({label})', citation_metadata_verified=True,
                           clause_label_kind='source_label' if section == '8.2' else 'generated_description',
                           parent_text=pages[page][a:b], parent_char_start=a, parent_char_end=b,
                           source_note=''))
    return rows


def build(pages):
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    rows = reviewed(pages)
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150, add_start_index=True)
    for page, text in sorted(pages.items()):
        for number, chunk in enumerate(splitter.split_documents([Document(page_content=text)])):
            a = chunk.metadata['start_index']
            b = a + len(chunk.page_content)
            if a < 0 or text[a:b] != chunk.page_content:
                raise ValueError(f'Exact source offset mismatch on PDF page {page}')
            rows.append(record(pages, page, a, b, f'page-{page}-chunk-{number}'))
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate record IDs')
    return rows


def apply(root, rows):
    import chromadb
    from langchain_huggingface import HuggingFaceEmbeddings
    client = chromadb.PersistentClient(path=str(root / 'data/chroma_db'))
    store = client.get_or_create_collection(COLLECTION, metadata={'embedding_model': MODEL})
    if (store.metadata or {}).get('embedding_model') != MODEL:
        raise ValueError('Embedding model mismatch: use a different collection')
    old = store.get(include=['metadatas'])
    previous = dict(zip(old['ids'], old['metadatas']))
    changed = [r for r in rows if (previous.get(r['id']) or {}).get('record_sha256') != r['metadata']['record_sha256']]
    stale = sorted(set(previous) - {r['id'] for r in rows})
    if changed:
        embedding = HuggingFaceEmbeddings(model_name=MODEL)
        for start in range(0, len(changed), 64):
            batch = changed[start:start + 64]
            vectors = embedding.embed_documents([r['text'] for r in batch])
            store.upsert(ids=[r['id'] for r in batch], documents=[r['text'] for r in batch],
                         metadatas=[r['metadata'] for r in batch], embeddings=vectors)
    # Delete stale v2 records only after all upserts succeed. No collection deletion.
    for start in range(0, len(stale), 64):
        store.delete(ids=stale[start:start + 64])
    print(f'Upserted: {len(changed)}; unchanged: {len(rows) - len(changed)}; removed: {len(stale)}')
    print(f'Collection: {COLLECTION}; records: {store.count()}')
    print('Legacy collection preserved. Current retrieval still uses the legacy collection.')


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--preview', action='store_true', help='Read-only; default')
    mode.add_argument('--apply', action='store_true', help='Incrementally index v2')
    args = parser.parse_args()
    items = json.loads((args.root / 'data/processed/handbook_pages.json').read_text(encoding='utf-8'))
    pages = {int(p['page']): p['text'] for p in items}
    if len(items) != len(pages) or not all(p in pages for p in (25, 26, 37)):
        raise ValueError('Duplicate or missing required pages')
    rows = build(pages)
    verified = [r for r in rows if r['metadata']['citation_metadata_verified']]
    print(f'Pages: {len(pages)}; records: {len(rows)}; reviewed clause records: {len(verified)}')
    for r in verified:
        m = r['metadata']
        if pages[m['pdf_page']][m['char_start']:m['char_end']] != r['text']:
            raise ValueError('Source slice mismatch')
        print(f"\n{m['clause_id']} | PDF {m['pdf_page']} | printed {m['printed_page']}")
        print(r['text'])
        if m['source_note']:
            print('SOURCE NOTE:', m['source_note'])
    if args.apply:
        apply(args.root, rows)
    else:
        print('\nPREVIEW ONLY: no database or project data written.')
        print('All source slices validated. Unreviewed chunks have unknown chapter/section metadata.')


if __name__ == '__main__':
    main()


