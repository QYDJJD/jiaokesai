from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'04_建模/多方式网络优化'))
from network_examples import tiny
from network_model import solve
from unserved_diagnostic import diagnose

class UnservedChecks(unittest.TestCase):
    def test_complete(self):
        r=diagnose(tiny(),seconds=5)
        self.assertTrue(r['has_solution']);self.assertTrue(r['minimum_certified'])
        self.assertAlmostEqual(r['worst_unserved'],0)
    def test_budget_shortage_with_safe_queue(self):
        c=tiny();c['parameters']['budget_yuan']=0
        self.assertFalse(solve(c,seconds=5)['has_solution'])
        r=diagnose(c,seconds=5)
        self.assertTrue(r['has_solution']);self.assertTrue(r['minimum_certified'])
        self.assertAlmostEqual(r['worst_unserved'],12)
        self.assertTrue(r['profiles'][0]['safe_queue'])
        self.assertEqual(r['profiles'][0]['remaining_people'],12)
    def test_partial_budget(self):
        c=tiny();c['parameters']['budget_yuan']=100
        r=diagnose(c,seconds=5)
        self.assertTrue(r['has_solution']);self.assertTrue(r['minimum_certified'])
        self.assertAlmostEqual(r['worst_unserved'],6)
        self.assertAlmostEqual(r['profiles'][0]['delivered_people'],6)
    def test_multiple_profiles_share_reservations(self):
        c=tiny();c['parameters']['budget_yuan']=100
        c['profiles'].append({'id':'early','label':'提前到达','arrivals':{'G':[12,0,0,0,0,0]}})
        r=diagnose(c,seconds=5)
        self.assertTrue(r['has_solution']);self.assertTrue(r['minimum_certified'])
        self.assertEqual(len(r['profiles']),2)
        self.assertAlmostEqual(r['worst_unserved'],max(p['remaining_people'] for p in r['profiles']))
    def test_safety_is_not_relaxed(self):
        c=tiny();c['parameters']['budget_yuan']=0;c['nodes'][0]['queue_limit_people']=5
        r=diagnose(c,seconds=5)
        self.assertFalse(r['has_solution']);self.assertFalse(r['minimum_certified'])

if __name__=='__main__': unittest.main()
