"""Scenario data, deliberately kept out of the solver and its constraints."""
from copy import deepcopy
from pathlib import Path
import json, math
from network_schema import SCHEMA, calendar

def node(key,label,cap=200,through=1000,area=100):
    return {'id':key,'label':label,'queue_limit_people':cap,'waiting_area_m2':area,'waiting_density_limit':None,'boarding_capacity':through,'receiving_capacity':through}

def mode(key,label,control='fixed',comfort='seats'):
    return {'id':key,'label':label,'control':control,'comfort':comfort,'enabled':True,'standing_density_limit':2,'standing_person_minutes_limit':None}

def pool(key,label,kind,home=None,units=1,total=2,seats=6,capacity=6,area=0,prepare=0,close=180,turn=0):
    return {'id':key,'label':label,'kind':kind,'home_node':home,'available_units':units,'total_units_limit':total,
      'seats':seats,'legal_capacity':capacity,'standing_area_m2':area,'prepare_minutes':prepare,'close_minutes':close,'turnaround_minutes':turn}

def link(key,label,origin,destination,mid,travel=10,boarding=0,fixed=0,seats=0,area=0,pid=None,max_units=0,cost=0,returned=0,end=180,start=0):
    return {'id':key,'label':label,'from':origin,'to':destination,'mode_id':mid,'travel_minutes':travel,'boarding_minutes':boarding,
      'fixed_capacity':fixed,'fixed_seats':seats,'fixed_standing_area_m2':area,'pool_id':pid,'max_units':max_units,
      'unit_cost_yuan':cost,'return_minutes':returned,'service_start_minutes':start,'service_end_minutes':end}

def group(key,label,origin,destination,allowed,initial=0,queue=None):
    return {'id':key,'label':label,'origin':origin,'destination':destination,'allowed_modes':allowed,'initial_people':initial,'queue_limit_people':queue}

def base(title,key,steps=6,deadline=80,budget=200):
    return {'schema_version':SCHEMA,'scenario_id':key,'record_kind':'纯模拟研究情景',
      'platform':{'title':title,'evidence_kind':'纯模拟','notes':'所有数值为声明假设；不对应实际调度权限或实测能力。','sources':''},
      'five_dimensions':{'information_lead_minutes':0},
      'parameters':{'start_time':'2026-10-20T08:00:00+08:00','step_minutes':10,'entry_steps':steps,
        'deadline_minutes':deadline,'origin_departure_deadline_minutes':None,'budget_yuan':budget,'queue_limit_people':300,
        'standing_person_minutes_limit':0},'nodes':[],'modes':[],'pools':[],'links':[],'groups':[],'profiles':[],'facilities':[]}

def tiny():
    c=base('12人网络手算示例','NET-TINY-12');c['parameters']['origin_departure_deadline_minutes']=60
    c['nodes']=[node('S','候客起点',20),node('D','接续目的节点')]
    c['modes']=[mode('custom','自定义校验运力','adjustable')]
    c['pools']=[pool('fleet','单车周转池','vehicle','S',close=90)]
    c['links']=[link('route','起点至目的节点','S','D','custom',travel=10,boarding=10,pid='fleet',max_units=1,cost=100,returned=10,end=60)]
    c['groups']=[group('G','示例旅客','S','D',['custom'])]
    c['profiles']=[{'id':'uniform','label':'逐段均匀进入','arrivals':{'G':[2]*6}}]
    return c

def multimodal():
    c=base('通用示例：地铁换乘与地面增援','NET-MULTI-120',steps=3,deadline=100,budget=200)
    c['nodes']=[node('H','枢纽候客区',150,100,100),node('M','轨道接续站',90,80,60),node('D','城区接续节点',300,120,100)]
    c['modes']=[mode('walk','步行换乘',comfort='unmeasured'),mode('metro','地铁既定服务'),mode('shuttle','接驳巴士','adjustable'),mode('ride','网约车预约','adjustable')]
    c['pools']=[pool('coaches','备用接驳车辆','vehicle','H',units=2,total=4,seats=20,capacity=20,close=140),
                pool('cars','确认的网约车服务包','quota',units=3,total=6,seats=4,capacity=4,close=80)]
    c['links']=[link('walk_to_station','步行至轨道站','H','M','walk',fixed=60),
      link('metro_departures','既定地铁班次','M','D','metro',travel=20,fixed=[0,40,0,40,0,40,0,40,0,0],seats=[0,40,0,40,0,40,0,40,0,0]),
      link('direct_coach','直达接驳','H','D','shuttle',travel=30,boarding=10,pid='coaches',max_units=2,cost=80,returned=20,end=80),
      link('direct_ride','预约直达','H','D','ride',travel=20,pid='cars',max_units=3,cost=30,end=80)]
    c['groups']=[group('G','城区接续旅客','H','D',[m['id'] for m in c['modes']])]
    c['profiles']=[{'id':'front','label':'前两段集中','arrivals':{'G':[60,60,0]}},
                   {'id':'late','label':'后两段集中','arrivals':{'G':[0,60,60]}}]
    c['platform']['notes']='演示可配置方式、固定地铁时刻、步行换乘、可周转巴士及网约车服务包；两个过程共用一套增援预约。全部为合成参数。'
    return c

def ferry():
    c=base('通用示例：道路中断后的水路接续','NET-WATER-80',steps=2,deadline=80,budget=100)
    c['nodes']=[node('A','待疏运集散点',100,100),node('P','码头换乘点',80,60),node('B','对岸接续点',100,60)]
    c['modes']=[mode('walk','步行通道',comfort='unmeasured'),mode('water','渡轮既定班次'),mode('road','道路接续服务')]
    c['links']=[link('approach','集散点至码头','A','P','walk',fixed=60),
       link('ferry','既定渡轮','P','B','water',travel=20,boarding=10,fixed=[0,40,0,40,0,40,0,0],seats=[0,40,0,40,0,40,0,0]),
       link('blocked_road','中断道路','A','B','road',fixed=0)]
    c['groups']=[group('G','跨岸接续旅客','A','B',['walk','water','road'])]
    c['profiles']=[{'id':'known','label':'两段进入','arrivals':{'G':[40,40]}}]
    c['platform']['notes']='水路与道路中断为模拟条件。渡轮与步行是数据条目，求解器不按名称切换公式。'
    return c

def convert_legacy(old):
    if old.get('schema_version')!='OPT-CARD-01':raise ValueError('只可将OPT-CARD-01旧卡转换为网络卡')
    p=old['parameters'];step=p['step_minutes'];last=p['deadline_minutes']
    arrival_allowance=max(d[k] for d in old['directions'] for k in ('bus_ride_minutes','taxi_ride_minutes','base_ride_minutes'))
    end=math.ceil((last+arrival_allowance)/step)*step;T=int(end/step)
    c=base(old.get('platform',{}).get('title',old['scenario_id'])+'（网络表达）',old['scenario_id']+'-NET',steps=int(p['entry_minutes']/step),deadline=end,budget=p['budget_yuan'])
    c['record_kind']=old.get('record_kind','旧卡转换');c['platform']=deepcopy(old.get('platform',c['platform']))
    c['platform']['title']+=' · 通用网络'
    c['platform']['notes']+=' 保留旧版离开起点截止，另设到达目的节点截止；完成口径和模型结构已扩展，不能直接沿用旧结果。'
    c['event_background']=deepcopy(old.get('event_background',{}));c['parameter_evidence']=deepcopy(old.get('parameter_evidence',{}))
    c['five_dimensions']['information_lead_minutes']=old['five_dimensions']['information_lead_minutes']
    c['parameters'].update(start_time=p['start_time'],step_minutes=step,origin_departure_deadline_minutes=last,
       queue_limit_people=p['queue_limit_people'],standing_person_minutes_limit=p['standing_person_minutes_limit'])
    c['nodes']=[node('H','枢纽候客系统',p['queue_limit_people'],p['shared_service_people_per_hour']*step/60,sum(d['waiting_area_m2'] for d in old['directions']))]
    c['nodes'][0]['waiting_density_limit']=p.get('waiting_comfort_density_people_m2')
    c['modes']=[mode('given','基础地面接续'),mode('reserve','备用公交','adjustable'),mode('booking','出租服务预约','adjustable')]
    for m in c['modes']:m['standing_density_limit']=p['standing_density_limit_people_m2']
    c['pools']=[pool('vehicles','备用公交池','vehicle','H',units=p['bus_fleet_size'],total=p['bus_trip_limit'],seats=p['bus_seats'],capacity=p['bus_legal_capacity'],area=p['bus_standing_area_m2'],prepare=p['bus_prepare_minutes'],close=p['vehicle_shift_end_minutes'],turn=p['bus_turnaround_minutes']),
       pool('bookings','确认的出租服务包','quota',units=p['taxi_max_blocks_per_step'],total=p['taxi_total_blocks'],seats=p['taxi_block_people'],capacity=p['taxi_block_people'],prepare=p['taxi_prepare_minutes'],close=p['taxi_service_end_minutes'])]
    c['facilities']=[{'id':'bay','label':'公交登乘站位折算（每段新开班次）','links':[],'capacity':p['bus_bays']*p['bus_legal_capacity']}]
    # The network engine separately supports physical occupancy facilities.
    c['occupancy_facilities']=[{'id':'bus_bay','label':'公交登乘站位','links':[],'available_units':p['bus_bays']}]
    for d in old['directions']:
        dest='D_'+d['id'];gid='G_'+d['id']
        n=node(dest,d['label']+'接续节点',100000,d['receiver_people_per_hour']*step/60,d['waiting_area_m2'])
        n['receiving_capacity']=[d['receiver_people_per_hour']*step/60 if p['receiver_open_minutes']<=(t+1)*step<=p['receiver_close_minutes'] else 0 for t in range(T)]
        c['nodes'].append(n);c['groups'].append(group(gid,d['label']+'旅客','H',dest,['given','reserve','booking'],d['initial_queue'],d['queue_limit_people']))
        active=[d['base_people_per_hour']*step/60 if (t+1)*step<=last else 0 for t in range(T)]
        b='reserve_'+d['id']
        c['links'] += [link('given_'+d['id'],'基础至'+d['label'],'H',dest,'given',travel=d['base_ride_minutes'],boarding=step,fixed=active,seats=active,end=last),
          link(b,'公交至'+d['label'],'H',dest,'reserve',travel=d['bus_ride_minutes'],boarding=p['bus_boarding_minutes'],pid='vehicles',max_units=1,cost=d['bus_trip_cost_yuan'],returned=d['bus_ride_minutes'],end=p['bus_service_end_minutes']),
          link('booking_'+d['id'],'预约至'+d['label'],'H',dest,'booking',travel=d['taxi_ride_minutes'],boarding=step,pid='bookings',max_units=p['taxi_max_blocks_per_step'],cost=p['taxi_block_cost_yuan'],end=p['taxi_service_end_minutes'])]
        c['facilities'][0]['links'].append(b);c['occupancy_facilities'][0]['links'].append(b)
    for s in old['arrival_profiles']:
        values={}
        for d in old['directions']:
            values['G_'+d['id']]=[s['hourly_people'][int(t*step//60)]*step/60*d['share'] for t in range(c['parameters']['entry_steps'])]
        c['profiles'].append({'id':s['id'],'label':s['label'],'arrivals':values})
    return c

def templates():
    root=Path(__file__).resolve().parents[2]
    old=json.loads((root/'03_情景库/模型输入卡-虹桥降雪背景.json').read_text(encoding='utf-8'))
    old['platform']={'title':'虹桥降雪真实背景示例','evidence_kind':'真实背景＋假设参数','notes':'2023年12月14日背景真实，所有运力与需求参数为声明假设。','sources':old['event_background']['source_url']}
    return {'network':multimodal(),'tiny':tiny(),'ferry':ferry(),'hongqiao':convert_legacy(old)}
