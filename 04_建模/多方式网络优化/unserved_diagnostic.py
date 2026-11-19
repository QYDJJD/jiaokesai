"""在安全及资源硬约束下求截止未到达目的节点的最坏人数。"""
import hashlib
import json
import numpy as np
from network_model import build, phase, assign_units, VERSION
from network_audit import check_plan, replay, verify_causality

def diagnose(card, seconds=15, gap=0.0):
    data=build(card,allow_unserved=True); matrix=data['m']; terminal=data['T']
    worst=matrix.var(('worst_unserved',))
    for profile in card['profiles']:
        terms=[(worst,1)]
        terms += [(i,-1) for (sid,gid,nid,t),i in data['hold'].items() if sid==profile['id'] and t==terminal]
        matrix.add(terms,lower=0)
    objective=np.zeros(len(matrix.names));objective[worst]=1
    result,info=phase(matrix,objective,seconds,gap)
    output={'model_version':VERSION,'diagnostic_version':'UNSERVED-01','phase':info,
            'has_solution':result.x is not None,'minimum_certified':info['status']==0 and info['relative_gap'] is not None and info['relative_gap']<=1e-8,
            'scope':'已给定需求过程、网络与安全资源约束下的截止未到达目的节点人数；非车辆缺口和现实预测',
            'input_sha256':hashlib.sha256(json.dumps(card,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    if result.x is None:return output
    x=result.x
    reserves=[{'link_id':aid,'start_step':t,'units':int(round(x[i]))} for (aid,t),i in data['units'].items() if x[i]>.5]
    policies=[{'profile_id':s['id'],'flows':[{'group_id':g,'link_id':a,'start_step':t,'people':max(0,float(x[i]))}
              for (sid,g,a,t),i in data['flows'].items() if sid==s['id'] and x[i]>1e-8]} for s in card['profiles']]
    solution={'common_plan':assign_units(card,reserves),'scenario_policy':policies}
    plan_check=check_plan(card,solution['common_plan'])
    policy_map={p['profile_id']:p for p in policies}
    replayed=[replay(card,solution['common_plan'],policy_map[s['id']],s) for s in card['profiles']]
    rows=[{k:r[k] for k in ('profile_id','task_people','delivered_people','remaining_people','peak_queue_people','safe_queue','complete_by_deadline')} for r in replayed]
    maximum=max(r['remaining_people'] for r in rows)
    if not all(r['safe_queue'] for r in rows):raise AssertionError('独立核算发现候客安全约束被违反')
    if maximum-float(x[worst])>1e-4 or (output['minimum_certified'] and abs(maximum-float(x[worst]))>1e-4):
        raise AssertionError('目标与独立核算未完成量不一致')
    output.update(worst_unserved=maximum,profiles=rows,plan=plan_check,independent_audit='通过：资源时序、人数守恒及候客安全',
                  nonanticipativity_checks=verify_causality(card,policies))
    return output
