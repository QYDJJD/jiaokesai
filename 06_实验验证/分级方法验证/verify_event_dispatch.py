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
PREPARATION_MINUTES = 60
INFORMATION_LEAD_MINUTES = 92

def arrivals(q, shape):
    q = F(q)
    if shape == '均匀进入': return [(F(0), F(6), q/6)]
    if shape == '前段集中': return [(F(0), F(2), q/3), (F(2), F(6), q/12)]
    if shape == '后段集中': return [(F(0), F(4), q/12), (F(4), F(6), q/3)]
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
    print(json.dumps({'保障结果':grade(main_rows),'计算过程数':CHECKS,'主要结果':compact,
        '敏感性':sensitivity,'基础能力下降':grade(reduced)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
