"""Multi-commodity, time-expanded MILP. No event or transport-name branches."""
from pathlib import Path
import sys, math, json, time, hashlib
from collections import defaultdict
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
try:
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import coo_array
except ImportError:
    sys.path.insert(0,str(ROOT/'.qa/model_runtime'))
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import coo_array
from network_schema import validate,calendar,capacity,lags,totals,VERSION

class Matrix:
    def __init__(self):self.names=[];self.lb=[];self.ub=[];self.integer=[];self.rows=[];self.low=[];self.high=[]
    def var(self,name,upper=np.inf,integer=False):
        i=len(self.names);self.names.append(name);self.lb.append(0.);self.ub.append(upper);self.integer.append(int(integer));return i
    def add(self,terms,lower=-np.inf,upper=np.inf):
        row=defaultdict(float)
        for i,v in terms:
            if v:row[i]+=v
        self.rows.append(dict(row));self.low.append(lower);self.high.append(upper)
    def constraints(self):
        rr=[];cc=[];vv=[]
        for r,row in enumerate(self.rows):
            for c,v in row.items():rr.append(r);cc.append(c);vv.append(v)
        a=coo_array((np.asarray(vv,dtype=float),(np.asarray(rr,dtype=np.int32),np.asarray(cc,dtype=np.int32))),shape=(len(self.rows),len(self.names))).tocsc()
        return LinearConstraint(a,np.asarray(self.low),np.asarray(self.high))

def layout(card):
    rec=validate(card);p=card['parameters'];step=p['step_minutes'];T=int(p['deadline_minutes']/step)
    caps={(a['id'],t):capacity(card,a,t) for a in card['links'] for t in range(T)}
    return rec,step,T,caps

def build(card):
    rec,step,T,caps=layout(card);p=card['parameters'];m=Matrix();units={};cost={};flows={};hold={};stand={};outgoing=defaultdict(list);incoming=defaultdict(list)
    for a in card['links']:
        for t in range(T):
            *_,maximum=caps[a['id'],t]
            if maximum:
                i=m.var(('units',a['id'],t),upper=maximum,integer=True);units[a['id'],t]=i;cost[i]=a['unit_cost_yuan']
    for s in card['profiles']:
        sid=s['id']
        for g in card['groups']:
            gid=g['id']
            # Prune only links that cannot lie on a mode-compatible static path.
            allowed=[a for a in card['links'] if a['mode_id'] in g['allowed_modes'] and any(caps[a['id'],t][0]>0 or caps[a['id'],t][4]>0 for t in range(T))]
            forward={g['origin']};reverse={g['destination']}
            for _ in card['nodes']:
                forward|={a['to'] for a in allowed if a['from'] in forward};reverse|={a['from'] for a in allowed if a['to'] in reverse}
            relevant=(forward&reverse)|{g['origin'],g['destination']}
            for n in card['nodes']:
                for t in range(T+1):hold[sid,gid,n['id'],t]=m.var(('hold',sid,gid,n['id'],t),upper=0 if t==T or n['id']==g['destination'] or n['id'] not in relevant else np.inf)
            for a in allowed:
                if a['from'] not in forward or a['to'] not in reverse or a['from']==g['destination']:continue
                b,ride=lags(card,a)
                for t in range(T):
                    fixed,_,unit,_,maximum=caps[a['id'],t]
                    if t+b+ride>T or fixed+unit*maximum<=0:continue
                    if a['from']==g['origin'] and p.get('origin_departure_deadline_minutes') is not None and (t+b)*step>p['origin_departure_deadline_minutes']+1e-6:continue
                    i=m.var(('flow',sid,gid,a['id'],t));flows[sid,gid,a['id'],t]=i
                    outgoing[sid,gid,a['from'],t].append(i);incoming[sid,gid,a['to'],t+b+ride].append(i)
            for n in card['nodes']:
                nid=n['id']
                if nid==g['destination']:continue
                for t in range(T+1):
                    exo=(g['initial_people'] if t==0 else 0)+(s['arrivals'][gid][t] if nid==g['origin'] and t<p['entry_steps'] else 0)
                    if nid!=g['origin']:exo=0
                    terms=[(hold[sid,gid,nid,t],1)]
                    if t:terms.append((hold[sid,gid,nid,t-1],-1))
                    terms += [(i,1) for i in outgoing[sid,gid,nid,t]]+[(i,-1) for i in incoming[sid,gid,nid,t]]
                    m.add(terms,lower=exo,upper=exo)
            target=[(i,1) for t in range(T+1) for i in incoming[sid,gid,g['destination'],t]]
            total=g['initial_people']+sum(s['arrivals'][gid]);m.add(target,lower=total,upper=total)
    flow_at=defaultdict(list);boarding_at=defaultdict(list);flows_by_time=defaultdict(list)
    for (sid,gid,aid,t),i in flows.items():
        flow_at[sid,aid,t].append(i);flows_by_time[sid,t].append((gid,aid,i))
        a=rec['links'][aid];b,ride=lags(card,a)
        for k in range(t+1,min(T+1,t+b)):boarding_at[sid,gid,a['from'],k].append(i)
    for s in card['profiles']:
        sid=s['id']
        for a in card['links']:
            aid=a['id'];mode=rec['modes'][a['mode_id']];b,ride=lags(card,a)
            for t in range(T):
                ys=flow_at[sid,aid,t]
                if not ys:continue
                fixed,seats,unit,unit_seats,_=caps[aid,t];terms=[(i,1) for i in ys]
                if (aid,t) in units:terms.append((units[aid,t],-unit))
                m.add(terms,upper=fixed)
                if mode['comfort']=='seats':
                    u=m.var(('standing',sid,aid,t));stand[sid,aid,t]=u
                    terms=[(u,1)]+[(i,-1) for i in ys]
                    if (aid,t) in units:terms.append((units[aid,t],unit_seats))
                    m.add(terms,lower=-seats)
        for mid,mode in rec['modes'].items():
            limit=mode.get('standing_person_minutes_limit')
            if limit is not None:m.add([(i,lags(card,rec['links'][aid])[1]*step) for (ss,aid,t),i in stand.items() if ss==sid and rec['links'][aid]['mode_id']==mid],upper=limit)
        if p.get('standing_person_minutes_limit') is not None:m.add([(i,lags(card,rec['links'][aid])[1]*step) for (ss,aid,t),i in stand.items() if ss==sid],upper=p['standing_person_minutes_limit'])
        for t in range(T+1):
            all_queue=[];all_const=0
            for n in card['nodes']:
                nid=n['id'];queue=[];constant=0
                for g in card['groups']:
                    if nid==g['destination']:continue
                    gid=g['id'];local=[];value=0
                    if t:local.append((hold[sid,gid,nid,t-1],1))
                    if nid==g['origin']:value=(g['initial_people'] if t==0 else 0)+(s['arrivals'][gid][t] if t<p['entry_steps'] else 0)
                    local += [(i,1) for i in incoming[sid,gid,nid,t]]
                    local += [(i,1) for i in boarding_at[sid,gid,nid,t]]
                    if nid==g['origin'] and g.get('queue_limit_people') is not None:m.add(local,upper=g['queue_limit_people']-value)
                    queue+=local;constant+=value
                m.add(queue,upper=n['queue_limit_people']-constant)
                if n.get('waiting_density_limit') is not None:m.add(queue,upper=n['waiting_density_limit']*n['waiting_area_m2']-constant)
                all_queue+=queue;all_const+=constant
                if t<T:m.add([(i,1) for g in card['groups'] for i in outgoing[sid,g['id'],nid,t]],upper=calendar(n['boarding_capacity'],T)[t])
                if t:m.add([(i,1) for g in card['groups'] for i in incoming[sid,g['id'],nid,t]],upper=calendar(n['receiving_capacity'],T)[t-1])
            m.add(all_queue,upper=p['queue_limit_people']-all_const)
        for facility in card.get('facilities',[]):
            for t in range(T):m.add([(i,1) for aid in facility['links'] for i in flow_at[sid,aid,t]],upper=calendar(facility['capacity'],T)[t])
    for pool in card['pools']:
        selected=[(aid,t,i) for (aid,t),i in units.items() if rec['links'][aid].get('pool_id')==pool['id']]
        m.add([(i,1) for aid,t,i in selected],upper=pool['total_units_limit'])
        last=math.ceil(pool['close_minutes']/step)
        for k in range(max(T,last)):
            active=[]
            for aid,t,i in selected:
                a=rec['links'][aid];b,ride=lags(card,a)
                end=t+1 if pool['kind']=='quota' else math.ceil(((t+b+ride)*step+a['return_minutes']+pool['turnaround_minutes'])/step)
                if t<=k<end:active.append((i,1))
            if active:m.add(active,upper=pool['available_units'])
    for facility in card.get('occupancy_facilities',[]):
        for k in range(T):m.add([(i,1) for (aid,t),i in units.items() if aid in facility['links'] and t<=k<t+lags(card,rec['links'][aid])[0]],upper=facility['available_units'])
    m.add(list(cost.items()),upper=p['budget_yuan'])
    # A common reservation plan and causal flows, including uncertain total/OD.
    equalities=0
    for t in range(T):
        histories={}
        for s in card['profiles']:
            hist=tuple(round(v,8) for g in card['groups'] for v in s['arrivals'][g['id']][:min(t+1,p['entry_steps'])])
            ref=histories.setdefault(hist,s['id'])
            if ref!=s['id']:
                for gid,aid,i in flows_by_time[s['id'],t]:
                    m.add([(i,1),(flows[ref,gid,aid,t],-1)],lower=0,upper=0);equalities+=1
    return {'m':m,'units':units,'flows':flows,'hold':hold,'standing':stand,'cost':cost,'step':step,'T':T,'rec':rec,'causal_equalities':equalities}

def phase(m,objective,seconds,gap):
    started=time.perf_counter();r=milp(np.asarray(objective),integrality=np.asarray(m.integer,dtype=np.int32),bounds=Bounds(m.lb,m.ub),constraints=m.constraints(),options={'time_limit':seconds,'mip_rel_gap':gap,'presolve':True})
    def finite(value):return float(value) if value is not None and math.isfinite(value) else None
    return r,{'status':int(r.status),'message':r.message,'seconds':time.perf_counter()-started,'objective':finite(r.fun),'dual_bound':finite(getattr(r,'mip_dual_bound',None)),'relative_gap':finite(getattr(r,'mip_gap',None))}

def assign_units(card,reservations):
    rec=validate(card);step=card['parameters']['step_minutes'];out=[]
    for pool in card['pools']:
        rows=sorted([r for r in reservations if rec['links'][r['link_id']].get('pool_id')==pool['id']],key=lambda r:(r['start_step'],r['link_id']))
        ends=[0.]*int(pool['available_units'])
        for row in rows:
            a=rec['links'][row['link_id']];b,ride=lags(card,a);start=row['start_step']*step
            end=(row['start_step']+b+ride)*step+a['return_minutes']+pool['turnaround_minutes']
            ids=[]
            if pool['kind']=='vehicle':
                available=sorted([i for i,e in enumerate(ends) if e<=start+1e-6],key=lambda i:(ends[i],i))
                if len(available)<row['units']:raise AssertionError('汇总安排不能分配给实际周转单位')
                for i in available[:row['units']]:ends[i]=end;ids.append(pool['label']+str(i+1))
            out.append({**row,'pool_id':pool['id'],'unit_ids':ids,'start_minute':start,'departure_minute':(row['start_step']+b)*step,'arrival_minute':(row['start_step']+b+ride)*step,'return_minute':end if pool['kind']=='vehicle' else None})
    return {'reservations':out}

def solve(card,seconds=35,gap=.001,objective='journey_time'):
    if objective not in ('journey_time','wait','cost'):raise ValueError('未知目标')
    d=build(card);m=d['m'];rec=d['rec'];step=d['step'];z=m.var(('worst',))
    for s in card['profiles']:
        terms=[(z,1)]
        terms += [(i,-step) for (ss,g,n,t),i in d['hold'].items() if ss==s['id'] and t<d['T']]
        for (ss,g,aid,t),i in d['flows'].items():
            if ss==s['id']:
                b,ride=lags(card,rec['links'][aid]);terms.append((i,-step*(b+(ride if objective!='wait' else 0))))
        m.add(terms,lower=0)
    c=np.zeros(len(m.names))
    if objective=='cost':
        for i,v in d['cost'].items():c[i]=v
    else:c[z]=1
    r,p1=phase(m,c,seconds,gap)
    result={'model_version':VERSION,'objective_kind':objective,'phase_primary':p1,'has_solution':r.x is not None,
      'variables':len(m.names),'integer_variables':sum(m.integer),'constraints':len(m.rows),'nonanticipativity_constraints':d['causal_equalities'],
      'input_sha256':hashlib.sha256(json.dumps(card,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    if r.x is None:return result
    x=r.x
    if objective!='cost':
        m.add([(z,1)],upper=float(x[z])+1e-5);c2=np.zeros(len(m.names))
        for i,v in d['cost'].items():c2[i]=v
        r2,p2=phase(m,c2,seconds,gap);result['phase_cost_tiebreak']=p2
        if r2.x is not None:x=r2.x
    for i,k in enumerate(m.integer):
        if k:m.add([(i,1)],lower=round(x[i]),upper=round(x[i]))
    # Remove arbitrary cycles/holding on fixed reservations, without scenario probabilities.
    c3=np.zeros(len(m.names))
    for (s,g,n,t),i in d['hold'].items():c3[i]=step
    for (s,g,aid,t),i in d['flows'].items():c3[i]=sum(lags(card,rec['links'][aid]))*step
    r3,p3=phase(m,c3,seconds,gap);result['phase_flow_refinement']=p3
    if r3.x is not None:
        x=r3.x;m.add([(i,v) for i,v in enumerate(c3) if v],upper=float(c3@x)+1e-5)
        c4=np.zeros(len(m.names))
        for (s,aid,t),i in d['standing'].items():c4[i]=lags(card,rec['links'][aid])[1]*step
        r4,p4=phase(m,c4,seconds,gap);result['phase_comfort_refinement']=p4
        if r4.x is not None:x=r4.x
    con=m.constraints();values=con.A@x
    violation=max(float(np.max(np.maximum(con.lb-values,0))),float(np.max(np.maximum(values-con.ub,0))),float(np.max(np.maximum(np.asarray(m.lb)-x,0))),float(np.max(np.maximum(x-np.asarray(m.ub),0))))
    if violation>1e-4:raise AssertionError('网络解违反模型约束：'+str(violation))
    reservations=[{'link_id':aid,'start_step':t,'units':int(round(x[i]))} for (aid,t),i in d['units'].items() if x[i]>.5]
    policies=[{'profile_id':s['id'],'flows':[{'group_id':g,'link_id':aid,'start_step':t,'people':max(0,float(x[i]))} for (ss,g,aid,t),i in d['flows'].items() if ss==s['id'] and x[i]>1e-8]} for s in card['profiles']]
    result.update(common_plan=assign_units(card,reservations),scenario_policy=policies,cost_yuan=sum(v*x[i] for i,v in d['cost'].items()),worst_objective_value=float(x[z]),max_constraint_violation=violation)
    return result
