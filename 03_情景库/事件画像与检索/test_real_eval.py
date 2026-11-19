import importlib.util
import json
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('real_eval', HERE/'真实事件评估.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class EvalChecks(unittest.TestCase):
    def setUp(self): self.cases=json.loads((HERE/'catalog.json').read_text(encoding='utf-8'))
    def test_empty_labels_are_not_accuracy(self):
        r=mod.evaluate(self.cases,{'labels':[]})
        self.assertEqual(r['eligible_queries'],0);self.assertIsNone(r['mean_top2_recall'])
    def test_complete_query_and_missing_queries(self):
        labels=[{'query_id':'HQ-E01','candidate_id':c['event_id'],'relevance':'高' if c['event_id']=='HQ-E02' else '低',
                 'evidence':'测试假设','annotator':'测试','date':'测试'} for c in self.cases if c['event_id']!='HQ-E01']
        r=mod.evaluate(self.cases,{'labels':labels});self.assertEqual(r['eligible_queries'],1)
        self.assertEqual(r['top1_hits'],1);self.assertEqual(r['mean_top2_recall'],1)
        labels[0]['relevance']='待核';self.assertEqual(mod.evaluate(self.cases,{'labels':labels})['eligible_queries'],0)
    def test_duplicate_and_self_excluded(self):
        row={'query_id':'HQ-E01','candidate_id':'HQ-E02','relevance':'低','evidence':'测试','annotator':'测试','date':'测试'}
        with self.assertRaises(ValueError):mod.evaluate(self.cases,{'labels':[row,row]})
        row['candidate_id']='HQ-E01'
        with self.assertRaises(ValueError):mod.evaluate(self.cases,{'labels':[row]})

if __name__=='__main__': unittest.main()
