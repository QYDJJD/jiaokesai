"""运行纯模拟资源不足诊断：python run_unserved_demo.py。"""
import json
from network_examples import tiny
from unserved_diagnostic import diagnose


def main():
    scenarios = []
    for name, budget, queue_limit in [('运力充足', 200, 20), ('部分运力', 100, 20),
                                      ('无运力', 0, 20), ('无运力且候车容量不足', 0, 5)]:
        card = tiny()
        card['parameters']['budget_yuan'] = budget
        card['nodes'][0]['queue_limit_people'] = queue_limit
        scenarios.append({'name': name, 'budget_yuan': budget, 'queue_limit_people': queue_limit,
                          'result': diagnose(card, seconds=5)})
    print(json.dumps({'notice': '纯模拟手算案例，不能作为真实调度方案。', 'scenarios': scenarios},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
