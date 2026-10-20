"""Reproduce different networks using the same engine and save compact records."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'04_建模/交互验证平台'))
from network_adapter import templates,evaluate,write_exports

def run(seconds=35):
    records=[];folder=ROOT/'.qa/network_reproduction';folder.mkdir(parents=True,exist_ok=True)
    for key,card in templates().items():
        output=folder/key;output.mkdir(exist_ok=True)
        result=evaluate(card,{'mode':'optimize','objective':'journey_time','seconds':seconds},progress=lambda stage:print(key+'：'+stage,flush=True))
        write_exports(output,result)
        solution=result.get('solution',{});audit=result.get('audit',{})
        record={'id':key,'title':card['platform']['title'],'schema_version':card['schema_version'],'input_sha256':result['input_sha256'],
          'settings':result['settings'],'modes':[m['label'] for m in card['modes']],'nodes':len(card['nodes']),'links':len(card['links']),
          'status':result['status'],'phase_primary':solution.get('phase_primary'),'variables':solution.get('variables'),
          'integer_variables':solution.get('integer_variables'),'plan':audit.get('plan'),
          'profiles':[{k:v for k,v in row.items() if k not in ('trace','node_trace')} for row in audit.get('profiles',[])],
          'baseline_profiles':[{k:v for k,v in row.items() if k not in ('trace','node_trace')} for row in result['baseline']['profiles']],
          'independent_checks':audit.get('independent_event_and_fifo_checks'),'implementation_sha256':result['implementation_sha256']}
        records.append(record)
        target=Path(__file__).parent/'多事件演示结果.json'
        target.write_text(json.dumps({'scope':'同一网络模型的多结构示例；虹桥仅提供背景，其余为合成验证，不证明实际处置改善率','cases':records},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'case':key,'status':result['status'],'cost':audit.get('plan',{}).get('cost_yuan')},ensure_ascii=False),flush=True)
    return records

if __name__=='__main__':run(float(sys.argv[1]) if len(sys.argv)>1 else 35)
