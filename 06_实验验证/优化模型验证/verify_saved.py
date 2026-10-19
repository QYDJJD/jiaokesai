"""Audit stored solver results and generated baseline metrics without re-solving."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'04_建模/接续运输优化原型'))
from simulate import audit_solution,causal_greedy,replay,check_plan


def main():
    path=ROOT/'06_实验验证/优化模型验证/优化实验结果.json'
    data=json.loads(path.read_text(encoding='utf-8'));replayed=0;statuses={}
    for name,expected in data['implementation_sha256'].items():
        actual=hashlib.sha256((ROOT/'04_建模/接续运输优化原型'/name).read_bytes()).hexdigest()
        assert actual==expected, '源代码与生成结果版本不同：'+name
    for case in data['cases']:
        card,result=case['card'],case['solution'];status=result['phase_primary']['status']
        statuses[str(status)]=statuses.get(str(status),0)+1
        expected=hashlib.sha256(json.dumps(card,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        assert result['input_sha256']==expected
        if result['has_solution']:
            audit=audit_solution(card,result);replayed+=len(audit['profiles'])
            assert abs(audit['plan']['cost_yuan']-case['audit']['plan']['cost_yuan'])<1e-4
            for a,b in zip(audit['profiles'],case['audit']['profiles']):
                for key in ['total_wait_person_minutes','peak_queue_people','standing_person_minutes','deadline_remaining_people']:
                    assert abs(a[key]-b[key])<1e-4,(case['id'],key)
        else:assert status in (1,2,4), '未取得排班但错误标为成功'
    base=data['cases'][0]['card'];rows={}
    for name,plan in data['baseline_plans'].items():
        check_plan(base,plan)
        for profile in base['arrival_profiles']:
            row=replay(base,plan,causal_greedy(base,plan,profile,horizon_minutes=480),profile)
            rows[name,profile['id']]=row;replayed+=1
    for saved in data['baselines']:
        if saved['策略']=='共同资源优化':continue
        name='base_only' if saved['策略']=='仅基础服务' else 'average_reservation'
        profile=next(p for p in base['arrival_profiles'] if p['label']==saved['进入过程'])
        row=rows[name,profile['id']]
        assert abs(round(row['peak_queue_people'],3)-saved['候客峰值'])<1e-6
        assert row['all_targets_met']==saved['通过']
    result={'case_count':len(data['cases']),'primary_status_counts':statuses,
            'independent_profiles_replayed':replayed,'source_and_input_hashes':'通过',
            'conservation_fifo_resources_comfort_deadline_causality':'通过',
            'scope':'存档数值一致性及声明模型内的独立复算；不代表真实事件实证精度'}
    (path.parent/'存档结果核对.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
