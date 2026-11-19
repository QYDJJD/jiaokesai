"""复现合成接口示例并使用既有独立核算。"""
import json
import sys
from pathlib import Path
import network_bridge

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'04_建模/多方式网络优化'))
from network_model import solve
from network_audit import audit_solution

portrait = json.loads((HERE/'demo-合成画像.json').read_text(encoding='utf-8'))
bundle = json.loads((HERE/'demo-合成参数包.json').read_text(encoding='utf-8'))
card, provenance = network_bridge.make_card(portrait, bundle)
solution = solve(card, seconds=10, gap=0, objective='journey_time')
if not solution.get('has_solution'):
    raise RuntimeError('合成示例未获得可行解：'+str(solution.get('phase_primary')))
audit = audit_solution(card, solution)
records = [{k: row.get(k) for k in ('profile_id', 'task_people', 'delivered_people',
           'remaining_people', 'peak_queue_people', 'origin_clear_minutes', 'completion_minutes',
           'total_wait_person_minutes', 'total_journey_person_minutes', 'safe_queue', 'complete_by_deadline')}
           for row in audit['profiles']]
result = {'scope':'12人合成假设；仅验证接口与模型流程，不是历史回放或现场绩效',
          'network_card_sha256':provenance['network_card_sha256'], 'phase_primary':solution['phase_primary'],
          'plan':audit['plan'], 'profiles':records,
          'independent_checks':audit.get('independent_event_and_fifo_checks')}
out = HERE/'demo-桥接输出'
out.mkdir(exist_ok=True)
for name, value in [('network-card.json',card),('provenance.json',provenance),('result.json',result)]:
    (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('研究示例求解及独立核算完成，输出位于',out)
