"""人工标签完整后评估。空白、待核和未冻结的数据不能当作准确率。"""
import argparse
import hashlib
import json
from pathlib import Path
import engine

HERE = Path(__file__).resolve().parent

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def evaluate(catalog, labels):
    cases = {c['event_id']:c for c in catalog}
    ids = set(cases)
    if len(ids)!=len(catalog): raise ValueError('案例编号重复')
    rows = labels.get('labels')
    if not isinstance(rows,list): raise ValueError('缺少标签列表')
    mapping = {}
    for row in rows:
        q,c = row.get('query_id'),row.get('candidate_id')
        if q not in ids or c not in ids or q==c or cases[q].get('event_family_id',q)==cases[c].get('event_family_id',c): raise ValueError('无效或同事件标签')
        if (q,c) in mapping: raise ValueError('标签重复')
        if row.get('relevance') not in ('高','中','低','待核'): raise ValueError('相关性必须为高、中、低或待核')
        if not isinstance(row.get('annotator'),str) or not row['annotator'].strip() or not isinstance(row.get('date'),str) or not row['date'].strip(): raise ValueError('需真实标注人和日期')
        if row['relevance'] != '待核' and (not isinstance(row.get('evidence'),str) or not row['evidence'].strip()): raise ValueError('已判断标签需要依据')
        mapping[q,c]=row
    summary=[]
    for q in sorted(ids):
        candidates={c for c in ids if cases[q].get('event_family_id',q)!=cases[c].get('event_family_id',c)}
        if any((q,c) not in mapping or mapping[q,c]['relevance']=='待核' for c in candidates):
            summary.append({'query_id':q,'status':'标注不完整或待核','eligible':False});continue
        ranked=[r for r in engine.retrieve(cases[q],catalog) if r['similarity'] is not None]
        relevant={c for c in candidates if mapping[q,c]['relevance']=='高'}
        if not relevant:
            summary.append({'query_id':q,'status':'无高相关候选','eligible':False});continue
        if not ranked or ranked[0]['similarity'] is None:
            summary.append({'query_id':q,'status':'无可比字段','eligible':False});continue
        top=[r['case_id'] for r in ranked[:2]]
        summary.append({'query_id':q,'status':'可计算','eligible':True,'top1_hit':top[0] in relevant,
                        'top2_recall':len(set(top)&relevant)/len(relevant),'relevant_count':len(relevant),'top2':top})
    valid=[x for x in summary if x['eligible']]
    return {'scope':'内部回顾性留一事件探索，已参与研发的案例不构成外部验证',
            'queries':len(summary),'eligible_queries':len(valid),'excluded_queries':len(summary)-len(valid),
            'top1_hits':sum(x['top1_hit'] for x in valid),
            'mean_top2_recall':sum(x['top2_recall'] for x in valid)/len(valid) if valid else None,'details':summary}

def main():
    p=argparse.ArgumentParser();p.add_argument('labels',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    labels=json.loads(args.labels.read_text(encoding='utf-8'))
    catalog_path=HERE/'catalog.json'; engine_path=HERE/'engine.py'
    freeze=labels.get('freeze',{})
    if freeze.get('catalog_sha256')!=sha(catalog_path) or freeze.get('engine_sha256')!=sha(engine_path):
        raise SystemExit('标签需先由标注人冻结，并匹配当前案例库和规则文件的SHA-256。')
    if not freeze.get('confirmed_by') or not freeze.get('date'): raise SystemExit('冻结记录须有确认人和日期。')
    catalog=json.loads(catalog_path.read_text(encoding='utf-8'))
    result=evaluate(catalog,labels)
    result['input_hashes']={'catalog_sha256':sha(catalog_path),'engine_sha256':sha(engine_path),'labels_sha256':sha(args.labels)}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('评估结果已保存；可计算查询数：',result['eligible_queries'])

if __name__=='__main__': main()
