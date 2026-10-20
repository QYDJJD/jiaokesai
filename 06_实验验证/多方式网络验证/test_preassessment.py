"""Check the parameter-first screen against an independent cumulative queue."""
from pathlib import Path
import sys,copy,json,time,unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'04_建模/交互验证平台'))
sys.path.insert(0,str(ROOT/'06_实验验证/分级方法验证'))
from preassessment import assess,example,assessment_example
from independent_reference import CumulativeQueue,arrival_curve

class ParameterScreenChecks(unittest.TestCase):
    def test_four_resource_labels(self):
        for q,grade in [(500,0),(1000,1),(2000,2),(3000,3)]:
            c=example();c['new_people']=q
            self.assertEqual(assess(c)['grade_index'],grade)

    def test_all_tiers_and_profiles_match_independent_queue(self):
        for lead in [-30,0,60,120]:
            c=example();c['information_lead_minutes']=lead;c['initial_people']=50;r=assess(c)
            for i,tier in enumerate(r['tiers']):
                supply=[]
                for j,s in enumerate(c['resources'][:i+1]):
                    start=0 if j==0 else max(0,s['prepare_minutes']-lead)
                    if s['end_minutes']>start:supply.append((start/60,s['end_minutes']/60,s['rate_people_hour']))
                for shape,row in zip(['uniform','front','back'],tier['profiles']):
                    oracle=CumulativeQueue(arrival_curve(c['new_people'],c['entry_minutes']/60,shape),supply,c['initial_people']).result(r['deadline_minutes']/60)
                    self.assertAlmostEqual(row['peak_people'],float(oracle['peak_people']))
                    self.assertAlmostEqual(row['remaining_at_deadline'],float(oracle['residual_at_deadline_people']))
                    if oracle['clear_h'] is None:self.assertIsNone(row['clear_minutes'])
                    else:self.assertAlmostEqual(row['clear_minutes'],float(oracle['clear_h'])*60)

    def test_uncertainty_changes_same_size_grade(self):
        c=example();c['arrival_set']='uniform'
        self.assertEqual(assess(c)['grade_index'],1)
        c['arrival_set']='three';self.assertEqual(assess(c)['grade_index'],2)

    def test_late_information_does_not_remove_existing_service(self):
        c=example();c['information_lead_minutes']=-30
        self.assertEqual(assess(c)['resource_ready_minutes'],[0,90,90])

    def test_service_end_is_respected(self):
        c=example()
        for s in c['resources']:s['end_minutes']=30
        r=assess(c);self.assertEqual(r['grade_index'],3)
        self.assertIsNone(r['tiers'][-1]['latest_clear_minutes'])

    def test_nested_resources_cannot_lose_passed_case(self):
        for q in [0,500,1000,2000,3000]:
            c=example();c['new_people']=q;passed=[r['passed'] for r in assess(c)['tiers']]
            self.assertEqual(passed,sorted(passed))

    def test_missing_is_not_treated_as_zero(self):
        c=example();c['resources'][0]['rate_people_hour']=None
        with self.assertRaises(ValueError):assess(c)
        c['resources'][0]['rate_people_hour']=0
        self.assertEqual(assess(c)['status'],'provisional')

    def test_boundary_unknown_and_incompatible_are_not_grades(self):
        for field,val,status in [('eligibility','unsafe','boundary_stop'),('eligibility','unknown','needs_information'),('compatible_pool','no','needs_split'),('compatible_pool','unknown','needs_split'),('arrival_set','unknown','needs_information')]:
            c=example();c[field]=val;r=assess(c)
            self.assertEqual(r['status'],status);self.assertIsNone(r['grade_index'])

    def test_initial_backlog_cannot_be_erased_by_future_service(self):
        c=example();c['initial_people']=1001
        self.assertEqual(assess(c)['grade_index'],3)

    def test_zero_demand_with_zero_service(self):
        c=example();c['new_people']=0
        for s in c['resources']:s['rate_people_hour']=0
        r=assess(c);self.assertEqual(r['grade_index'],0)
        self.assertEqual(r['tiers'][0]['latest_clear_minutes'],0)

    def test_preliminary_grade_does_not_lock_network(self):
        from network_adapter import templates,evaluate
        c=templates()['tiny'];plain=evaluate(c,{'seconds':5})
        p=example();p['new_people']=3000
        c['preassessment']={'input':p,'result':{'grade_label':'伪造的旧结果'}}
        screened=evaluate(c,{'seconds':5})
        self.assertEqual(screened['status'],plain['status'])
        self.assertEqual(screened['audit']['plan']['cost_yuan'],plain['audit']['plan']['cost_yuan'])
        self.assertEqual(screened['preassessment']['screen']['grade_index'],3)
        self.assertFalse(screened['preassessment']['main_inputs_match'])

    def test_export_keeps_recomputed_preliminary_context(self):
        from network_adapter import templates,evaluate,report_html
        c=templates()['tiny'];c['preassessment']={'input':example(),'result':{'grade_index':0}}
        result=evaluate(c,{'mode':'manual'},{'reservations':[]})
        self.assertEqual(result['card']['preassessment']['result']['grade_index'],2)
        self.assertFalse(result['preassessment']['resource_mapping_verified'])
        self.assertIn('参数预判与细化核对',report_html(result).decode('utf-8'))

class EventEvaluationChecks(unittest.TestCase):
    def test_default_reports_indicators_without_own_resource_grade(self):
        r=assess(assessment_example())
        self.assertEqual(r['status'],'assessed');self.assertIsNone(r['grade_index'])
        self.assertEqual(r['tiers'],[]);self.assertEqual(len(r['profiles']),3)
        self.assertEqual(r['response_mapping']['status'],'not_automatically_mapped')

    def test_baseline_indicators_match_independent_queue(self):
        for rate in [250,500,1000,2000]:
            c=assessment_example();c['initial_people']=50;c['resources'][0]['rate_people_hour']=rate;r=assess(c)
            for shape,row in zip(['uniform','front','back'],r['profiles']):
                oracle=CumulativeQueue(arrival_curve(2000,2,shape),[(0,3,rate)],50).result(3)
                self.assertAlmostEqual(row['peak_people'],float(oracle['peak_people']))
                self.assertAlmostEqual(row['remaining_at_deadline'],float(oracle['residual_at_deadline_people']))
                if oracle['clear_h'] is None:self.assertIsNone(row['clear_minutes'])
                else:self.assertAlmostEqual(row['clear_minutes'],float(oracle['clear_h'])*60)

    def test_extra_historical_packages_do_not_change_primary_evaluation(self):
        c=assessment_example();plain=assess(c)
        c['resources']+=example()['resources'][1:]
        for r in c['resources'][1:]:r['rate_people_hour']=1e6
        self.assertEqual(plain['profiles'],assess(c)['profiles'])

    def test_official_reference_does_not_invent_response_level(self):
        c=assessment_example();c['reference_id']='rail_delay_linkage_2023';r=assess(c)
        self.assertEqual(r['external_reference']['type'],'官方处置机制')
        self.assertFalse(r['external_reference']['auto_grade_available']);self.assertIsNone(r['grade_index'])

    def test_unknown_reference_is_rejected(self):
        c=assessment_example();c['reference_id']='invented'
        with self.assertRaises(ValueError):assess(c)
        c=assessment_example();c['assessment_kind']='misspelled'
        with self.assertRaises(ValueError):assess(c)

    def test_zero_queue_target_has_no_infinite_ratio(self):
        c=assessment_example();c['queue_limit_people']=0;r=assess(c)
        self.assertTrue(all(row['queue_limit_ratio'] is None for row in r['profiles']))
        self.assertFalse(r['all_controls_met']);json.dumps(r,allow_nan=False)

    def test_unused_increment_can_be_unknown(self):
        c=assessment_example();c['resources'].append({'rate_people_hour':None})
        self.assertEqual(assess(c)['status'],'assessed')

    def test_export_keeps_assessment_and_external_scope(self):
        from network_adapter import templates,evaluate,report_html
        c=templates()['tiny'];d=assessment_example();d['reference_id']='multimodal_scheduling_2025'
        c['preassessment']={'input':d,'result':{'grade_index':2,'grade_label':'联合保障'}}
        result=evaluate(c,{'mode':'manual'},{'reservations':[]});screen=result['preassessment']['screen']
        self.assertIsNone(screen['grade_index']);self.assertEqual(result['card']['preassessment']['result']['tiers'],[])
        report=report_html(result).decode('utf-8');self.assertIn('事件评估与处置参照',report)
        self.assertIn('10.1016/j.trc.2025.105117',json.dumps(screen));self.assertNotIn('联合保障',report)

if __name__=='__main__':
    start=time.perf_counter();out=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    samples=[]
    for q in [500,1000,2000,3000]:
        c=example();c['new_people']=q;r=assess(c)
        samples.append({'input':c,'grade_label':r['grade_label'],'grade_index':r['grade_index']})
    report={'tests':out.testsRun,'failures':len(out.failures),'errors':len(out.errors),'seconds':round(time.perf_counter()-start,3),
      'test_groups':{'historical_resource_comparison':12,'event_conditions':8},
      'independent_profile_comparisons':{'historical_resource_comparison':36,'current_event_conditions':12},
      'scope':'旧资源包计算兼容性与当前事件指标评估；不把自拟档位当作当前创新点或真实分级准确率',
      'implementation_sha256':assess(example())['implementation_sha256'],'examples':samples}
    (Path(__file__).parent/'参数预判检查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if out.wasSuccessful() else 1)
