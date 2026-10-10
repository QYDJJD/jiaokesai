"""Reproducible directional and shared-capacity stress checks (synthetic).

Run after build_library.py. Standard library only; the input cases are
deliberately small counterexamples, not Hongqiao operational calibration.
"""
from pathlib import Path
from copy import deepcopy
import json
import hashlib
from grading_engine import evaluate,profile,EPS
from directional_grading import grade_directional

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent


def demand(q=1000,d=2,k=400,h=.5):
    return dict(q=q,d=d,b0=0,k=k,h=h)


def resource(rid,directions,rate,layer=0,start=0,end=None):
    return {'id':rid,'pool_id':rid,'mode':'synthetic_service','directions':directions,
            'capacity':[[start,end,rate]],'layer':layer,'evidence_type':'ASSUMPTION'}


def alloc(rid,d,rate,start=0,end=None):
    return {'resource_id':rid,'direction':d,'segments':[[start,end,rate]]}


def plan(pid,layer,allocations):
    return {'id':pid,'introduced_layer':layer,'allocations':allocations}


def base():
    return {'safe':True,'known':True,'supported':True,
            'directions':{'A':demand(),'B':demand()},
            'joint_profiles':[{'id':'omega_uniform','shapes':{'A':'uniform','B':'uniform'}}],
            'resources':[],'groups':[],'plans':[],
            'reference_version':'REF-DIR-SYN-01','goal_version':'GOAL-DIR-SYN-01'}


def cases():
    specs=[]
    def add(sid,title,purpose,x,expected):
        specs.append({'id':sid,'title':title,'purpose':purpose,'type':'synthetic_directional',
                      'input':deepcopy(x),'expected_grade':expected})
    x=base()
    x['resources']=[resource('A_base',['A'],1500),resource('B_base',['B'],100),resource('B_extra',['B'],400,1)]
    p0=[alloc('A_base','A',1500),alloc('B_base','B',100)]
    x['plans']=[plan('base',0,p0),plan('strengthened',1,p0+[alloc('B_extra','B',400)])]
    add('SC-N01','总运力够但B方向不足','方向不可互换',x,'F1')
    x2=deepcopy(x);x2['directions']['A']['q']=1900;x2['directions']['B']['q']=100
    add('SC-N02','总人数不变而方向分布改变','方向混合决定等级',x2,'F0')
    shared=base()
    shared['resources']=[resource('A_base',['A'],500),resource('B_base',['B'],500),resource('B_bypass',['B'],500,1),resource('A_bypass',['A'],500,2)]
    shared['groups']=[{'id':'G_boarding','resource_ids':['A_base','B_base'],'capacity':[[0,None,600]],'evidence_type':'ASSUMPTION'}]
    s0=[alloc('A_base','A',300),alloc('B_base','B',300)]
    shared['plans']=[plan('shared_base',0,s0),plan('B_support',1,s0+[alloc('B_bypass','B',500)]),plan('AB_support',2,s0+[alloc('B_bypass','B',500),alloc('A_bypass','A',500)])]
    shared['plans'].append(plan('reallocate_shared_at_V1',1,[alloc('A_base','A',400),alloc('B_base','B',200),alloc('B_bypass','B',500)]))
    add('SC-N03','两项服务共用上客能力','共享能力不可重复',shared,'F1')
    crossed=base()
    crossed['resources']=[resource('flex',['A','B'],2000)]
    crossed['joint_profiles']=[{'id':'omega_A_early','shapes':{'A':'front','B':'back'}},{'id':'omega_B_early','shapes':{'A':'back','B':'front'}}]
    earlyA=[alloc('flex','A',1500,0,1),alloc('flex','B',500,0,1),alloc('flex','A',500,1),alloc('flex','B',1500,1)]
    earlyB=[alloc('flex','A',500,0,1),alloc('flex','B',1500,0,1),alloc('flex','A',1500,1),alloc('flex','B',500,1)]
    crossed['plans']=[plan('favor_A_first',0,earlyA),plan('favor_B_first',0,earlyB)]
    add('SC-N04','每条轨迹有方案但没有共同通过方案','不能事后分别选策略',crossed,'F3')
    common=deepcopy(crossed)
    common['plans'].append(plan('balanced',0,[alloc('flex','A',1000),alloc('flex','B',1000)]))
    add('SC-N05','补入同资源下的共同通过方案','候选清单遗漏可能误升级',common,'F0')
    late=deepcopy(x)
    late['resources'][2]['capacity']=[[1,None,400]]
    late['resources'].append(resource('B_joint',['B'],500,2,1))
    late['plans']=[plan('base',0,p0),plan('strengthened',1,p0+[alloc('B_extra','B',400,1)]),plan('joint',2,p0+[alloc('B_extra','B',400,1),alloc('B_joint','B',500,1)])]
    add('SC-N06','B方向增援较晚生效','异质生效时间',late,'F2')
    window=base()
    window['resources']=[resource('A_base',['A'],1500),resource('B_base',['B'],500,0,0,1),resource('B_extension',['B'],500,1,1)]
    wp=[alloc('A_base','A',1500),alloc('B_base','B',500,0,1)]
    window['plans']=[plan('before_close',0,wp),plan('extend_B',1,wp+[alloc('B_extension','B',500,1)])]
    add('SC-N07','B方向服务结束需接续','方向服务日历',window,'F1')
    invalid=deepcopy(shared);invalid['plans'][0]['allocations']=[alloc('A_base','A',500),alloc('B_base','B',500)]
    add('SC-N08','申报供给超出共用上客能力','非法方案拒绝而非默默删去',invalid,'X-CONFIG')
    alias=deepcopy(x);alias['resources'].append({**deepcopy(alias['resources'][0]),'id':'A_alias'})
    add('SC-N09','同一资源池被换名重复计入','资源身份去重',alias,'X-CONFIG')
    missing=deepcopy(x);missing['known']=False
    add('SC-N10','分方向关键数据未知','缺失不填0',missing,'X-DATA')
    structure=deepcopy(x);structure['supported']=False
    add('SC-N11','需模拟途中换乘与共线运行','完整网络仍超出本工具',structure,'X-STRUCTURE')
    incompatible=deepcopy(x);incompatible['plans'][0]['allocations'][0]['direction']='B'
    add('SC-N12','将A专用服务错配到B','方向约束检查',incompatible,'X-CONFIG')
    waiting=base()
    waiting['resources']=[resource('flex',['A','B'],2000),resource('extra',['A','B'],1000,1)]
    waiting['joint_profiles']=[{'id':'both_early','shapes':{'A':'front','B':'front'}}]
    waiting['plans']=[plan('balanced',0,[alloc('flex','A',1000),alloc('flex','B',1000)]),plan('add_balanced',1,[alloc('flex','A',1000),alloc('flex','B',1000),alloc('extra','A',500),alloc('extra','B',500)])]
    waiting['waiting_groups']=[{'id':'shared_waiting','directions':['A','B'],'k':500}]
    add('SC-N13','各方向不过线但共用候客区超线','合计必须在同一时刻检查',waiting,'F1')
    staggered=deepcopy(waiting)
    staggered['joint_profiles']=[{'id':'staggered','shapes':{'A':'front','B':'back'}}]
    add('SC-N14','两个方向峰值错开','不能把各自峰值直接相加',staggered,'F0')
    return specs


def main():
    records=[];checks=[]
    def check(name,ok,count=1):
        checks.append({'name':name,'comparisons':count,'pass':bool(ok)})
        if not ok:raise AssertionError(name)
    for spec in cases():
        result=grade_directional(spec['input'])
        check(spec['id']+'_expected_behavior',result['grade']==spec['expected_grade'])
        x=spec['input']
        reference={k:x.get(k,[]) for k in ('resources','groups','plans')}
        goals={'direction_goals':{d:{k:p[k] for k in ('k','h')} for d,p in x['directions'].items()},'waiting_groups':x.get('waiting_groups',[])}
        def fingerprint(value):
            return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
        records.append({**spec,'reference_fingerprint':fingerprint(reference),'goal_fingerprint':fingerprint(goals),'result':result})
    by_id={r['id']:r for r in records}
    # Independent aggregation counterexample. These are not the constraints
    # used by the directional evaluator; deliberately aggregate them away.
    merged=evaluate(profile(2000,2,'uniform'),[(0,None,1600)],0,2.5)
    check('aggregation_false_pass',merged['peak_people']==0 and merged['clear_h']==2 and by_id['SC-N01']['result']['grade']=='F1')
    naive=evaluate(profile(1000,2,'uniform'),[(0,None,500)],0,2.5)
    check('shared_capacity_false_pass',naive['peak_people']==0 and naive['clear_h']==2 and by_id['SC-N03']['result']['grade']=='F1')
    cross=by_id['SC-N04']['result']
    each_has_plan=all(any(p['runs'][i]['pass'] for p in cross['plans']) for i in range(2))
    check('forall_exists_is_not_exists_forall',each_has_plan and not any(p['pass'] for p in cross['plans']))
    check('adding_feasible_plan_can_resolve_F3',by_id['SC-N05']['result']['grade']=='F0')
    check('input_plan_invalid_not_silently_discarded',by_id['SC-N08']['result']['grade']=='X-CONFIG' and 'shared capacity' in by_id['SC-N08']['result']['reason'])
    # Constant per-direction rates reproduce independent closed-form maxima
    # and clearance, also proving no transport demand has migrated to A.
    run=by_id['SC-N01']['result']['plans'][0]['runs'][0]['directions']['B']
    check('per_direction_closed_form',abs(run['peak_people']-800)<EPS and abs(run['clear_h']-10)<EPS)
    check('baseline_reduction_to_single_pool',grade_directional({**deepcopy(by_id['SC-N01']['input']),
           'directions':{'A':demand(2000,2,1000,1)},
           'joint_profiles':[{'id':'uniform','shapes':{'A':'uniform'}}],
           'resources':[resource('one',['A'],500),resource('more',['A'],500,1)],
           'plans':[plan('one',0,[alloc('one','A',500)]),plan('more',1,[alloc('one','A',500),alloc('more','A',500)])]})['grade']=='F1')
    compare=0
    for sid in ('SC-N01','SC-N02','SC-N03','SC-N05','SC-N06','SC-N07'):
        x=deepcopy(by_id[sid]['input']);base_grade=int(grade_directional(x)['grade'][1])
        for change in ('demand','goals','uncertainty'):
            y=deepcopy(x)
            if change=='demand':
                for d in y['directions'].values():d['q']*=1.2
            elif change=='goals':
                for d in y['directions'].values():d['k']*=1.2;d['h']+=.5
            else:
                y['joint_profiles'].append({'id':'additional','shapes':{d:'front' for d in y['directions']}})
            ng=int(grade_directional(y)['grade'][1])
            assert ng <= base_grade if change=='goals' else ng >= base_grade
            compare+=1
        r=grade_directional(x)
        assert all(not a['pass'] or b['pass'] for a,b in zip(r['tiers'],r['tiers'][1:]))
        compare+=2
    check('directional_monotonicity_and_nested_sets',True,compare)
    allruns=[d for r in records if r['result']['grade'].startswith('F') for p in r['result']['plans'] for w in p['runs'] for d in w['directions'].values()]
    check('directional_mass_balance',all(abs(d['arrived_people']-d['served_people']-d['unserved_people'])<1e-6 for d in allruns),len(allruns))
    simultaneous=by_id['SC-N13']['result']['plans'][0]['runs'][0]
    offset=by_id['SC-N14']['result']['plans'][0]['runs'][0]
    check('shared_waiting_peak_rejects_false_pass',all(d['pass'] for d in simultaneous['directions'].values()) and abs(simultaneous['waiting_groups'][0]['peak_people']-600)<EPS and not simultaneous['pass'])
    check('sum_of_peaks_is_not_peak_of_sum',abs(sum(d['peak_people'] for d in offset['directions'].values())-600)<EPS and abs(offset['waiting_groups'][0]['peak_people']-300)<EPS and offset['pass'])
    # Independent necessary lower bounds: B-only rate, combined boarding,
    # and the unavoidable first-half-hour waiting mass, respectively.
    minimum_rate=max(1000/2.5,(1000-400)/2)
    check('three_independent_V0_failure_certificates',minimum_rate>100 and 2*minimum_rate>600 and (3200-2000)*.5>500 and all(by_id[s]['result']['grade']=='F1' for s in ('SC-N01','SC-N03','SC-N13')),3)
    def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    write(OUT/'分方向与共享约束验证结果.json',{'version':'CHECK-DIR-01','date':'2026-10-11','evidence_type':'SYNTHETIC','checks':checks,'scenarios':records,'independent_empirical_accuracy':None})
    old=json.loads((ROOT/'03_情景库/初始情景库-v1.json').read_text(encoding='utf-8'))
    library={'version':'LIB-INIT-02','rule_version':'RULE-02','date':'2026-10-11',
             'grade_meaning':'minimum tier among predeclared fixed feasible service plans',
             'actual_operating_standard':False,
             'reference_note':'reference_version identifies a synthetic schema family; inventories, plans and goals can differ. Compare stored inputs and fingerprints; F labels are not unconditional cross-case risk ranks.',
             'single_pool_synthetic':old['synthetic'],'directional_synthetic':records,
             'observed_material':old['observed_material'],
             'limitations':['not all policies enumerated','effective curves not calibrated','no route travel/vehicle cycle/transfer simulation','real materials not independently graded'],
             'goal_status':'user confirmed peak and cohort-clearance main; personal wait diagnostic'}
    write(ROOT/'03_情景库/初始情景库-v2.json',library)
    lines=['# 初始情景库 v2','','版本LIB-INIT-02 / RULE-02；2026年10月11日。32张合成检查卡＋4张真实材料卡。原18张单池卡保持[原输入与结果](初始情景库-v1.md)，新增14张分方向及共享约束卡；不按36起实际事件计数。','','[完整JSON](初始情景库-v2.json)；[分方向规则](分方向与共享约束判级规则-v2.md)；[验证记录](../06_实验验证/分级方法验证/分方向验证说明.md)。','','## 新卡索引','','所有人数、服务率、候客目标、完成时限及共享能力均为合成假设；A/B为抽象方向，不指已测的虹桥线路。每方向默认Q=1000人、D=2小时、K=400人、H=0.5小时、B0=0。','','| 卡号 | 检查目的 | 结果 |','|---|---|---|']
    lines += [f"| {r['id']} | {r['title']} | {r['result']['grade']} |" for r in records]
    lines += ['','资源版本名标识合成配置族，不表示每卡资源库存相同；具体库存、方案及目标以JSON和指纹为准。不同目标或资源版本下的F标签不能直接当作统一绝对风险排序。']
    lines += ['','## 三个关键对照','','N01：A方向1500、B方向100人/小时。合计1600看似足够接走合计2000人，但B方向需10小时完成。补B方向400后才能通过，故F1；不能用A方向闲置能力直接冲抵B方向积压。','','N03：两项服务各500人/小时，共用上客区只有600人/小时。V0总共只有600，而常率条件下两方向各至少需400，故V0不足；V1补B方向旁路500，再把共享区按A400/B200分配即可通过，故F1。若各按500计算会错误通过；违反600的申报方案直接拒绝为X-CONFIG。','','N04：两条允许轨迹各能找到不同方案，但没有一个现有候选方案同时覆盖两条，故F3。N05在相同资源下补入平衡方案后变F0。这说明候选遗漏可导致过高等级；本方法只声称清单内最低通过层，没有证明实际全局最少资源。','','## 真实卡与未覆盖部分','','E01—E04仍列缺项并记X-DATA；不因有新计算器就填假设值。N11所指途中换乘、旅行时间和共线运行仍需完整网络模型，登记X-STRUCTURE。N13/N14已检查共享候客区合计峰值：同时出现为600人，错开为300人，不能直接加各方向峰值。离散车辆班次、车队周转、换乘容量、空间通行和资源再分配反馈尚未模拟，供给曲线及候客分组需先明确这些适用条件。','','本库证明了部分结构条件能改变分级，尚不证明所有空间、方向、服务模式和实际频率均已覆盖。重建：先运行`build_library.py`，再运行`build_directional_library.py`。','']
    (ROOT/'03_情景库/初始情景库-v2.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'checks':len(checks),'registered_comparisons':sum(c['comparisons'] for c in checks),'new_synthetic_cards':len(records),'combined_synthetic_cards':18+len(records),'observed_material_cards':4,'grades':[(r['id'],r['result']['grade']) for r in records]},ensure_ascii=False))


if __name__=='__main__':main()
