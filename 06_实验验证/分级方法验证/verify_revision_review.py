"""Revision checks: evidence scope, metadata gates and concrete boundary fixes."""
from pathlib import Path
from copy import deepcopy
import json
from grading_engine import grade_case
from directional_grading import grade_directional
from evidence_screen import event_readiness, screen_candidate
from service_calendar import window

ROOT=Path(__file__).resolve().parents[2]
audit=json.loads((ROOT/'02_数据与案例/公开证据登记-2026-10-11.json').read_text(encoding='utf-8'))
claims=audit['round2_claims']
checks=[]

def check(name, passed, details):
    if not passed:raise AssertionError(name)
    checks.append({'name':name,'pass':True,'details':details})

def rejected(call):
    try:call()
    except ValueError:return True
    return False

sources={s['id']:s for s in audit['sources']}
check('已核来源与未核线索分别计数',len(sources)==len(audit['sources'])==24 and all(s['url'] for s in sources.values()) and all(x['id'] not in sources for x in audit['round2_excluded_leads']),{'readable_records':24,'excluded_leads':3,'not_independent_events':True})
a15,a16=claims['activation_reports']
check('返城报道按2016事件年登记',sources['R2-01']['body_date']=='2016-02-16' and all(t.startswith('2016-') for t in a16['event_dates']),{'2016_dates':a16['event_dates']})
check('两篇报道不写成累计启用两次',len(a16['event_dates'])==3 and a16['separate_activation_each_day'],{'activation_report_count':2,'global_activation_total_unknown':True})
check('三晚约2万不擅自乘三或作Q',a16['aggregation']=='per_night_or_three_nights_not_explicit' and a16['cohort_queue_Q'] is None,{'raw_scale':20000,'aggregation_not_resolved':True})
check('两时刻56分钟不升级成H或逐客链',a15['timestamp_gap_minutes']==56 and a15['normative_H'] is None and not a15['last_cohort_entry_known'],{'reported_gap_minutes':56,'normative_H':None})

targets={
 'K':{'quantity':'queue_peak_control_limit','role':'normative_goal','unit':'people','location':'declared_service_queue','cohort':'declared_research_cohort','applicable_window':'declared_event_window'},
 'H':{'quantity':'completion_allowance_after_last_entry','role':'normative_goal','unit':'hours','location':'declared_service_queue','cohort':'declared_research_cohort','completion_boundary':'leave_declared_service_queue','applicable_window':'declared_event_window'}}
reviews=[]
for c in audit['parameter_candidate_review']:
    r=screen_candidate(c['metadata'],targets[c['target']])
    if r['status']!=c['decision']:raise AssertionError('candidate metadata mismatch')
    reviews.append({'id':c['id'],**r})
check('安置色标和时差不填实际K/H',all(r['status']=='REJECT_SCOPE' and not r['actual_parameter_assigned'] for r in reviews),reviews)
matched=deepcopy(targets['K'])
check('同口径正对照仍不自动赋实际参数',screen_candidate(matched,targets['K'])['status']=='ALIGNED_REFERENCE' and not screen_candidate(matched,targets['K'])['actual_parameter_assigned'],{'hypothesis_only':True,'scope_alignment_not_safety_certification':True})
unknown=deepcopy(matched);unknown['applicable_window']=None
check('未知适用窗口不当作明确冲突',screen_candidate(unknown,targets['K'])['status']=='UNRESOLVED_METADATA',{'hypothesis_only':True,'not_rejected_solely_due_to_missing_date':True})
matched['publication_date']='2018-02-06'
check('旧发布日期本身不证明规则失效',screen_candidate(matched,targets['K'])['status']=='ALIGNED_REFERENCE',{'hypothesis_only':True,'publication_date_distinct_from_applicable_window':True})

holiday=claims['holiday_reference']
check('210列是区域计划而非虹桥疏运实绩',holiday['planned_train_scope']=='长三角铁路' and holiday['executed_night_trains'] is None and holiday['local_effective_service_people_per_hour'] is None,{'planned_trains':210,'role':holiday['train_role']})
check('46.8预测和44.3口径未明不合成区间',holiday['forecast_hongqiao_station_daily_arrival_person_trips']==468000 and not holiday['values_form_common_interval'] and not holiday['hub_443000_cohort_and_date_confirmed'],{'forecast_station':468000,'reported_hub':443000,'not_night_queue_Q':True})
check('发布概要采用主管机关且不冒充正文',claims['standard_reference']['preferred_source']=='R2-11' and not claims['standard_reference']['formal_fulltext_obtained'],{'same_origin_summary_records':['R2-06','R2-11'],'not_K_H_or_F_mapping':True})
readiness=[{'event':e['event_id'],**event_readiness(e)} for e in audit['event_gap_audit']]
positive=deepcopy(audit['event_gap_audit'][0]);positive['fields']={k:'complete' for k in positive['fields']};positive['calculation_ready']=False
check('缺参状态由字段推导不只读取ready标记',all(not r['ready'] and r['unresolved_fields'] for r in readiness) and event_readiness(positive)['ready'],{'real_event_statuses':readiness,'complete_positive_control_hypothesis_only':True})

feeder=deepcopy(next(r for r in audit['planned_bus_services'] if r['id']=='BUS-DZ321'))
invalid=deepcopy(feeder);invalid['end_rule']['kind']='unknown_typo'
check('未知结束规则与异日末班时刻报错',rejected(lambda:window(invalid,'2026-10-05')) and rejected(lambda:window(feeder,'2026-10-05','2026-10-07T00:00:00')),{'no_silent_rule_fallback':True,'no_borrowing_from_other_night':True})
zero=grade_case({'q':1000,'d':2,'p':1},0,0)
initial=grade_case({'q':1000,'d':2,'p':1,'b0':1},0,0)
check('K为0允许无积压但初始超限仍失败',zero['grade']=='F0' and initial['grade']=='F3',{'hypothesis_only':True,'no_backlog_grade':zero['grade'],'initial_backlog_grade':initial['grade']})
case={'directions':{d:{'q':1000,'d':2,'b0':0,'k':0,'h':0} for d in ('A','B')},'resources':[{'id':'r','pool_id':'r','directions':['A','B'],'layer':0,'capacity':[[0,None,1000]]}],'plans':[{'id':'base','introduced_layer':0,'allocations':[{'resource_id':'r','direction':d,'segments':[[0,None,500]]} for d in ('A','B')]}],'joint_profiles':[{'id':'same','shapes':{'A':'uniform','B':'uniform'}}],'waiting_groups':[{'id':'s','directions':['A','B'],'k':0}]}
result=grade_directional(case)
check('方向与共享候客K为0边界一致',result['grade']=='F0' and result['plans'][0]['runs'][0]['waiting_groups'][0]['peak_people']==0,{'hypothesis_only':True,'grade':result['grade'],'shared_peak':0})

out={'version':'CHECK-REVIEW-01','date':'2026-10-11','checks':len(checks),'passed':len(checks),'readable_source_records':24,'new_readable_source_records':9,'excluded_round2_leads':3,'actual_parameters_assigned':0,'validation_scope':'metadata scope and transcription checks plus concrete numerical/calendar regressions; not empirical accuracy','results':checks}
(ROOT/'06_实验验证/分级方法验证/更新审查验证结果.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k!='results'},ensure_ascii=False))
