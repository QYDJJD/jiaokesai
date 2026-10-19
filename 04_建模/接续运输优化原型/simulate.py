"""Independent event/FIFO replay. Does not read or reuse the MILP matrix."""
from collections import deque, defaultdict
import math
import copy

EPS=2e-5
MODES=('base','taxi','bus')


def entered(card, profile, t):
    p=card['parameters'];minute=t*p['step_minutes']
    total=profile['hourly_people'][int(minute//60)]*p['step_minutes']/60 if minute<p['entry_minutes'] else 0
    return [total*d['share'] for d in card['directions']]


def check_plan(card, plan):
    p=card['parameters'];ds=card['directions'];dt=p['step_minutes'];tasks=plan['bus_tasks']
    assert len(tasks)<=p['bus_trip_limit'], '公交班次超限'
    vehicles=defaultdict(list); bays=defaultdict(int); fleet=defaultdict(int)
    ready=max(0,p['bus_prepare_minutes']-card['five_dimensions']['information_lead_minutes'])
    for task in tasks:
        d=ds[task['direction']];start=task['start_slot']*dt
        board=math.ceil(p['bus_boarding_minutes']/dt)*dt; depart=start+board
        returned=depart+2*d['bus_ride_minutes']+p['bus_turnaround_minutes']
        assert abs(start-task['start_minute'])<EPS
        assert abs(depart-task['departure_minute'])<EPS
        assert abs(returned-task['return_minute'])<EPS
        assert task['departure_slot']==math.ceil(depart/dt)-1
        assert start+EPS>=ready and depart<=p['bus_service_end_minutes']+EPS
        assert returned<=p['vehicle_shift_end_minutes']+EPS
        assert p['receiver_open_minutes']<=depart+d['bus_ride_minutes']<=p['receiver_close_minutes']
        vehicles[task['vehicle_id']].append((start,returned))
        for k in range(task['start_slot'],math.ceil(depart/dt)):bays[k]+=1
        for k in range(task['start_slot'],math.ceil(returned/dt)):fleet[k]+=1
    assert len(vehicles)<=p['bus_fleet_size']
    for spans in vehicles.values():
        spans.sort()
        assert all(b<=c+EPS for (a,b),(c,e) in zip(spans,spans[1:])), '同一车辆周转冲突'
    assert max(bays.values(),default=0)<=p['bus_bays'], '共享站位冲突'
    assert max(fleet.values(),default=0)<=p['bus_fleet_size']
    taxi=plan['taxi_blocks'];nt=len(taxi[0]);total=0
    tr=max(0,p['taxi_prepare_minutes']-card['five_dimensions']['information_lead_minutes'])
    for t in range(nt):
        blocks=sum(taxi[d][t] for d in range(len(ds)))
        assert blocks<=p['taxi_max_blocks_per_step']+EPS
        total+=blocks
        for d in range(len(ds)):
            n=taxi[d][t]
            assert n>=0 and abs(n-round(n))<EPS
            if n:
                at=(t+1)*dt+ds[d]['taxi_ride_minutes']
                assert t*dt+EPS>=tr and (t+1)*dt<=p['taxi_service_end_minutes']+EPS
                assert p['receiver_open_minutes']<=at<=p['receiver_close_minutes']
    assert total<=p['taxi_total_blocks']+EPS
    cost=sum(ds[t['direction']]['bus_trip_cost_yuan'] for t in tasks)+total*p['taxi_block_cost_yuan']
    assert cost<=p['budget_yuan']+EPS,'预约成本超过预算'
    return {'cost_yuan':cost,'bus_trips':len(tasks),'used_vehicles':len(vehicles),
            'taxi_reserved_people':total*p['taxi_block_people'],
            'peak_bay_occupancy':max(bays.values(),default=0),
            'peak_busy_vehicles':max(fleet.values(),default=0)}


def bus_counts(plan):
    out=defaultdict(int)
    for t in plan['bus_tasks']:out[t['direction'],t['departure_slot']]+=1
    return out


def causal_greedy(card,plan,profile,horizon_minutes=None):
    """A transparent current-queue baseline; no future arrival observations."""
    p=card['parameters'];ds=card['directions'];dt=p['step_minutes']
    nt=math.ceil((horizon_minutes or p['deadline_minutes'])/dt);nd=len(ds)
    queue=[d['initial_queue'] for d in ds];received=defaultdict(float)
    flows={mode:[[0.0]*nt for d in ds] for mode in MODES};buses=bus_counts(plan)
    remaining_standing=p['standing_person_minutes_limit']
    for t in range(nt):
        new=entered(card,profile,t);queue=[a+b for a,b in zip(queue,new)]
        shared=p['shared_service_people_per_hour']*dt/60
        order=sorted(range(nd),key=lambda d:(-queue[d],d))
        for mode in MODES:
            for d in order:
                direction=ds[d];count=buses[d,t]
                at=(t+1)*dt+direction[mode+'_ride_minutes'];slot=math.ceil(at/dt)-1
                if not p['receiver_open_minutes']<=at<=p['receiver_close_minutes']:continue
                receive=max(0,direction['receiver_people_per_hour']*dt/60-received[d,slot])
                if mode=='base':cap=direction['base_people_per_hour']*dt/60
                elif mode=='taxi':cap=(plan['taxi_blocks'][d][t] if t<len(plan['taxi_blocks'][d]) else 0)*p['taxi_block_people']
                else:
                    cap=min(p['bus_legal_capacity'],p['bus_seats']+p['standing_density_limit_people_m2']*p['bus_standing_area_m2'])*count
                    if direction['bus_ride_minutes']>0:cap=min(cap,p['bus_seats']*count+remaining_standing/direction['bus_ride_minutes'])
                n=min(queue[d],shared,receive,cap)
                n=max(0,n);flows[mode][d][t]=n;queue[d]-=n;shared-=n;received[d,slot]+=n
                if mode=='bus':remaining_standing-=max(0,n-p['bus_seats']*count)*direction['bus_ride_minutes']
    return {'profile_id':profile['id'],'flows':flows}


def replay(card,plan,policy,profile):
    p=card['parameters'];ds=card['directions'];dt=p['step_minutes'];nd=len(ds)
    flows=policy['flows'];nt=len(flows['base'][0]);buses=bus_counts(plan)
    batches=[deque() for d in ds]
    for d,direction in enumerate(ds):
        if direction['initial_queue']:batches[d].append([0.0,float(direction['initial_queue'])])
    queue=[float(d['initial_queue']) for d in ds]; initial=sum(queue)
    total_arrivals=0.;served=0.;wait=0.;area=0.;maxwait=0.;standing=0.;ride=0.
    peak=sum(queue);dir_peak=queue[:];received=defaultdict(float);trace=[]
    expected=card['five_dimensions']['new_onward_passengers']+initial
    deadline_residual=None;completion=0 if expected==0 else None;standing_max=0.;counts=defaultdict(float)
    last_entry=0
    for t in range(nt):
        start=t*dt;end=(t+1)*dt;new=entered(card,profile,t)
        for d,n in enumerate(new):
            if n>0:batches[d].append([float(start),float(n)]);last_entry=end
            queue[d]+=n
        total_arrivals+=sum(new);peak=max(peak,sum(queue));before=queue[:]
        dir_peak=[max(a,b) for a,b in zip(dir_peak,queue)]
        # Separate minute-by-minute area calculation, with boundary events only.
        for minute in range(int(dt)):area+=sum(queue)
        step_served=0
        for mode in MODES:
            for d,direction in enumerate(ds):
                n=flows[mode][d][t]
                assert n>=-EPS,'服务人数为负'
                n=max(0,n)
                assert n<=queue[d]+EPS,'服务了尚未进入的旅客'
                n=min(n,sum(amount for entered_at,amount in batches[d]))
                step_served+=n
                if mode=='base':cap=direction['base_people_per_hour']*dt/60
                elif mode=='taxi':cap=(plan['taxi_blocks'][d][t] if t<len(plan['taxi_blocks'][d]) else 0)*p['taxi_block_people']
                else:
                    cap=min(p['bus_legal_capacity'],p['bus_seats']+p['standing_density_limit_people_m2']*p['bus_standing_area_m2'])*buses[d,t]
                    count_standing=max(0,n-p['bus_seats']*buses[d,t])
                    standing+=count_standing*direction['bus_ride_minutes']
                    standing_max=max(standing_max,count_standing/(p['bus_standing_area_m2']*buses[d,t]) if buses[d,t] else 0)
                assert n<=cap+EPS, '服务超过方式或舒适载客容量'
                at=end+direction[mode+'_ride_minutes'];slot=math.ceil(at/dt)-1
                if n>EPS:assert p['receiver_open_minutes']-EPS<=at<=p['receiver_close_minutes']+EPS
                received[d,slot]+=n
                assert received[d,slot]<=direction['receiver_people_per_hour']*dt/60+EPS,'下游接续容量冲突'
                ride+=n*direction[mode+'_ride_minutes'];counts[mode]+=n
                left=n
                while left>1e-9:
                    assert batches[d], 'FIFO批次不足'
                    entered_at,amount=batches[d][0];take=min(left,amount)
                    wait+=take*(end-entered_at);maxwait=max(maxwait,end-entered_at)
                    batches[d][0][1]-=take;left-=take
                    if batches[d][0][1]<1e-9:batches[d].popleft()
                queue[d]=sum(amount for entered_at,amount in batches[d]);served+=n
        assert step_served<=p['shared_service_people_per_hour']*dt/60+EPS, '共享上客流量超限'
        if abs(end-p['deadline_minutes'])<EPS:deadline_residual=sum(queue)
        if total_arrivals+initial>=expected-EPS and sum(queue)<EPS and completion is None:completion=end
        trace.append({'minute':end,'queue_before':sum(before),'queue_after':sum(queue),
                      'direction_queues':queue[:],'served_this_step':step_served})
    accrued_remaining=sum(n*(nt*dt-entered_at) for batch in batches for entered_at,n in batch)
    assert abs(area-wait-accrued_remaining)<.02,'事件积分与FIFO等待不一致'
    assert abs(total_arrivals+initial-served-sum(queue))<EPS,'人数不守恒'
    assert standing<=p['standing_person_minutes_limit']+EPS,'站立人分钟超限'
    complete=completion is not None and completion<=p['deadline_minutes']+EPS
    safe=peak<=p['queue_limit_people']+EPS and all(v<=d['queue_limit_people']+EPS for v,d in zip(dir_peak,ds))
    comfort_density=p.get('waiting_comfort_density_people_m2')
    if comfort_density is not None:safe=safe and all(v<=comfort_density*d['waiting_area_m2']+EPS for v,d in zip(dir_peak,ds))
    return {'profile_id':profile['id'],'label':profile['label'],'arrived_people':total_arrivals,
            'served_people':served,'remaining_people':sum(queue),'deadline_remaining_people':deadline_residual,
            'peak_queue_people':peak,'direction_peak_people':dir_peak,
            'peak_waiting_density_people_m2':max(v/d['waiting_area_m2'] for v,d in zip(dir_peak,ds)),
            'completion_minutes':completion,'total_wait_person_minutes':wait+accrued_remaining,
            'mean_wait_minutes':(wait/(initial+total_arrivals) if initial+total_arrivals else 0) if completion is not None else None,
            'max_wait_minutes':maxwait if completion is not None else None,
            'standing_person_minutes':standing,'max_standing_density_people_m2':standing_max,
            'in_vehicle_person_minutes':ride,'by_mode_people':dict(counts),
            'safe_queue':safe,'complete_by_deadline':complete,'all_targets_met':safe and complete,
            'trace':trace}


def verify_causality(card,policies):
    dt=card['parameters']['step_minutes'];nt=round(card['parameters']['deadline_minutes']/dt)
    histories={p['id']:[] for p in card['arrival_profiles']};rows={p['profile_id']:p for p in policies};checks=0
    for t in range(nt):
        same={}
        for profile in card['arrival_profiles']:
            key=profile['id'];histories[key].extend(round(v,8) for v in entered(card,profile,t))
            hist=tuple(histories[key]);reference=same.setdefault(hist,key)
            if reference!=key:
                for mode in MODES:
                    for d in range(len(card['directions'])):
                        assert abs(rows[key]['flows'][mode][d][t]-rows[reference]['flows'][mode][d][t])<EPS,'共同历史上的服务决策不同'
                        checks+=1
    return checks


def audit_solution(card,result):
    assert result['has_solution']
    plan_info=check_plan(card,result['common_plan'])
    policies={p['profile_id']:p for p in result['scenario_policy']}
    rows=[replay(card,result['common_plan'],policies[p['id']],p) for p in card['arrival_profiles']]
    assert all(r['all_targets_met'] for r in rows), '求解排班未通过独立目标核对'
    if result['objective_kind']=='wait':
        actual=max(r['total_wait_person_minutes'] for r in rows)
        assert actual<=result['worst_wait_person_minutes']+.05,'独立等待超过求解目标上界'
        lower=result['phase_primary'].get('dual_bound')
        if lower is not None:assert actual+.05>=lower,'独立等待低于合法求解界限'
    assert abs(plan_info['cost_yuan']-result['cost_yuan'])<.01
    return {'plan':plan_info,'profiles':rows,'nonanticipativity_equalities_checked':verify_causality(card,result['scenario_policy']),
            'independent_event_and_fifo_checks':'通过'}


def average_plan(card):
    """Evenly spread reservations, with explicit return-compatible vehicle IDs."""
    p=card['parameters'];ds=card['directions'];dt=p['step_minutes'];nt=round(p['deadline_minutes']/dt)
    eligible=round(p['bus_service_end_minutes']/dt);board=math.ceil(p['bus_boarding_minutes']/dt)
    ends=[0]*int(p['bus_fleet_size']);tasks=[];served_share=[0]*len(ds)
    for i in range(int(p['bus_trip_limit'])):
        target=math.floor(i*(eligible-board+1)/p['bus_trip_limit'])
        chosen=None
        for start in range(target,eligible-board+1):
            if any(set(range(start,start+board))&set(range(x['start_slot'],x['departure_slot']+1)) for x in tasks):continue
            candidates=[v for v,e in enumerate(ends) if e<=start*dt]
            if not candidates:continue
            direction=max(range(len(ds)),key=lambda d:ds[d]['share']*(i+1)-served_share[d])
            d=ds[direction];depart=(start+board)*dt
            returned=depart+2*d['bus_ride_minutes']+p['bus_turnaround_minutes']
            ready=max(0,p['bus_prepare_minutes']-card['five_dimensions']['information_lead_minutes'])
            if start*dt<ready or returned>p['vehicle_shift_end_minutes']:continue
            if not p['receiver_open_minutes']<=depart+d['bus_ride_minutes']<=p['receiver_close_minutes']:continue
            v=min(candidates,key=lambda v:ends[v]);ends[v]=returned;served_share[direction]+=1
            chosen={'direction':direction,'start_slot':start,'departure_slot':start+board-1,
                    'start_minute':start*dt,'departure_minute':depart,'return_minute':returned,
                    'destination_minute':depart+d['bus_ride_minutes'],'vehicle_id':'备用公交'+str(v+1)}
            break
        if chosen:tasks.append(chosen)
    bus_cost=sum(ds[t['direction']]['bus_trip_cost_yuan'] for t in tasks)
    affordable=math.floor(max(0,p['budget_yuan']-bus_cost)/p['taxi_block_cost_yuan']) if p['taxi_block_cost_yuan'] else int(p['taxi_total_blocks'])
    blocks=[[0]*nt for d in ds];total=min(int(p['taxi_total_blocks']),affordable)
    slots=[t for t in range(nt) if t*dt>=max(0,p['taxi_prepare_minutes']-card['five_dimensions']['information_lead_minutes']) and (t+1)*dt<=p['taxi_service_end_minutes']]
    assigned=[0]*len(ds)
    for j in range(total):
        if not slots:break
        t=slots[min(len(slots)-1,int(j*len(slots)/total))]
        if sum(b[t] for b in blocks)>=p['taxi_max_blocks_per_step']:continue
        d=max(range(len(ds)),key=lambda d:ds[d]['share']*(j+1)-assigned[d])
        blocks[d][t]+=1;assigned[d]+=1
    return {'bus_tasks':tasks,'taxi_blocks':blocks}
