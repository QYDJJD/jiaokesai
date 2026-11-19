"""显式假设研究卡桥接；不会将历史报道自动转成网络数据。"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '04_建模/多方式网络优化'))
from network_schema import validate as validate_network, totals

REQUIRED_SECTIONS = ('parameters', 'five_dimensions', 'nodes', 'modes', 'pools', 'links', 'groups', 'profiles', 'facilities')

def leaves(value, path=''):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, path+'/'+key.replace('~','~0').replace('/','~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, path+'/'+str(index))
    else:
        yield path, value

def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

def make_card(portrait, bundle):
    engine.validate(portrait)
    if bundle.get('version') != 'RESEARCH-BUNDLE-01' or bundle.get('purpose') != 'synthetic_research_only':
        raise ValueError('仅支持明确标注的合成研究参数包')
    if bundle.get('portrait_id') != portrait['event_id']:
        raise ValueError('参数包与画像事件编号不一致')
    card = deepcopy(bundle.get('network_card'))
    if not isinstance(card, dict):
        raise ValueError('缺少完整网络卡')
    evidence = bundle.get('section_evidence', {})
    for name in REQUIRED_SECTIONS:
        item = evidence.get(name, {})
        if name not in card or item.get('status') != 'assumption' or not isinstance(item.get('source'), str) or not item['source'].strip():
            raise ValueError(f'{name} 必须提供参数与合成假设来源说明')
    validate_network(card)
    onward = engine.field(portrait, 'onward_people')
    initial = engine.field(portrait, 'initial_queue')
    arrival = engine.field(portrait, 'arrival_profile')
    safety = engine.field(portrait, 'safety_status')
    authorization = engine.field(portrait, 'authorization')
    for name, item in [('待接续人数',onward),('初始候客',initial),('到达过程',arrival),('安全状态',safety),('研究计算授权',authorization)]:
        if item['status'] != 'assumption':
            raise ValueError(f'{name}必须明确标注为合成假设；本桥接不处理真实调度')
    if safety['value'] != '假设可继续运输':
        raise ValueError('安全状态不允许或尚不明确，停止生成研究卡')
    if authorization['value'] != '仅允许合成研究计算':
        raise ValueError('研究计算范围未确认，停止生成研究卡')
    if not isinstance(arrival['value'], dict):
        raise ValueError('到达过程必须填写逐群体分时数组')
    if len(card['profiles']) != 1 or card['profiles'][0]['arrivals'] != arrival['value']:
        raise ValueError('画像逐群体分时到达与网络过程不一致；首版仅支持单过程')
    initial_total = sum(g['initial_people'] for g in card['groups'])
    for value in totals(card).values():
        if onward['status'] != 'unknown' and abs((value - initial_total) - onward['value']) > 1e-6:
            raise ValueError('新增接续人数与网络进入过程不一致')
    if initial['status'] != 'unknown' and abs(initial_total - initial['value']) > 1e-6:
        raise ValueError('初始候客人数与网络群体不一致')
    card['record_kind'] = '历史背景下的合成研究示例；非实际事件方案'
    card['platform']['notes'] = '模型参数为完整合成假设；不代表历史实测、实时资源或授权。'
    field_evidence = []
    for section in REQUIRED_SECTIONS:
        for path, value in leaves(card[section], '/'+section):
            field_evidence.append({'path':path,'value':value,'status':'assumption','source':evidence[section]['source'],
                                   'source_granularity':'继承参数组说明；待补逐字段实证'})
    provenance = {'version': 'BRIDGE-02', 'portrait_id': portrait['event_id'],
                  'portrait_sha256': digest(portrait), 'bundle_sha256': digest(bundle),
                  'network_card_sha256': digest(card), 'section_evidence': evidence,
                  'portrait_unknown_fields': [n for n in engine.FIELDS if engine.field(portrait, n)['status'] == 'unknown'],
                  'field_evidence':field_evidence,
                  'cross_checks': {'new_onward_people': onward['status'], 'initial_queue': initial['status'],
                                   'arrival_profile':'逐群体逐时段完全一致',
                                   'safety':'仅假设可继续运输', 'authorization':'仅允许合成研究计算'},
                  'boundary': '研究示例；历史受影响人数不映射为需求；不构成已确认调度指令'}
    return card, provenance

def main():
    import argparse
    p = argparse.ArgumentParser(description='生成合成研究网络卡并保留来源')
    p.add_argument('portrait', type=Path)
    p.add_argument('bundle', type=Path)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    portrait = json.loads(args.portrait.read_text(encoding='utf-8'))
    bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
    card, provenance = make_card(portrait, bundle)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in [('network-card.json', card), ('provenance.json', provenance)]:
        (args.output_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('生成合成研究卡和来源记录：', args.output_dir)

if __name__ == '__main__': main()
