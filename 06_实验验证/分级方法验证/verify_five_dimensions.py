"""Controlled tests of the five scenario descriptors, not field calibration.

All levels are synthetic. Other descriptors, goals and reference resources are
held fixed within each contrast. D is also contrasted at a fixed absolute
deadline to separate arrival compression from a changed completion deadline.
"""
from pathlib import Path
from copy import deepcopy
from itertools import combinations
from collections import defaultdict
import json
from grading_engine import grade_case
from independent_reference import reference_single_grade

ROOT = Path(__file__).resolve().parent


def main():
    checks = []
    def check(name, ok):
        checks.append({'name': name, 'pass': bool(ok)})
        if not ok:
            raise AssertionError(name)

    axes = {'P1': 'p', 'U': 'shapes', 'D': 'd', 'Q': 'q', 'R': 'ends'}
    data = json.loads((ROOT / '汇报补强验证结果.json').read_text(encoding='utf-8'))
    rows = data['coverage_grid']['rows']
    check('all_72_grades_match_independent_reference', all(
        r['result']['grade'] == reference_single_grade(r['input']) for r in rows))
    summaries = []
    for label, field in axes.items():
        groups = defaultdict(list)
        for row in rows:
            other = {k: v for k, v in row['input'].items() if k != field}
            groups[json.dumps(other, sort_keys=True)].append(row)
        pairs = []
        for group in groups.values():
            for left, right in combinations(group, 2):
                changed = [k for k in left['input'] if left['input'][k] != right['input'][k]]
                check(label + '_only_target_field_changes_' + left['id'] + '_' + right['id'], changed == [field])
                pairs.append({'left': left['id'], 'right': right['id'],
                              'left_level': left['input'][field], 'right_level': right['input'][field],
                              'left_grade': left['result']['grade'], 'right_grade': right['result']['grade']})
        different = [p for p in pairs if p['left_grade'] != p['right_grade']]
        check(label + '_has_a_nonredundancy_witness', bool(different))
        summaries.append({'axis': label, 'pair_count': len(pairs),
                          'grade_changes': len(different), 'pairs': pairs})

    common = {'p': 1, 'shapes': ['uniform'], 'q': 2000, 'd': 2,
              'ends': [None, None, None], 'b0': 0}
    designs = [
        ('P1', dict(common, q=3500, p=1), dict(common, q=3500, p=0), 1, 1),
        ('U', common, dict(common, shapes=['uniform', 'front', 'back']), 1, 1),
        ('D', common, dict(common, d=0.5), 1, 2.5),
        ('Q', dict(common, q=500), common, 1, 1),
        ('R', dict(common, q=1000, p=0), dict(common, q=1000, p=0, ends=[1, None, None]), 1, 1),
    ]
    expected = [('F2', 'F3'), ('F1', 'F2'), ('F1', 'F2'), ('F0', 'F1'), ('F0', 'F1')]
    witnesses = []
    for (label, a, b, ha, hb), grades in zip(designs, expected):
        ra, rb = grade_case(a, h=ha), grade_case(b, h=hb)
        check(label + '_witness_expected_grades', (ra['grade'], rb['grade']) == grades)
        check(label + '_witness_independent_reproduction',
              ra['grade'] == reference_single_grade(a, h=ha) and
              rb['grade'] == reference_single_grade(b, h=hb))
        if label == 'D':
            check('D_witness_has_identical_absolute_deadline', a['d'] + ha == b['d'] + hb == 3)
        witnesses.append({'axis': label, 'left': {'input': a, 'H': ha, 'result': ra},
                          'right': {'input': b, 'H': hb, 'result': rb}})

    # Five main descriptors alone cannot determine the grade: same descriptor
    # values but a different initial queue changes the result.
    a, b = common, dict(common, b0=1200)
    ra, rb = grade_case(a), grade_case(b)
    check('identical_five_descriptors_with_different_initial_queue_have_different_grades',
          ra['grade'] == 'F1' and rb['grade'] == 'F3')
    check('initial_queue_counterexample_matches_independent_reference',
          ra['grade'] == reference_single_grade(a) and rb['grade'] == reference_single_grade(b))

    out = {'version': 'FIVE-DIMENSIONS-01', 'evidence_type': 'SYNTHETIC',
           'scope': 'Five descriptor families plus required supporting fields; no minimality or real-world accuracy claim.',
           'grid_summary': summaries, 'controlled_witnesses': witnesses,
           'insufficiency_counterexample': {'left': {'input': a, 'result': ra}, 'right': {'input': b, 'result': rb}},
           'checks': checks,
           'interpretation': {'U': 'The grid varies allowed arrival sets around the same nominal uniform forecast, not observed spread.',
                              'D_grid': 'H=1 is fixed; the resulting absolute deadlines vary with D.',
                              'D_witness': 'Absolute deadline=3 is fixed; H is a derived quantity, not a relaxed completion target.',
                              'R_grid': 'Only the base service window is varied; other mode, location and direction states are not exhaustively covered.'}}
    (ROOT / '五维划分验证结果.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'all_pass': all(c['pass'] for c in checks), 'checks': len(checks),
                      'grid_summary': [{k: s[k] for k in ('axis', 'pair_count', 'grade_changes')} for s in summaries],
                      'controlled_grades': [{ 'axis': w['axis'], 'grades': [w['left']['result']['grade'], w['right']['result']['grade']]} for w in witnesses]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
