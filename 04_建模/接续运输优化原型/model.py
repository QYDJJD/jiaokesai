"""Time-indexed MILP: common vehicle/taxi reservations, causal scenario flows.

All queue and waiting statements refer to the declared boundary-batch model.
Physical parameters of the Hongqiao example are synthetic, not calibrated.
"""
from pathlib import Path
import sys
import math
import time
import json
import hashlib
from collections import defaultdict
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
try:
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import coo_array
except ImportError:
    # Optional isolated runtime used in this workspace; no global installation.
    sys.path.insert(0, str(ROOT / '.qa/model_runtime'))
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import coo_array

MODES = ('base', 'taxi', 'bus')
TOL = 1e-6


def validate(card):
    if card.get('schema_version') != 'OPT-CARD-01':
        raise ValueError('需要OPT-CARD-01完整参数卡；五维标签不能代替必填参数')
    p, directions, profiles = card['parameters'], card['directions'], card['arrival_profiles']
    required = ('step_minutes','entry_minutes','deadline_minutes','budget_yuan',
                'queue_limit_people','standing_person_minutes_limit','bus_fleet_size',
                'bus_trip_limit','bus_seats','bus_legal_capacity','bus_standing_area_m2',
                'standing_density_limit_people_m2','shared_service_people_per_hour',
                'bus_bays','bus_boarding_minutes','bus_turnaround_minutes',
                'bus_prepare_minutes','taxi_prepare_minutes','bus_service_end_minutes',
                'taxi_service_end_minutes','vehicle_shift_end_minutes','taxi_block_people',
                'taxi_block_cost_yuan','taxi_max_blocks_per_step','taxi_total_blocks',
                'receiver_open_minutes','receiver_close_minutes')
    for key in required:
        if p.get(key) is None or not isinstance(p[key], (int,float)) or not math.isfinite(p[key]):
            raise ValueError('缺少有效数值参数：'+key)
        if p[key] < 0:
            raise ValueError('参数不能为负：'+key)
    step = p['step_minutes']
    if step <= 0 or 60 % step or p['deadline_minutes'] % step or p['entry_minutes'] % 60:
        raise ValueError('时间步须整除60，进入期按整小时，截止须在时间边界')
    if p['deadline_minutes'] < p['entry_minutes']:
        raise ValueError('截止不能早于新增进入结束')
    for key in ('bus_fleet_size','bus_trip_limit','bus_bays','bus_seats','bus_legal_capacity',
                'taxi_block_people','taxi_max_blocks_per_step','taxi_total_blocks'):
        if int(p[key])!=p[key]:raise ValueError('资源计数须为整数：'+key)
    if p['taxi_block_people']<=0:raise ValueError('预约包服务名额须为正')
    if p.get('waiting_comfort_density_people_m2') is not None and p['waiting_comfort_density_people_m2']<0:
        raise ValueError('候客舒适密度不得为负')
    if p['bus_standing_area_m2'] <= 0 or p['bus_legal_capacity'] < p['bus_seats']:
        raise ValueError('车辆站立面积或容量口径错误')
    if not directions or len({d['id'] for d in directions}) != len(directions):
        raise ValueError('方向编号必须唯一且非空')
    if abs(sum(d['share'] for d in directions)-1) > TOL:
        raise ValueError('方向份额加总须为1')
    for d in directions:
        for key in ('share','initial_queue','waiting_area_m2','queue_limit_people',
                    'base_people_per_hour','bus_ride_minutes','taxi_ride_minutes',
                    'base_ride_minutes','bus_trip_cost_yuan','receiver_people_per_hour'):
            if d.get(key) is None or not math.isfinite(d[key]) or d[key] < 0:
                raise ValueError('方向参数缺失或为负：'+d['id']+'/'+key)
        if d['waiting_area_m2'] <= 0:
            raise ValueError('候客有效面积须为正')
    if not profiles or len({s['id'] for s in profiles}) != len(profiles):
        raise ValueError('进入过程编号必须唯一')
    q = card['five_dimensions']['new_onward_passengers']
    if p['entry_minutes'] != card['five_dimensions']['entry_duration_minutes']:
        raise ValueError('五维持续时间与模型进入期不一致')
    for s in profiles:
        if len(s['hourly_people']) != p['entry_minutes']//60:
            raise ValueError('每个过程须覆盖完整进入期')
        if any(not math.isfinite(v) or v < 0 for v in s['hourly_people']):
            raise ValueError('进入量须为非负有效人数')
        if abs(sum(s['hourly_people'])-q) > TOL:
            raise ValueError('进入量与新增待接续人数不一致')
    lead = card['five_dimensions'].get('information_lead_minutes')
    if lead is None or not math.isfinite(lead):
        raise ValueError('信息提前量缺失')


def arrivals(card):
    p = card['parameters']; step=p['step_minutes']; periods=round(p['deadline_minutes']/step)
    n=len(card['directions']); values=[]
    for s in card['arrival_profiles']:
        a=np.zeros((n,periods))
        for t in range(round(p['entry_minutes']/step)):
            total=s['hourly_people'][int(t*step//60)]*step/60
            for d, direction in enumerate(card['directions']):a[d,t]=total*direction['share']
        values.append(a)
    return np.asarray(values)


def tasks(card):
    p=card['parameters']; step=p['step_minutes']; out=[]
    ready=max(0,p['bus_prepare_minutes']-card['five_dimensions']['information_lead_minutes'])
    boarding=math.ceil(p['bus_boarding_minutes']/step)
    for d, direction in enumerate(card['directions']):
        for start in range(round(p['deadline_minutes']/step)):
            depart=(start+boarding)*step
            cycle=boarding*step+2*direction['bus_ride_minutes']+p['bus_turnaround_minutes']
            returned=start*step+cycle
            destination=depart+direction['bus_ride_minutes']
            if start*step+TOL < ready or depart > p['bus_service_end_minutes']+TOL:continue
            if returned > p['vehicle_shift_end_minutes']+TOL:continue
            if not p['receiver_open_minutes'] <= destination <= p['receiver_close_minutes']:continue
            out.append({'direction':d,'start_slot':start,'departure_slot':start+boarding-1,
                        'departure_minute':depart,'return_minute':returned,
                        'destination_minute':destination,'bay_slots':list(range(start,start+boarding)),
                        'fleet_slots':list(range(start,math.ceil(returned/step)))})
    return out


class Matrix:
    def __init__(self):
        self.names=[];self.lb=[];self.ub=[];self.integer=[];self.rows=[];self.lower=[];self.upper=[]

    def var(self,name,upper=np.inf,integer=False):
        idx=len(self.names);self.names.append(name);self.lb.append(0.0);self.ub.append(upper)
        self.integer.append(1 if integer else 0);return idx

    def add(self,terms,lower=-np.inf,upper=np.inf):
        row=defaultdict(float)
        for i,value in terms:
            if value:row[i]+=value
        self.rows.append(dict(row));self.lower.append(lower);self.upper.append(upper)

    def constraint(self):
        rr=[];cc=[];vv=[]
        for r,row in enumerate(self.rows):
            for c,v in row.items():rr.append(r);cc.append(c);vv.append(v)
        a=coo_array((np.asarray(vv,dtype=float),(np.asarray(rr,dtype=np.int32),
                     np.asarray(cc,dtype=np.int32))),shape=(len(self.rows),len(self.names))).tocsc()
        return LinearConstraint(a,np.asarray(self.lower),np.asarray(self.upper))


def build(card, fixed_plan=None):
    validate(card)
    p=card['parameters']; ds=card['directions']; aa=arrivals(card)
    ns,nd,nt=aa.shape; step=p['step_minutes']; m=Matrix(); tt=tasks(card)
    bus=[m.var('bus_'+str(j),1,True) for j in range(len(tt))]
    taxi={}; cost={i:ds[t['direction']]['bus_trip_cost_yuan'] for i,t in zip(bus,tt)}
    ready=max(0,p['taxi_prepare_minutes']-card['five_dimensions']['information_lead_minutes'])
    for d in range(nd):
        for t in range(nt):
            arrival=(t+1)*step+ds[d]['taxi_ride_minutes']
            valid=t*step+TOL>=ready and (t+1)*step<=p['taxi_service_end_minutes'] and p['receiver_open_minutes']<=arrival<=p['receiver_close_minutes']
            i=m.var(f'taxi_{d}_{t}',p['taxi_max_blocks_per_step'] if valid else 0,True)
            taxi[d,t]=i;cost[i]=p['taxi_block_cost_yuan']
    for t in range(nt):m.add([(taxi[d,t],1) for d in range(nd)],upper=p['taxi_max_blocks_per_step'])
    m.add([(i,1) for i in taxi.values()],upper=p['taxi_total_blocks'])
    m.add([(i,1) for i in bus],upper=p['bus_trip_limit'])
    for k in range(math.ceil(p['vehicle_shift_end_minutes']/step)):
        m.add([(i,1) for i,t in zip(bus,tt) if k in t['fleet_slots']],upper=p['bus_fleet_size'])
        m.add([(i,1) for i,t in zip(bus,tt) if k in t['bay_slots']],upper=p['bus_bays'])
    m.add(list(cost.items()),upper=p['budget_yuan'])
    by_depart=defaultdict(list)
    for i,t in zip(bus,tt):by_depart[t['direction'],t['departure_slot']].append(i)
    if fixed_plan is not None:
        selected={(t['direction'],t['start_slot']) for t in fixed_plan['bus_tasks']}
        for i,t in zip(bus,tt):m.add([(i,1)],lower=int((t['direction'],t['start_slot']) in selected),upper=int((t['direction'],t['start_slot']) in selected))
        known={(t['direction'],t['start_slot']) for t in tt}
        if not selected<=known:raise ValueError('固定排班含当前窗口不可用的公交任务')
        for (d,t),i in taxi.items():
            v=fixed_plan['taxi_blocks'][d][t]
            m.add([(i,1)],lower=v,upper=v)
    q={};flow={};standing={};z=m.var('worst_wait')
    total=card['five_dimensions']['new_onward_passengers']+sum(d['initial_queue'] for d in ds)
    comfort_cap=min(p['bus_legal_capacity'],p['bus_seats']+p['standing_density_limit_people_m2']*p['bus_standing_area_m2'])
    for s in range(ns):
        for d in range(nd):
            for t in range(nt):
                q[s,d,t]=m.var(f'q_{s}_{d}_{t}',total)
                for mode in MODES:
                    cap=ds[d]['base_people_per_hour']*step/60 if mode=='base' else total
                    at=(t+1)*step+ds[d][mode+'_ride_minutes']
                    if not p['receiver_open_minutes']<=at<=p['receiver_close_minutes']:cap=0
                    flow[s,d,t,mode]=m.var(f'serve_{s}_{d}_{t}_{mode}',cap)
                sb=flow[s,d,t,'bus'];st=flow[s,d,t,'taxi'];xs=by_depart[d,t]
                m.add([(sb,1)]+[(i,-comfort_cap) for i in xs],upper=0)
                m.add([(st,1),(taxi[d,t],-p['taxi_block_people'])],upper=0)
                u=m.var(f'standing_{s}_{d}_{t}',total);standing[s,d,t]=u
                m.add([(u,1),(sb,-1)]+[(i,p['bus_seats']) for i in xs],lower=0)
                terms=[(q[s,d,t],1)]+[(flow[s,d,t,mode],1) for mode in MODES]
                rhs=aa[s,d,t]+(ds[d]['initial_queue'] if t==0 else 0)
                if t:terms.append((q[s,d,t-1],-1))
                m.add(terms,lower=rhs,upper=rhs)
                limit=ds[d]['queue_limit_people']
                if p.get('waiting_comfort_density_people_m2') is not None:
                    limit=min(limit,p['waiting_comfort_density_people_m2']*ds[d]['waiting_area_m2'])
                pre=ds[d]['initial_queue'] if t==0 else 0
                m.add([(q[s,d,t-1],1)] if t else [],upper=limit-aa[s,d,t]-pre)
            m.add([(q[s,d,nt-1],1)],lower=0,upper=0)
        for t in range(nt):
            pre=sum(d['initial_queue'] for d in ds) if t==0 else 0
            m.add([(q[s,d,t-1],1) for d in range(nd)] if t else [],upper=p['queue_limit_people']-float(aa[s,:,t].sum())-pre)
            m.add([(flow[s,d,t,mode],1) for d in range(nd) for mode in MODES],upper=p['shared_service_people_per_hour']*step/60)
        m.add([(standing[s,d,t],ds[d]['bus_ride_minutes']) for d in range(nd) for t in range(nt)],upper=p['standing_person_minutes_limit'])
        m.add([(z,1)]+[(q[s,d,t],-step) for d in range(nd) for t in range(nt)],lower=total*step)
        for d in range(nd):
            receiving=defaultdict(list)
            for t in range(nt):
                for mode in MODES:
                    at=(t+1)*step+ds[d][mode+'_ride_minutes']
                    receiving[math.ceil(at/step)-1].append((flow[s,d,t,mode],1))
            for terms in receiving.values():m.add(terms,upper=ds[d]['receiver_people_per_hour']*step/60)
    # Allocation decisions may differ only after their observed arrival histories differ.
    for t in range(nt):
        groups={}
        for s in range(ns):
            key=tuple(np.round(aa[s,:,:t+1].ravel(),9));ref=groups.setdefault(key,s)
            if ref!=s:
                for d in range(nd):
                    for mode in MODES:m.add([(flow[s,d,t,mode],1),(flow[ref,d,t,mode],-1)],lower=0,upper=0)
    return {'matrix':m,'arrivals':aa,'tasks':tt,'bus':bus,'taxi':taxi,'queue':q,
            'flow':flow,'standing':standing,'worst':z,'cost':cost}


def _phase(m, objective, seconds, gap):
    started=time.perf_counter()
    result=milp(np.asarray(objective),integrality=np.asarray(m.integer,dtype=np.int32),
                bounds=Bounds(m.lb,m.ub),constraints=m.constraint(),
                options={'time_limit':seconds,'mip_rel_gap':gap,'presolve':True})
    report={'status':int(result.status),'message':result.message,'seconds':time.perf_counter()-started,
            'objective':float(result.fun) if result.fun is not None else None,
            'dual_bound':float(result.mip_dual_bound) if getattr(result,'mip_dual_bound',None) is not None else None,
            'relative_gap':float(result.mip_gap) if getattr(result,'mip_gap',None) is not None else None,
            'node_count':int(result.mip_node_count) if getattr(result,'mip_node_count',None) is not None else None}
    return result,report


def assign_vehicles(selected, fleet):
    ends=[0.0]*fleet;out=[]
    for task in sorted(selected,key=lambda x:(x['start_minute'],x['direction'])):
        available=[i for i,e in enumerate(ends) if e<=task['start_minute']+TOL]
        if not available:raise AssertionError('无法把汇总任务分配至实际车辆')
        vehicle=min(available,key=lambda i:(ends[i],i));ends[vehicle]=task['return_minute']
        out.append({**task,'vehicle_id':'备用公交'+str(vehicle+1)})
    return out


def solve(card, seconds=45, gap=0.001, objective='wait', fixed_plan=None):
    data=build(card,fixed_plan);m=data['matrix'];c=np.zeros(len(m.names))
    if objective=='cost':
        for i,v in data['cost'].items():c[i]=v
    else:c[data['worst']]=1
    r,p1=_phase(m,c,seconds,gap)
    out={'model_version':'OPT-MILP-01','input_sha256':hashlib.sha256(json.dumps(card,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
         'objective_kind':objective,'phase_primary':p1,'variables':len(m.names),
         'integer_variables':sum(m.integer),'constraints':len(m.rows),'has_solution':r.x is not None}
    if r.x is None:return out
    x=r.x;primary=float(c@x)
    if objective=='wait':
        m.add([(data['worst'],1)],upper=primary+1e-5)
        c2=np.zeros(len(m.names))
        for i,v in data['cost'].items():c2[i]=v
        r2,p2=_phase(m,c2,seconds,gap);out['phase_cost_tiebreak']=p2
        if r2.x is not None:x=r2.x
    # Fix the common reservations and remove arbitrary delay / crowding in
    # non-worst scenarios. These are tie-breaking LPs, not probability weights.
    for i,kind in enumerate(m.integer):
        if kind:m.add([(i,1)],lower=round(x[i]),upper=round(x[i]))
    c3=np.zeros(len(m.names))
    for i in data['queue'].values():c3[i]=1
    r3,p3=_phase(m,c3,seconds,gap);out['phase_fixed_plan_wait_refinement']=p3
    if r3.x is not None:
        x=r3.x;m.add([(i,1) for i in data['queue'].values()],upper=float(c3@x)+1e-6)
        c4=np.zeros(len(m.names))
        for (s,d,t),i in data['standing'].items():c4[i]=card['directions'][d]['bus_ride_minutes']
        r4,p4=_phase(m,c4,seconds,gap);out['phase_fixed_plan_comfort_refinement']=p4
        if r4.x is not None:x=r4.x
    con=m.constraint();values=con.A@x
    violation=max(float(np.max(np.maximum(con.lb-values,0))),float(np.max(np.maximum(values-con.ub,0))))
    bound_violation=max(float(np.max(np.maximum(np.asarray(m.lb)-x,0))),float(np.max(np.maximum(x-np.asarray(m.ub),0))))
    int_error=max((abs(x[i]-round(x[i])) for i,kind in enumerate(m.integer) if kind),default=0)
    if max(violation,bound_violation,int_error)>1e-4:raise AssertionError(('求解结果违反约束',violation,bound_violation,int_error))
    p=card['parameters'];step=p['step_minutes'];nd=len(card['directions']);nt=data['arrivals'].shape[2]
    selected=[]
    for i,t in zip(data['bus'],data['tasks']):
        if x[i]>.5:selected.append({k:v for k,v in t.items() if k not in ('bay_slots','fleet_slots')}|{'start_minute':t['start_slot']*step})
    plan={'bus_tasks':assign_vehicles(selected,int(p['bus_fleet_size'])),
          'taxi_blocks':[[int(round(x[data['taxi'][d,t]])) for t in range(nt)] for d in range(nd)]}
    policy=[]
    for s,profile in enumerate(card['arrival_profiles']):
        policy.append({'profile_id':profile['id'], 'flows':{
            mode:[[max(0,float(x[data['flow'][s,d,t,mode]])) for t in range(nt)] for d in range(nd)] for mode in MODES}})
    out.update({'common_plan':plan,'scenario_policy':policy,
                'cost_yuan':sum(v*x[i] for i,v in data['cost'].items()),
                'worst_wait_person_minutes':float(x[data['worst']]),
                'max_matrix_violation':violation,'max_integrality_error':int_error,
                'primary_proved_to_requested_gap':p1['status']==0,
                'cost_tiebreak_proved_to_requested_gap':out.get('phase_cost_tiebreak',p1)['status']==0})
    return out


if __name__ == '__main__':
    card=json.loads((ROOT/'03_情景库/模型输入卡-虹桥降雪背景.json').read_text(encoding='utf-8'))
    result=solve(card)
    print(json.dumps({k:v for k,v in result.items() if k not in ('common_plan','scenario_policy')},ensure_ascii=False,indent=2))
