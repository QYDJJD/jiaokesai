"""Public evidence constraints and identifiability checks, not event calibration.

The source inventory is an audited transcription. These checks catch misuse of
its scope, units, calendar and network role; they do not audit source databases.
"""
from pathlib import Path
from datetime import datetime, timedelta
import json
from grading_engine import grade_case, evaluate, profile

ROOT = Path(__file__).resolve().parents[2]
AUDIT = json.loads((ROOT / '02_数据与案例/公开证据登记-2026-10-11.json').read_text(encoding='utf-8'))
ROUTES = {r['id']: r for r in AUDIT['planned_bus_services']}
MEASURES = {m['id']: m for m in AUDIT['measurements']}


def window(route, operating_date, last_train_arrival=None):
    """Resolve the PLAN calendar only. A missing endpoint stays None."""
    if operating_date not in route['operating_dates']:
        return None
    day = datetime.fromisoformat(operating_date)
    start = None if route['start_clock'] is None else datetime.fromisoformat(operating_date + 'T' + route['start_clock'])
    rule = route['end_rule']
    if rule['kind'] == 'next_day_fixed':
        end = datetime.fromisoformat((day + timedelta(days=1)).date().isoformat() + 'T' + rule['clock'])
    elif rule['kind'] == 'same_day_fixed':
        end = datetime.fromisoformat(operating_date + 'T' + rule['clock'])
    else:
        end = None if last_train_arrival is None else datetime.fromisoformat(last_train_arrival) + timedelta(minutes=rule['minutes'])
    if start is not None and end is not None and end < start:
        raise ValueError('last train timing inconsistent with operating window')
    return start, end


checks = []


def check(name, condition, details):
    if not condition:
        raise AssertionError(name)
    checks.append({'name': name, 'pass': True, 'details': details})


first = [r for r in ROUTES.values() if r['role'] == 'HONGQIAO_FIRST_LEG_CANDIDATE']
downstream = [r for r in ROUTES.values() if r['role'] == 'DOWNSTREAM_FEEDER']
check('12线路的拓扑分工', len(first) == 8 and len(downstream) == 4,
      {'first_leg_planned_lines': 8, 'downstream_planned_lines': 4, 'note': '线路数不是运力率；纠正把4条下游接驳算作虹桥直发'})
check('4条下游线路不能直接给虹桥队列服务', all(not r['hongqiao_origin_capacity_eligible'] for r in downstream),
      {'origins': [r['origin'] for r in downstream]})
check('12条计划均未被补成有效能力或实绩', all(r['effective_people_per_hour'] is None and r['executed_trips'] is None and r['passengers'] is None for r in ROUTES.values()),
      {'source_role': 'PLAN', 'availability_guarantee': False})

custom = ROUTES['BUS-DZ1']
interval = window(custom, '2026-10-06')
check('定制窗口归凌晨自然日', interval == (datetime(2026,10,6),datetime(2026,10,6,4,30)) and window(custom,'2026-10-05') is None,
      {'start': interval[0].isoformat(), 'end': interval[1].isoformat(), 'not_oct_5_morning': True})
check('末日窗口不能续到次日凌晨', window(custom,'2026-10-08')[1] == datetime(2026,10,8,4,30) and window(custom,'2026-10-09') is None,
      {'last_custom_window_end': '2026-10-08T04:30:00'})
conventional = window(ROUTES['BUS-R5'],'2026-10-07')
check('常规延时跨日及未知起点', conventional == (None,datetime(2026,10,8,4,30)),
      {'start': None, 'last_end': conventional[1].isoformat(), 'note': '原末班时刻未取得；不虚构完整连续供给'})
feeder = ROUTES['BUS-DZ321']
check('接驳终点未知不解释为永久可用', window(feeder,'2026-10-05') == (datetime(2026,10,5,22,30),None),
      {'end': None, 'meaning': 'UNKNOWN_LAST_TRAIN_ARRIVAL; NOT_UNLIMITED_SERVICE'})
example_end = window(feeder,'2026-10-05','2026-10-05T23:50:00')[1]
check('接驳15分钟跟随本地轨交到达时点', example_end == datetime(2026,10,6,0,5),
      {'hypothetical_last_train_arrival': '2026-10-05T23:50:00', 'derived_end': example_end.isoformat(), 'actual_observation': False})

legacy = AUDIT['legacy_shared_service_reference']
check('历史多线共用01号站位不设三份独立容量', len(legacy['routes']) == 3 and legacy['shared_node'] == '虹桥东交通中心01号停车位' and legacy['shared_capacity_people_per_hour'] is None,
      {'routes': [r['id'] for r in legacy['routes']], 'unknown_joint_capacity': True, 'not_actual_simultaneous_activation': True})
check('2022配车与2025设施不回填2023或2026资源', legacy['network_version'] == 2022 and legacy['current_2026_committed_inventory'] is None and MEASURES['M-TAXI-UPPER']['network_version'] == 2025,
      {'year_specific_only': True})
check('辆每小时和车次不能直接作人每小时', MEASURES['M-TAXI-UPPER']['unit'] == 'vehicles_per_hour' and MEASURES['M-E02-TAXI']['unit'] == 'vehicle_trips' and 'actual_available_people_per_hour' in MEASURES['M-TAXI-UPPER']['not_as'],
      {'missing_conversion': ['actual passengers per vehicle','existing occupation','directions','available vehicles and windows']})
check('首车规定到位不代替H或全部生效', MEASURES['M-FIRST-BUS']['quantity'] == 'normative_first_vehicle_arrival_after_receipt' and 'normative_H' in MEASURES['M-FIRST-BUS']['not_as'],
      {'normative_first_vehicle_minutes':15,'measured_all_vehicle_activation':None})
check('金山卫阈值不作为虹桥上限', MEASURES['M-JINSHAN']['location'] == '金山卫站' and 'Hongqiao_holding_K' in MEASURES['M-JINSHAN']['not_as'],
      {'other_station_values':[300,600,1000],'Hongqiao_K':None})
check('多枢纽实绩不归给虹桥单独', len(MEASURES['M-MULTIHUB']['locations']) == 3 and 'Hongqiao_only_supply' in MEASURES['M-MULTIHUB']['not_as'],
      {'multi_hub_added_trains':56,'reported_passenger_scale':'33000余','Hongqiao_allocation':None})
e01_gap = (datetime.fromisoformat(MEASURES['M-E01-CLEAR']['value']) - datetime.fromisoformat(MEASURES['M-E01-Q']['window'][1])).total_seconds()/60
check('E01报道时刻差不是服务目标', e01_gap == 10 and AUDIT['goal_policy']['H_actual'] is None,
      {'reported_timestamp_gap_minutes':e01_gap,'cohort_last_arrival_confirmed':False,'normative_H':None})
check('机场多目的转送和准备安置不补需求或K', MEASURES['M-E04-BUS']['people'] is None and 'holding_limit_K' in MEASURES['M-E03-SHELTER']['not_as'],
      {'pudong_transfer_vehicles':16,'pudong_multi_destination_trips':31,'Hongqiao_demand':None,'shelter_actual_occupants':None})

missing_runs = []
for event in AUDIT['event_gap_audit']:
    result = grade_case({'known':event['calculation_ready']})
    missing_runs.append({'event':event['event_id'],'grade':result['grade']})
check('4个真实卡缺参时拒绝数值分级', all(r['grade']=='X-DATA' for r in missing_runs), missing_runs)

# An independent analytic requirement checks four possible hidden resource
# inventories. These are hypothetical countermodels, not imputed event values.
q,d,k,h,b0 = 2000,2,1000,1,0
minimum = max((b0+q)/(d+h),(b0+q-k)/d,0)
completions = []
for factor,expected in [(1.4,'F0'),(.8,'F1'),(.4,'F2'),(.2,'F3')]:
    capacities = [500*factor,1000*factor,2000*factor]
    analytic = next(('F'+str(i) for i,c in enumerate(capacities) if c>=minimum),'F3')
    calculated = grade_case({'q':q,'d':d,'b0':b0,'factor':factor,'p':1},k,h)['grade']
    if calculated != analytic or calculated != expected:
        raise AssertionError('independent resource ambiguity comparison')
    completions.append({'hypothesis_only':True,'resource_rates':capacities,'grade':calculated,'analytic_grade':analytic})
check('相同人数历时和目标仍不能识别资源层', {r['grade'] for r in completions} == {'F0','F1','F2','F3'},
      {'known_hypothetical_q':q,'d':d,'k':k,'h':h,'rate_requirement':minimum,'resource_completions':completions,'note':'不是4个真实事件的可行等级集合，证明缺资源数据无法唯一判级'})

# A serial path must transport the same people across both legs. This min-cut
# upper bound is independent of the queue evaluator and shows why rates add
# only for parallel alternatives, not consecutive services.
upstream,downstream_rate = 600,400
check('串联后续接驳不能与上游运力相加', min(upstream,downstream_rate) == 400 and upstream+downstream_rate == 1000,
      {'hypothesis_only':True,'throughput_upper_bound':400,'incorrect_sum':1000,'timing_travel_and_space_would_add_constraints':True})

beta,kappa,eta = .1,.2,.5
gamma = max((1+beta)/(1+eta),1+beta-kappa,0)
normalized_case = {'q':1000,'d':2,'b0':100,'k':200,'h':1}
rate = gamma*normalized_case['q']/normalized_case['d']
boundary_runs=[]
for c,expected in [(rate-1,False),(rate,True),(rate+1,True)]:
    row=evaluate(profile(1000,2,'uniform'),[(0,None,c)],100,3)
    passed=row['peak_people']<=200+1e-8 and row['clear_h'] is not None and row['clear_h']<=3+1e-8
    if passed!=expected:raise AssertionError('normalized boundary')
    boundary_runs.append({'rate':c,'peak':row['peak_people'],'clear_h':row['clear_h'],'pass':passed})
check('不指定实际K/H也能检验参数化门槛', abs(gamma-.9)<1e-9,
      {'hypothesis_only':True,'beta':beta,'kappa':kappa,'eta':eta,'gamma_min':gamma,'people_per_hour':rate,'boundary_runs':boundary_runs,'prerequisites':'Q>0,D>0,B0<=K, uniform inflow, constant eligible continuous supply'})

out={'version':'CHECK-PUBLIC-01','date':'2026-10-11','checks':len(checks),'passed':len(checks),'source_records':len(AUDIT['sources']),'source_records_are_not_independent_events':True,'real_event_gap_audits':4,'numeric_actual_grades':0,'independent_resource_completions':4,'normalized_boundary_comparisons':3,'validation_scope':'audited transcription, public constraints, missing-data gate and analytic identifiability; not real classification accuracy','results':checks}
(ROOT/'06_实验验证/分级方法验证/公开证据约束验证结果.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k!='results'},ensure_ascii=False))
