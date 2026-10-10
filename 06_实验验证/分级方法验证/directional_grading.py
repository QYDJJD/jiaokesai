"""Finite, predeclared service-plan validation for directional grading.

This is not a network optimizer. Each plan fixes resource allocations for
ALL allowed joint arrival profiles. Listed flow constraints are checked;
route travel, vehicle cycles and discrete boarding must be represented in
the supplied effective curves or remain an explicit unsupported boundary.
"""
from grading_engine import evaluate, profile, nonnegative, validate_segments, EPS


def rate_at(segments, t):
    return sum(r for a,b,r in segments if a <= t and (b is None or t < b))


def _points(*segment_lists):
    points={0.0}
    for segments in segment_lists:
        points.update(t for a,b,r in segments for t in (a,b) if t is not None)
    points=sorted(points)
    return [(a+b)/2 for a,b in zip(points,points[1:])] + [points[-1]+1]


def backlog_at(trace,t):
    for (a,x),(b,y) in zip(trace,trace[1:]):
        if a <= t <= b:
            return x+(y-x)*(t-a)/(b-a)
    return trace[-1][1]


def validate_plan(resources, groups, directions, plan, max_layer):
    """Validate per-resource and per-facility simultaneous reservations.

    A rejected candidate is NOT a usable reference plan. Reject the whole
    configuration rather than silently delete it and claim a higher grade.
    """
    by_id={}
    pools=set()
    for res in resources:
        rid=res['id'];pid=res['pool_id']
        if rid in by_id or pid in pools:
            raise ValueError('duplicate resource or physical pool')
        if res['layer'] not in (0,1,2) or not res['directions'] or any(d not in directions for d in res['directions']):
            raise ValueError('invalid resource layer/direction')
        validate_segments(res['capacity'],supply=True)
        by_id[rid]=res;pools.add(pid)
    group_ids=set()
    for g in groups:
        if g['id'] in group_ids or len(set(g['resource_ids'])) != len(g['resource_ids']) or any(r not in by_id for r in g['resource_ids']):
            raise ValueError('invalid shared group')
        group_ids.add(g['id'])
        validate_segments(g['capacity'],supply=True)
    allocations=plan['allocations']
    per_resource={r:[] for r in by_id}
    per_direction={d:[] for d in directions}
    for alloc in allocations:
        rid,d=alloc['resource_id'],alloc['direction']
        if rid not in by_id or d not in directions or d not in by_id[rid]['directions']:
            raise ValueError('resource cannot serve assigned direction')
        if by_id[rid]['layer'] > max_layer:
            raise ValueError('resource assigned before eligible layer')
        validate_segments(alloc['segments'],supply=True)
        per_resource[rid].extend(alloc['segments'])
        per_direction[d].extend(alloc['segments'])
    mids=_points(*per_resource.values(),*[r['capacity'] for r in resources],*[g['capacity'] for g in groups])
    for t in mids:
        for rid,res in by_id.items():
            if rate_at(per_resource[rid],t) > rate_at(res['capacity'],t)+EPS:
                raise ValueError('resource capacity exceeded: '+rid)
        for group in groups:
            used=sum(rate_at(per_resource[rid],t) for rid in group['resource_ids'])
            if used > rate_at(group['capacity'],t)+EPS:
                raise ValueError('shared capacity exceeded: '+group['id'])
    return per_direction


def grade_directional(case):
    blockers=[]
    if case.get('safe') is False:
        blockers.append('X-SAFE')
    if case.get('known',True) is False or case.get('safe',True) is None:
        blockers.append('X-DATA')
    if case.get('supported',True) is False:
        blockers.append('X-STRUCTURE')
    if blockers:
        return {'grade':blockers[0],'blockers':blockers,'tiers':[]}
    try:
        demands=case['directions']
        if not demands:
            raise ValueError('no demand directions')
        for d,x in demands.items():
            if not nonnegative(x['b0']) or not nonnegative(x['k']) or x['k']==0 or not nonnegative(x['h']):
                raise ValueError('invalid direction goal/backlog')
            profile(x['q'],x['d'],'uniform')
        waiting_groups=case.get('waiting_groups',[])
        wait_ids=set()
        for group in waiting_groups:
            if group['id'] in wait_ids or not group['directions'] or len(set(group['directions'])) != len(group['directions']) or any(d not in demands for d in group['directions']) or not nonnegative(group['k']) or group['k']==0:
                raise ValueError('invalid shared waiting-space goal')
            wait_ids.add(group['id'])
        members=case['joint_profiles']
        if not members or len({m['id'] for m in members}) != len(members):
            raise ValueError('empty/duplicate joint profiles')
        for member in members:
            if set(member['shapes']) != set(demands):
                raise ValueError('joint profile directions missing')
            for d,shape in member['shapes'].items():
                profile(demands[d]['q'],demands[d]['d'],shape)
        plans=case['plans']
        if not plans or len({p['id'] for p in plans}) != len(plans):
            raise ValueError('empty/duplicate plans')
        if not any(p['introduced_layer']==0 for p in plans):
            raise ValueError('baseline plan missing; cannot infer V0 failure')
        resources,groups=case['resources'],case.get('groups',[])
        curves={}
        for plan in plans:
            if plan['introduced_layer'] not in (0,1,2):
                raise ValueError('invalid plan layer')
            curves[plan['id']]=validate_plan(resources,groups,demands,plan,plan['introduced_layer'])
        plan_results=[]
        for plan in plans:
            runs=[]
            for member in members:
                results={}
                traces={}
                for d,x in demands.items():
                    row=evaluate(profile(x['q'],x['d'],member['shapes'][d]),curves[plan['id']][d],x['b0'],x['d']+x['h'],include_trace=True)
                    traces[d]=row.pop('queue_trace')
                    failures=[]
                    if row['peak_people'] > x['k']+EPS:
                        failures.append('peak_over_K')
                    if row['clear_h'] is None:
                        failures.append('unfinished')
                    elif row['clear_h'] > x['d']+x['h']+EPS:
                        failures.append('clear_after_D_plus_H')
                    results[d]={**row,'pass':not failures,'failures':failures}
                group_results=[]
                for group in waiting_groups:
                    times=sorted({t for d in group['directions'] for t,b in traces[d]})
                    peak=max(sum(backlog_at(traces[d],t) for d in group['directions']) for t in times)
                    group_results.append({'id':group['id'],'K_people':group['k'],'peak_people':peak,'pass':peak <= group['k']+EPS})
                runs.append({'joint_profile':member['id'],'directions':results,'waiting_groups':group_results,
                             'pass':all(r['pass'] for r in results.values()) and all(g['pass'] for g in group_results)})
            plan_results.append({'id':plan['id'],'introduced_layer':plan['introduced_layer'],
                                 'pass':all(r['pass'] for r in runs),'runs':runs})
        tiers=[]
        for j in range(3):
            # Higher layers retain ALL previously available plans. This
            # checks nested plan sets without forcing worse reassignment.
            allowed=[p for p in plan_results if p['introduced_layer'] <= j]
            passed=[p['id'] for p in allowed if p['pass']]
            tiers.append({'tier':'V'+str(j),'candidate_plan_ids':[p['id'] for p in allowed],
                          'pass':bool(passed),'passing_plan_ids':passed})
        grade=next((j for j,t in enumerate(tiers) if t['pass']),3)
        return {'grade':'F'+str(grade),'blockers':[],
                'interpretation':'minimum layer among listed fixed plans; not all physically feasible policies',
                'quantifier':'exists one listed plan, for all joint profiles and directions',
                'tiers':tiers,'plans':plan_results}
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        return {'grade':'X-CONFIG','blockers':['X-CONFIG'],'reason':str(exc),'tiers':[]}
