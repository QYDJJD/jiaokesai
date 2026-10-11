"""Exhaustive finite grid of precommitted piecewise reservations, not feedback control."""
from copy import deepcopy
from itertools import product
from math import isfinite
from finite_plan_search import enumerate_constant_plans
from directional_grading import validate_plan, rate_at


def enumerate_piecewise_plans(case, breaks, step=250, max_combinations=100000):
    if (len(breaks) < 2 or breaks[0] != 0 or
        any(isinstance(t, bool) or not isinstance(t, (int, float)) or not isfinite(t) for t in breaks) or
        any(b <= a for a, b in zip(breaks, breaks[1:]))):
        raise ValueError('strictly increasing finite breakpoints starting at zero required')
    if breaks[-1] < max(x['d'] + x['h'] for x in case['directions'].values()):
        raise ValueError('search horizon must include every completion deadline')
    validate_plan(case['resources'], case.get('groups', []), case['directions'], {'allocations': []}, 2)
    # Split at every physical capacity change, even if caller omitted it.
    points = sorted(set(breaks) | {t for r in case['resources'] + case.get('groups', [])
        for a, b, rate in r['capacity'] for t in (a, b) if t is not None and 0 < t < breaks[-1]})
    choices = []; counts = []; total = 1
    for a, b in zip(points, points[1:]):
        local = deepcopy(case)
        for r in local['resources'] + local.get('groups', []):
            r['capacity'] = [[0, None, rate_at(r['capacity'], (a+b)/2)]]
        grid = enumerate_constant_plans(local, step, max_combinations)
        choices.append(grid['plans']); counts.append(grid['feasible_plan_count'])
        total *= counts[-1]
        if total > max_combinations:
            raise ValueError('piecewise Cartesian grid exceeds search budget')
    plans = []
    for i, pieces in enumerate(product(*choices)):
        merged = {}; layer = 0
        for a, b, piece in zip(points, points[1:], pieces):
            layer = max(layer, piece['introduced_layer'])
            for x in piece['allocations']:
                key = (x['resource_id'], x['direction'])
                merged.setdefault(key, []).append([a, b, x['segments'][0][2]])
        plan = {'id': 'piecewise-' + str(i), 'introduced_layer': layer,
                'allocations': [{'resource_id': rid, 'direction': d, 'segments': seg}
                                for (rid, d), seg in merged.items()]}
        validate_plan(case['resources'], case.get('groups', []), case['directions'], plan, layer)
        plans.append(plan)
    return {'breakpoints': points, 'step_people_per_hour': step,
            'interval_feasible_counts': counts, 'feasible_plan_count': total, 'plans': plans,
            'scope': 'all fixed schedules on declared time/rate grid; zero service after horizon; no adaptive or continuous optimum'}
