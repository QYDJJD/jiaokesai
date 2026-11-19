"""运行完整的模拟文档候选示例；不会联网或修改种子库。"""
from pathlib import Path
import json
import engine
import research_workflow as workflow

HERE=Path(__file__).resolve().parent
portrait=json.loads((HERE/'demo-事件画像.json').read_text(encoding='utf-8'))
catalog=json.loads((HERE/'catalog.json').read_text(encoding='utf-8'))
mock_document={'url':'https://example.org/simulated-source','title':'模拟保障材料，非真实网页',
               'publication_date':'2023-12-19','collected_at':'2026-10-28T12:00:00+08:00',
               'publisher':'模拟提供器','text':'模拟文本：列车晚点到达，地铁延时运营，公交加密，出租车保障。'}
result={'scope':'模拟来源；未联网，不是已核原文或真实事件新证据',
        'local_results':engine.retrieve(portrait,catalog),
        'candidate_result':workflow.recommend(portrait,workflow.MockProvider([mock_document]))}
(HERE/'demo-模拟证据候选.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('已生成模拟证据候选；无需联网。')
