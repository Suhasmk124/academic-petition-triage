"""Source-authored challenge pairs for the conservative extractive acceptance gate."""
import json
from pathlib import Path
from assessment import Finding,verify_findings
from index_corpus import reviewed
from retrieval import source_pages,citation,validate_record,normal

ROOT=Path(__file__).resolve().parents[1]


def main():
    records={record['id']:record for record in reviewed(source_pages())}
    by_clause={record['metadata']['clause_id']:record for record in records.values()}
    cases=[]
    for record in records.values():
        cases.append((record['metadata']['clause_id']+'-canonical',record,normal(record['text']),True))
    mutations=[('8.1(i)','80%','70%'),('8.1(ii)','CMO','any doctor'),('8.1(iii)','SLCM','SAP'),
               ('8.1(iii)','seven days','thirty days'),('5.7(C)(3)','June 30','July 30'),
               ('5.7(C)(4)','shall not be awarded','shall be awarded')]
    for number,(clause,old,new) in enumerate(mutations):
        record=by_clause[clause]; text=normal(record['text'])
        if old not in text:raise AssertionError('Challenge source anchor changed: '+clause)
        cases.append((f'mutation-{number+1}',record,text.replace(old,new,1),False))
    # These short statements are supported in meaning but intentionally rejected
    # by the full-quotation policy. Their false-negative cost stays visible.
    for clause,claim in [('8.1(i)','Attendance in classes must be at least 80%.'),
                         ('8.1(iii)','Medical leave applications on SLCM are due within seven days of recovery.'),
                         ('5.7(C)(4)','X grades shall not be awarded for summer-term courses.')]:
        cases.append((clause+'-supported-paraphrase',by_clause[clause],claim,True))
    rows=[]
    for identifier,record,claim,expected in cases:
        item=citation(record)
        finding=Finding(finding_id=identifier,evidence_id=record['id'],statement=claim,supporting_quote=record['text'],citation=item)
        check=verify_findings([finding],records,validate_record)
        rows.append(dict(id=identifier,clause=item['clause_id'],claim=claim,meaning_supported_label=expected,
                         quote_presence_only_accepts=True,extractive_gate_accepts=check.passed))
    summary={}
    for policy in ('quote_presence_only_accepts','extractive_gate_accepts'):
        tp=sum(row[policy] and row['meaning_supported_label'] for row in rows)
        fp=sum(row[policy] and not row['meaning_supported_label'] for row in rows)
        fn=sum(not row[policy] and row['meaning_supported_label'] for row in rows)
        summary[policy]=dict(true_positive=tp,false_positive=fp,false_negative=fn,precision=tp/(tp+fp) if tp+fp else None,
                             recall=tp/(tp+fn) if tp+fn else None,unsupported_acceptance_rate=fp/max(1,sum(not row['meaning_supported_label'] for row in rows)))
    report=dict(cases=len(rows),results=rows,summary=summary,hosted_requests=0,
                scope='Hand-authored source-meaning labels and exact extractive acceptance. A component before/after comparison, not a general semantic/NLI benchmark. Valid paraphrases are deliberately rejected; the recall cost is reported.')
    (ROOT/'evaluations/semantic_challenges.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    assert summary['extractive_gate_accepts']['false_positive']==0
    print(f'PASS: {len(rows)} source-meaning challenges; all condition mutations rejected, conservative paraphrase rejection reported.')
    return report


if __name__=='__main__':main()
