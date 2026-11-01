"""Portable officer handoffs. Values are escaped; no raw petition or secrets included."""
from html import escape


def review_packet(run):
    keys=('run_id','status','mode','correlation_id','created_at','updated_at','attempts','result','error')
    return {'schema_version':'review-packet-v1','human_review_required':True,'final_decision_made':False,
            'notice':'Conditional source-backed context only. Facts are unverified; an academic officer must decide.',
            'run':{key:run[key] for key in keys if key in run}}


def review_html(packet):
    run=packet['run']; result=run.get('result') or {}
    brief=result.get('draft') or result.get('assessment') or {}
    def text(value): return escape(str(value),quote=True)
    findings=[]
    for item in brief.get('claims',brief.get('findings',[])):
        cite=item.get('citation',{})
        findings.append('<article><h3>'+text(cite.get('clause_id','Source provision'))+
                        ' - PDF page '+text(cite.get('pdf_page','unknown'))+'</h3><blockquote>'+
                        text(item.get('supporting_quote',cite.get('exact_quote','')))+
                        '</blockquote><p>'+text(cite.get('title',cite.get('source','Handbook')))+' - '+text(cite.get('version',''))+
                        ('; printed page '+text(cite.get('printed_page')) if cite.get('printed_page_verified') else '')+
                        '</p><p>'+text(cite.get('source_note',''))+'</p><p>Evidence: '+text(item.get('evidence_id',''))+'</p></article>')
    missing=''.join('<li>'+text(item)+'</li>' for item in brief.get('missing_evidence',[]))
    position=result.get('position',{})
    reasons=''.join('<li>'+text(item)+'</li>' for item in position.get('reasons',[]))
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Academic officer review brief</title>'
            '<style>body{font:16px/1.5 system-ui;max-width:850px;margin:40px auto;padding:20px;color:#173f36}'
            'blockquote{white-space:pre-wrap;border-left:3px solid #789;padding-left:16px}article{break-inside:avoid}'
            '.notice{border:2px solid;padding:14px}@media print{body{margin:0;font-size:11pt}}</style>'
            '<h1>Academic officer review brief</h1><p class="notice">'+text(packet['notice'])+'</p>'
            '<p>Run: '+text(run['run_id'])+'<br>Execution: '+text(run['status'])+
            '<br>Mode: '+text(run.get('mode',''))+'<br>Trace: '+text(result.get('trace_id','unavailable'))+'</p>'
            '<h2>Conditional position</h2><p>'+text(position.get('recommendation','REFER_TO_COMMITTEE'))+
            '</p><ul>'+reasons+'</ul><h2>Source provisions</h2>'+(''.join(findings) or '<p>No supported findings available. Refer to an officer.</p>')+
            '<h2>Records to establish before a decision</h2><ul>'+missing+'</ul>'
            '<p>Simulation: '+text(result.get('mode')=='STUB')+'; output gate: '+text(result.get('safety',{}).get('output','unavailable'))+
            '. This document is an exported snapshot, not an approval or rejection.</p></html>')
