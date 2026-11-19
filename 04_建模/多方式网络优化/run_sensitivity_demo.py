"""运行 12 人纯模拟的资源敏感性示例。"""
import json
from network_examples import tiny
from resource_sensitivity import compare


def main():
    card = tiny()
    card['parameters']['budget_yuan'] = 100
    variants = [
        {'name': '增加一次预约预算', 'changes': [{'target': 'parameters', 'field': 'budget_yuan', 'value': 200}]},
        {'name': '仅增加可用车辆', 'changes': [{'target': 'pools', 'id': 'fleet', 'field': 'available_units', 'value': 2}]},
        {'name': '仅延长到达截止时间', 'changes': [{'target': 'parameters', 'field': 'deadline_minutes', 'value': 100}]},
        {'name': '预算及车辆同时增加', 'changes': [
            {'target': 'parameters', 'field': 'budget_yuan', 'value': 200},
            {'target': 'pools', 'id': 'fleet', 'field': 'available_units', 'value': 2}]},
    ]
    print(json.dumps(compare(card, variants, seconds=5), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
