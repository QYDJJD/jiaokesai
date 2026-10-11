"""Controlled ablations and windowed search. All inputs are synthetic."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import json
from grading_engine import grade_case
from directional_grading import grade_directional
from build_directional_library import cases
from piecewise_plan_search import enumerate_piecewise_plans

OUT = Path(__file__).resolve().parent

def main():
    checks = []
    def check(name, ok):
        checks.append({'name': name, 'pass': bool(ok)})
        assert ok, name
    source = json.loads((OUT/'汇报补强验证结果.json').read_text(encoding='utf-8'))
    rows = []
    for row in source['coverage_grid']['rows']:
        p = row['input']; full = grade_case(p)
        nominal = grade_case({**p, 'shapes': ['uniform']})['grade']
        # Remove only peak goal; retain every arrival profile, deadline and supply window.
        completion = 'F' + str(next((j for j,t in enumerate(full['tiers']) if all(
            r['clear_h'] is not None and r['clear_h'] <= p['d']+1+1e-9 for r in t['runs'])),3))
        rows.append({'id': row['id'], 'input': p, 'full': full['grade'],
                     'uniform_only': nominal, 'completion_only': completion})
    for key in ['uniform_only','completion_only']:
        check(key+'_never_more_demanding', all(r[key] <= r['full'] for r in rows))
    summary = {key: {'same': sum(r[key]==r['full'] for r in rows),
                      'lower': sum(r[key]<r['full'] for r in rows),
                      'transitions': dict(Counter(r[key]+'→'+r['full'] for r in rows if r[key]!=r['full']))}
               for key in ['uniform_only','completion_only']}
    by_id = {c['id']: c['input'] for c in cases()}; searches = []
    for sid, step in [('SC-N04',500),('SC-N06',100),('SC-N07',500)]:
        c = deepcopy(by_id[sid]); horizon = max(x['d']+x['h'] for x in c['directions'].values())
        grid = enumerate_piecewise_plans(c,[0,1,horizon],step)
        c['plans'] = grid['plans']; result = grade_directional(c)
        check(sid+'_valid_search', result['grade'].startswith('F'))
        check(sid+'_not_worse_than_original', result['grade'] <= grade_directional(by_id[sid])['grade'])
        witness = next((p for p in result['plans'] if p['pass'] and p['introduced_layer']==int(result['grade'][1])),None)
        searches.append({'id':sid,'original_grade':grade_directional(by_id[sid])['grade'],
                         'grade':result['grade'], **{k:v for k,v in grid.items() if k!='plans'},
                         'witness': next((p for p in grid['plans'] if witness and p['id']==witness['id']),None)})
    check('N04_independent_balanced_witness', searches[0]['grade']=='F0')
    check('N07_service_extension_required', searches[2]['grade']=='F1')
    # Independent integral bound: B at V1 has 100*2.5 + 400*1.5 = 850 < 1000.
    check('N06_independent_V1_capacity_bound', 100*2.5+400*1.5 < 1000 and searches[1]['grade']=='F2')
    auto=enumerate_piecewise_plans(by_id['SC-N07'],[0,2.5],500)
    check('physical_window_breakpoint_inserted',auto['breakpoints']==[0,1,2.5] and auto['feasible_plan_count']==64)
    for label, breaks, budget in [('early_horizon',[0,1],100000),('budget',[0,1,2.5],2)]:
        try:
            enumerate_piecewise_plans(by_id['SC-N04'],breaks,500,budget); ok=False
        except ValueError: ok=True
        check('reject_'+label,ok)
    # A disconnected service window cannot serve later arrivals with unused earlier capacity.
    p={'q':1000,'d':2,'shapes':['back'],'ends':[1,1,1], 'p':1}
    r=grade_case(p,k=1000,h=1)
    check('unused_early_capacity_cannot_be_stored',r['grade']=='F3' and
          all(t['runs'][0]['unserved_people']>0 for t in r['tiers']))
    output={'version':'METHOD-COMPARISON-01','evidence_type':'SYNTHETIC','date':'2026-10-11',
            'baseline_scope':'controlled ablation of one assumption/constraint, not reproduction of published algorithms',
            'checks':checks,'comparison_summary':summary,'comparison_rows':rows,'piecewise_searches':searches}
    (OUT/'方法对照与分时搜索结果.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'checks':len(checks),'comparison':summary,'searches':searches},ensure_ascii=False))

if __name__=='__main__': main()
