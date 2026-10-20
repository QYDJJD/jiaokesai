"""Platform adapter. Keeps the audited OPT-MILP-01 implementation unchanged."""
from pathlib import Path
import sys, json, math, copy, datetime as dt, hashlib, csv, io, html, zipfile

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / '04_建模/接续运输优化原型'
sys.path.insert(0, str(MODEL))
from build_input import make_card
from model import validate, tasks, solve
from simulate import check_plan, audit_solution, replay, causal_greedy

VERSION = 'PLATFORM-01'
LIMITS = {'directions': 6, 'profiles': 8, 'entry_hours': 12, 'periods': 180,
          'seconds_per_phase': 60, 'body_bytes': 2_000_000}

# key, Chinese label, unit, explanation. This schema also drives the forms.
GROUPS = [
 ('任务与目标', [
  ('deadline_minutes','全部完成时限','分钟','相对事件开始。完成指离开候客系统，不是到家；不得早于进入结束。'),
  ('queue_limit_people','全体候客人数上限','人','检查每段服务前候客人数，不是累计受影响人数。'),
  ('budget_yuan','增量预约预算','元','只计算本模型公交班次与出租服务包预约费用。'),
  ('shared_service_people_per_hour','共同上客通过能力','人/小时','所有方向和方式共用的服务瓶颈，不能按方式重复相加。')]),
 ('公交资源', [
  ('bus_fleet_size','可调备用公交','辆','实际同时可用的车辆，不是班次数。0表示无公交。'),
  ('bus_trip_limit','公交班次总上限','班','同一车辆可周转多班，但须满足返回时间。'),
  ('bus_bays','公交上客站位','个','登乘期间占用；并非全枢纽所有站位。'),
  ('bus_seats','每车座位','座','本版按同质车型处理。'),
  ('bus_legal_capacity','每车核定人数上限','人','还会同时检查座位和站立密度给出的舒适容量。'),
  ('bus_standing_area_m2','每车有效站立面积','平方米','不能用整车面积代替；即使全员有座也需填写正值。'),
  ('bus_boarding_minutes','每班登乘时长','分钟','向上取整到时间步，同时占用站位及车辆。必须大于0。'),
  ('bus_turnaround_minutes','返回后的周转准备','分钟','本版去程与回程运行时间相同；在回程后额外增加。'),
  ('bus_prepare_minutes','公交调令至可开始登乘','分钟','有效等待为准备时间减信息提前量，最低为0。'),
  ('bus_service_end_minutes','公交最晚离站','分钟','相对事件开始；例如360表示开始后6小时。'),
  ('vehicle_shift_end_minutes','公交最晚返回','分钟','最后一班也必须在此时刻前返回枢纽。')]),
 ('出租增援', [
  ('taxi_block_people','每服务包名额','人','是有效运送名额，不是出租车辆数；服务包不能拆分预约。'),
  ('taxi_block_cost_yuan','每服务包预约费','元','即使名额闲置也计费。'),
  ('taxi_max_blocks_per_step','每时间步最多服务包','包','所有方向合计。时间步改变时须重新核对本参数。'),
  ('taxi_total_blocks','全程最多服务包','包','0表示无新增出租服务。'),
  ('taxi_prepare_minutes','出租协调至可服务','分钟','与公交一样减去信息提前量后计算可用时刻。'),
  ('taxi_service_end_minutes','出租增援最晚完成上客','分钟','相对事件开始，超过窗口的名额不可使用。')]),
 ('舒适与下游', [
  ('standing_density_limit_people_m2','公交允许站立密度','人/平方米','与核定容量同时约束；是政策输入，不是满意度评分。'),
  ('standing_person_minutes_limit','公交累计站立负担上限','人分钟','站立人数乘乘车分钟后加总；0表示公交全员有座。'),
  ('waiting_comfort_density_people_m2','候客舒适密度上限','人/平方米','选填。留空只采用候客人数上限；填写后按方向面积增加约束。'),
  ('receiver_open_minutes','下游接续节点开放','分钟','相对开始，可为0。各方向沿用此公共窗口。'),
  ('receiver_close_minutes','下游接续节点关闭','分钟','按实际到达节点时刻核对；容量另按方向填写。')])]
DIRECTION_FIELDS = [
 ('initial_queue','初始候客','人','在事件开始时已经位于本研究候客系统的人数。'),
 ('base_people_per_hour','基础剩余接续能力','人/小时','必须是本任务可用的剩余能力，报道运送量不能直接代入。'),
 ('waiting_area_m2','有效候客面积','平方米','仅计算本方向可用候客空间。'),
 ('queue_limit_people','本方向候客上限','人','同时受全体候客上限约束。'),
 ('bus_ride_minutes','公交单程运行','分钟','本版返回也用该时长。'),
 ('taxi_ride_minutes','出租到接续节点','分钟','不据此推算逐辆出租周转。'),
 ('base_ride_minutes','基础服务到节点','分钟','用于检查下游到达窗口与容量。'),
 ('bus_trip_cost_yuan','公交每班增量费','元','合成研究或合同预约单价，不是旅客票价。'),
 ('receiver_people_per_hour','下游接收能力','人/小时','本方向不同方式到达共同占用的节点容量。')]
LABELS = {v[0]:v[1] for _, fields in GROUPS for v in fields}
LABELS.update({v[0]:v[1] for v in DIRECTION_FIELDS})
LABELS.update(step_minutes='时间步', entry_minutes='进入持续时间', share='方向份额',
              information_lead_minutes='信息提前量', new_onward_passengers='新增待接续人数')
INTEGER_KEYS = {'bus_fleet_size','bus_trip_limit','bus_bays','bus_seats','bus_legal_capacity',
                'taxi_block_people','taxi_max_blocks_per_step','taxi_total_blocks'}

def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec='seconds')

def tiny_card():
    c=make_card();p=c['parameters'];d=c['directions'][0]
    c.update(scenario_id='SIM-TINY-12',record_kind='纯模拟事件',event_background={})
    c['platform']={'title':'12人手算示例','evidence_kind':'纯模拟', 'notes':'用于熟悉输入输出。每10分钟进入2人，两班6座公交。', 'sources':''}
    c['parameter_evidence']={'all_model_numbers':'全部为教学模拟参数，不对应真实事件'}
    c['five_dimensions'].update(information_lead_minutes=0,new_onward_passengers=12,
          entry_duration_minutes=60,arrival_uncertainty='单一均匀过程',service_state='无基础与出租服务，只有一辆公交')
    p.update(start_time='2026-10-20T08:00:00+08:00',entry_minutes=60,deadline_minutes=60,
          budget_yuan=200,queue_limit_people=20,bus_fleet_size=1,bus_trip_limit=2,bus_seats=6,
          bus_legal_capacity=6,bus_standing_area_m2=1,bus_turnaround_minutes=0,bus_prepare_minutes=0,
          taxi_prepare_minutes=0,bus_service_end_minutes=60,taxi_service_end_minutes=60,
          vehicle_shift_end_minutes=90,taxi_total_blocks=0,taxi_max_blocks_per_step=0,
          receiver_close_minutes=120,standing_person_minutes_limit=0)
    d.update(id='D1',label='示例方向',share=1,initial_queue=0,queue_limit_people=20,base_people_per_hour=0,
          bus_ride_minutes=10,taxi_ride_minutes=10,base_ride_minutes=10,bus_trip_cost_yuan=100,
          receiver_people_per_hour=1000)
    c['directions']=[d];c['arrival_profiles']=[{'id':'uniform','label':'均匀进入','hourly_people':[12]}]
    return c

def templates():
    c=make_card()
    c['platform']={'title':'虹桥降雪背景：6000人合成实验','evidence_kind':'真实背景＋假设参数',
      'notes':'2023年12月14日事件背景真实，6000人、方向、能力、成本等模型数值均为研究假设。',
      'sources':c['event_background']['source_url']}
    return {'tiny':tiny_card(),'hongqiao':c}

def human_error(exc):
    text=str(exc) or '输入不符合模型规则'
    for key in sorted(LABELS,key=len,reverse=True):text=text.replace(key,LABELS[key])
    return text

def finite_number(value):
    return type(value) in (int,float) and math.isfinite(value)

def check_input(card):
    errors=[];warnings=[]
    def error(field,message):errors.append({'field':field,'message':message})
    if not isinstance(card,dict):return {'valid':False,'errors':[{'field':'card','message':'输入必须是一张完整情景卡'}],'warnings':[]}
    if not isinstance(card.get('scenario_id'),str) or not card['scenario_id'].strip():error('scenario_id','请填写情景编号')
    if 'platform' in card and not isinstance(card['platform'],dict):error('platform','事件说明须为对象')
    for key in ('parameters','five_dimensions'):
        if not isinstance(card.get(key),dict):error(key,'缺少'+('模型参数' if key=='parameters' else '五维字段'))
    for key in ('directions','arrival_profiles'):
        if not isinstance(card.get(key),list) or not card[key]:error(key,'方向与进入过程均须至少保留一项')
    if errors:return {'valid':False,'errors':errors,'warnings':warnings}
    p=card['parameters'];f=card['five_dimensions'];ds=card['directions'];ps=card['arrival_profiles']
    if len(ds)>LIMITS['directions']:error('directions','第一版最多6个方向')
    if len(ps)>LIMITS['profiles']:error('arrival_profiles','第一版最多8种进入过程')
    keys=[v[0] for _,fields in GROUPS for v in fields]+['step_minutes','entry_minutes']
    for key in keys:
        value=p.get(key)
        if key=='waiting_comfort_density_people_m2' and value is None:continue
        if not finite_number(value):error('parameters.'+key,'请填写有效的'+LABELS.get(key,key))
        elif value<0:error('parameters.'+key,LABELS.get(key,key)+'不能为负')
        elif key in INTEGER_KEYS and int(value)!=value:error('parameters.'+key,LABELS[key]+'必须是整数')
    for key in ('new_onward_passengers','entry_duration_minutes','information_lead_minutes'):
        if not finite_number(f.get(key)):error('five_dimensions.'+key,'请填写有效的'+LABELS.get(key,'进入持续时间'))
    if finite_number(f.get('new_onward_passengers')) and f['new_onward_passengers']<0:error('five_dimensions.new_onward_passengers','新增人数不能为负')
    try:
        start=dt.datetime.fromisoformat(p['start_time'])
        if start.tzinfo is None:raise ValueError()
    except (KeyError,ValueError,TypeError):error('parameters.start_time','请填写包含时区的开始时间')
    if p.get('step_minutes') not in (5,10,15,20,30):error('parameters.step_minutes','时间步请选择5、10、15、20或30分钟')
    if finite_number(p.get('entry_minutes')) and not 60<=p['entry_minutes']<=720:error('parameters.entry_minutes','第一版进入持续时间为1至12个整小时')
    if finite_number(p.get('bus_boarding_minutes')) and p['bus_boarding_minutes']<=0:error('parameters.bus_boarding_minutes','公交登乘时长必须大于0')
    if finite_number(p.get('step_minutes')) and p['step_minutes']>0 and finite_number(p.get('deadline_minutes')):
        if p['deadline_minutes']/p['step_minutes']>LIMITS['periods']:error('parameters.deadline_minutes','请缩短时域或加大时间步：第一版最多180个时段')
    for key in ('deadline_minutes','bus_service_end_minutes','taxi_service_end_minutes','vehicle_shift_end_minutes','receiver_close_minutes'):
        if finite_number(p.get(key)) and p[key]>1440:error('parameters.'+key,'第一版相对时刻不得超过1440分钟')
    for key,upper in [('bus_fleet_size',200),('bus_trip_limit',500),('bus_bays',100),('bus_seats',200),('bus_legal_capacity',200),('taxi_block_people',10000),('taxi_max_blocks_per_step',10000),('taxi_total_blocks',50000)]:
        if finite_number(p.get(key)) and p[key]>upper:error('parameters.'+key,LABELS[key]+f'超过第一版平台规模上限{upper}，请先检查单位')
    for i,d in enumerate(ds):
        if not isinstance(d,dict):error('directions','方向条目格式错误');continue
        if not isinstance(d.get('id'),str) or not d['id'].strip():error('directions','每个方向须有编号')
        if not isinstance(d.get('label'),str) or not d['label'].strip():error('directions','请填写方向名称')
        for key in ['share']+[v[0] for v in DIRECTION_FIELDS]:
            if not finite_number(d.get(key)) or d[key]<0:error(f'directions.{i}.{key}',f'方向{i+1}：请填写非负的'+LABELS[key])
    for i,s in enumerate(ps):
        if not isinstance(s,dict):error('arrival_profiles','进入过程格式错误');continue
        if not isinstance(s.get('id'),str) or not s['id'].strip():error('arrival_profiles','每个进入过程须有编号')
        if not isinstance(s.get('label'),str) or not s['label'].strip():error('arrival_profiles','请填写每个进入过程名称')
        if not isinstance(s.get('hourly_people'),list) or any(not finite_number(v) or v<0 for v in s['hourly_people']):error(f'arrival_profiles.{i}','分小时人数须为非负有效数字')
    if not errors:
        try:validate(card)
        except (ValueError,KeyError,TypeError,OverflowError) as exc:error('card',human_error(exc))
    if errors:return {'valid':False,'errors':errors,'warnings':warnings}
    if p['receiver_close_minutes']<p['receiver_open_minutes']:error('parameters.receiver_close_minutes','下游关闭不能早于开放')
    if p['bus_boarding_minutes']%p['step_minutes']:warnings.append('公交登乘时长将向上取整到完整时间步。')
    if any(d[k]%p['step_minutes'] for d in ds for k in ('bus_ride_minutes','taxi_ride_minutes','base_ride_minutes')):warnings.append('运行时长不整除时间步，下游容量按模型到达时段归并，临界结果需另作精度检查。')
    warnings.append('输入来源由你记录，平台不会自动把手工录入或报道数字认证为实测参数。')
    warnings.append('段初批量进入、段末服务完成；同方向旅客假设可接受所列方式，人数采用连续近似。')
    count=len(tasks(card))
    if not count and p['bus_fleet_size']>0:warnings.append('当前准备、运行或服务窗口下没有可用公交候选班次。')
    return {'valid':not errors,'errors':errors,'warnings':warnings,'candidate_bus_tasks':count,
            'total_task_people':f['new_onward_passengers']+sum(d['initial_queue'] for d in ds),
            'periods':round(p['deadline_minutes']/p['step_minutes'])}

def read_settings(raw):
    if not isinstance(raw,dict):raise ValueError('运行设置格式错误')
    mode=raw.get('mode','optimize');objective=raw.get('objective','wait')
    if mode not in ('optimize','manual') or objective not in ('wait','cost'):raise ValueError('运行模式或目标无效')
    seconds=raw.get('seconds',35)
    if not finite_number(seconds) or not 1<=seconds<=60:raise ValueError('每阶段计算限时为1至60秒')
    return {'mode':mode,'objective':objective,'seconds':float(seconds),'gap':0.001}

def make_manual_plan(card,manual):
    if not isinstance(manual,dict):raise ValueError('请填写手工排班')
    p=card['parameters'];step=p['step_minutes'];nd=len(card['directions']);nt=round(p['deadline_minutes']/step)
    buses=manual.get('bus',[]);taxis=manual.get('taxi',[])
    if not isinstance(buses,list) or not isinstance(taxis,list) or len(buses)>500 or len(taxis)>1500:raise ValueError('手工排班条目格式或数量不符合限制')
    candidates={(t['direction'],t['departure_minute']):t for t in tasks(card)};out=[];counts=[[0]*nt for _ in range(nd)]
    ids={d['id']:i for i,d in enumerate(card['directions'])}
    for i,row in enumerate(buses):
        d=ids.get(row.get('direction_id'));minute=row.get('departure_minute');vehicle=row.get('vehicle_id')
        if d is None or not finite_number(minute) or not isinstance(vehicle,str) or not vehicle.strip():raise ValueError(f'公交第{i+1}班：方向、离站分钟和车辆编号必须有效')
        candidate=candidates.get((d,minute))
        if candidate is None:raise ValueError(f'公交第{i+1}班：离站时刻不符合时间步、准备、返回或节点窗口；请检查资源约束')
        out.append({k:v for k,v in candidate.items() if k not in ('bay_slots','fleet_slots')}|{'start_minute':candidate['start_slot']*step,'vehicle_id':vehicle.strip()})
    for i,row in enumerate(taxis):
        d=ids.get(row.get('direction_id'));minute=row.get('start_minute');people=row.get('people')
        if d is None or not finite_number(minute) or not finite_number(people) or minute<0 or minute%step or people<0 or people%p['taxi_block_people']:raise ValueError(f'出租第{i+1}行：开始分钟须对齐时间步，名额须为每包人数的整数倍')
        t=int(minute/step)
        if t>=nt:raise ValueError(f'出租第{i+1}行：开始时刻超过核对窗口')
        counts[d][t]+=int(people/p['taxi_block_people'])
    plan={'bus_tasks':out,'taxi_blocks':counts}
    try:check_plan(card,plan)
    except (AssertionError,KeyError,IndexError,ValueError) as exc:raise ValueError('手工排班资源核对未通过：'+human_error(exc)) from exc
    return plan

def diagnostics(card):
    p=card['parameters'];step=p['step_minutes'];messages=[]
    initial=sum(d['initial_queue'] for d in card['directions'])
    if initial>p['queue_limit_people']+1e-6:messages.append('初始候客已超过全体上限；任何后续安排都不能消除开始时点的越限。')
    for s in card['arrival_profiles']:
        for h in range(len(s['hourly_people'])):
            need=sum(s['hourly_people'][h:])+(initial if h==0 else 0)
            upper=max(0,p['deadline_minutes']-h*60)*p['shared_service_people_per_hour']/60
            if need>upper+1e-6:
                messages.append(f'“{s["label"]}”从第{h+1}小时起至少需服务{need:g}人，但到截止的共享通过能力至多{upper:g}人。该必要条件已不满足。');break
        first=initial+s['hourly_people'][0]*step/60
        if first>p['queue_limit_people']+1e-6:messages.append(f'“{s["label"]}”第一段服务前已有{first:g}人，超过全体候客上限。')
    return messages or ['未发现上述简单必要条件矛盾。若求解证明不可行，可能由车辆、窗口、方向、舒适、预算等约束共同造成；平台未计算最小冲突约束集合。']

def clock(card,minute):
    if minute is None:return '核对窗口内未完成'
    return (dt.datetime.fromisoformat(card['parameters']['start_time'])+dt.timedelta(minutes=minute)).astimezone(dt.timezone(dt.timedelta(hours=8))).strftime('%m-%d %H:%M')

def evaluate(card,settings,manual=None,progress=lambda stage:None):
    settings=read_settings(settings);checked=check_input(card)
    if not checked['valid']:raise ValueError('；'.join(e['message'] for e in checked['errors']))
    result={'platform_version':VERSION,'created_at':now(),'card':copy.deepcopy(card),'settings':settings,
            'validation':checked,'input_sha256':hashlib.sha256(json.dumps(card,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            'implementation_sha256':{n:hashlib.sha256((MODEL/n).read_bytes()).hexdigest() for n in ('model.py','simulate.py')},
            'platform_implementation_sha256':{n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in ('core.py','worker.py','web/app.js')},
            'evidence_note':'事件背景与模型参数分别记录；输入来源由录入者声明，不自动认定真实效果。'}
    progress('正在核对手工资源' if settings['mode']=='manual' else '正在优化求解')
    if settings['mode']=='manual':
        plan=make_manual_plan(card,manual or {});progress('正在独立复算候客与等待')
        policies=[causal_greedy(card,plan,s) for s in card['arrival_profiles']]
        profiles=[replay(card,plan,policy,s) for policy,s in zip(policies,card['arrival_profiles'])]
        audit={'plan':check_plan(card,plan),'profiles':profiles,'independent_event_and_fifo_checks':'通过',
               'execution_rule':'仅看当前队列，基础、出租、公交依次服务，同方向先到先服务'}
        result.update(solution=None,plan=plan,audit=audit,execution_policies=policies,status='passed' if all(s['all_targets_met'] for s in profiles) else 'failed_targets')
    else:
        solution=solve(card,seconds=settings['seconds'],gap=settings['gap'],objective=settings['objective'])
        result['solution']=solution
        if solution['has_solution']:
            progress('正在独立复核优化结果');audit=audit_solution(card,solution)
            result.update(plan=solution['common_plan'],audit=audit,status='passed')
            greedy=[replay(card,result['plan'],causal_greedy(card,result['plan'],s),s) for s in card['arrival_profiles']]
            result['current_queue_execution']=greedy
        else:
            status=solution['phase_primary']['status']
            result.update(status='infeasible' if status==2 else 'unresolved',diagnostics=diagnostics(card))
    progress('正在生成对照与导出材料')
    nt=round(card['parameters']['deadline_minutes']/card['parameters']['step_minutes'])
    empty={'bus_tasks':[],'taxi_blocks':[[0]*nt for _ in card['directions']]}
    result['baseline']={'label':'仅基础服务（同一完成截止）','plan':check_plan(card,empty),
        'profiles':[replay(card,empty,causal_greedy(card,empty,s),s) for s in card['arrival_profiles']]}
    if result.get('audit'):
        reasons=[]
        for row in result['audit']['profiles']:
            if not row['safe_queue']:reasons.append('“'+row['label']+'”候客人数或候客密度超过设定上限。')
            if not row['complete_by_deadline']:reasons.append('“'+row['label']+'”截止仍有'+f'{row["deadline_remaining_people"]:.2f}'+'人未完成。')
        result['diagnostics']=reasons
    return result

def csv_bytes(rows,headers):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=headers);writer.writeheader();writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')

def tables(result):
    card=result['card'];p=card['parameters'];plan=result.get('plan');bus=[];taxi=[];metrics=[];traces=[]
    if plan:
        for t in plan['bus_tasks']:
            bus.append({'车辆':t['vehicle_id'],'方向':card['directions'][t['direction']]['label'],'开始登乘':clock(card,t['start_minute']),
                        '离站':clock(card,t['departure_minute']),'到接续节点':clock(card,t['destination_minute']),'可再次投入':clock(card,t['return_minute'])})
        for d,blocks in enumerate(plan['taxi_blocks']):
            for t,n in enumerate(blocks):
                if n:taxi.append({'方向':card['directions'][d]['label'],'时段开始':clock(card,t*p['step_minutes']),
                      '时段结束':clock(card,(t+1)*p['step_minutes']),'预约名额':n*p['taxi_block_people'],'费用元':n*p['taxi_block_cost_yuan']})
    for label,audit in [('本次方案',result.get('audit')),('仅基础服务',result.get('baseline'))]:
        if not audit:continue
        for r in audit['profiles']:
            metrics.append({'方案':label,'进入过程':r['label'],'候客峰值':r['peak_queue_people'],'平均等待分钟':r['mean_wait_minutes'],
                '最长等待分钟':r['max_wait_minutes'],'完成时刻':clock(card,r['completion_minutes']),'截止剩余人数':r['deadline_remaining_people'],
                '站立人分钟':r['standing_person_minutes'],'候客通过':r['safe_queue'],'截止通过':r['complete_by_deadline'],'全部通过':r['all_targets_met']})
            previous=sum(d['initial_queue'] for d in card['directions'])
            for trace in r['trace']:
                traces.append({'方案':label,'进入过程':r['label'],'时段开始':clock(card,trace['minute']-p['step_minutes']),
                  '时段结束':clock(card,trace['minute']),'本段新增人数':max(0,trace['queue_before']-previous),
                  '服务前候客':trace['queue_before'],'本段服务':trace['served_this_step'],'服务后候客':trace['queue_after'],
                  '守恒残差':trace['queue_before']-trace['served_this_step']-trace['queue_after']})
                previous=trace['queue_after']
    return {'公交排班.csv':csv_bytes(bus,['车辆','方向','开始登乘','离站','到接续节点','可再次投入']),
            '出租预约.csv':csv_bytes(taxi,['方向','时段开始','时段结束','预约名额','费用元']),
            '过程指标与对照.csv':csv_bytes(metrics,['方案','进入过程','候客峰值','平均等待分钟','最长等待分钟','完成时刻','截止剩余人数','站立人分钟','候客通过','截止通过','全部通过']),
            '分时核算明细.csv':csv_bytes(traces,['方案','进入过程','时段开始','时段结束','本段新增人数','服务前候客','本段服务','服务后候客','守恒残差'])}

def queue_svg(card,row,baseline):
    step=card['parameters']['step_minutes'];limit=card['parameters']['queue_limit_people']
    xmax=max(t['minute'] for t in row['trace']);ymax=max(1,limit,*[t['queue_before'] for r in (row,baseline) for t in r['trace']])*1.12
    x=lambda minute:55+minute/xmax*790
    y=lambda people:240-people/ymax*205
    svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 285" role="img" aria-label="候客曲线">']
    for i in range(5):
        value=ymax*i/4
        svg.append(f'<line x1="55" x2="845" y1="{y(value)}" y2="{y(value)}" stroke="#dce5e9"/><text x="45" y="{y(value)+4}" text-anchor="end" font-size="11" fill="#667a86">{value:.0f}</text>')
    for i in range(5):
        minute=xmax*i/4
        svg.append(f'<text x="{x(minute)}" y="265" text-anchor="middle" font-size="11" fill="#667a86">{clock(card,minute)[6:]}</text>')
    svg.append(f'<line x1="55" x2="845" y1="{y(limit)}" y2="{y(limit)}" stroke="#b75e5e" stroke-dasharray="5 4"/>')
    for r,color in [(baseline,'#94a7b2'),(row,'#117b80')]:
        points=' '.join(f'{x(t["minute"]-step):.3f},{y(t["queue_before"]):.3f}' for t in r['trace'])
        points+=f' {x(r["trace"][-1]["minute"]):.3f},{y(r["trace"][-1]["queue_after"]):.3f}'
        svg.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
    return ''.join(svg)+'</svg>'

def report_html(result):
    esc=lambda v:html.escape(str(v));c=result['card'];title=c.get('platform',{}).get('title',c['scenario_id'])
    statuses={'passed':'方案通过所列目标','failed_targets':'资源合法，但目标未全部通过','infeasible':'当前候选集合不可行','unresolved':'计算限时内未取得可行方案，不能认定无解'}
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+esc(title)+' · 验证报告</title>',
       '<style>body{font:15px/1.8 "Microsoft YaHei",sans-serif;max-width:1050px;margin:35px auto;color:#173348;padding:0 24px}h1{font-size:26px}h2{font-size:20px;margin-top:30px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:7px;border:1px solid #ccd9df;text-align:left}th{background:#edf4f5}.note{padding:14px;background:#f1f6f7}svg{width:100%;height:auto}@media print{button{display:none}body{margin:0;max-width:none}tr{break-inside:avoid}h2{break-after:avoid}}</style>',
       '<button onclick="window.print()">打印／另存为PDF</button><h1>'+esc(title)+'</h1>',
       '<p>'+esc(result['created_at'])+' · '+esc(VERSION)+' · '+esc(statuses[result['status']])+'</p>',
       '<div class="note">'+esc(result['evidence_note'])+' 使用段初进入／段末服务的离散模型，研究结论限于所列参数与进入过程。未完成过程的平均等待留空，不能以0表示。</div>',
       '<h2>事件与输入口径</h2><p>'+esc(c.get('platform',{}).get('notes',''))+'</p>',
       '<p>来源记录：'+esc(c.get('platform',{}).get('sources','未填写'))+'</p>',
       '<p>新增人数 '+esc(c['five_dimensions']['new_onward_passengers'])+'；初始候客 '+esc(sum(d['initial_queue'] for d in c['directions']))+'；预算 '+esc(c['parameters']['budget_yuan'])+'元；截止 '+esc(clock(c,c['parameters']['deadline_minutes']))+'。</p>']
    if result.get('audit'):
        a=result['audit']['plan'];parts.append('<p>费用 '+esc(a['cost_yuan'])+'元；公交 '+esc(a['bus_trips'])+'班，使用 '+esc(a['used_vehicles'])+'辆；出租预约 '+esc(a['taxi_reserved_people'])+'个服务名额。</p>')
        parts.append('<h2>候客过程</h2><p>青色为本次安排，灰色为仅基础服务，红虚线为全体候客上限；人数取每段服务前值。</p>')
        for row in result['audit']['profiles']:
            baseline=next(r for r in result['baseline']['profiles'] if r['profile_id']==row['profile_id'])
            parts.append('<h3>'+esc(row['label'])+'</h3>'+queue_svg(c,row,baseline))
    sol=result.get('solution')
    if sol:
        parts.append('<h2>求解状态</h2><table><tr><th>阶段</th><th>状态码</th><th>相对差距</th><th>秒</th></tr>')
        for k,label in [('phase_primary','主目标'),('phase_cost_tiebreak','费用择优'),('phase_fixed_plan_wait_refinement','固定资源等待整理'),('phase_fixed_plan_comfort_refinement','固定资源站立整理')]:
            phase=sol.get(k)
            if phase:parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [label,phase['status'],phase.get('relative_gap'),round(phase['seconds'],3)])+'</tr>')
        parts.append('</table><p>状态0为达到所设求解差距，1为达到时限，2为当前候选集合不可行。可行解不等于已证明精确最优。</p>')
    for filename,data in tables(result).items():
        if filename=='分时核算明细.csv':continue
        rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))));parts.append('<h2>'+esc(filename[:-4])+'</h2><table>')
        for i,row in enumerate(rows):
            tag='th' if i==0 else 'td';parts.append('<tr>'+''.join('<'+tag+'>'+esc(v)+'</'+tag+'>' for v in row)+'</tr>')
        parts.append('</table>')
    parts.append('<h2>检查与适用边界</h2><ul>')
    for note in result.get('diagnostics',[])+result['validation']['warnings']:parts.append('<li>'+esc(note)+'</li>')
    if result.get('current_queue_execution') is not None:parts.append('<li>同一预约在只看当前队列的执行器下：'+esc('所有过程通过' if all(r['all_targets_met'] for r in result['current_queue_execution']) else '有过程未通过，须使用所列条件服务策略或进一步改进执行规则')+'。</li>')
    parts.append('</ul><p>完整输入、服务过程、参数属性与代码版本哈希见同包JSON。真实事件背景不等于历史排班回放；平台没有自动认证真实改善率。</p></html>')
    return ''.join(parts).encode('utf-8')

def write_exports(folder,result):
    folder=Path(folder)
    contents={'输入情景卡.json':json.dumps(result['card'],ensure_ascii=False,indent=2).encode('utf-8'),
              '完整计算结果.json':json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8'),
              '验证报告.html':report_html(result),**tables(result)}
    contents['复现说明.txt']=('交科赛接续运输研究平台 '+VERSION+'\n将输入情景卡导入平台，使用完整计算结果中的运行设置重新计算。\n求解限时和求解器版本可能影响具体排班，按目标、约束和求解差距比较，不要求每个平局排班完全相同。\n原代码版本哈希、输入哈希及各过程完整数据见完整计算结果。\n输入来源由录入者声明，平台不自动认证真实效果；所有时间均相对输入开始时刻解释。\n').encode('utf-8')
    for name,data in contents.items():(folder/name).write_bytes(data)
    with zipfile.ZipFile(folder/'完整验证包.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in contents.items():archive.writestr(name,data)
    return list(contents)+['完整验证包.zip']
