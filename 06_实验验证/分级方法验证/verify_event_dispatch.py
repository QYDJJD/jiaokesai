"""Event-grounded conditional schedules; never a replay of historical dispatch.

All queue demands, capacities, bus offers, goals and future-arrival scenarios
below are declared synthetic. Twenty bus departures and the time window are
inspired by the public event, but neither usable seats nor departure times
are observed. Bus boarding is approximated as continuous over ten minutes;
completion means leaving the waiting area with compatible transport obtained.
"""
from pathlib import Path
from fractions import Fraction as F
import json, math
from grading_engine import evaluate
from independent_reference import CumulativeQueue

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'https://jtw.sh.gov.cn/xydt/20231226/6f4ed792491949fb871c7237e4d636ff.html'
NAMES = ['现有保障可达标', '需加强保障', '需联合保障', '已列方案均未达标']
SHAPES = ['均匀进入', '前段集中', '后段集中']
K = F(1000)
LIMIT = F(2000)
CHECKS = 0
DIMENSION_CHECKS = 0
PREPARATION_MINUTES = 60
INFORMATION_LEAD_MINUTES = 92

def arrivals(q, shape, duration=6):
    q, d = F(q), F(duration)
    if shape == '均匀进入': return [(F(0), d, q/d)]
    if shape == '前段集中': return [(F(0), d/3, 2*q/d), (d/3, d, q/(2*d))]
    if shape == '后段集中': return [(F(0), 2*d/3, q/(2*d)), (2*d/3, d, 2*q/d)]
    raise ValueError(shape)

def bus_segments(style):
    if style == '平均排班':
        departures = [F(3,10)*(i+1) for i in range(20)]
    else:
        departures = [F(i,5) for i in range(1,11)] + [F(4)+F(i,5) for i in range(1,11)]
    # 40 places / (10/60 h) = 240 people per hour, in each boarding window.
    return departures, [(t-F(1,6), t, F(240)) for t in departures]

def plan(layer, style, base=1200):
    extra = F(layer*250)
    departures, buses = bus_segments(style)
    reserve = []
    if extra:
        if style == '平均排班': reserve = [(F(0), F(6), extra*F(2,3))]
        else: reserve = [(F(0), F(2), extra), (F(4), F(6), extra)]
    effective_start = max(F(0), F(PREPARATION_MINUTES-INFORMATION_LEAD_MINUTES,60))
    assert all(a >= effective_start for a,b,r in reserve)
    caps = [(F(0), None, F(base))] + reserve + buses
    points = sorted({F(0), *[t for a,b,r in caps for t in (a,b) if t is not None]})
    for a,b in zip(points,points[1:]):
        t = (a+b)/2
        offered = sum(r for x,y,r in caps if x <= t and (y is None or t < y))
        assert offered <= LIMIT, 'shared boarding bound violated'
    assert len(departures) == len(set(departures)) == 20
    assert all(F(0) <= a < b <= F(6) for a,b,r in buses)
    assert sum((b-a)*r for a,b,r in buses) == 800
    assert sum((b-a)*r for a,b,r in reserve) == layer*1000
    assert all(b <= c for (_,b,_),(c,_,__) in zip(buses,buses[1:]))
    return {'层次':layer,'排班':style,'公交发车小时':departures,
            '公交预约名额':800,'增援预约服务量':layer*1000,
            '出租车增援时段':reserve,'供给':caps}

def floats(segments): return [(float(a),None if b is None else float(b),float(r)) for a,b,r in segments]

def run(q, allowance_minutes, p):
    global CHECKS
    deadline = F(6) + F(allowance_minutes,60)
    records = []
    for shape in SHAPES:
        a = arrivals(q,shape)
        primary = evaluate(floats(a),floats(p['供给']),0,float(deadline),True)
        independent = CumulativeQueue(a,p['供给'],0).result(deadline)
        for key in ['peak_people','clear_h','residual_at_deadline_people','arrived_people','served_people','unserved_people']:
            x,y = primary[key],independent[key]
            assert (x is None and y is None) or (x is not None and y is not None and abs(x-float(y)) < 1e-6), (shape,key,x,y)
        # Conservation and forward completion under the declared continuous approximation.
        assert abs(primary['arrived_people']-q) < 1e-6
        assert abs(primary['served_people']+primary['unserved_people']-q) < 1e-6
        passed = independent['peak_people'] <= K and independent['clear_h'] is not None and independent['clear_h'] <= deadline
        CHECKS += 1
        records.append({'到达过程':shape,'通过':passed,
            '峰值候客人数':float(independent['peak_people']),
            '完成小时':float(independent['clear_h']) if independent['clear_h'] is not None else None,
            '截止未完成人数':float(independent['residual_at_deadline_people']),
            '个人最长等待分钟':primary['max_wait_h']*60,
            '平均等待分钟':primary['total_waiting_people_h']/q*60,
            '候客曲线':primary['queue_trace']})
    return {'层次':p['层次'],'排班':p['排班'],'全部通过':all(r['通过'] for r in records),'逐过程':records}

def lower_layer_bounds(q, allowance_minutes, base=1200):
    """Upper capacity bounds apply to any timing under the stated bay/window caps.

    At most one bus boarding window at a time (240/h); all bus windows and
    reinforcements must end by hour 6. Using 480 places in either two-hour
    burst independently is an optimistic upper bound, even though one fixed
    plan may not use 480 in both. Failure under this upper bound excludes the
    layer without an exhaustive departure-time search.
    """
    q=F(q); h=F(allowance_minutes,60); base=F(base)
    burst=q*F(2,3)
    rows=[]
    for j in range(3):
        cap=base+j*250
        early_unserved=max(F(0),burst-(2*cap+480))
        possible_by_deadline=2*cap+480+h*base
        rows.append({'层次':j,'集中两小时进入人数':float(burst),
            '前段结束时至少候客人数':float(early_unserved),
            '后段至截止最多可服务人数':float(possible_by_deadline),
            '可排除该层次':early_unserved>K or possible_by_deadline<burst})
    return rows

def grade(rows):
    j = min((r['层次'] for r in rows if r['全部通过']),default=3)
    return NAMES[j]

def checked_dimension_plan(q, duration, p, allowance_minutes=30):
    """Check a changed input without changing the original 180 calculations.

    Peak, completion, residual and conservation use both queue implementations.
    Waiting uses the current FIFO implementation, as in the original results.
    This evaluates the stated schedule; it does not claim schedule optimality.
    """
    global DIMENSION_CHECKS
    deadline = F(duration) + F(allowance_minutes, 60)
    records = []
    for shape in SHAPES:
        a = arrivals(q, shape, duration)
        primary = evaluate(floats(a), floats(p['供给']), 0, float(deadline), True)
        independent = CumulativeQueue(a, p['供给'], 0).result(deadline)
        for key in ['peak_people', 'clear_h', 'residual_at_deadline_people',
                    'arrived_people', 'served_people', 'unserved_people']:
            x, y = primary[key], independent[key]
            assert (x is None and y is None) or (x is not None and y is not None
                    and abs(x-float(y)) < 1e-6), (shape, duration, key, x, y)
        assert abs(primary['arrived_people']-q) < 1e-6
        assert abs(primary['served_people']+primary['unserved_people']-q) < 1e-6
        passed = independent['peak_people'] <= K and independent['clear_h'] is not None and independent['clear_h'] <= deadline
        DIMENSION_CHECKS += 1
        records.append({'到达过程': shape, '通过': passed,
            '峰值候客人数': float(independent['peak_people']),
            '完成小时': float(independent['clear_h']) if independent['clear_h'] is not None else None,
            '截止未完成人数': float(independent['residual_at_deadline_people']),
            '个人最长等待分钟': primary['max_wait_h']*60,
            '平均等待分钟': primary['total_waiting_people_h']/q*60})
    return {'层次': p['层次'], '排班': p['排班'],
            '全部通过': all(r['通过'] for r in records), '逐过程': records}

def dimension_checks(main_rows, plans, sensitivity, reduced, bounds):
    """Single-input checks demonstrate what each dimension changes.

    They remain synthetic conditional checks, not historic counterfactuals.
    Only taxi reinforcements in the notice check need 60-minute preparation;
    the existing base supply and bus offers are explicitly left available.
    Duration changes only arrival times and the cohort deadline. The physical
    resource windows, promises and facility limits retain their original values.
    """
    compact = lambda row: {**row, '逐过程': [
        {k: v for k, v in r.items() if k != '候客曲线'} for r in row['逐过程']]}
    notices = []
    for lead in [92, 0]:
        p = plans[5]
        ready = max(F(0), F(PREPARATION_MINUTES-lead, 60))
        reserved = p['出租车增援时段']
        executable = [(max(a, ready), b, rate) for a, b, rate in reserved if max(a, ready) < b]
        usable = sum((b-a)*rate for a, b, rate in executable)
        modified = {**p, '供给': [p['供给'][0]] + executable + bus_segments('集中窗口排班')[1]}
        result = compact(main_rows[5]) if lead == 92 else checked_dimension_plan(6000, 6, modified)
        notices.append({'信息提前量分钟': lead,
            '出租增援最早生效小时': float(ready),
            '原计划增援预约服务量': 2000,
            '沿用原排班可兑现的增援服务量': float(usable),
            '无法兑现的原计划增援服务量': float(2000-usable),
            '所给排班结果': result})
    assert notices[1]['无法兑现的原计划增援服务量'] == 500
    assert notices[1]['所给排班结果']['全部通过']

    uniform_existing = next(r for r in main_rows[1]['逐过程'] if r['到达过程'] == '均匀进入')
    assert uniform_existing['通过']
    assert bounds[0]['可排除该层次'] and bounds[1]['可排除该层次']

    short_rows = [checked_dimension_plan(6000, 3, p) for p in plans]
    # A concentrated hour contains 4000 people. One bus bay offers at most
    # 240/h and joint-tier taxi supply at most 1200+500/h. Even granting all
    # these simultaneous maxima, at least 4000-1940 people must wait.
    max_hourly = F(1200+500+240)
    inevitable_peak = F(4000)-max_hourly
    assert inevitable_peak == 2060 and inevitable_peak > K
    assert grade(short_rows) == NAMES[3]
    duration_bound = {'集中一小时进入人数': 4000,
        '联合层一小时乐观服务上限': float(max_hourly),
        '任意排班至少出现的候客人数': float(inevitable_peak),
        '候客上限': float(K), '全部参考层次可排除': True,
        '适用条件': '基础服务至多1200人每小时、出租增援至多500人每小时、一处公交登乘设施至多240人每小时；实际共享上限2000人每小时未进一步收紧该上界'}
    assert all(b['可排除该层次'] for b in lower_layer_bounds(6000, 30, 900))
    # Space-only pressure check: no service can precede passengers' arrival.
    # A joint-tier schedule can serve at most the shared-bay limit through
    # hour 6, then only the unchanged 1200/h base supply until the deadline.
    constrained_shared_limit = F(1500)
    space_upper = 2*constrained_shared_limit + F(1,2)*1200
    space_shortfall = F(4000)-space_upper
    assert space_upper == 3600 and space_shortfall == 400
    space_bound = {'原共用上客上限人数每小时': float(LIMIT),
        '改变后的共用上客上限人数每小时': float(constrained_shared_limit),
        '保持不变': '新增6000人、持续6小时、三种过程、基础1200人每小时、公交与出租增援原参考资源、最后进入后30分钟时限；仅改变共享设施处理上限',
        '后段两小时进入人数': 4000,
        '后段两小时至截止最多可服务人数': float(space_upper),
        '到截止至少未完成人数': float(space_shortfall),
        '全部参考层次可排除': True,
        '界限依据': '后段两小时即使持续用满共享上限也最多服务3000人；05:00后公交与增援窗口已结束，30分钟基础服务最多再服务600人，总计3600人，少于4000人',
        '性质及范围': '该1500人每小时限制为声明的空间压力假设，不是虹桥实测设施能力；结论适用于原服务窗口与候客群体，改变设施或窗口须重新计算'}
    population = [{k: v for k, v in x.items() if k in ['新增待接续人数', '保障结果']}
                  for x in sensitivity if x['最后进入后的服务时限分钟'] == 30]
    return {
        '检查性质': '在真实事件启发的声明假设内，一次改变一个五维输入；不估计当年真实效果，不将候选排班失败当作所有排班失败',
        '信息提前量': {'保持不变': '需求、三种到达过程、持续时间、公交及基础服务、原出租增援排班和目标；只改变新增出租增援的可生效时点',
            '准备假设': '仅新增出租增援需要60分钟准备；既有基础服务和公交供给不受本次信息提前量变化影响',
            '执行规则': '沿用原排班，删除早于增援实际生效时点的服务，不在本检查中另排补偿服务；预约总量仍为2000，但可兑现量可能减少',
            '比较': notices,
            '决策变化': '信息到达较晚时，需更正首段可兑现供给及候客预期，不能沿用92分钟提前量下的200人峰值结论；本检查的0分钟情况仍通过，不认定为必须升档'},
        '到达不确定性': {'保持不变': '新增6000人、持续6小时、资源层次及服务目标',
            '只检查均匀进入': {'保障结果': NAMES[0], '所给现有层排班结果':
                {k: v for k, v in uniform_existing.items() if k != '候客曲线'}},
            '检查三种可能过程': {'保障结果': grade(main_rows), '联合层通过方案': compact(main_rows[5]),
                '较低层排除界限': bounds},
            '决策变化': '从只按平均输入安排现有资源，改变为事先准备可覆盖前段或后段集中进入的联合资源；三种过程不代表真实发生概率'},
        '旅客进入持续时间': {'保持不变': '新增6000人、三种形状及比例、基础能力、公交和增援物理窗口0至6小时、预约总量、设施上限及最后进入后的30分钟时限',
            '六小时': {'保障结果': grade(main_rows), '联合层通过方案': compact(main_rows[5])},
            '三小时': {'保障结果': grade(short_rows), '所给六个候选安排结果': short_rows,
                '任意排班排除界限': duration_bound},
            '决策变化': '人数不变但进入期压缩，原联合资源也无法满足候客上限；必须改变已列资源或服务结构，而非继续沿用六小时情景的等级结论'},
        '新增待接续人数': {'保持不变': '持续6小时、三种到达过程、资源及30分钟服务时限',
            '比较': population,
            '决策变化': '3000人准备现有保障即可，6000人需联合保障，9000人超出已列参考资源；既避免准备不足，也避免所有情景一律申请最高档'},
        '方式与空间服务状态': {'保持不变': '新增6000人、三种到达过程、持续6小时、公交与新增出租资源、设施上限和目标',
            '基础服务每小时1200人': {'保障结果': grade(main_rows), '联合层通过方案': compact(main_rows[5])},
            '基础服务每小时900人': {'保障结果': grade(reduced), '联合层原排班结果': compact(reduced[5]),
                '任意排班排除界限': lower_layer_bounds(6000, 30, 900)},
            '共享设施能力下降的独立检查': space_bound,
            '决策变化': '同样人数和到达过程下，基础服务减弱或共享上客能力下降均可使参考联合层不足；前者需补充实际服务能力，后者需解除设施瓶颈或改变服务窗口，不能只增加车辆承诺',
            '证明范围': '本项分别检查基础服务能力变化和共享设施处理上限变化；方向不适配、方式停运等其他服务状态须按各自约束另核，不能由本项结果宣称都已定量验证'},
        '验证范围': {'新增过程计算数': DIMENSION_CHECKS,
            '峰值完成截止剩余及人数守恒': '现行队列与独立累计曲线逐项核对，一致',
            '等待指标': '按现行先到先服务程序计算，未另设个人等待门槛',
            '界限用途': '持续时间三小时、基础能力下降及共享设施受限的整体不足有任意排班容量界限；信息提前量仅评价裁减后的明确原排班，不证明重新排班后的最优结果',
            '结论范围': '证明五个维度各自对应必要的决策检查，不证明五维数量唯一、一般情景下始终优于其他方法或优于当年实际处理'}
    }

def main():
    plans = [plan(layer,style) for layer in range(3) for style in ['平均排班','集中窗口排班']]
    main_rows = [run(6000,30,p) for p in plans]
    bounds=lower_layer_bounds(6000,30)
    assert bounds[0]['可排除该层次'] and bounds[1]['可排除该层次']
    assert bounds[1]['后段至截止最多可服务人数']==3980
    sensitivity=[]
    for q in [3000,6000,9000]:
        for h in [15,30,45]:
            rows = main_rows if (q,h)==(6000,30) else [run(q,h,p) for p in plans]
            j=NAMES.index(grade(rows)); bs=lower_layer_bounds(q,h)
            assert all(b['可排除该层次'] for b in bs[:j]), (q,h,'lower tier not excluded')
            sensitivity.append({'新增待接续人数':q,'最后进入后的服务时限分钟':h,'保障结果':grade(rows),
                '联合平均排班通过':rows[4]['全部通过'],'联合集中排班通过':rows[5]['全部通过']})
    reduced=[run(6000,30,plan(j,s,900)) for j in range(3) for s in ['平均排班','集中窗口排班']]
    assert grade(main_rows)=='需联合保障'
    assert not main_rows[4]['全部通过'] and main_rows[5]['全部通过']
    assert grade(reduced)=='已列方案均未达标'
    assert all(b['可排除该层次'] for b in lower_layer_bounds(6000,30,900))
    reduced_summary={'基础服务人数每小时':900,'保障结果':grade(reduced),
        '联合集中排班':reduced[5]}
    dimensions = dimension_checks(main_rows, plans, sensitivity, reduced, bounds)
    data={'标题':'2023年虹桥晚点保障：真实事件基础上的条件调度验证',
        '证据性质':'事件真实；定量需求、资源能力、服务目标与排班全部为研究假设；非历史回放',
        '真实来源':SOURCE,
        '原处理记录':{'指令时点':'2023-12-14 21:28','报道影响窗口':'23:00至次日05:00',
            '受影响旅客':10008,'受影响列车':28,'轨道末端':'次日00:30','轨道加开班次':3,
            '轨道运送人次':273,'两条夜宵公交班次':20,'两条夜宵公交运送人次':32,
            '报道出租平均等待分钟范围':[5,15],'报道疏散完成':'次日05:10'},
        '未核字段':['真实新增接续需求','初始候客','分时与分方向进入','实际剩余能力','各资源生效时点','个人等待分布','实际响应级别'],
        '示范五维':{'信息提前量分钟':92,'信息提前量性质':'将指令时点作为示范决策起点、假设首批23:00进入；非当年真实提前量',
            '到达不确定性':SHAPES,'旅客进入持续时间小时':6,'新增待接续人数':6000,
            '方式与空间服务状态':'真实轨道末端保留；计算仅用假设兼容的地面候客群体，初始候客0，基准服务1200人/小时，20次公交预约各40人，增援分层，共用上客界限2000人/小时'},
        '示范目标':{'候客人数上限':1000,'最后进入后的服务时限分钟':30,'示范完成截止':'次日05:30'},
        '研究模型':'一处公交登乘设施一次一班，十分钟内连续登乘近似＋出租连续服务；公交与增援窗口截至05:00，基础服务在05:00后持续。同一兼容群体按先到先服务；非完整车辆、路网、返程周转或旅客选择模型',
        '参考保障结果':grade(main_rows),'候选安排':plans,'主要结果':main_rows,
        '目标与人数敏感性':sensitivity,'基础能力下降检查':reduced_summary,'较低层排除界限':bounds,
        '逐维决策检查': dimensions,
        '验证':{'计算过程数':CHECKS,'独立累计曲线核对':'全部一致','人数守恒':'通过','预约总量与共享限制':'通过',
            '同一个事先方案覆盖三种过程':'通过','较低保障层任意排班排除':'声明服务窗口与单公交登乘设施条件下的容量界限通过',
            '最优性范围':'保障层次在声明资源边界内可确定；具体排班仅比较六个候选，未证明连续最优或五维数量唯一'}}
    def serial(x):
        if isinstance(x,F):return float(x)
        raise TypeError(type(x))
    target=Path(__file__).with_name('真实事件条件调度验证结果.json')
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=serial)+'\n',encoding='utf-8')
    compact=[]
    for x in main_rows:
        compact.append({k:v for k,v in x.items() if k!='逐过程'} | {'逐过程':[{k:v for k,v in r.items() if k!='候客曲线'} for r in x['逐过程']]})
    print(json.dumps({'保障结果':grade(main_rows),'计算过程数':CHECKS,'新增逐维过程计算数':DIMENSION_CHECKS,
        '主要结果':compact,'敏感性':sensitivity,'基础能力下降':grade(reduced),
        '信息提前量检查':dimensions['信息提前量']['比较'],
        '持续时间缩短界限':dimensions['旅客进入持续时间']['三小时']['任意排班排除界限']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
