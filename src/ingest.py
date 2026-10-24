"""Auditable PDF extraction with source fingerprint and explicit source-change approval."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1]


def ingest(root=ROOT,apply=False,accept_source_change=False):
    started=time.monotonic(); pdf=root/'data/raw/UG-HandBook-25-26.pdf'
    digest=hashlib.sha256(pdf.read_bytes()).hexdigest()
    manifest_path=root/'data/processed/source_manifest.json'
    previous=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    changed=bool(previous and previous['pdf_sha256']!=digest)
    if changed and not accept_source_change:
        raise ValueError('Source PDF changed. Review page labels and clause anchors before using --accept-source-change.')
    with fitz.open(pdf) as document:
        pages=[{'page':number,'text':page.get_text('text')} for number,page in enumerate(document,1)]
    serialized=json.dumps(pages,ensure_ascii=False,indent=2)
    destination=root/'data/processed/handbook_pages.json'
    unchanged=destination.exists() and destination.read_text(encoding='utf-8')==serialized
    manifest=dict(pdf_sha256=digest,pages_sha256=hashlib.sha256(serialized.encode()).hexdigest(),
                  pages=len(pages),source_version='2025-26',extractor_version=importlib.metadata.version('pymupdf'))
    if apply:
        destination.parent.mkdir(parents=True,exist_ok=True)
        if not unchanged:
            destination.write_text(serialized,encoding='utf-8')
            (destination.parent/'handbook_text.txt').write_text('\n'.join(f"\n--- PAGE {page['page']} ---\n{page['text']}" for page in pages),encoding='utf-8')
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return dict(**manifest,applied=apply,unchanged=unchanged,source_change=changed,elapsed_seconds=time.monotonic()-started)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true'); parser.add_argument('--accept-source-change',action='store_true')
    args=parser.parse_args(); print(json.dumps(ingest(apply=args.apply,accept_source_change=args.accept_source_change),indent=2))


if __name__=='__main__':main()
