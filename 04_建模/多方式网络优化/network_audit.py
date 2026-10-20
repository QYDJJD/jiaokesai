"""Independent resource calendar and cohort replay, without solver matrices."""
from collections import defaultdict,deque
import math
from network_schema import validate, calendar

EPS=5e-5

def time_parts(card,a):
    step=card['parameters']['step_minutes']
    return math.ceil(a['boarding_minutes']/step),math.ceil(a['travel_minutes']/step)

def service_tables(card,plan):
    rec=validate(card);p=card['parameters'];step=p['step_minutes'];T=int(p['deadline_minutes']/step)
    reserved=defaultdict(int)
    for row in plan['reservations']:reserved[row['link_id'],row['start_step']]+=row['units']
    result={}
    for a in card['links']:
        mid=a['mode_id'];mode=rec['modes'][mid];b,travel=time_parts(card,a);pool=rec['pools'].get(a.get('pool_id'))
        for t in range(T):
            active=mode.get('enabled',True) and a['service_start_minutes']-EPS<=(t+b)*step<=a['service_end_minutes']+EPS and t+b+travel<=T
            fixed=calendar(a['fixed_capacity'],T)[t] if active else 0
            seats=min(fixed,calendar(a['fixed_seats'],T)[t]);area=calendar(a['fixed_standing_area_m2'],T)[t] if active else 0
            units=reserved[a['id'],t];additional=pool['legal_capacity'] if pool else 0
            if mode['comfort']=='seats':
                fixed=min(fixed,seats+area*mode['standing_density_limit'])
                if pool:additional=min(additional,pool['seats']+pool['standing_area_m2']*mode['standing_density_limit'])
            result[a['id'],t]={'capacity':fixed+units*additional,'seats':seats+units*(pool['seats'] if pool else 0),
                'standing_area':area+units*(pool['standing_area_m2'] if pool else 0),'board':b,'travel':travel}
    return rec,T,step,result

def check_plan(card,plan):
    rec=validate(card);p=card['parameters'];step=p['step_minutes'];T=int(p['deadline_minutes']/step)
    assert isinstance(plan,dict) and isinstance(plan.get('reservations'),list),'资源计划须包含预约条目'
    aggregate=defaultdict(int);fleet=defaultdict(int);total=defaultdict(int);ids=defaultdict(list);bays=defaultdict(int);cost=0.;mode_units=defaultdict(int)
    for row in plan['reservations']:
        aid=row.get('link_id');t=row.get('start_step');units=row.get('units')
        assert aid in rec['links'] and type(t) is int and 0<=t<T and type(units) is int and units>0,'预约线路、时段或单位数无效'
        a=rec['links'][aid];pool=rec['pools'].get(a.get('pool_id'));mode=rec['modes'][a['mode_id']]
        assert pool and mode.get('enabled',True) and mode['control']=='adjustable','既定或停用方式不允许新增预约'
        b,ride=time_parts(card,a);depart=(t+b)*step;arrive=(t+b+ride)*step
        assert a['service_start_minutes']-EPS<=depart<=a['service_end_minutes']+EPS and arrive<=p['deadline_minutes']+EPS,'预约不符合线路时段或到达截止'
        assert t*step+EPS>=max(0,pool['prepare_minutes']-card['five_dimensions']['information_lead_minutes']),'预约早于资源准备完成'
        end=depart if pool['kind']=='quota' else arrive+a['return_minutes']+pool['turnaround_minutes']
        assert end<=pool['close_minutes']+EPS,'预约超过资源服务或返回窗口'
        aggregate[aid,t]+=units;total[pool['id']]+=units;cost+=units*a['unit_cost_yuan'];mode_units[a['mode_id']]+=units
        stop=t+1 if pool['kind']=='quota' else math.ceil(end/step)
        for k in range(t,stop):fleet[pool['id'],k]+=units
        if pool['kind']=='vehicle':
            unit_ids=row.get('unit_ids',[])
            assert len(unit_ids)==units and len(set(unit_ids))==units,'周转单位编号数量须与预约数一致'
            for key in unit_ids:ids[pool['id'],key].append((t*step,end))
        for f in card.get('occupancy_facilities',[]):
            if aid in f['links']:
                for k in range(t,t+b):bays[f['id'],k]+=units
        for field,expected in [('start_minute',t*step),('departure_minute',depart),('arrival_minute',arrive)]:
            if field in row:assert abs(row[field]-expected)<EPS,'输出时刻与原始参数不一致'
        if pool['kind']=='vehicle' and row.get('return_minute') is not None:assert abs(row['return_minute']-end)<EPS,'返回时刻不一致'
    for (aid,t),n in aggregate.items():assert n<=calendar(rec['links'][aid]['max_units'],T)[t]+EPS,'线路预约单位超限'
    for pool in card['pools']:
        assert total[pool['id']]<=pool['total_units_limit']+EPS,'资源池全程投放次数超限'
        assert max([v for (pid,k),v in fleet.items() if pid==pool['id']],default=0)<=pool['available_units']+EPS,'资源池并发或每步服务包超限'
        used_ids={key for pid,key in ids if pid==pool['id']}
        if pool['kind']=='vehicle':assert len(used_ids)<=pool['available_units'],'实际使用周转单位数量超限'
    for spans in ids.values():
        spans.sort();assert all(a[1]<=b[0]+EPS for a,b in zip(spans,spans[1:])),'同一周转单位任务冲突'
    for f in card.get('occupancy_facilities',[]):assert max([v for (fid,t),v in bays.items() if fid==f['id']],default=0)<=f['available_units']+EPS,'共用登乘位冲突'
    assert cost<=p['budget_yuan']+EPS,'预约费用超过预算'
    return {'cost_yuan':cost,'reserved_units':sum(total.values()),'by_pool_units':dict(total),'by_mode_units':dict(mode_units),
      'used_reusable_units':len(ids),'reservations':len(plan['reservations'])}

def replay(card,plan,policy,profile):
    check_plan(card,plan);rec,T,step,services=service_tables(card,plan);p=card['parameters']
    flow=defaultdict(float)
    for row in policy['flows']:
        gid=row.get('group_id');aid=row.get('link_id');t=row.get('start_step');n=row.get('people')
        assert gid in rec['groups'] and aid in rec['links'] and type(t) is int and 0<=t<T,'服务流引用的群体、线路或时段无效'
        assert type(n) in (int,float) and math.isfinite(n) and n>=-EPS,'服务人数无效'
        flow[gid,aid,t]+=max(0,n)
    queues={(g['id'],n['id']):deque() for g in card['groups'] for n in card['nodes']}
    incoming=defaultdict(list);boarding=[];released=defaultdict(float);left_origin=0.;last_origin=None
    initial=sum(g['initial_people'] for g in card['groups']);expected=initial+sum(sum(v) for v in profile['arrivals'].values())
    arrived=0.;delivered=0.;wait_cohorts=0.;journey=0.;max_wait=0.;wait_area=0.;travel_total=0.;stand_total=0.;mode_stand=defaultdict(float)
    mode_boardings=defaultdict(float);node_peaks=defaultdict(float);group_origin_peaks=defaultdict(float);trace=[];node_trace=[];completion=0 if expected==0 else None;peak=0.
    for t in range(T+1):
        time=t*step;arrivals_here=defaultdict(float);delivered_now=0
        next_boarding=[]
        for end,gid,nid,count,first in boarding:
            if end<=t:
                if first:left_origin+=count
            else:next_boarding.append((end,gid,nid,count,first))
        boarding=next_boarding
        if left_origin>=expected-EPS and last_origin is None:last_origin=time
        for gid,nid,batch in incoming[t]:
            n=batch['n'];arrivals_here[gid,nid]+=n
            if nid==rec['groups'][gid]['destination']:
                delivered+=n;delivered_now+=n;wait_cohorts+=n*batch['wait'];journey+=n*(time-batch['entered']);max_wait=max(max_wait,batch['wait'])
                assert abs((time-batch['entered'])-batch['wait']-batch['travel'])<1e-5,'旅程分解不一致'
            else:queues[gid,nid].append({**batch,'since':t})
        for node in card['nodes']:
            received=sum(n for (g,nid),n in arrivals_here.items() if nid==node['id'])
            if t:assert received<=calendar(node['receiving_capacity'],T)[t-1]+EPS,'下游或换乘节点接收能力冲突'
        exo=defaultdict(float)
        for g in card['groups']:
            n=(g['initial_people'] if t==0 else 0)+(profile['arrivals'][g['id']][t] if t<p['entry_steps'] else 0)
            if n:queues[g['id'],g['origin']].append({'n':n,'entered':time,'since':t,'wait':0.,'travel':0.,'left':False});exo[g['id'],g['origin']]=n
            arrived+=n
        waiting_before={k:sum(b['n'] for b in q) for k,q in queues.items()}
        physical_nodes={n['id']:sum(v for (gid,nid),v in waiting_before.items() if nid==n['id'])+sum(v for end,gid,nid,v,first in boarding if nid==n['id']) for n in card['nodes']}
        physical=sum(physical_nodes.values());peak=max(peak,physical)
        for nid,v in physical_nodes.items():node_peaks[nid]=max(node_peaks[nid],v)
        for g in card['groups']:
            val=waiting_before[g['id'],g['origin']]+sum(n for end,gid,nid,n,first in boarding if gid==g['id'] and nid==g['origin'])
            group_origin_peaks[g['id']]=max(group_origin_peaks[g['id']],val)
        used=defaultdict(float);starts=defaultdict(float);moved=0
        for a in card['links']:
            aid=a['id'];mode=rec['modes'][a['mode_id']];amount=sum(flow[g['id'],aid,t] for g in card['groups']) if t<T else 0
            if not amount:continue
            service=services[aid,t];b,ride=service['board'],service['travel']
            assert t+b+ride<=T and amount<=service['capacity']+EPS,'线路容量或运行时序不满足'
            assert mode.get('enabled',True),'使用了停用方式'
            if mode['comfort']=='seats':
                standing=max(0,amount-service['seats']);stand_total+=standing*ride*step;mode_stand[mode['id']]+=standing*ride*step
                assert standing<=service['standing_area']*mode['standing_density_limit']+EPS,'实际站立密度超限'
            used[a['from']]+=amount;starts[aid]=amount;mode_boardings[mode['id']]+=amount;travel_total+=amount*ride*step;moved+=amount
            for g in card['groups']:
                gid=g['id'];n=flow[gid,aid,t]
                if n<EPS:continue
                assert aid in rec['links'] and a['mode_id'] in g['allowed_modes'] and a['from']!=g['destination'],'使用了群体不接受的方式或离开最终目的节点'
                if a['from']==g['origin'] and p.get('origin_departure_deadline_minutes') is not None:assert (t+b)*step<=p['origin_departure_deadline_minutes']+EPS,'旅客离开起点超过规定截止'
                queue=queues[gid,a['from']];available=sum(q['n'] for q in queue)
                assert n<=available+EPS,'服务了尚未到达该节点的旅客，或换乘时间不足'
                n=min(n,available);left=n
                while left>1e-8:
                    batch=queue[0];take=min(left,batch['n']);first=not batch['left'] and a['from']==g['origin']
                    incoming[t+b+ride].append((gid,a['to'],{'n':take,'entered':batch['entered'],'since':t+b+ride,
                      'wait':batch['wait']+(t-batch['since']+b)*step,'travel':batch['travel']+ride*step,'left':batch['left'] or first}))
                    if b:boarding.append((t+b,gid,a['from'],take,first))
                    elif first:left_origin+=take
                    batch['n']-=take;left-=take
                    if batch['n']<1e-8:queue.popleft()
        for node in card['nodes']:
            if t<T:assert used[node['id']]<=calendar(node['boarding_capacity'],T)[t]+EPS,'共用节点登乘能力超限'
        for f in card.get('facilities',[]):
            if t<T:assert sum(starts[a] for a in f['links'])<=calendar(f['capacity'],T)[t]+EPS,'共享通道服务能力超限'
        waiting_after={k:sum(b['n'] for b in q) for k,q in queues.items()}
        for (gid,nid),value in waiting_after.items():
            entered=exo[gid,nid]+arrivals_here[gid,nid] if nid!=rec['groups'][gid]['destination'] else 0
            started=sum(flow[gid,a['id'],t] for a in card['links'] if a['from']==nid) if t<T else 0
            residual=waiting_before[gid,nid]-started-value
            assert abs(residual)<EPS,'节点人数不守恒'
            if waiting_before[gid,nid] or value or entered or started:node_trace.append({'minute':time,'group_id':gid,'node_id':nid,'new_or_transfer_arrivals':entered,'waiting_before':waiting_before[gid,nid],
                 'boarding_started':started,'waiting_after':value,'boarding_active_after':sum(n for end,gg,nn,n,first in boarding if gg==gid and nn==nid),'conservation_residual':residual})
        if t<T:wait_area+=(sum(waiting_after.values())+sum(n for end,g,nid,n,first in boarding))*step
        if delivered>=expected-EPS and completion is None:completion=time
        if left_origin>=expected-EPS and last_origin is None:last_origin=time
        trace.append({'minute':time,'queue_before':physical,'queue_after':sum(waiting_after.values())+sum(n for end,g,nid,n,first in boarding),
           'delivered_this_boundary':delivered_now,'boarding_started':moved,'node_queues':physical_nodes})
    residual=expected-delivered
    assert abs(arrived-expected)<EPS,'输入任务人数不一致'
    remaining_wait=sum(b['n']*(b['wait']+(T-b['since'])*step) for q in queues.values() for b in q)
    assert abs(wait_area-wait_cohorts-remaining_wait)<.05,'队列积分与独立批次等待不一致'
    assert abs(residual-sum(b['n'] for q in queues.values() for b in q))<EPS,'网络总人数不守恒'
    if p.get('standing_person_minutes_limit') is not None:assert stand_total<=p['standing_person_minutes_limit']+EPS,'累计站立负担超限'
    for mode in card['modes']:
        if mode.get('standing_person_minutes_limit') is not None:assert mode_stand[mode['id']]<=mode['standing_person_minutes_limit']+EPS,'方式站立负担超限'
    safe=peak<=p['queue_limit_people']+EPS
    for node in card['nodes']:
        safe=safe and node_peaks[node['id']]<=node['queue_limit_people']+EPS
        if node.get('waiting_density_limit') is not None:safe=safe and node_peaks[node['id']]<=node['waiting_density_limit']*node['waiting_area_m2']+EPS
    for g in card['groups']:
        if g.get('queue_limit_people') is not None:safe=safe and group_origin_peaks[g['id']]<=g['queue_limit_people']+EPS
    complete=residual<EPS and completion is not None
    return {'profile_id':profile['id'],'label':profile['label'],'task_people':expected,'delivered_people':delivered,'remaining_people':max(0,residual),
      'deadline_remaining_people':max(0,residual),'peak_queue_people':peak,'node_peak_people':dict(node_peaks),'completion_minutes':completion,
      'origin_clear_minutes':last_origin,'total_wait_person_minutes':wait_area,'total_journey_person_minutes':journey if complete else None,
      'mean_wait_minutes':wait_cohorts/expected if complete and expected else (0 if not expected else None),
      'max_wait_minutes':max_wait if complete else None,'mean_journey_minutes':journey/expected if complete and expected else (0 if not expected else None),
      'travel_person_minutes':travel_total,'standing_person_minutes':stand_total,'by_mode_boardings':dict(mode_boardings),
      'safe_queue':bool(safe),'complete_by_deadline':bool(complete),'all_targets_met':bool(safe and complete),
      'trace':trace,'node_trace':node_trace}

def greedy_policy(card,plan,profile):
    """Uses only observed demand and the known, already-reserved service calendar."""
    check_plan(card,plan);rec,T,step,services=service_tables(card,plan);p=card['parameters']
    best={};edges=defaultdict(list)
    for a in card['links']:edges[a['from']].append(a)
    for g in card['groups']:
        for t in range(T,-1,-1):
            for node in card['nodes']:
                nid=node['id'];value=t if nid==g['destination'] else (best.get((g['id'],nid,t+1),math.inf) if t<T else math.inf)
                for a in edges[nid]:
                    if t>=T or a['mode_id'] not in g['allowed_modes'] or not services[a['id'],t]['capacity']:continue
                    b,ride=time_parts(card,a)
                    if t+b+ride<=T:value=min(value,best.get((g['id'],a['to'],t+b+ride),math.inf))
                best[g['id'],nid,t]=value
    queue=defaultdict(float);incoming=defaultdict(list);received=defaultdict(float);flows=[];standing_left=p.get('standing_person_minutes_limit');mode_left={m['id']:m.get('standing_person_minutes_limit') for m in card['modes']}
    for t in range(T):
        for gid,nid,people in incoming[t]:
            if nid!=rec['groups'][gid]['destination']:queue[gid,nid]+=people
        for g in card['groups']:queue[g['id'],g['origin']]+=(g['initial_people'] if t==0 else 0)+(profile['arrivals'][g['id']][t] if t<p['entry_steps'] else 0)
        remaining={a['id']:services[a['id'],t]['capacity'] for a in card['links']};loads=defaultdict(float)
        node_left={n['id']:calendar(n['boarding_capacity'],T)[t] for n in card['nodes']};facility_left={i:calendar(f['capacity'],T)[t] for i,f in enumerate(card.get('facilities',[]))}
        for g in card['groups']:
            gid=g['id']
            for node in card['nodes']:
                nid=node['id']
                if nid==g['destination']:continue
                choices=[]
                for a in edges[nid]:
                    service=services[a['id'],t];at=t+service['board']+service['travel']
                    if a['mode_id'] not in g['allowed_modes'] or at>T:continue
                    if nid==g['origin'] and p.get('origin_departure_deadline_minutes') is not None and (t+service['board'])*step>p['origin_departure_deadline_minutes']+EPS:continue
                    score=best.get((gid,a['to'],at),math.inf)
                    if math.isfinite(score):choices.append((score,a['travel_minutes'],a['id'],a))
                for score,duration,aid,a in sorted(choices,key=lambda x:x[:3]):
                    service=services[aid,t];at=t+service['board']+service['travel'];destination=rec['nodes'][a['to']];mode=rec['modes'][a['mode_id']]
                    receive=max(0,calendar(destination['receiving_capacity'],T)[at-1]-received[a['to'],at])
                    n=min(queue[gid,nid],remaining[aid],node_left[nid],receive)
                    affected=[i for i,f in enumerate(card.get('facilities',[])) if aid in f['links']]
                    for i in affected:n=min(n,facility_left[i])
                    if mode['comfort']=='seats':
                        seated_margin=max(0,service['seats']-loads[aid]);ride=service['travel']*step
                        for limit in (standing_left,mode_left[mode['id']]):
                            if limit is not None:n=min(n,seated_margin+max(0,limit)/ride)
                    n=max(0,n)
                    if n<EPS:continue
                    increment=(max(0,loads[aid]+n-service['seats'])-max(0,loads[aid]-service['seats']))*service['travel']*step if mode['comfort']=='seats' else 0
                    if standing_left is not None:standing_left-=increment
                    if mode_left[mode['id']] is not None:mode_left[mode['id']]-=increment
                    queue[gid,nid]-=n;remaining[aid]-=n;node_left[nid]-=n;loads[aid]+=n;received[a['to'],at]+=n
                    for i in affected:facility_left[i]-=n
                    incoming[at].append((gid,a['to'],n));flows.append({'group_id':gid,'link_id':aid,'start_step':t,'people':n})
    return {'profile_id':profile['id'],'flows':flows}

def verify_causality(card,policies):
    p=card['parameters'];T=int(p['deadline_minutes']/p['step_minutes']);lookup=defaultdict(float)
    for policy in policies:
        for row in policy['flows']:lookup[policy['profile_id'],row['group_id'],row['link_id'],row['start_step']]+=row['people']
    checked=0
    for t in range(T):
        histories={}
        for s in card['profiles']:
            history=tuple(round(v,8) for g in card['groups'] for v in s['arrivals'][g['id']][:min(t+1,p['entry_steps'])]);ref=histories.setdefault(history,s['id'])
            if ref!=s['id']:
                for g in card['groups']:
                    for a in card['links']:
                        assert abs(lookup[s['id'],g['id'],a['id'],t]-lookup[ref,g['id'],a['id'],t])<EPS,'相同观测历史下使用了不同服务决策';checked+=1
    return checked

def audit_solution(card,result):
    info=check_plan(card,result['common_plan']);rows=[];policies={r['profile_id']:r for r in result['scenario_policy']}
    for s in card['profiles']:
        row=replay(card,result['common_plan'],policies[s['id']],s);assert row['all_targets_met'],'优化解未通过独立目标检查';rows.append(row)
    assert abs(info['cost_yuan']-result['cost_yuan'])<.01
    key='total_wait_person_minutes' if result['objective_kind']=='wait' else 'total_journey_person_minutes'
    if result['objective_kind']!='cost':
        actual=max(row[key] for row in rows);assert actual<=result['worst_objective_value']+.05,'独立时间核算超过优化上界'
        bound=result['phase_primary'].get('dual_bound')
        if bound is not None:assert actual+.05>=bound,'独立核算低于求解器下界'
    return {'plan':info,'profiles':rows,'independent_event_and_fifo_checks':'通过','nonanticipativity_equalities_checked':verify_causality(card,result['scenario_policy'])}
