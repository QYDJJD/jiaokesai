import copy
import json
from pathlib import Path
import unittest
import research_workflow as w

HERE=Path(__file__).resolve().parent
class WorkflowChecks(unittest.TestCase):
    def setUp(self):
        self.p=json.loads((HERE/'demo-事件画像.json').read_text(encoding='utf-8'))
        self.doc={'url':'https://example.org/demo','title':'模拟材料','publication_date':'2023-12-19',
                  'collected_at':'2026-10-28T12:00:00+08:00','publisher':'模拟发布方',
                  'text':'模拟文本：地铁延时运营，公交加密，出租车保障。'}
    def test_recommendations_have_exact_offsets_and_no_current_values(self):
        r=w.recommend(self.p,w.MockProvider([self.doc,self.doc]))
        self.assertEqual(len(r['recommendations']),3)
        for c in r['recommendations']:
            self.assertIsNone(c['current_value']);self.assertEqual(c['confirmation'],'pending')
            self.assertEqual(len(c['evidence']),1)
            e=c['evidence'][0];self.assertEqual(self.doc['text'][e['start']:e['end']],e['quote'])
            self.assertEqual(e['source_status'],'演示文本，未验证原页')
    def test_fixed_fields_not_duplicated_and_confirmation_explicit(self):
        r=w.recommend(self.p,w.MockProvider([self.doc]),fixed_indicators=['metro_extension'])
        self.assertNotIn('metro_extension',[x['indicator_id'] for x in r['recommendations']])
        c=r['recommendations'][0]
        with self.assertRaises(ValueError):w.confirm(c,'','张','2026-10-28T12:00:00+08:00')
        result=w.confirm(c,'待现场核实','张','2026-10-28T12:00:00+08:00')
        self.assertEqual(result['confirmation'],'confirmed');self.assertEqual(c['confirmation'],'pending')
    def test_missing_evidence_metadata_rejected(self):
        doc=copy.deepcopy(self.doc);del doc['collected_at']
        with self.assertRaises(ValueError):w.recommend(self.p,w.MockProvider([doc]))

    def test_general_resource_field_does_not_hide_specific_candidates(self):
        self.p['fields']['resource_inventory']={'value':'已知有公交','status':'observed','source':'模拟','as_of':'2026-11-19T12:00:00+08:00'}
        items={x['indicator_id']:x for x in w.recommend(self.p,w.MockProvider([self.doc]))['recommendations']}
        self.assertTrue(items['bus_service']['broader_field_present'])
        self.assertIn('taxi_service',items)
        self.assertIsNone(items['bus_service']['current_value'])

if __name__=='__main__':unittest.main()
