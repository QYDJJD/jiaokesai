"""Meaningful gates: exact tiny enumeration, invalid-input and physical traps."""
from pathlib import Path
import sys,json,copy,itertools,unittest,time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'04_建模/接续运输优化原型'))
from build_input import make_card
from model import solve,validate,tasks,assign_vehicles
from simulate import causal_greedy,replay,check_plan,verify_causality,audit_solution


def tiny():
    c=make_card();p=c['parameters'];d=c['directions'][0]
    c['five_dimensions'].update(new_onward_passengers=12,entry_duration_minutes=60)
    p.update(entry_minutes=60,deadline_minutes=60,budget_yuan=200,queue_limit_people=20,
             bus_fleet_size=1,bus_trip_limit=2,bus_seats=6,bus_legal_capacity=6,
             bus_standing_area_m2=1,bus_turnaround_minutes=0,bus_prepare_minutes=0,
             taxi_prepare_minutes=0,bus_service_end_minutes=60,taxi_service_end_minutes=60,
             vehicle_shift_end_minutes=90,taxi_total_blocks=0,taxi_max_blocks_per_step=0,
             receiver_close_minutes=120,standing_person_minutes_limit=0)
    d.update(share=1,initial_queue=0,queue_limit_people=20,base_people_per_hour=0,
             bus_ride_minutes=10,taxi_ride_minutes=10,base_ride_minutes=10,
             bus_trip_cost_yuan=100,receiver_people_per_hour=1000)
    c['directions']=[d];c['arrival_profiles']=[{'id':'tiny','label':'手算12人','hourly_people':[12]}]
    return c


class ModelTests(unittest.TestCase):
    def test_exact_enumeration_matches_solver(self):
        c=tiny();candidates=tasks(c);best=None;feasible=0
        for size in range(3):
            for indices in itertools.combinations(range(len(candidates)),size):
                selected=[{k:v for k,v in candidates[i].items() if k not in ('bay_slots','fleet_slots')}|{'start_minute':candidates[i]['start_slot']*10} for i in indices]
                try:
                    plan={'bus_tasks':assign_vehicles(selected,1),'taxi_blocks':[[0]*6]}
                    check_plan(c,plan)
                except AssertionError:continue
                policy=causal_greedy(c,plan,c['arrival_profiles'][0]);r=replay(c,plan,policy,c['arrival_profiles'][0])
                if r['all_targets_met']:
                    feasible+=1;best=min(best or float('inf'),r['total_wait_person_minutes'])
        result=solve(c,seconds=10,gap=0);audit=audit_solution(c,result)
        self.assertEqual(best,240)
        self.assertGreater(feasible,0)
        self.assertAlmostEqual(result['worst_wait_person_minutes'],best,places=3)
        self.assertEqual(audit['plan']['cost_yuan'],200)

    def test_zero_budget_proves_infeasible(self):
        c=tiny();c['parameters']['budget_yuan']=0
        r=solve(c,seconds=10,gap=0);self.assertFalse(r['has_solution']);self.assertEqual(r['phase_primary']['status'],2)

    def test_missing_capacity_rejected(self):
        c=tiny();c['parameters']['bus_legal_capacity']=None
        with self.assertRaises(ValueError):validate(c)

    def test_mismatched_population_rejected(self):
        c=tiny();c['five_dimensions']['new_onward_passengers']=10008
        with self.assertRaises(ValueError):validate(c)

    def test_late_preparation_removes_service(self):
        c=tiny();c['five_dimensions']['information_lead_minutes']=-60
        self.assertEqual(tasks(c),[])
        r=solve(c,seconds=10,gap=0);self.assertEqual(r['phase_primary']['status'],2)

    def test_zero_demand_needs_no_dispatch(self):
        c=tiny();c['five_dimensions']['new_onward_passengers']=0;c['arrival_profiles'][0]['hourly_people']=[0]
        r=solve(c,seconds=10,gap=0);a=audit_solution(c,r)
        self.assertEqual(a['plan']['cost_yuan'],0)
        self.assertEqual(a['profiles'][0]['mean_wait_minutes'],0)

    def test_nonanticipativity_rejects_different_same_history(self):
        c=tiny();c['arrival_profiles'].append({'id':'same','label':'同观测','hourly_people':[12]})
        r=solve(c,seconds=10,gap=0);audit_solution(c,r)
        bad=copy.deepcopy(r['scenario_policy']);bad[1]['flows']['base'][0][0]+=.1
        with self.assertRaises(AssertionError):verify_causality(c,bad)

    def test_vehicle_overlap_is_detected(self):
        c=tiny();c['parameters']['bus_fleet_size']=2
        cs=tasks(c);sel=[]
        for i in [0,1]:sel.append({k:v for k,v in cs[i].items() if k not in ('bay_slots','fleet_slots')}|{'start_minute':cs[i]['start_slot']*10,'vehicle_id':'重复占用'})
        with self.assertRaises(AssertionError):check_plan(c,{'bus_tasks':sel,'taxi_blocks':[[0]*6]})

    def test_future_service_detected(self):
        c=tiny();r=solve(c,seconds=10,gap=0)
        bad=copy.deepcopy(r['scenario_policy'][0]);bad['flows']['base'][0][0]=20
        with self.assertRaises(AssertionError):replay(c,r['common_plan'],bad,c['arrival_profiles'][0])

    def test_standing_and_density_really_limit_capacity(self):
        c=tiny();p=c['parameters']
        p.update(bus_trip_limit=1,bus_legal_capacity=12,bus_standing_area_m2=3,
                 standing_density_limit_people_m2=2,standing_person_minutes_limit=60,budget_yuan=100)
        r=solve(c,seconds=10,gap=0);a=audit_solution(c,r)
        self.assertAlmostEqual(a['profiles'][0]['standing_person_minutes'],60,places=3)
        self.assertAlmostEqual(a['profiles'][0]['max_standing_density_people_m2'],2,places=3)
        p['standing_person_minutes_limit']=0
        self.assertEqual(solve(c,seconds=10,gap=0)['phase_primary']['status'],2)
        p['standing_person_minutes_limit']=60;p['standing_density_limit_people_m2']=1
        self.assertEqual(solve(c,seconds=10,gap=0)['phase_primary']['status'],2)

    def test_closed_downstream_cannot_count_as_completion(self):
        c=tiny();c['parameters']['receiver_close_minutes']=60
        self.assertEqual(solve(c,seconds=10,gap=0)['phase_primary']['status'],2)

    def test_shared_throughput_cannot_be_added_twice(self):
        c=tiny();c['parameters']['shared_service_people_per_hour']=2
        self.assertEqual(solve(c,seconds=10,gap=0)['phase_primary']['status'],2)

    def test_initial_queue_is_part_of_task(self):
        c=tiny();c['directions'][0]['initial_queue']=4
        self.assertEqual(solve(c,seconds=10,gap=0)['phase_primary']['status'],2)


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ModelTests)
    start=time.perf_counter();result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'seconds':time.perf_counter()-start,'scope':'小例穷举、无解和缺参、无提前信息、零需求、因果性、车辆冲突及未来服务'}
    (ROOT/'06_实验验证/优化模型验证/测试结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
