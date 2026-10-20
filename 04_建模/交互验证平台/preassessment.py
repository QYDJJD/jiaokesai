"""Fast, explicitly aggregated resource-tier screening before network detail."""
from pathlib import Path
import sys, math, json, hashlib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'06_实验验证/分级方法验证'))
from grading_engine import evaluate,profile

VERSION='ASSESS-02'
LABELS=['现有保障','加强保障','联合保障','参考资源仍不足']
SHAPES={'uniform':'均匀进入','front':'前四分之一时段进入80%','back':'后四分之一时段进入80%'}

def example():
    return {'title':'参数预判示例','evidence':'研究假设，非虹桥实测或行政分级标准',
      'new_people':2000,'initial_people':0,'entry_minutes':120,'information_lead_minutes':60,
      'arrival_set':'three','queue_limit_people':1000,'clearance_minutes':60,
      'eligibility':'eligible','compatible_pool':'yes',
      'resources':[
        {'label':'现有有效服务','rate_people_hour':500,'prepare_minutes':0,'end_minutes':180},
        {'label':'第一批新增服务','rate_people_hour':500,'prepare_minutes':60,'end_minutes':180},
        {'label':'第二批新增服务','rate_people_hour':1000,'prepare_minutes':60,'end_minutes':180}]}

def references():
    return json.loads((Path(__file__).parent/'reference_rules.json').read_text(encoding='utf-8'))['references']

def assessment_example():
    data=example()
    data.update(title='事件条件评估示例',assessment_kind='event_conditions',reference_id='none',
      reference_options=[{'id':r['id'],'label':r['label']} for r in references()])
    data['resources']=data['resources'][:1]
    data['resources'][0]['label']='基准有效服务'
    return data

def assess(data):
    if not isinstance(data,dict):raise ValueError('请提供参数预判输入')
    if data.get('assessment_kind') not in (None,'event_conditions','historical_resource_comparison'):raise ValueError('事件评估模式无效')
    event_mode=data.get('assessment_kind')=='event_conditions'
    def value(obj,key,label,negative=False):
        v=obj.get(key)
        if v is None:raise ValueError(label+'尚未填写；未知不能用0代替')
        if type(v) not in (int,float) or not math.isfinite(v) or (not negative and v<0):raise ValueError(label+'须为有效'+('数值' if negative else '非负数'))
        if abs(v)>1e9:raise ValueError(label+'超出预判规模，请检查单位')
        return float(v)
    result={'version':VERSION,'assessment_kind':'event_conditions' if event_mode else 'historical_resource_comparison',
      'scope':'相同目的服务的一组兼容候客人群；连续有效服务近似',
      'completion_boundary':'离开当前候客队列，不表示到达城市目的节点',
      'input_sha256':hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
      'implementation_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),ROOT/'06_实验验证/分级方法验证/grading_engine.py')},
      'status':'needs_information','grade_index':None,'grade_label':'暂不判级','tiers':[]}
    eligibility=data.get('eligibility');compatible=data.get('compatible_pool')
    if eligibility not in ('eligible','unsafe','unknown') or compatible not in ('yes','no','unknown'):raise ValueError('请说明继续运输条件及需求兼容范围')
    if eligibility=='unsafe':return {**result,'status':'boundary_stop','grade_label':'先处理安全条件','reason':'已明确不宜继续运输，不能将其当作最高运力等级。'}
    if eligibility=='unknown':return {**result,'reason':'继续运输条件尚不明确，先核条件。'}
    if compatible!='yes':return {**result,'status':'needs_split','reason':'不同去向或共用瓶颈不能当作同一个资源池相加；先拆成兼容组或直接进行网络细化。'}
    q=value(data,'new_people','新增待接续人数');initial=value(data,'initial_people','初始候客人数')
    duration=value(data,'entry_minutes','进入持续时间');lead=value(data,'information_lead_minutes','信息提前量',True)
    k=value(data,'queue_limit_people','候客人数上限');slack=value(data,'clearance_minutes','进入结束后允许疏运时间')
    if q>0 and duration<=0:raise ValueError('持续新增旅客须填写正的进入时间；瞬时积压请填入初始候客')
    if duration+slack>2880:raise ValueError('预判时域最多2880分钟，请检查分钟与小时')
    if data.get('arrival_set') not in ('uniform','three','unknown'):raise ValueError('请选择进入节奏的预判范围')
    if data['arrival_set']=='unknown':return {**result,'reason':'进入节奏未知。可明确选择三种研究过程进行条件预判，但不能自动当作均匀进入。'}
    resources=data.get('resources')
    if not isinstance(resources,list) or (len(resources)<1 if event_mode else len(resources)!=3):raise ValueError('请填写基准有效服务' if event_mode else '须分别填写现有服务与两批增援；每批填写新增量，不重复填累计能力')
    if event_mode:resources=resources[:1]
    caps=[];ready=[]
    for i,r in enumerate(resources):
        if not isinstance(r,dict):raise ValueError('服务参数不完整')
        rate=value(r,'rate_people_hour','有效服务人数/小时');prepare=value(r,'prepare_minutes','准备时长');end=value(r,'end_minutes','服务结束分钟')
        if prepare>2880 or end>2880:raise ValueError('服务时长最多2880分钟，请检查单位')
        if i==0 and prepare!=0:raise ValueError('现有服务从事件开始即有效，准备时长须填0；延迟服务请归入增援')
        start=0 if i==0 else max(0,prepare-lead);ready.append(start)
        caps.append((start/60,end/60,rate) if end>start and rate>0 else None)
    shapes=['uniform'] if data['arrival_set']=='uniform' else list(SHAPES)
    tiers=[];deadline=(duration+slack)/60
    for index,name in enumerate(['输入的基准有效服务'] if event_mode else LABELS[:3]):
        supply=[s for s in caps[:index+1] if s is not None];rows=[]
        for shape in shapes:
            r=evaluate(profile(q,duration/60,shape),supply,initial,deadline)
            failures=[]
            if r['peak_people']>k+1e-7:failures.append('候客人数超过上限')
            if r['clear_h'] is None or r['clear_h']>deadline+1e-7:failures.append('未在规定时间内接走全部旅客')
            rows.append({'profile':SHAPES[shape],'peak_people':r['peak_people'],
              'clear_minutes':None if r['clear_h'] is None else r['clear_h']*60,
              'remaining_at_deadline':r['residual_at_deadline_people'],'passed':not failures,'reasons':failures})
        tiers.append({'label':name,'passed':all(r['passed'] for r in rows),'profiles':rows,
          'worst_peak_people':max(r['peak_people'] for r in rows),
          'latest_clear_minutes':None if any(r['clear_minutes'] is None for r in rows) else max(r['clear_minutes'] for r in rows),
          'reasons':list(dict.fromkeys(v for r in rows for v in r['reasons']))})
    if event_mode:
        reference_id=data.get('reference_id','none');catalog=references()
        selected=next((r for r in catalog if r['id']==reference_id),None)
        if reference_id!='none' and selected is None:raise ValueError('所选既有规则或方法未登记')
        row=tiers[0];label='所列过程均满足设定控制条件' if row['passed'] else '部分过程超出设定控制条件'
        for item in row['profiles']:
            item['queue_limit_ratio']=item['peak_people']/k if k>0 else None
            item['completion_margin_minutes']=None if item['clear_minutes'] is None else duration+slack-item['clear_minutes']
        return {**result,'status':'assessed','grade_index':None,'grade_label':label,'assessment_label':label,
          'tiers':[],'profiles':row['profiles'],'all_controls_met':row['passed'],
          'worst_peak_people':row['worst_peak_people'],'latest_clear_minutes':row['latest_clear_minutes'],
          'deadline_minutes':duration+slack,'profiles_checked':[SHAPES[s] for s in shapes],
          'external_reference':selected,
          'reference_catalog_sha256':hashlib.sha256(json.dumps(catalog,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
          'response_mapping':{'status':'not_automatically_mapped','label':'尚未自动映射正式响应级别',
            'reason':'已登记资料的完整、适用触发条件不足以执行自动定级；结果提供指标与所设目标的核对，不以自拟保障档位替代。'},
          'reason':'按基准有效服务评估候客压力和完成情况；控制目标属于输入条件，结果不直接等于法定响应级别。',
          'next_step':'补充网络和时段细节，定位瓶颈；匹配适用的既有预案或研究方法，将其作为后续处置参照。'}
    grade=next((i for i,t in enumerate(tiers) if t['passed']),3)
    return {**result,'status':'provisional','grade_index':grade,'grade_label':LABELS[grade],'tiers':tiers,
      'resource_ready_minutes':ready,'profiles_checked':list(SHAPES[s] for s in shapes),
      'deadline_minutes':duration+slack,
      'reason':'所填三档参考资源均未满足两项主条件，需要调整资源、目标或事件边界后重算。' if grade==3 else '在所填有效服务、进入过程和两项主条件下，最低通过的研究保障档位。',
      'next_step':'补充去向、换乘、时刻、周转、共享设施、预算与舒适条件，逐档复核；预判不锁定优化结果。'}
