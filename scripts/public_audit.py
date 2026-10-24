"""Scan reachable Git history and current tracked files without exposing secret values."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    def git(*arguments): return subprocess.check_output(['git',*arguments],cwd=ROOT)
    configured = [value.encode() for key,value in dotenv_values(ROOT/'.env').items() if value and len(value)>=16 and any(token in key.upper() for token in ('KEY','SECRET','PASSWORD','TOKEN'))]
    directory = ROOT/'.secrets'
    if directory.exists(): configured.extend(path.read_bytes().strip() for path in directory.iterdir() if path.is_file())
    patterns = [rb'gsk_[A-Za-z0-9]{25,}',rb'gh[pousr]_[A-Za-z0-9]{25,}',rb'github_pat_[A-Za-z0-9_]{30,}',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
    objects = git('rev-list','--objects','--all').decode().splitlines()
    findings=[]; scanned=0
    for entry in objects:
        identifier,_,path = entry.partition(' ')
        if git('cat-file','-t',identifier).strip()!=b'blob': continue
        data=git('cat-file','blob',identifier); scanned+=1
        if any(secret and secret in data for secret in configured) or any(re.search(pattern,data) for pattern in patterns):
            findings.append(dict(object=identifier,path=path,reason='Potential credential material'))
        if path=='.env' or path.startswith(('.secrets/','data/runtime/')):
            findings.append(dict(object=identifier,path=path,reason='Private runtime/configuration path in history'))
    for path in git('ls-files','--cached','--others','--exclude-standard').decode().splitlines():
        file=ROOT/path
        if not file.is_file(): continue
        data=file.read_bytes()
        if any(secret and secret in data for secret in configured) or any(re.search(pattern,data) for pattern in patterns):
            findings.append(dict(path=path,reason='Potential credential material in current tree'))
    report=dict(passed=not findings,history_blobs_scanned=scanned,findings=findings,
                scope='Exact configured-secret and common credential-pattern scan of reachable history plus tracked working files. Does not replace a general data/privacy review.')
    (ROOT/'evaluations/publication_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'blobs_scanned':scanned,'finding_count':len(findings)}))
    if findings: raise SystemExit('Publication blocked: inspect the audit report; no credential values were printed.')


if __name__=='__main__': main()
