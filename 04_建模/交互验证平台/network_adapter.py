"""UI/exports for the general network model; legacy cards remain readable."""
from pathlib import Path
import sys,json,hashlib,math,datetime,csv,io,html,zipfile,copy
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).parent;MODEL=ROOT/'04_建模/多方式网络优化'
sys.path.insert(0,str(MODEL))
from network_schema import validate,totals,five_summary,calendar,SCHEMA,VERSION,LIMITS
from network_examples import templates,convert_legacy
from network_model import solve,assign_units
from network_audit import check_plan,replay,greedy_policy,audit_solution
from preassessment import assess as assess_preliminary

def now():return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
def clock(card,minute):
    if minute is None:return '未完成'
    return (datetime.datetime.fromisoformat(card['parameters']['start_time'])+datetime.timedelta(minutes=minute)).astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime('%m-%d %H:%M')

def check_input(card):
    try:
        rec=validate(card)
        if len(card.get('facilities',[]))>24 or len(card.get('occupancy_facilities',[]))>24:raise ValueError('第一版最多24项共享设施')
        values=totals(card);warnings=['各时段按网格边界进入；登乘与运行分别向上取整到完整时间步。','目的节点到达与离开起点分别报告，换乘节点候客也计入安全检查。','方式名称不决定公式；既定服务与可协调增援须依据实际权限和确认能力选择。']
        if any(m['comfort']=='unmeasured' for m in card['modes']):warnings.append('标记“未测度”的方式只检查容量和时间，不表示其舒适要求已经满足。')
        T=int(card['parameters']['deadline_minutes']/card['parameters']['step_minutes'])
        if any(any(seats>cap for seats,cap in zip(calendar(a['fixed_seats'],T),calendar(a['fixed_capacity'],T))) for a in card['links']):warnings.append('部分时段声明座位多于可用服务能力；有效座位按两者较小值取，取消服务时不会保留可用座位。')
        return {'valid':True,'errors':[],'warnings':warnings,'task_people_by_profile':values,
                'periods':int(card['parameters']['deadline_minutes']/card['parameters']['step_minutes']),
                'modes':len(card['modes']),'nodes':len(card['nodes']),'links':len(card['links']),'five_dimensions':five_summary(card)}
    except (ValueError,KeyError,TypeError,OverflowError) as exc:return {'valid':False,'errors':[{'field':'card','message':str(exc) or '网络参数不完整'}],'warnings':[]}

def settings(raw):
    raw=raw or {};mode=raw.get('mode','optimize');objective=raw.get('objective','journey_time');seconds=raw.get('seconds',35)
    if mode not in ('optimize','manual') or objective not in ('journey_time','wait','cost'):raise ValueError('运行方式或目标无效')
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 1<=seconds<=60:raise ValueError('阶段限时为1至60秒')
    return {'mode':mode,'objective':objective,'seconds':float(seconds),'gap':.001}

def make_manual_plan(card,manual):
    validate(card);step=card['parameters']['step_minutes'];rows=manual.get('reservations',[]) if isinstance(manual,dict) else None
    if not isinstance(rows,list) or len(rows)>1000:raise ValueError('请提供最多1000条通用运力预约')
    combined={};provided={}
    for row in rows:
        aid=row.get('link_id');minute=row.get('start_minute');count=row.get('units');ids=row.get('unit_ids',[])
        if type(minute) not in (int,float) or not math.isfinite(minute) or minute<0 or minute%step:raise ValueError('登乘开始分钟须对齐时间步')
        if type(count) not in (int,float) or not math.isfinite(count) or count<0 or int(count)!=count:raise ValueError('预约单位数须为非负整数')
        if not count:continue
        key=(aid,int(minute/step));combined[key]=combined.get(key,0)+int(count)
        if not isinstance(ids,list) or any(not isinstance(v,str) or not v.strip() for v in ids):raise ValueError('周转单位编号须为非空字符串数组')
        if ids:provided.setdefault(key,[]).extend(ids)
    try:
        plan=assign_units(card,[{'link_id':aid,'start_step':t,'units':n} for (aid,t),n in combined.items()])
        for row in plan['reservations']:
            key=row['link_id'],row['start_step']
            if key in provided:row['unit_ids']=provided[key]
        check_plan(card,plan)
        return plan
    except (ValueError,AssertionError,KeyError,IndexError) as exc:raise ValueError('手工资源安排未通过：'+(str(exc) or '请检查线路、时段和资源数量')) from exc

def diagnostics(card):
    rec=validate(card);messages=[]
    for g in card['groups']:
        reached={g['origin']}
        for _ in card['nodes']:reached|={a['to'] for a in card['links'] if a['from'] in reached and a['mode_id'] in g['allowed_modes'] and rec['modes'][a['mode_id']].get('enabled',True)}
        if g['destination'] not in reached:messages.append(g['label']+'在当前可接受方式下没有连通到目的节点的路径。')
    return messages or ['未发现简单静态断路。若已证明不可行，说明当前时序、容量、队列、资源、舒适或预算无法共同满足；尚未计算最小冲突约束集合。']

def evaluate(card,raw,manual=None,progress=lambda stage:None):
    conf=settings(raw);checked=check_input(card)
    if not checked['valid']:raise ValueError('；'.join(e['message'] for e in checked['errors']))
    files=[MODEL/n for n in ('network_schema.py','network_examples.py','network_model.py','network_audit.py')]+[HERE/'network_adapter.py',HERE/'web/app.js',HERE/'preassessment.py',HERE/'reference_rules.json',ROOT/'06_实验验证/分级方法验证/grading_engine.py']
    result={'platform_version':'PLATFORM-02','model_family':'multimodal_network','created_at':now(),'card':copy.deepcopy(card),'settings':conf,
      'validation':checked,'input_sha256':hashlib.sha256(json.dumps(card,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
      'implementation_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
      'evidence_note':'网络与方式来自输入，不按事件名称选择公式。真实背景、研究假设、协调权限与实测能力分别记录。'}
    preliminary=card.get('preassessment')
    if isinstance(preliminary,dict) and isinstance(preliminary.get('input'),dict):
        try:
            screen=assess_preliminary(preliminary['input']);d=preliminary['input'];matched=None
            if screen['status'] in ('provisional','assessed'):
                target=d['new_people']+d['initial_people'];p=card['parameters']
                matched=all(abs(v-target)<1e-5 for v in totals(card).values()) and abs(p['entry_steps']*p['step_minutes']-d['entry_minutes'])<1e-5 and card['five_dimensions']['information_lead_minutes']==d['information_lead_minutes']
            result['preassessment']={'screen':screen,'main_inputs_match':matched,'resource_mapping_verified':False,
              'interpretation':'事件评估与详细核算分别记录；既有预案或论文方法作为处置参照，未自动推导正式响应等级，当前调度程序用于验证情景输入。' if screen.get('assessment_kind')=='event_conditions' else '历史自拟资源包试验，保留原输入及结果；不作为当前研究的事件等级或主要创新成果。'}
            result['card']['preassessment']['result']=copy.deepcopy(screen)
        except ValueError as exc:result['preassessment']={'status':'invalid_preliminary','reason':str(exc),'interpretation':'预判参数未完成；本次仅计算详细网络，不强行赋等级。'}
    if conf['mode']=='manual':
        progress('正在核对通用资源与运行日历');plan=make_manual_plan(card,manual or {})
        policies=[greedy_policy(card,plan,s) for s in card['profiles']];progress('正在按旅客批次核对运行与换乘')
        rows=[replay(card,plan,policy,s) for s,policy in zip(card['profiles'],policies)]
        result.update(solution=None,plan=plan,execution_policies=policies,audit={'plan':check_plan(card,plan),'profiles':rows,'independent_event_and_fifo_checks':'通过'},
          status='passed' if all(r['all_targets_met'] for r in rows) else 'failed_targets')
    else:
        progress('正在构建并求解多方式时间展开网络');solution=solve(card,seconds=conf['seconds'],gap=conf['gap'],objective=conf['objective']);result['solution']=solution
        if solution['has_solution']:
            progress('正在独立核对各节点人数、换乘和资源');audit=audit_solution(card,solution)
            result.update(plan=solution['common_plan'],audit=audit,status='passed')
            result['current_queue_execution']=[replay(card,result['plan'],greedy_policy(card,result['plan'],s),s) for s in card['profiles']]
        else:result.update(status='infeasible' if solution['phase_primary']['status']==2 else 'unresolved',diagnostics=diagnostics(card))
    progress('正在生成既定服务对照与验证包');empty={'reservations':[]}
    result['baseline']={'label':'仅既定服务','plan':check_plan(card,empty),'profiles':[replay(card,empty,greedy_policy(card,empty,s),s) for s in card['profiles']]}
    if result.get('audit'):
        result['diagnostics']=[]
        for row in result['audit']['profiles']:
            if not row['safe_queue']:result['diagnostics'].append(row['label']+'的节点、群体或全网络候客上限未通过。')
            if not row['complete_by_deadline']:result['diagnostics'].append(row['label']+f'截止仍有{row["remaining_people"]:g}人未到目的节点。')
    return result

def csv_data(rows,headers):
    f=io.StringIO(newline='');w=csv.DictWriter(f,fieldnames=headers);w.writeheader();w.writerows(rows);return f.getvalue().encode('utf-8-sig')

def tables(result):
    card=result['card'];rec=validate(card);step=card['parameters']['step_minutes'];reservations=[];use=[];metrics=[];details=[]
    for row in result.get('plan',{}).get('reservations',[]):
        a=rec['links'][row['link_id']];pool=rec['pools'][a['pool_id']]
        reservations.append({'方式':rec['modes'][a['mode_id']]['label'],'线路':a['label'],'资源池':pool['label'],'单位数':row['units'],
          '单位编号':'、'.join(row['unit_ids']),'开始登乘':clock(card,row['start_minute']),'离站':clock(card,row['departure_minute']),
          '到下一节点':clock(card,row['arrival_minute']),'返回基地':clock(card,row['return_minute']) if row['return_minute'] is not None else '按服务名额预约',
          '预约费元':row['units']*a['unit_cost_yuan']})
    policies=result.get('execution_policies',[])
    if not policies and result.get('solution'):policies=result['solution'].get('scenario_policy',[])
    for policy in policies:
        for row in policy['flows']:
            a=rec['links'][row['link_id']];t=row['start_step'];b=math.ceil(a['boarding_minutes']/step);ride=math.ceil(a['travel_minutes']/step)
            use.append({'进入过程':rec['profiles'][policy['profile_id']]['label'],'群体':rec['groups'][row['group_id']]['label'],
                '方式':rec['modes'][a['mode_id']]['label'],'线路':a['label'],'登乘开始':clock(card,t*step),
                '离站':clock(card,(t+b)*step),'到下一节点':clock(card,(t+b+ride)*step),'登乘或通行人次':row['people']})
    for label,audit in [('本次方案',result.get('audit')),('仅既定服务',result.get('baseline'))]:
        if not audit:continue
        for r in audit['profiles']:
            metrics.append({'安排':label,'过程':r['label'],'任务人数':r['task_people'],'到达目的人数':r['delivered_people'],'候客峰值':r['peak_queue_people'],
               '平均等待分钟':r['mean_wait_minutes'],'平均全程分钟':r['mean_journey_minutes'],'离开起点完成':clock(card,r['origin_clear_minutes']),
               '目的节点完成':clock(card,r['completion_minutes']),'截止未完成':r['remaining_people'],'站立人分钟':r['standing_person_minutes'],'全部目标通过':r['all_targets_met']})
            for t in r['node_trace']:details.append({'安排':label,'过程':r['label'],'时刻':clock(card,t['minute']),'群体':rec['groups'][t['group_id']]['label'],
              '节点':rec['nodes'][t['node_id']]['label'],'本段新增及换乘到达':t['new_or_transfer_arrivals'],'开始登乘前等待':t['waiting_before'],
              '本次开始登乘':t['boarding_started'],'剩余待登乘':t['waiting_after'],'仍在登乘':t['boarding_active_after'],'节点守恒残差':t['conservation_residual']})
    return {'运力预约.csv':csv_data(reservations,['方式','线路','资源池','单位数','单位编号','开始登乘','离站','到下一节点','返回基地','预约费元']),
      '方式与线路使用.csv':csv_data(use,['进入过程','群体','方式','线路','登乘开始','离站','到下一节点','登乘或通行人次']),
      '过程指标与对照.csv':csv_data(metrics,['安排','过程','任务人数','到达目的人数','候客峰值','平均等待分钟','平均全程分钟','离开起点完成','目的节点完成','截止未完成','站立人分钟','全部目标通过']),
      '逐节点核算.csv':csv_data(details,['安排','过程','时刻','群体','节点','本段新增及换乘到达','开始登乘前等待','本次开始登乘','剩余待登乘','仍在登乘','节点守恒残差'])}

def queue_svg(card,row,baseline):
    T=card['parameters']['deadline_minutes'];high=max(1,*[t['queue_before'] for r in (row,baseline) for t in r['trace']])*1.12
    x=lambda t:55+790*t/T
    y=lambda q:235-200*q/high
    parts=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 285" role="img" aria-label="全网络候客过程">']
    for i in range(5):
        q=high*i/4;minute=T*i/4
        parts.append(f'<line x1="55" x2="845" y1="{y(q)}" y2="{y(q)}" stroke="#dce5e9"/><text x="45" y="{y(q)+4}" font-size="11" text-anchor="end">{q:.0f}</text><text x="{x(minute)}" y="260" font-size="11" text-anchor="middle">{clock(card,minute)[6:]}</text>')
    for r,color in [(baseline,'#91a6b0'),(row,'#117b80')]:
        points=' '.join(f'{x(t["minute"]):.3f},{y(t["queue_before"]):.3f}' for t in r['trace'])
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.3"/>')
    return ''.join(parts)+'</svg>'

def report_html(result):
    e=lambda v:html.escape(str(v));c=result['card'];title=c.get('platform',{}).get('title',c['scenario_id'])
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+e(title)+'</title><style>body{font:14px/1.8 "Microsoft YaHei",sans-serif;max-width:1100px;margin:30px auto;padding:20px;color:#173848}table{width:100%;border-collapse:collapse;font-size:11px}th,td{padding:7px;border:1px solid #cedde3;text-align:left}th{background:#edf4f5}h2{margin-top:30px}.note{padding:14px;background:#edf5f5}@media print{button{display:none}tr{break-inside:avoid}}</style>',
      '<button onclick="window.print()">打印／另存为PDF</button><h1>'+e(title)+'</h1><p>'+e(result['created_at'])+' · '+e(VERSION)+'</p>',
      '<div class="note">'+e(result['evidence_note'])+' 目的节点到达与离开起点为两个不同指标；方式乘坐人次可以包含换乘，不能相加当作旅客总人数。</div>',
      '<h2>五维与输入范围</h2><pre>'+e(json.dumps(five_summary(c),ensure_ascii=False,indent=2))+'</pre>',
      '<p>事件说明：'+e(c.get('platform',{}).get('notes',''))+'</p><p>来源：'+e(c.get('platform',{}).get('sources','未填写'))+'</p>',
      '<h2>运行结果</h2><p>'+e({'passed':'所列过程通过','failed_targets':'资源安排合法但目标未全部通过','infeasible':'当前候选集合已证明不可行','unresolved':'限时内未取得可行方案，不能认定无解'}[result['status']])+'</p>']
    if result.get('preassessment'):
        pre=result['preassessment'];screen=pre.get('screen',{})
        event_mode=screen.get('assessment_kind')=='event_conditions'
        parts.append('<h2>'+('事件评估与处置参照' if event_mode else '参数预判与细化核对')+'</h2><p>'+e(screen.get('assessment_label',screen.get('grade_label','尚未完成评估')))+'；主要人数、持续时间及提前量一致：'+e(pre.get('main_inputs_match'))+'。</p><p>'+e(pre['interpretation'])+'</p>')
        if event_mode:
            parts.append('<table><tr><th>进入过程</th><th>候客峰值</th><th>占所设上限</th><th>全部离开分钟</th><th>完成余量分钟</th><th>截止剩余</th></tr>')
            for row in screen.get('profiles',[]):
                ratio=row['queue_limit_ratio'];values=[row['profile'],round(row['peak_people'],6),'上限为0，按人数核对' if ratio is None else str(round(ratio*100,3))+'%',row['clear_minutes'],row['completion_margin_minutes'],round(row['remaining_at_deadline'],6)]
                parts.append('<tr>'+''.join('<td>'+e('未完成' if v is None else v)+'</td>' for v in values)+'</tr>')
            parts.append('</table><p>'+e(screen.get('response_mapping',{}).get('reason',''))+'</p>')
            source=screen.get('external_reference')
            if source:parts.append('<p>既有参照：<a href="'+e(source['source_url'])+'">'+e(source['label'])+'</a></p><p>'+e(source['read_scope'])+'</p><p>'+e(source['limitation'])+'</p>')
    if result.get('solution'):
        r=result['solution'];name={'journey_time':'最坏累计全程人分钟','wait':'最坏累计等待人分钟','cost':'满足条件的新增预约费用'}[r['objective_kind']]
        parts.append('<p>主目标 '+e(name)+'；状态 '+e(r['phase_primary']['status'])+'；相对差距 '+e(r['phase_primary']['relative_gap'])+'。状态0表示达到所设差距，1为限时，2为不可行。</p>')
    if result.get('audit'):
        parts.append('<h2>全网络候客过程</h2><p>青线为本次方案，灰线为仅既定服务的当前队列对照。对照不声称为既定资源下的最优分配。</p>')
        for row in result['audit']['profiles']:
            baseline=next(r for r in result['baseline']['profiles'] if r['profile_id']==row['profile_id'])
            parts.append('<h3>'+e(row['label'])+'</h3>'+queue_svg(c,row,baseline))
        parts.append('<h2>各方式乘坐或通行人次</h2><p>换乘旅客可以在多个方式计人次，不能相加当作已完成旅客人数。逐时段分配见同包方式与线路使用表。</p><table><tr><th>进入过程</th><th>方式</th><th>人次</th></tr>')
        for row in result['audit']['profiles']:
            for mid,people in row['by_mode_boardings'].items():parts.append('<tr><td>'+e(row['label'])+'</td><td>'+e(next(m['label'] for m in c['modes'] if m['id']==mid))+'</td><td>'+e(round(people,6))+'</td></tr>')
        parts.append('</table>')
    for filename,data in tables(result).items():
        if filename in ('逐节点核算.csv','方式与线路使用.csv'):continue
        parts.append('<h2>'+e(filename[:-4])+'</h2><table>')
        for i,row in enumerate(csv.reader(io.StringIO(data.decode('utf-8-sig')))):
            tag='th' if i==0 else 'td';parts.append('<tr>'+''.join('<'+tag+'>'+e(v)+'</'+tag+'>' for v in row)+'</tr>')
        parts.append('</table>')
    parts.append('<h2>适用边界</h2><ul>')
    for note in result['validation']['warnings']+result.get('diagnostics',[]):parts.append('<li>'+e(note)+'</li>')
    parts.append('</ul><p>采用固定运行时间与时间步、连续旅客流近似；未内生求解道路拥堵、轨道闭塞、驾驶员排班和现场权限。详见同包输入与完整结果，逐节点表可核对中间换乘。</p></html>')
    return ''.join(parts).encode('utf-8')

def write_exports(folder,result):
    folder=Path(folder);contents={'输入情景卡.json':json.dumps(result['card'],ensure_ascii=False,indent=2).encode('utf-8'),
      '完整计算结果.json':json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8'),'验证报告.html':report_html(result),**tables(result)}
    contents['复现说明.txt']=('多方式网络优化 '+VERSION+'\n输入卡可直接导入平台。方式、节点、线路、资源池及旅客群体均来自输入。\n既定服务不由模型擅自新增；周转单位与分时服务名额按各自资源约束。\n旅客总人数与方式通行人次分别统计；离开起点与到达目的节点分别报告。\n手工模式按当前队列与已知供给日历选择最早可到达路径，不观察未来需求。\n完整结果含输入和代码版本哈希；求解时限可能导致不同平局安排。\n').encode('utf-8')
    for name,data in contents.items():(folder/name).write_bytes(data)
    with zipfile.ZipFile(folder/'完整验证包.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name,data in contents.items():z.writestr(name,data)
    return list(contents)+['完整验证包.zip']
