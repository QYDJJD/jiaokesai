"""Rebuild the optimized plans, independent audits, comparison CSVs and chart."""
from pathlib import Path
from copy import deepcopy
import json
import csv
import datetime as dt
import sys
import time
import importlib.metadata
import hashlib
from model import ROOT, solve
from simulate import audit_solution, average_plan, causal_greedy, replay, check_plan

RESULT_DIR=ROOT/'06_实验验证/优化模型验证'
PLAN_DIR=ROOT/'05_协同调度/优化模型输出'
CARD_PATH=ROOT/'03_情景库/模型输入卡-虹桥降雪背景.json'


def table(path,rows):
    if not rows:return
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def clock(card,minute):
    if minute is None:return '核对窗口内未完成'
    when=dt.datetime.fromisoformat(card['parameters']['start_time'])+dt.timedelta(minutes=minute)
    return when.strftime('%m-%d %H:%M')


def summarize(case):
    r=case['solution'];a=case.get('audit')
    return {'实验':case['label'],'预算元':case['card']['parameters']['budget_yuan'],
            '站立人分钟上限':case['card']['parameters']['standing_person_minutes_limit'],
            '状态':('已取得并核对可行解' if a else ('当前候选集合不可行' if r['phase_primary']['status']==2 else '未证可行或不可行')),
            '增量费用元':round(a['plan']['cost_yuan'],3) if a else None,
            '最大候客人数':round(max(v['peak_queue_people'] for v in a['profiles']),3) if a else None,
            '最坏平均等待分钟':round(max(v['mean_wait_minutes'] for v in a['profiles']),5) if a else None,
            '最坏站立人分钟':round(max(v['standing_person_minutes'] for v in a['profiles']),3) if a else None,
            '最晚完成':clock(case['card'],max(v['completion_minutes'] for v in a['profiles'])) if a else None,
            '首阶段相对差距':r['phase_primary']['relative_gap'],
            '首阶段求解秒':round(r['phase_primary']['seconds'],3)}


def write_chart(main,baselines):
    # SVG with explicit axes, labels and source note; no external plotting package.
    from html import escape
    w,h=960,620;left,top,right,bottom=75,80,35,80;pw=w-left-right;ph=h-top-bottom
    rows=main['audit']['profiles'];peak=max([r['peak_queue_people'] for r in rows]+[r['peak_queue_people'] for r in baselines]);ymax=max(1000,int(peak/250+1)*250)
    xmax=480;parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="Microsoft YaHei,SimSun,sans-serif" fill="#233b45">',
        '<text x="75" y="30" font-size="21">虹桥降雪背景合成实验：候客过程对照</text>',
        '<text x="75" y="54" font-size="13">实线为共同资源优化；灰虚线为基础服务；候客以每段服务前人数表示</text>']
    def x(v):return left+v/xmax*pw
    def y(v):return top+ph-v/ymax*ph
    for value in range(0,ymax+1,250):
        parts.append(f'<path d="M{left},{y(value):.2f}H{w-right}" stroke="#dbe4e8"/><text x="{left-12}" y="{y(value)+4:.2f}" text-anchor="end" font-size="12">{value}</text>')
    for value in range(0,481,60):
        parts.append(f'<text x="{x(value):.2f}" y="{top+ph+24}" text-anchor="middle" font-size="12">{(23+value//60)%24:02d}:00</text>')
    parts.append(f'<path d="M{left},{y(1000):.2f}H{w-right}" stroke="#b64343" stroke-dasharray="7 5"/><text x="{left+5}" y="{y(1000)-7:.2f}" font-size="12" fill="#a33">研究候客上限1000人</text>')
    for r in baselines:
        points=' '.join(f"{x(v['minute']-10):.2f},{y(v['queue_before']):.2f}" for v in r['trace'])
        points+=f" {x(r['trace'][-1]['minute']):.2f},{y(r['trace'][-1]['queue_after']):.2f}"
        parts.append(f'<polyline points="{points}" fill="none" stroke="#a5adb1" stroke-width="1.2" stroke-dasharray="4 4"/>')
    palette=['#217a9a','#c46b30','#3d8a5b','#895ca5']
    for i,r in enumerate(rows):
        points=' '.join(f"{x(v['minute']-10):.2f},{y(v['queue_before']):.2f}" for v in r['trace'])
        points+=f" {x(r['trace'][-1]['minute']):.2f},{y(r['trace'][-1]['queue_after']):.2f}"
        parts.append(f'<polyline points="{points}" fill="none" stroke="{palette[i%4]}" stroke-width="2.2"/>')
        parts.append(f'<text x="{100+i*205}" y="{h-36}" font-size="13" fill="{palette[i%4]}">{escape(r["label"])}</text>')
    parts.extend(['<text x="18" y="80" font-size="12">候客人数</text>',
                  '<text x="75" y="607" font-size="11">参数为研究假设；不是当年队列还原。基准可延伸至07:00，优化主目标截止为05:30。</text>','</g></svg>'])
    (PLAN_DIR/'候客过程对照.svg').write_text('\n'.join(parts),encoding='utf-8')


def run(seconds=35):
    RESULT_DIR.mkdir(exist_ok=True);PLAN_DIR.mkdir(exist_ok=True)
    base=json.loads(CARD_PATH.read_text(encoding='utf-8'));cases=[]
    specifications=[
        ('main','四过程共同方案：预算24000、站立上限3000',{'budget_yuan':24000},'wait'),
        ('nominal','仅均匀进入',{},'wait'),
        ('low_budget','四过程：预算18000',{'budget_yuan':18000},'wait'),
        ('high_budget','四过程：预算30000',{'budget_yuan':30000},'wait'),
        ('seated','四过程：公交全员有座政策',{'standing_person_minutes_limit':0},'wait'),
        ('seated_higher_budget','四过程：公交全员有座、预算30000',{'standing_person_minutes_limit':0,'budget_yuan':30000},'wait'),
        ('looser_comfort','四过程：站立上限12000',{'standing_person_minutes_limit':12000},'wait'),
        ('minimum_cost','四过程：最小可行预约费用',{'budget_yuan':30000},'cost'),
        ('late_notice','四过程：无提前信息',{'budget_yuan':30000},'wait'),
        ('restricted_space','四过程：共享上客1500人每小时',{'shared_service_people_per_hour':1500,'budget_yuan':30000},'wait'),
        ('existing_package','新目标版本：现有参考包',{'taxi_total_blocks':0,'taxi_max_blocks_per_step':0,'budget_yuan':30000},'cost'),
        ('strengthened_package','新目标版本：加强参考包',{'taxi_total_blocks':100,'taxi_max_blocks_per_step':4,'budget_yuan':30000},'cost'),
    ]
    for key,label,changes,objective in specifications:
        card=deepcopy(base);card['parameters'].update(changes)
        if key=='nominal':card['arrival_profiles']=card['arrival_profiles'][:1]
        if key=='late_notice':card['five_dimensions']['information_lead_minutes']=0
        started=time.perf_counter();result=solve(card,seconds=seconds,objective=objective)
        case={'id':key,'label':label,'card':card,'solution':result}
        if result['has_solution']:case['audit']=audit_solution(card,result)
        cases.append(case)
        # Checkpoint after each case to preserve completed work on interruption.
        (RESULT_DIR/'优化实验结果.json').write_text(json.dumps({'cases':cases},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'实验':key,'状态':result['phase_primary']['status'],'耗时秒':round(time.perf_counter()-started,2),
                          '费用':case.get('audit',{}).get('plan',{}).get('cost_yuan'),
                          '最坏平均等待':max((r['mean_wait_minutes'] for r in case.get('audit',{}).get('profiles',[])),default=None)},ensure_ascii=False),flush=True)
    main=cases[0];assert main.get('audit'),'主案例未取得经独立核对的排班'
    plan=main['solution']['common_plan'];baseline_rows=[];comparison=[]
    empty={'bus_tasks':[],'taxi_blocks':[[0]*len(plan['taxi_blocks'][0]) for d in base['directions']]}
    avg=average_plan(base)
    for name,bplan in [('仅基础服务',empty),('平均预留资源',avg)]:
        info=check_plan(base,bplan)
        for profile in base['arrival_profiles']:
            policy=causal_greedy(base,bplan,profile,horizon_minutes=480)
            row=replay(base,bplan,policy,profile)
            comparison.append({'策略':name,'进入过程':row['label'],'费用元':info['cost_yuan'],
                '候客峰值':round(row['peak_queue_people'],3),'平均等待分钟':round(row['mean_wait_minutes'],5) if row['mean_wait_minutes'] is not None else None,
                '站立人分钟':round(row['standing_person_minutes'],3),'完成':clock(base,row['completion_minutes']),
                '截止未完成人数':round(row['deadline_remaining_people'],3),'通过':row['all_targets_met']})
            if name=='仅基础服务':baseline_rows.append(row)
    for row in main['audit']['profiles']:
        comparison.append({'策略':'共同资源优化','进入过程':row['label'],'费用元':main['audit']['plan']['cost_yuan'],
            '候客峰值':round(row['peak_queue_people'],3),'平均等待分钟':round(row['mean_wait_minutes'],5),
            '站立人分钟':round(row['standing_person_minutes'],3),'完成':clock(base,row['completion_minutes']),
            '截止未完成人数':round(row['deadline_remaining_people'],3),'通过':row['all_targets_met']})
    # Validate an implementable, current-queue dispatcher using the optimized reservations.
    greedy=[]
    for profile in base['arrival_profiles']:
        greedy.append(replay(base,plan,causal_greedy(base,plan,profile,horizon_minutes=480),profile))
    holdout=[]
    for profile in [
        {'id':'heldout_mix','label':'未参与优化的混合过程','hourly_people':[500,1500,2000,500,500,1000]},
        {'id':'heldout_spike','label':'未参与优化的末小时极端集中','hourly_people':[0,0,0,0,0,6000]}]:
        row=replay(base,plan,causal_greedy(base,plan,profile,horizon_minutes=480),profile);holdout.append(row)
    bus_rows=[]
    for t in plan['bus_tasks']:
        bus_rows.append({'车辆':t['vehicle_id'],'方向':base['directions'][t['direction']]['label'],
                        '登乘开始':clock(base,t['start_minute']),'离站':clock(base,t['departure_minute']),
                        '到接续节点':clock(base,t['destination_minute']),'可再次投入':clock(base,t['return_minute'])})
    taxi_rows=[]
    for d,direction in enumerate(base['directions']):
        for t,blocks in enumerate(plan['taxi_blocks'][d]):
            if blocks:taxi_rows.append({'方向':direction['label'],'时段开始':clock(base,t*base['parameters']['step_minutes']),
                                       '时段结束':clock(base,(t+1)*base['parameters']['step_minutes']),
                                       '预约服务名额':blocks*base['parameters']['taxi_block_people'],
                                       '费用元':blocks*base['parameters']['taxi_block_cost_yuan']})
    output={'model_version':'OPT-MILP-01','implementation_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ['model.py','simulate.py']},
            'runtime':{'numpy':importlib.metadata.version('numpy'),'scipy':importlib.metadata.version('scipy')},
            'nature':'真实事件背景下的合成参数实验；有限情景集合内条件验证，不是历史处置反事实效果',
            'cases':cases,'summary':[summarize(c) for c in cases],
            'baseline_plans':{'base_only':empty,'average_reservation':avg},
            'baselines':comparison,'optimized_reservations_with_causal_greedy':greedy,'heldout':holdout}
    (RESULT_DIR/'优化实验结果.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    table(PLAN_DIR/'公交排班.csv',bus_rows);table(PLAN_DIR/'出租预约.csv',taxi_rows)
    table(PLAN_DIR/'策略对照.csv',comparison);table(PLAN_DIR/'预算舒适取舍.csv',output['summary'])
    write_chart(main,baseline_rows)
    print('全部实验及独立核对完成',flush=True)


if __name__=='__main__':
    run(float(sys.argv[1]) if len(sys.argv)>1 else 35)
