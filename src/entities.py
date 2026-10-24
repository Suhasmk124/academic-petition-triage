"""Small auditable extraction of stated entities; never verification of student facts."""
import re
from datetime import date
from assessment import classify


def extract_entities(petition):
    text=petition.lower()
    result={'petition_type':classify(petition),'facts_verified':False,'course_codes':sorted(set(re.findall(r'\b[A-Z]{2,4}[ -]?\d{3}\b',petition))),
            'portals':sorted(portal for portal in ('SAP','SLCM') if re.search(r'\b'+portal+r'\b',petition,re.I)),
            'dates':[]}
    for value in re.findall(r'\b\d{4}-\d{2}-\d{2}\b',petition):
        try: result['dates'].append(date.fromisoformat(value).isoformat())
        except ValueError: pass
    percentages=[float(value) for value in re.findall(r'\b(\d{1,3}(?:\.\d+)?)\s*%',text)]
    result['stated_attendance_percent']=percentages[0] if len(percentages)==1 and 0<=percentages[0]<=100 and result['petition_type']=='ATTENDANCE' else None
    result['medical_reason_stated']=any(term in text for term in ('medical','illness','sick'))
    return result
