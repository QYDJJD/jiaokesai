"""比较独立、显式设定的资源情景；不推断现实资源的可用性或授权。"""
from copy import deepcopy
from math import isfinite
from unserved_diagnostic import diagnose

FIELDS = {
    'parameters': {'budget_yuan', 'deadline_minutes', 'origin_departure_deadline_minutes'},
    'pools': {'available_units', 'total_units_limit', 'prepare_minutes', 'close_minutes', 'turnaround_minutes'},
    'links': {'max_units', 'service_start_minutes', 'service_end_minutes'},
}


def apply_changes(card, changes):
    revised = deepcopy(card)
    seen = set()
    for change in changes:
        target, field = change['target'], change['field']
        identifier = change.get('id')
        if target not in FIELDS or field not in FIELDS[target]:
            raise ValueError('不支持修改该资源字段')
        key = (target, identifier, field)
        if key in seen:
            raise ValueError('同一情景中不能重复修改同一字段')
        seen.add(key)
        if target == 'parameters':
            if identifier is not None: raise ValueError('参数项不使用 id')
            row = revised['parameters']
        else:
            matches = [r for r in revised[target] if r['id'] == identifier]
            if len(matches) != 1: raise ValueError('资源或线路 id 不存在或不唯一')
            row = matches[0]
        value = change['value']
        numbers = value if isinstance(value, list) else [value]
        if not numbers or any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in numbers):
            raise ValueError('修改值须为有限非负数或非空数值数组')
        if isinstance(value, list) and field != 'max_units':
            raise ValueError('只有线路每段增援上限支持数组')
        row[field] = deepcopy(value)
    return revised


def compare(card, variants, seconds=15):
    """基准与每个变体独立求解；未证明最优时不宣称差异为改善量。"""
    if not variants: raise ValueError('至少提供一个比较情景')
    names = [v['name'] for v in variants]
    if any(not isinstance(n, str) or not n.strip() for n in names) or len(set(names)) != len(names) or '基准' in names:
        raise ValueError('情景名称须非空、唯一且不能使用基准')
    base = diagnose(card, seconds=seconds)
    def row(name, changes, result):
        return {'name': name, 'changes': deepcopy(changes), 'has_solution': result['has_solution'],
                'minimum_certified': result['minimum_certified'], 'worst_unserved': result.get('worst_unserved'),
                'profiles': result.get('profiles'), 'phase': result['phase'], 'input_sha256': result['input_sha256']}
    rows = [row('基准', [], base)]
    for variant in variants:
        changes = variant['changes']
        try:
            result = diagnose(apply_changes(card, changes), seconds=seconds)
            item = row(variant['name'], changes, result)
            item['certified_reduction_people'] = (base['worst_unserved'] - result['worst_unserved']
                if base['minimum_certified'] and result['minimum_certified'] else None)
        except (ValueError, KeyError, TypeError) as exc:
            item = {'name': variant['name'], 'changes': deepcopy(changes), 'error': str(exc),
                    'has_solution': False, 'minimum_certified': False, 'certified_reduction_people': None}
        rows.append(item)
    return {'scope': '各变体独立相对基准，结果仅对输入数据和已列举情景有效；不代表授权或实际调度。', 'scenarios': rows}
