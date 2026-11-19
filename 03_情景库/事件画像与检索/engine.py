"""可追溯的结构化事件画像与示例检索；不执行调度。"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
VERSION = 'PORTRAIT-01'
FIELDS = ('event_type', 'cause', 'time_period', 'location', 'affected_people',
          'onward_people', 'arrival_profile', 'road_status', 'metro_status',
          'initial_queue', 'resource_inventory', 'safety_status', 'authorization')
MATCH = {'event_type': 4, 'cause': 2, 'time_period': 2, 'location': 2,
         'road_status': 1, 'metro_status': 1}
NUMERIC = {'affected_people', 'onward_people', 'initial_queue'}
STATUS = {'observed', 'forecast', 'assumption', 'unknown'}
# 仅做明确同义词映射；未知词保留原值，不推断地点包含关系。
ALIASES = {'event_type': {'铁路晚点集中到达':'列车晚点集中到达', '高铁晚点集中到达':'列车晚点集中到达'},
           'time_period': {'夜间时段':'夜间', '夜晚':'夜间'},
           'location': {'上海虹桥火车站':'虹桥火车站', '上海虹桥站':'虹桥火车站'},
           'cause': {'北方降雪':'降雪'}}

def canonical(name, value):
    return ALIASES.get(name, {}).get(value.strip(), value.strip()) if isinstance(value, str) else value

def validate(portrait):
    if not isinstance(portrait, dict) or portrait.get('schema_version') != VERSION:
        raise ValueError('需要 PORTRAIT-01 事件画像')
    if not isinstance(portrait.get('event_id'), str) or not portrait['event_id'].strip():
        raise ValueError('事件编号不能为空')
    if not isinstance(portrait.get('fields'), dict):
        raise ValueError('缺少字段集合')
    for name, item in portrait['fields'].items():
        if name not in FIELDS or not isinstance(item, dict):
            raise ValueError(f'未知或无效字段：{name}')
        state, value = item.get('status'), item.get('value')
        if state not in STATUS:
            raise ValueError(f'{name} 的数据状态无效')
        if state == 'unknown':
            if value is not None:
                raise ValueError(f'{name} 未知时必须为空')
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f'{name} 必须有值或标记未知')
        if name in NUMERIC and (type(value) not in (int, float) or not 0 <= value < 1e9):
            raise ValueError(f'{name} 必须为非负人数')
        if name == 'arrival_profile' and isinstance(value, dict):
            if not value or any(not isinstance(k, str) or not isinstance(v, list) or not v or any(type(x) not in (int, float) or not 0 <= x < 1e9 for x in v) for k, v in value.items()):
                raise ValueError('到达过程必须是群体编号到非负分时人数数组的映射')
        elif name not in NUMERIC and not isinstance(value, str):
            raise ValueError(f'{name} 必须为文字')
        if not isinstance(item.get('source'), str) or not item['source'].strip():
            raise ValueError(f'{name} 缺少来源或假设说明')
        when = item.get('as_of')
        if not isinstance(when, str):
            raise ValueError(f'{name} 缺少含时区的记录时间')
        try:
            dt = datetime.fromisoformat(when)
            if dt.utcoffset() is None:
                raise ValueError()
        except ValueError:
            raise ValueError(f'{name} 的时间必须使用带时区的 ISO 格式') from None
    return portrait

def field(portrait, name):
    return portrait.get('fields', {}).get(name, {'status': 'unknown', 'value': None})

def retrieve(portrait, catalog):
    validate(portrait)
    results = []
    for case in catalog:
        validate(case)
        # 相同事件的多篇报道不能成为自己的测试候选。
        if portrait.get('event_family_id', portrait['event_id']) == case.get('event_family_id', case['event_id']):
            continue
        comparable, match, same, different, missing = 0, 0, [], [], []
        for name, weight in MATCH.items():
            a, b = field(portrait, name), field(case, name)
            if a['status'] == 'unknown' or b['status'] == 'unknown':
                missing.append(name)
                continue
            comparable += weight
            if canonical(name, a['value']) == canonical(name, b['value']):
                match += weight
                same.append(name)
            else:
                different.append({'field': name, 'current': a['value'], 'case': b['value']})
        results.append({'case_id': case['event_id'], 'title': case['title'],
                        'similarity': round(match / comparable, 3) if comparable else None,
                        'coverage': round(comparable / sum(MATCH.values()), 3),
                        'coverage_note': '可比信息不足，需人工复核' if comparable / sum(MATCH.values()) < 0.5 else '覆盖率仅表示字段可比程度',
                        'same': same, 'different': different, 'missing': missing,
                        'source': case['source']})
    return sorted(results, key=lambda r: (r['similarity'] is not None, r['similarity'] or 0, r['coverage']), reverse=True)

def readiness(portrait):
    validate(portrait)
    mapping = {
        'onward_people': '各群体 profiles[].arrivals：需总量、去向及逐时段过程',
        'arrival_profile': 'profiles[].arrivals：逐群体、逐时间步',
        'initial_queue': 'groups[].initial_people：逐群体初始人数',
        'resource_inventory': 'modes/pools/links：资源、服务能力、准备和授权',
        'safety_status': 'nodes/links/facilities：安全及空间约束',
        'authorization': '方式可协调条件及人工确认',
    }
    return [{'field': name, 'status': field(portrait, name)['status'],
             'target': target, 'has_value': field(portrait, name)['status'] != 'unknown',
             'mapping_status': '待逐项核对单位、粒度和网络结构'}
            for name, target in mapping.items()]

def main():
    import argparse
    parser = argparse.ArgumentParser(description='事件画像检索与字段就绪检查')
    parser.add_argument('portrait', type=Path)
    parser.add_argument('--catalog', type=Path, default=HERE/'catalog.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    portrait = json.loads(args.portrait.read_text(encoding='utf-8'))
    cases = json.loads(args.catalog.read_text(encoding='utf-8'))
    output = {'version': VERSION, 'portrait': validate(portrait),
              'retrieval': retrieve(portrait, cases), 'mapping_check': readiness(portrait),
              'model_input_status': '未生成网络模型卡：仍需网络、逐时段需求及参数确认',
              'notice': '相似度为演示规则；历史数值不自动回填当前事件。'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('已输出画像与检索报告：', args.output)

if __name__ == '__main__':
    main()
