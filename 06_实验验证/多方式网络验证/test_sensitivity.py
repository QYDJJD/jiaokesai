from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '04_建模/多方式网络优化'))
from network_examples import tiny
from resource_sensitivity import compare, apply_changes


class SensitivityChecks(unittest.TestCase):
    def setUp(self):
        self.card = tiny()
        self.card['parameters']['budget_yuan'] = 100

    def test_independent_variants_and_bottleneck(self):
        original = deepcopy(self.card)
        variants = [
            {'name': '预算', 'changes': [{'target': 'parameters', 'field': 'budget_yuan', 'value': 200}]},
            {'name': '车辆', 'changes': [{'target': 'pools', 'id': 'fleet', 'field': 'available_units', 'value': 2}]},
        ]
        rows = compare(self.card, variants, seconds=5)['scenarios']
        self.assertEqual(self.card, original)
        self.assertEqual([r['worst_unserved'] for r in rows], [6, 0, 6])
        self.assertEqual([r['certified_reduction_people'] for r in rows[1:]], [6, 0])
        self.assertTrue(all(r['minimum_certified'] for r in rows))

    def test_invalid_and_infeasible_not_reported_as_zero(self):
        variants = [
            {'name': '错误字段', 'changes': [{'target': 'pools', 'id': 'fleet', 'field': 'seats', 'value': 8}]},
            {'name': '候车不足', 'changes': [{'target': 'parameters', 'field': 'budget_yuan', 'value': 0}]},
        ]
        self.card['nodes'][0]['queue_limit_people'] = 5
        # Baseline itself is feasible: six people can travel; zero budget is infeasible.
        rows = compare(self.card, variants, seconds=5)['scenarios']
        self.assertIn('error', rows[1]); self.assertFalse(rows[2]['has_solution'])
        self.assertIsNone(rows[2]['worst_unserved']); self.assertIsNone(rows[2]['certified_reduction_people'])

    def test_deadline_does_not_extend_resource_calendars(self):
        self.card['nodes'][0]['boarding_capacity'] = [100] * 8
        result = compare(self.card, [{'name': '延期', 'changes': [
            {'target': 'parameters', 'field': 'deadline_minutes', 'value': 100}]}], seconds=5)['scenarios'][1]
        self.assertIn('error', result)
        self.assertIn('10段', result['error'])

    def test_duplicate_change_rejected(self):
        change = {'target': 'parameters', 'field': 'budget_yuan', 'value': 200}
        with self.assertRaises(ValueError): apply_changes(self.card, [change, change])

    def test_uncertified_solution_does_not_claim_reduction(self):
        def fake(card, seconds):
            return {'has_solution': True, 'minimum_certified': False, 'worst_unserved': 4,
                    'profiles': [], 'phase': {'status': 1}, 'input_sha256': 'example'}
        with patch('resource_sensitivity.diagnose', side_effect=fake):
            row = compare(self.card, [{'name': '预算', 'changes': [
                {'target': 'parameters', 'field': 'budget_yuan', 'value': 200}]}])['scenarios'][1]
        self.assertEqual(row['worst_unserved'], 4)
        self.assertIsNone(row['certified_reduction_people'])


if __name__ == '__main__': unittest.main()
