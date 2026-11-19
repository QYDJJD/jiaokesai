import copy
import json
from pathlib import Path
import unittest
import engine
import network_bridge
import verify_retrieval

HERE = Path(__file__).resolve().parent

class PortraitChecks(unittest.TestCase):
    def setUp(self):
        self.p = json.loads((HERE/'demo-事件画像.json').read_text(encoding='utf-8'))
        self.cases = json.loads((HERE/'catalog.json').read_text(encoding='utf-8'))

    def test_retrieval_explains_differences_and_does_not_fill_data(self):
        before = copy.deepcopy(self.p)
        result = engine.retrieve(self.p, self.cases)
        self.assertEqual(result[0]['case_id'], 'HQ-E02')
        self.assertEqual(self.p, before)
        self.assertTrue(any(d['field'] == 'cause' for d in result[0]['different']))
        self.assertIsNone(engine.field(self.p, 'onward_people')['value'])

    def test_unknown_is_not_zero(self):
        self.p['fields']['onward_people']['value'] = 0
        with self.assertRaises(ValueError): engine.validate(self.p)

    def test_missing_timestamp_or_source_rejected(self):
        del self.p['fields']['event_type']['as_of']
        with self.assertRaises(ValueError): engine.validate(self.p)

    def test_no_comparable_features_no_score(self):
        self.p['fields'] = {}
        self.assertTrue(all(r['similarity'] is None for r in engine.retrieve(self.p, self.cases)))

    def test_missing_inputs_stay_unavailable(self):
        rows = {r['field']: r for r in engine.readiness(self.p)}
        self.assertFalse(rows['onward_people']['has_value'])
        self.assertFalse(rows['resource_inventory']['has_value'])

    def test_low_coverage_perfect_match_does_not_precede_better_supported_case(self):
        query = copy.deepcopy(self.cases[0]); query['event_id'] = 'query'; query['event_family_id'] = 'query'
        sparse = copy.deepcopy(query); sparse.update(event_id='sparse',event_family_id='sparse',title='低覆盖')
        sparse['fields'] = {'event_type': query['fields']['event_type']}
        fuller = copy.deepcopy(query); fuller.update(event_id='full',event_family_id='full',title='较高覆盖')
        fuller['fields']['cause'] = {'value':'不同诱因','status':'observed','source':'测试','as_of':'2026-11-19T12:00:00+08:00'}
        ranked = engine.retrieve(query, [sparse,fuller])
        self.assertEqual(ranked[0]['case_id'],'full')
        self.assertEqual(ranked[1]['similarity'],1.0)
        self.assertLess(ranked[1]['coverage'],0.5)

class BridgeChecks(unittest.TestCase):
    def setUp(self):
        self.p = json.loads((HERE/'demo-合成画像.json').read_text(encoding='utf-8'))
        self.b = json.loads((HERE/'demo-合成参数包.json').read_text(encoding='utf-8'))

    def test_card_is_synthetic_and_matches_portrait(self):
        card, prov = network_bridge.make_card(self.p, self.b)
        self.assertEqual(sum(card['profiles'][0]['arrivals']['G']), 12)
        self.assertEqual(self.p['fields']['affected_people']['value'], 10008)
        self.assertEqual(prov['network_card_sha256'], network_bridge.digest(card))
        self.assertIn('合成', card['record_kind'])

    def test_disagreement_rejected(self):
        self.p['fields']['onward_people']['value'] = 13
        with self.assertRaises(ValueError): network_bridge.make_card(self.p, self.b)

    def test_missing_assumption_or_wrong_identity_rejected(self):
        del self.b['section_evidence']['pools']
        with self.assertRaises(ValueError): network_bridge.make_card(self.p, self.b)
        self.b['portrait_id'] = 'wrong'
        with self.assertRaises(ValueError): network_bridge.make_card(self.p, self.b)

    def test_bad_network_rejected(self):
        self.b['network_card']['parameters']['step_minutes'] = 7
        with self.assertRaises(ValueError): network_bridge.make_card(self.p, self.b)

    def test_profile_timing_conflict_with_equal_total_rejected(self):
        self.p['fields']['arrival_profile']['value']['G'] = [12,0,0,0,0,0]
        with self.assertRaisesRegex(ValueError, '分时到达'): network_bridge.make_card(self.p, self.b)

    def test_safety_and_authorization_gate(self):
        for field in ('safety_status', 'authorization'):
            p = copy.deepcopy(self.p)
            p['fields'][field] = {'value':None,'status':'unknown'}
            with self.assertRaises(ValueError): network_bridge.make_card(p, self.b)
        self.p['fields']['safety_status']['value'] = '不可继续运输'
        with self.assertRaises(ValueError): network_bridge.make_card(self.p, self.b)

    def test_provenance_includes_each_leaf(self):
        card, prov = network_bridge.make_card(self.p, self.b)
        paths = {row['path'] for row in prov['field_evidence']}
        self.assertIn('/profiles/0/arrivals/G/0', paths)
        self.assertIn('/groups/0/initial_people', paths)
        self.assertTrue(all(row['status'] == 'assumption' for row in prov['field_evidence']))

class RetrievalFixtureChecks(unittest.TestCase):
    def test_fixtures(self):
        cases = json.loads((HERE/'catalog.json').read_text(encoding='utf-8'))
        fixtures = json.loads((HERE/'检索测试样例.json').read_text(encoding='utf-8'))
        for fixture in fixtures:
            with self.subTest(fixture=fixture['id']):
                self.assertTrue(verify_retrieval.check(fixture, cases)['passed'])

if __name__ == '__main__': unittest.main()
