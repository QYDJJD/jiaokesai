"""Generalization, network timing and resource tests with independent replay."""
from pathlib import Path
import sys,copy,json,unittest,time,itertools
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'04_建模/多方式网络优化'));sys.path.insert(0,str(ROOT/'04_建模/交互验证平台'))
from network_schema import validate
from network_examples import tiny,multimodal,ferry,templates,mode,link,node,group
from network_model import solve,assign_units
from network_audit import audit_solution,replay,greedy_policy,check_plan,verify_causality
from network_adapter import make_manual_plan,write_exports,evaluate

def run(card,objective='journey_time'):
    result=solve(card,seconds=5,gap=0,objective=objective)
    return result,audit_solution(card,result) if result['has_solution'] else None

def resize(card,deadline):
    card['parameters']['deadline_minutes']=deadline;T=int(deadline/card['parameters']['step_minutes'])
    for row in card['nodes']+card['links']:
        for k in ('fixed_capacity','fixed_seats','fixed_standing_area_m2','max_units','boarding_capacity','receiving_capacity'):
            if isinstance(row.get(k),list):row[k]=[row[k][i] if i<len(row[k]) else 0 for i in range(T)]

class GeneralNetworkChecks(unittest.TestCase):
    def test_tiny_exact_journey_and_separate_endpoints(self):
        r,a=run(tiny());row=a['profiles'][0]
        self.assertAlmostEqual(row['total_wait_person_minutes'],240);self.assertAlmostEqual(row['total_journey_person_minutes'],360)
        self.assertEqual(row['origin_clear_minutes'],60);self.assertEqual(row['completion_minutes'],70)

    def test_tiny_exhaustive_schedule_agrees(self):
        c=tiny();best=None
        for a,b in itertools.combinations(range(6),2):
            try:
                plan=assign_units(c,[{'link_id':'route','start_step':a,'units':1},{'link_id':'route','start_step':b,'units':1}])
                check_plan(c,plan);row=replay(c,plan,greedy_policy(c,plan,c['profiles'][0]),c['profiles'][0])
            except AssertionError:continue
            if row['all_targets_met']:best=min(best or float('inf'),row['total_journey_person_minutes'])
        r,a=run(c);self.assertEqual(best,360);self.assertAlmostEqual(r['phase_primary']['objective'],best)

    def test_four_modes_and_transfer_are_used(self):
        r,a=run(multimodal());used=set().union(*(row['by_mode_boardings'] for row in a['profiles']))
        self.assertEqual(used,{'walk','metro','shuttle','ride'});self.assertEqual(a['plan']['cost_yuan'],190)

    def test_mode_identifiers_and_names_do_not_change_result(self):
        c=multimodal();r1,a=run(c);mapping={m['id']:'arbitrary_'+str(i) for i,m in enumerate(c['modes'])}
        for m in c['modes']:m.update(id=mapping[m['id']],label='任意命名运输方式')
        for a in c['links']:a['mode_id']=mapping[a['mode_id']]
        for g in c['groups']:g['allowed_modes']=[mapping[mid] for mid in g['allowed_modes']]
        r2,a=run(c);self.assertAlmostEqual(r1['worst_objective_value'],r2['worst_objective_value'],places=3);self.assertAlmostEqual(r1['cost_yuan'],r2['cost_yuan'])

    def test_adding_a_fifth_mode_needs_no_new_solver_branch(self):
        c=multimodal();c['modes'].append(mode('extra','任意新增轨道方式'))
        c['links'].append(link('express','新增直达服务','H','D','extra',travel=10,fixed=200,seats=200))
        c['groups'][0]['allowed_modes'].append('extra');r,a=run(c)
        self.assertEqual(a['plan']['cost_yuan'],0);self.assertTrue(all(row['by_mode_boardings']['extra']>=120-1e-4 for row in a['profiles']))

    def test_water_network_uses_same_solver(self):
        r,a=run(ferry());row=a['profiles'][0]
        self.assertEqual(row['delivered_people'],80);self.assertEqual(row['by_mode_boardings']['water'],80);self.assertEqual(row['completion_minutes'],60)

    def test_closing_only_reachable_transport_is_infeasible(self):
        c=ferry();c['modes'][1]['enabled']=False;r,a=run(c)
        self.assertFalse(r['has_solution']);self.assertEqual(r['phase_primary']['status'],2)

    def test_cancelled_service_cannot_use_remaining_seat_declaration(self):
        c=ferry();c['links'][1]['fixed_capacity']=[0]*8
        r,a=run(c);self.assertEqual(r['phase_primary']['status'],2)

    def test_different_total_demand_is_supported(self):
        c=multimodal();c['profiles'][1]['arrivals']['G']=[60,0,0];r,a=run(c)
        self.assertEqual([row['task_people'] for row in a['profiles']],[120,60]);self.assertTrue(all(row['all_targets_met'] for row in a['profiles']))

    def test_multiple_origins_and_destination_groups(self):
        c=ferry();c['nodes'] += [node('X','第二来源节点',100,100),node('C','第二目的节点',100,100)]
        c['links'].append(link('extra_source','第二来源直达','X','C','road',travel=10,fixed=100,seats=100))
        c['groups'].append(group('G2','第二来源旅客','X','C',['road']));c['profiles'][0]['arrivals']['G2']=[20,20]
        r,a=run(c);self.assertAlmostEqual(a['profiles'][0]['task_people'],120);self.assertAlmostEqual(a['profiles'][0]['delivered_people'],120)

    def test_disallowed_walking_prevents_instant_transfer(self):
        c=multimodal();c['groups'][0]['allowed_modes']=['metro'];r,a=run(c)
        self.assertEqual(r['phase_primary']['status'],2)

    def test_destination_deadline_cannot_be_replaced_by_origin_clearance(self):
        c=tiny();resize(c,60);r,a=run(c);self.assertEqual(r['phase_primary']['status'],2)

    def test_fixed_mode_cannot_be_dispatched_without_changing_scope(self):
        c=tiny();c['modes'][0]['control']='fixed'
        with self.assertRaisesRegex(ValueError,'既定服务'):validate(c)

    def test_interchange_queue_is_a_real_constraint(self):
        c=multimodal();c['parameters']['budget_yuan']=0;c['nodes'][1]['queue_limit_people']=20
        r,a=run(c);self.assertEqual(r['phase_primary']['status'],2)
        c['nodes'][1]['queue_limit_people']=40;r,a=run(c);self.assertIsNotNone(a)

    def test_measured_ferry_standing_load_changes_feasibility(self):
        c=ferry();c['links'][1]['fixed_seats']=[0,20,0,20,0,20,0,0];c['links'][1]['fixed_standing_area_m2']=10
        r,a=run(c);self.assertEqual(r['phase_primary']['status'],2)
        c['parameters']['standing_person_minutes_limit']=400;r,a=run(c);self.assertIsNotNone(a);self.assertAlmostEqual(a['profiles'][0]['standing_person_minutes'],400)
        c['modes'][1]['standing_density_limit']=0;r,a=run(c);self.assertEqual(r['phase_primary']['status'],2)

    def test_shared_passenger_bottleneck_is_enforced(self):
        c=tiny();c['facilities']=[{'id':'F','label':'共用通道','links':['route'],'capacity':1}]
        r,a=run(c);self.assertEqual(r['phase_primary']['status'],2)

    def test_manual_same_unit_collision_is_rejected(self):
        c=tiny();c['pools'][0]['available_units']=2
        manual={'reservations':[{'link_id':'route','start_minute':0,'units':1,'unit_ids':['同一车']},
                               {'link_id':'route','start_minute':10,'units':1,'unit_ids':['同一车']}]}
        with self.assertRaisesRegex(ValueError,'冲突'):make_manual_plan(c,manual)

    def test_boarding_occupancy_counts_units_not_just_people(self):
        c=tiny();c['pools'][0]['available_units']=2;c['links'][0]['max_units']=2
        c['occupancy_facilities']=[{'id':'bay','label':'可用登乘位','links':['route'],'available_units':1}]
        plan=assign_units(c,[{'link_id':'route','start_step':0,'units':2}])
        with self.assertRaisesRegex(AssertionError,'登乘位'):check_plan(c,plan)

    def test_people_still_boarding_remain_in_queue_safety_count(self):
        c=tiny();c['links'][0]['boarding_minutes']=20;c['pools'][0]['available_units']=2;c['nodes'][0]['queue_limit_people']=3
        r,a=run(c)
        # At minute 10 the first two people cannot have finished a 20-minute
        # boarding process; two new people already make four in the area.
        self.assertEqual(r['phase_primary']['status'],2)

    def test_same_history_tampering_is_detected(self):
        c=multimodal();c['profiles'][1]['arrivals']['G']=[60,0,60];r,a=run(c);policies=copy.deepcopy(r['scenario_policy'])
        target=next(v for v in policies[1]['flows'] if v['start_step']==0);target['people']+=.1
        with self.assertRaisesRegex(AssertionError,'观测历史'):verify_causality(c,policies)

    def test_replay_rejects_passengers_before_they_enter(self):
        c=tiny();plan=assign_units(c,[{'link_id':'route','start_step':0,'units':1}]);policy={'profile_id':'uniform','flows':[{'group_id':'G','link_id':'route','start_step':0,'people':6}]}
        with self.assertRaisesRegex(AssertionError,'尚未'):replay(c,plan,policy,c['profiles'][0])

    def test_zero_budget_and_zero_demand_have_distinct_results(self):
        c=tiny();c['parameters']['budget_yuan']=0;r,a=run(c);self.assertEqual(r['phase_primary']['status'],2)
        c['profiles'][0]['arrivals']['G']=[0]*6;r,a=run(c);self.assertEqual(a['plan']['cost_yuan'],0);self.assertEqual(a['profiles'][0]['completion_minutes'],0)

    def test_manual_legal_but_unfinished_is_reported(self):
        c=tiny();r=evaluate(c,{'mode':'manual'},{'reservations':[{'link_id':'route','start_minute':20,'units':1}]})
        self.assertEqual(r['status'],'failed_targets');self.assertAlmostEqual(r['audit']['profiles'][0]['remaining_people'],6);self.assertIsNone(r['audit']['profiles'][0]['mean_journey_minutes'])

    def test_legacy_conversion_preserves_facts_and_separates_deadlines(self):
        c=templates()['hongqiao'];validate(c)
        self.assertEqual(c['event_background']['facts']['affected_passengers'],10008)
        self.assertEqual(c['parameters']['origin_departure_deadline_minutes'],390)
        self.assertGreater(c['parameters']['deadline_minutes'],390)

if __name__=='__main__':
    started=time.perf_counter();out=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    summary={'tests':out.testsRun,'failures':len(out.failures),'errors':len(out.errors),'seconds':round(time.perf_counter()-started,3),
      'scope':'数据驱动方式与网络、不同需求总量、换乘时序、站立、共享资源、因果分配及旧卡迁移；不等于真实效果验证'}
    (Path(__file__).parent/'通用性与约束检查.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if out.wasSuccessful() else 1)
