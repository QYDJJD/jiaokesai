"""Enumerate an explicitly bounded grid of constant resource reservations.

This supplements listed plans; it does not solve continuous or adaptive
dispatch. Every resource/group must have one constant [0, None, rate] curve.
The grid includes unused capacity and all eligible direction allocations.
"""
from itertools import product
from math import floor, isfinite
from directional_grading import validate_plan


def constant_rate(curve):
    if len(curve) != 1 or curve[0][0] != 0 or curve[0][1] is not None:
        raise ValueError('search supports only constant service from time zero')
    rate = curve[0][2]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not isfinite(rate) or rate < 0:
        raise ValueError('invalid constant capacity')
    return rate


def enumerate_constant_plans(case, step=100, max_combinations=100000):
    """Return every feasible plan on this grid, or reject an unsupported input.

    The budget counts the Cartesian product BEFORE filtering. Exceeding it
    raises rather than silently truncates a claimed exhaustive search.
    The introduced layer is the highest layer of any actually used resource.
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) or not isfinite(step) or step <= 0:
        raise ValueError('positive finite grid step required')
    if isinstance(max_combinations, bool) or not isinstance(max_combinations, int) or max_combinations <= 0:
        raise ValueError('positive integer search budget required')
    resources = case['resources']; groups = case.get('groups', [])
    if not resources:
        raise ValueError('resource inventory required')
    # Validate identities, eligibility and groups even for zero reservations.
    validate_plan(resources, groups, case['directions'], {'allocations': []}, 2)
    group_rates = {g['id']: constant_rate(g['capacity']) for g in groups}
    options = []; size = 1
    for res in resources:
        rate = constant_rate(res['capacity'])
        if len(set(res['directions'])) != len(res['directions']):
            raise ValueError('duplicate resource direction')
        units = floor(rate / step + 1e-10)
        vectors = []
        # Bound intermediate enumeration before materializing it.
        if (units + 1) ** len(res['directions']) > max_combinations:
            raise ValueError('resource grid exceeds search budget')
        for values in product(range(units + 1), repeat=len(res['directions'])):
            if sum(values) <= units:
                vectors.append(values)
        size *= len(vectors)
        if size > max_combinations:
            raise ValueError('Cartesian grid exceeds search budget')
        options.append(vectors)
    plans = []; rejected = 0
    for index, vectors in enumerate(product(*options)):
        totals = {r['id']: step * sum(v) for r, v in zip(resources, vectors)}
        if any(sum(totals[rid] for rid in g['resource_ids']) > group_rates[g['id']] + 1e-9 for g in groups):
            rejected += 1
            continue
        allocations = []; layer = 0
        for res, values in zip(resources, vectors):
            for direction, units in zip(res['directions'], values):
                if units:
                    layer = max(layer, res['layer'])
                    allocations.append({'resource_id': res['id'], 'direction': direction,
                                        'segments': [[0, None, step * units]]})
        plan = {'id': 'grid-' + str(index), 'introduced_layer': layer, 'allocations': allocations}
        validate_plan(resources, groups, case['directions'], plan, layer)
        plans.append(plan)
    return {'step_people_per_hour': step, 'raw_combinations': size,
            'rejected_shared_capacity': rejected, 'feasible_plan_count': len(plans),
            'exhaustive_within_declared_grid': True, 'plans': plans,
            'scope': 'constant rates from t=0; fixed reservations; grid multiples; no adaptive or continuous optimum'}
