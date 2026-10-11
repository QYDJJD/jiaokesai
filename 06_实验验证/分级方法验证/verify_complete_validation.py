"""Predeclared, reproducible method-level validation; no field-data requirement.

Uses a separately derived rational cumulative oracle, closed forms,
generated scenarios, parameter boundaries and traceable library inputs.
"""
from pathlib import Path
from copy import deepcopy
from itertools import product
from random import Random
from collections import Counter
from hashlib import sha256
import json
from independent_reference import CumulativeQueue, reference_single_grade, reference_directional_grade
from grading_engine import evaluate, profile, grade_case
from directional_grading import grade_directional
from build_directional_library import cases, resource, alloc, plan, demand

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
SEED=20261012


def main():
    checks=[];failures=[];max_error=0.0
    def check(name,ok,count=1):
        checks.append({'name':name,'comparisons':count,'pass':bool(ok)})
        if not ok:failures.append(name)
    def compare_metrics(x,ref):
        nonlocal max_error
        for key in ('peak_people','clear_h','residual_at_deadline_people','unserved_people','served_people','arrived_people'):
            a,b=x[key],ref[key]
            if a is None or b is None:
                if not(a is None and b is None):return False
            else:
                err=abs(a-float(b));max_error=max(max_error,err)
                if err>1e-6:return False
        return True
    library=json.loads((ROOT/'03_情景库/初始情景库-v1.json').read_text(encoding='utf-8'))
    hrows=[]
    for c in library['synthetic']:
        g=grade_case(c['input'])['grade'];ref=reference_single_grade(c['input'])
        hrows.append({'id':c['id'],'engine':g,'reference':ref})
    check('all_18_single_library_cards_independent_grade',all(r['engine']==r['reference'] for r in hrows),18)
    nrows=[]
    for c in cases():
        g=grade_directional(c['input'])['grade'];ref=reference_directional_grade(c['input'])
        nrows.append({'id':c['id'],'engine':g,'reference':ref})
    check('all_14_directional_library_cards_independent_grade',all(r['engine']==r['reference'] for r in nrows),14)

    # New inputs are generated after the algorithm is fixed. No hand-picked outputs.
    # This is computational out-of-example checking, not independent social events.
    rng=Random(SEED);queue_inputs=[];queue_ok=True
    for i in range(600):
        ends=[j*.5 for j in range(9)]
        arr=[(a,b,rng.randrange(0,17)*125) for a,b in zip(ends,ends[1:]) if rng.random()<.7]
        cap=[(a,b,rng.randrange(0,21)*100) for a,b in zip(ends,ends[1:]) if rng.random()<.7]
        # Mix finite service, gaps, overlapping physical offers and permanent tail.
        if i%3==0:cap.append((rng.choice(ends),None,rng.choice([125,500,1000])))
        if i%5==0:cap.append((.75,2.75,325))
        b0=rng.choice([0,125,500,1500]);deadline=rng.choice([.25,1,2.5,4,5])
        inp={'arrivals':arr,'supplies':cap,'initial':b0,'deadline':deadline};queue_inputs.append(inp)
        x=evaluate(arr,cap,b0,deadline);ref=CumulativeQueue(arr,cap,b0).result(deadline)
        queue_ok &= compare_metrics(x,ref)
    check('600_new_piecewise_queues_six_metrics',queue_ok,600*6)

    dir_inputs=[];dir_ok=True;dir_counts=Counter()
    for i in range(120):
        ds=['A','B'] if i%2==0 else ['A','B','C']
        c={'safe':True,'known':True,'supported':True,
           'directions':{d:demand(q=rng.choice([250,800,1700,3000]),d=rng.choice([1,2,3]),k=rng.choice([200,600,1200]),h=rng.choice([0,.5,1])) for d in ds},
           'resources':[],'groups':[],'plans':[],
           'joint_profiles':[{'id':'joint-'+str(j),'shapes':{d:rng.choice(['uniform','front','back']) for d in ds}} for j in range(3)],
           'waiting_groups':[{'id':'shared_waiting','directions':ds,'k':rng.choice([300,1000,2000])}]}
        for j in range(3):c['resources'].append(resource('R'+str(j),ds,rng.choice([500,1000,2000]),j,start=0 if j==0 else rng.choice([0,.5,1]),end=None))
        # Each resource's half capacity is divided among eligible directions;
        # all declared plans remain within resource/shared capacities.
        caps=sum(r['capacity'][0][2] for r in c['resources'])
        c['groups']=[{'id':'boarding','resource_ids':[r['id'] for r in c['resources']],'capacity':[[0,None,caps*.6]]}]
        for layer in range(3):
            aa=[]
            for r in c['resources'][:layer+1]:
                start=r['capacity'][0][0];amount=r['capacity'][0][2]/(2*len(ds))
                for d in ds:aa.append(alloc(r['id'],d,amount,start))
            c['plans'].append(plan('P'+str(layer),layer,aa))
        g=grade_directional(c)['grade'];ref=reference_directional_grade(c)
        dir_ok &= g==ref;dir_counts[g]+=1;dir_inputs.append(c)
    check('120_new_two_three_direction_cases_independent_grade',dir_ok,120)

    # Theoretical threshold, with strict failure/equality/strict success.
    boundary_ok=True;boundary_rows=[]
    for b0,k,q,d,h in product([0,500,1000],[500,1000,1500],[500,2000],[.5,2],[0,.5,1]):
        threshold=max((b0+q)/(d+h),(b0+q-k)/d,0)
        for scale in [.99,1,1.01]:
            c=threshold*scale;x=evaluate(profile(q,d,'uniform'),[(0,None,c)],b0,d+h)
            expected=b0<=k and scale>=1
            passed=x['peak_people']<=k+1e-8 and x['clear_h'] is not None and x['clear_h']<=d+h+1e-8
            boundary_ok &= expected==passed
            boundary_rows.append({'B0':b0,'K':k,'Q':q,'D':d,'H':h,'C':c,'expected_pass':expected,'actual_pass':passed})
    check('324_analytical_threshold_boundary_runs',boundary_ok,len(boundary_rows))

    coverage=json.loads((OUT/'汇报补强验证结果.json').read_text(encoding='utf-8'))['coverage_grid']['rows']
    sensitivity=[];sense_ok=True;changed=0;ordering_ok=True
    for row in coverage:
        runs=[]
        for k,h in product([750,1000,1250],[.5,1,2]):
            g=grade_case(row['input'],k,h)['grade'];ref=reference_single_grade(row['input'],k,h)
            sense_ok &= g==ref;runs.append({'K':k,'H':h,'grade':g,'reference':ref})
        def g(k,h):return next(r['grade'] for r in runs if r['K']==k and r['H']==h)
        ordering_ok &= all(g(750,h)>=g(1000,h)>=g(1250,h) for h in [.5,1,2])
        ordering_ok &= all(g(k,.5)>=g(k,1)>=g(k,2) for k in [750,1000,1250])
        grades=sorted({r['grade'] for r in runs});changed+=len(grades)>1
        sensitivity.append({'id':row['id'],'grade_set':grades,'runs':runs})
    check('648_target_configurations_independent_grade',sense_ok,72*9)
    check('target_relaxation_cannot_raise_grade',ordering_ok,72*6)

    # Resource sets / same-scenario plans: preserve every old plan when extending.
    structural_ok=True;structural_count=0
    for c in dir_inputs:
        base=grade_directional(c)['grade']
        y=deepcopy(c);y['joint_profiles']=y['joint_profiles'][:1]
        structural_ok &= grade_directional(y)['grade']<=base;structural_count+=1
        y=deepcopy(c)
        for x in y['directions'].values():x['q']*=1.1
        structural_ok &= grade_directional(y)['grade']>=base;structural_count+=1
        y=deepcopy(c)
        for x in y['directions'].values():x['k']*=1.1;x['h']+=.25
        y['waiting_groups'][0]['k']*=1.1
        structural_ok &= grade_directional(y)['grade']<=base;structural_count+=1
    check('new_directional_demand_uncertainty_goals_orders',structural_ok,structural_count)
    exact_wait_ok=True
    for b,c,lag in product([100,1000],[500,1500],[0,.5,2]):
        r=evaluate([],[(lag,None,c)],b,lag+b/c)
        exact_wait_ok &= abs(r['max_wait_h']-(lag+b/c))<1e-8
    check('12_batch_FIFO_maximum_wait_closed_forms',exact_wait_ok,12)

    # Deliberately flawed rules must disagree on predeclared counterexamples.
    by_id={c['id']:c['input'] for c in cases()}
    front=evaluate(profile(2000,2,'front'),[(0,None,1000)],0,3)
    false_average_peak=max(0,2000-1000*2)
    idle=CumulativeQueue([(1,2,1000)],[(0,1,2000)]).result(3)
    n04=grade_directional(by_id['SC-N04'])
    false_per_profile_pass=all(any(p['runs'][i]['pass'] for p in n04['plans']) for i in range(2))
    n14=grade_directional(by_id['SC-N14'])['plans'][0]['runs'][0]
    n14_false_shared_peak=sum(x['peak_people'] for x in n14['directions'].values())
    defects=[
        {'id':'arrival_shape_removed','wrong_result':false_average_peak,'correct_result':front['peak_people'],'detected':false_average_peak<front['peak_people']},
        {'id':'directions_merged','wrong_result':'F0','correct_result':reference_directional_grade(by_id['SC-N01']),'detected':reference_directional_grade(by_id['SC-N01'])!='F0'},
        {'id':'shared_boarding_ignored','wrong_result':'F0','correct_result':reference_directional_grade(by_id['SC-N03']),'detected':reference_directional_grade(by_id['SC-N03'])!='F0'},
        {'id':'idle_capacity_stored','wrong_result':'completed_by_total_capacity','correct_result':None,'detected':idle['clear_h'] is None and idle['unserved_people']==1000},
        {'id':'quantifiers_reversed','wrong_result':false_per_profile_pass,'correct_result':n04['grade'],'detected':false_per_profile_pass and n04['grade']=='F3'},
        {'id':'non_simultaneous_peaks_added','wrong_result':n14_false_shared_peak,'correct_result':n14['waiting_groups'][0]['peak_people'],'detected':n14_false_shared_peak>500 and n14['waiting_groups'][0]['peak_people']<=500},
        {'id':'unknown_treated_as_zero_supply','wrong_result':'F3','correct_result':reference_single_grade({'q':1000,'d':2,'known':False}),'detected':reference_single_grade({'q':1000,'d':2,'known':False})=='X-DATA'},
    ]
    check('seven_documented_defects_detected',all(x['detected'] for x in defects),len(defects))

    record={'version':'METHOD-VALIDATION-COMPLETE-01','date':'2026-10-11','seed':SEED,
            'scope':'declared continuous queue, fixed plan sets and finite uncertainty set; method-level completion',
            'evidence_type':'THEORETICAL_AND_SYNTHETIC','independent_implementation':True,'independent_external_research_team':False,
            'checks':checks,'failures':failures,'defect_detection':defects,'maximum_metric_absolute_error':max_error,
            'original_library_grade_comparisons':hrows+nrows,'generated_directional_grade_counts':dict(dir_counts),
            'sensitivity_scenarios_with_grade_change':changed,'sensitivity_scenario_count':72,
            'boundary_runs':len(boundary_rows),'sensitivity_runs':648,
            'queue_inputs':queue_inputs,'directional_inputs':dir_inputs,'threshold_rows':boundary_rows,'sensitivity_rows':sensitivity}
    for key in ['queue_inputs','directional_inputs']:
        canonical=json.dumps(record[key],ensure_ascii=False,sort_keys=True,separators=(',',':'))
        record[key+'_sha256']=sha256(canonical.encode('utf-8')).hexdigest()
    (OUT/'方法完整验证结果.json').write_text(json.dumps(record,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:record[k] for k in ['checks','failures','maximum_metric_absolute_error','generated_directional_grade_counts','sensitivity_scenarios_with_grade_change','boundary_runs','sensitivity_runs']},ensure_ascii=False))
    if failures:raise AssertionError(failures)


if __name__=='__main__':main()
