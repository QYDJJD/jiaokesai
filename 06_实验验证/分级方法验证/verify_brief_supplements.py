"""Targeted supplementation for the self-contained mentor briefing.

Run: python -X utf8 verify_brief_supplements.py
All scenarios and targets below are synthetic, never Hongqiao calibration.
"""
from pathlib import Path
from copy import deepcopy
from itertools import product
from collections import Counter
import json
from finite_plan_search import enumerate_constant_plans
from directional_grading import grade_directional
from grading_engine import grade_case, EPS
from build_directional_library import cases

OUT = Path(__file__).resolve().parent


def main():
    checks = []
    def check(name, ok):
        checks.append({'name': name, 'pass': bool(ok)})
        if not ok:
            raise AssertionError(name)
    by_id = {c['id']: c['input'] for c in cases()}
    searches = []
    for sid in ('SC-N04', 'SC-N03'):
        original = deepcopy(by_id[sid])
        grid = enumerate_constant_plans(original)
        expanded = deepcopy(original)
        expanded['plans'] += grid['plans']
        result = grade_directional(expanded)
        expected = 'F0' if sid == 'SC-N04' else 'F1'
        check(sid + '_exhaustive_grid_grade', result['grade'] == expected)
        if sid == 'SC-N04':
            balanced_id = next(p['id'] for p in grid['plans'] if
                               {a['direction']: a['segments'][0][2] for a in p['allocations']} == {'A': 1000, 'B': 1000})
            passing_id = next(p['id'] for p in result['plans'] if p['pass'] and p['id'] == balanced_id)
        else:
            passing_id = next(p['id'] for p in result['plans'] if p['pass'])
        passing_plan = next(p for p in expanded['plans'] if p['id'] == passing_id)
        searches.append({'case_id': sid, 'original_grade': grade_directional(original)['grade'],
                         'expanded_grade': result['grade'],
                         **{k: v for k, v in grid.items() if k != 'plans'},
                         'passing_example': passing_plan,
                         'passing_example_result': next(p for p in result['plans'] if p['id'] == passing_id),
                         'passing_count_by_tier': [len(t['passing_plan_ids']) for t in result['tiers']]})
    check('N04_grid_count_by_independent_triangle_formula', searches[0]['feasible_plan_count'] == 21 * 22 // 2)
    check('N03_shared_lower_bound_rejects_all_V0_plans', 2 * max(1000 / 2.5, (1000 - 400) / 2) > 600 and searches[1]['passing_count_by_tier'][0] == 0)
    # Reject unsupported windows and incomplete searches, rather than claiming completeness.
    for name, x, kwargs in [('window', deepcopy(by_id['SC-N06']), {}),
                            ('budget', deepcopy(by_id['SC-N04']), {'max_combinations': 10}),
                            ('zero_step', deepcopy(by_id['SC-N04']), {'step': 0})]:
        try:
            enumerate_constant_plans(x, **kwargs)
            ok = False
        except ValueError:
            ok = True
        check('search_rejects_' + name, ok)
    # Non-multiple capacity is floored only for grid completeness, not physical capacity.
    small = deepcopy(by_id['SC-N04']); small['resources'][0]['capacity'] = [[0, None, 250]]
    tiny = enumerate_constant_plans(small, 100)
    check('grid_retains_unused_capacity', tiny['feasible_plan_count'] == 6 and any(not p['allocations'] for p in tiny['plans']))

    axes = {'P1_hours': [0, 1], 'U_shapes': [['uniform'], ['uniform', 'front', 'back']],
            'D_hours': [1, 2, 4], 'Q_people': [1000, 2000, 3000],
            'R_base_end_hours': [None, 1]}
    rows = []
    for p, shapes, d, q, end in product(*axes.values()):
        params = {'p': p, 'shapes': shapes, 'd': d, 'q': q, 'ends': [end, None, None]}
        result = grade_case(params, k=1000, h=1)
        rows.append({'id': 'C-' + str(len(rows) + 1).zfill(2), 'input': params, 'result': result})
    check('five_axis_declared_cartesian_grid_has_72_combinations', len(rows) == 2 * 2 * 3 * 3 * 2 and len({json.dumps(r['input'], sort_keys=True) for r in rows}) == 72)
    check('coverage_grid_has_no_invalid_configuration', all(r['result']['grade'].startswith('F') for r in rows))
    # Distinct from empirical accuracy: check declared comparative expectations.
    def find(p, shapes, d, q, end):
        return next(r['result'] for r in rows if r['input'] == {'p': p, 'shapes': shapes, 'd': d, 'q': q, 'ends': [end, None, None]})
    check('advance_and_uncertainty_orders_across_grid',
          all(int(find(1, shapes, d, q, end)['grade'][1]) <= int(find(0, shapes, d, q, end)['grade'][1])
              for shapes, d, q, end in product(axes['U_shapes'], axes['D_hours'], axes['Q_people'], axes['R_base_end_hours']))
          and all(int(find(p, ['uniform'], d, q, end)['grade'][1]) <= int(find(p, ['uniform', 'front', 'back'], d, q, end)['grade'][1])
                  for p, d, q, end in product(axes['P1_hours'], axes['D_hours'], axes['Q_people'], axes['R_base_end_hours'])))
    check('closing_base_service_cannot_improve_grade', all(int(find(p, shapes, d, q, None)['grade'][1]) <= int(find(p, shapes, d, q, 1)['grade'][1])
          for p, shapes, d, q in product(axes['P1_hours'], axes['U_shapes'], axes['D_hours'], axes['Q_people'])))
    # Missing actual targets: independently derived constant-rate requirements.
    bounds = []
    for k, h in product([0, 500, 1000], [0, 1, 2]):
        c = max(2000 / (2 + h), (2000 - k) / 2, 0)
        bounds.append({'Q': 2000, 'D': 2, 'B0': 0, 'K': k, 'H': h, 'C_min_people_per_hour': c})
    check('goal_boundaries_match_expected_values', abs(next(b['C_min_people_per_hour'] for b in bounds if b['K'] == 1000 and b['H'] == 1) - 2000 / 3) < EPS
          and all(b['C_min_people_per_hour'] == 1000 for b in bounds if b['K'] == 0 or b['H'] == 0))
    output = {'version': 'CHECK-BRIEF-01', 'date': '2026-10-11', 'evidence_type': 'SYNTHETIC',
              'checks': checks, 'finite_searches': searches,
              'coverage_grid': {'axes': axes, 'goals': {'K_people': 1000, 'H_hours': 1, 'B0_people': 0},
                                'reference': '500 base, 500+1000 increments; activation lag 1h; start=max(0,1-P1)',
                                'count': len(rows), 'grade_counts': dict(Counter(r['result']['grade'] for r in rows)), 'rows': rows},
              'constant_rate_target_boundaries': bounds,
              'limitations': ['finite constant-rate grid only', 'chosen levels are not calibrated',
                              'no population or probability coverage', 'no independent actual event validation']}
    (OUT / '汇报补强验证结果.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'checks': len(checks), 'all_pass': all(c['pass'] for c in checks),
                      'searches': [{k: s[k] for k in ('case_id', 'original_grade', 'expanded_grade', 'raw_combinations', 'feasible_plan_count')} for s in searches],
                      'coverage_combinations': len(rows), 'grade_counts': output['coverage_grid']['grade_counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
