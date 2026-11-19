"""固定规则下的合成功能检查；不当作统计准确率。"""
from pathlib import Path
import json
import engine

HERE = Path(__file__).resolve().parent

def check(fixture, catalog):
    query = {'schema_version':'PORTRAIT-01','event_id':'TEST-'+fixture['id'],
             'event_family_id':fixture.get('event_family_id','TEST-'+fixture['id']),
             'fields':{k:{'value':v,'status':'assumption','source':'人工设计功能测试',
                           'as_of':'2026-10-28T00:00:00+08:00'} for k,v in fixture['query'].items()}}
    rows = engine.retrieve(query, catalog)
    checks = {}
    if 'expected_first' in fixture: checks['first'] = bool(rows) and rows[0]['case_id'] == fixture['expected_first']
    if 'expected_in_top2' in fixture: checks['top2'] = set(fixture['expected_in_top2']) <= {r['case_id'] for r in rows[:2]}
    if 'expected_missing' in fixture: checks['missing'] = fixture['expected_missing'] in rows[0]['missing']
    if fixture.get('expected_difference'):
        row = next(r for r in rows if r['case_id']==fixture['difference_case'])
        checks['difference'] = any(d['field']==fixture['expected_difference'] for d in row['different'])
    if 'max_coverage' in fixture:
        row = next(r for r in rows if r['case_id']==fixture['coverage_case'])
        checks['coverage'] = row['coverage'] < fixture['max_coverage'] and '不足' in row['coverage_note']
    if fixture.get('all_scores_null'): checks['no_score'] = all(r['similarity'] is None for r in rows)
    if 'excluded_case' in fixture: checks['exclusion'] = fixture['excluded_case'] not in [r['case_id'] for r in rows]
    return {'id':fixture['id'],'description':fixture['description'],'checks':checks,'passed':all(checks.values()),
            'top_results':[{k:r[k] for k in ('case_id','similarity','coverage','coverage_note','same','different','missing')} for r in rows[:2]]}

def main():
    catalog = json.loads((HERE/'catalog.json').read_text(encoding='utf-8'))
    fixtures = json.loads((HERE/'检索测试样例.json').read_text(encoding='utf-8'))
    rows = [check(x,catalog) for x in fixtures]
    result = {'scope':'人工构造的功能样例；不是独立真实事件或检索准确率', 'weight_version':'MATCH规则固定',
              'tests':len(rows),'passed':sum(x['passed'] for x in rows),'results':rows}
    (HERE/'检索功能检查结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"检索功能检查 {result['passed']}/{result['tests']} 通过")
    if result['passed'] != result['tests']: raise SystemExit(1)

if __name__ == '__main__': main()
