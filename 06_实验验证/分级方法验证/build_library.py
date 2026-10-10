"""Build the traceable initial library and run independent method checks.

python -X utf8 build_library.py (standard library only).
These checks assess conditional mechanics, never empirical accuracy.
"""
from pathlib import Path
import json
from grading_engine import evaluate, profile, grade_case, EPS

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def main():
    checks = []
    def check(name, ok, count=1):
        checks.append({"name":name,"comparisons":count,"pass":bool(ok)})
        if not ok:
            raise AssertionError(name)
    specs = [
        ("SC-H01","基准需求","Q_aff",dict(q=2000,d=2),"F1"),
        ("SC-H02","较小需求","Q_aff",dict(q=500,d=2),"F0"),
        ("SC-H03","较大需求","Q_aff",dict(q=3500,d=2),"F2"),
        ("SC-H04","三个参考包均不足","Q_aff",dict(q=7000,d=2),"F3"),
        ("SC-H05","H03失去提前量","P1",dict(q=3500,d=2,p=0),"F3"),
        ("SC-H06","H01输入集中","D",dict(q=2000,d=.5),"F2"),
        ("SC-H07","H01预测集合扩大","U/Ω",dict(q=2000,d=2,shapes=["uniform","front"]),"F2"),
        ("SC-H08","H01有效供给减半","R/有效供给",dict(q=2000,d=2,factor=.5),"F2"),
        ("SC-H09","H01附带初始积压","B0",dict(q=2000,d=2,b0=800),"F1"),
        ("SC-H10","H01服务窗口缩短","服务日历",dict(q=2000,d=2,ends=[1,2,2]),"F2"),
        ("SC-H11","仅有既有积压","D=0/B0",dict(q=0,d=0,b0=1000),"F1"),
        ("SC-H12","有效供给为零","零能力",dict(q=2000,d=2,factor=0),"F3"),
        ("SC-H13","继续运输前提不满足","安全边界",dict(q=2000,d=2,safe=False),"X-SAFE"),
        ("SC-H14","关键输入未知","数据边界",dict(q=2000,d=2,known=False),"X-DATA"),
        ("SC-H15","多方向不可合池","方向边界",dict(q=2000,d=2,supported=False),"X-STRUCTURE"),
        ("SC-H16","多服务共享瓶颈","共享资源边界",dict(q=2000,d=2,supported=False),"X-STRUCTURE"),
        ("SC-H17","初始已超过研究上限","B0>K",dict(q=500,d=2,b0=1200),"F3"),
        ("SC-H18","输入不合法","配置边界",dict(q=2000,d=-1),"X-CONFIG"),
    ]
    synthetic = []
    for sid,title,axis,params,expected in specs:
        record = {"id":sid,"title":title,"type":"synthetic","axis_or_boundary":axis,
                  "reference_version":"REF-SYN-01/window-variant" if "ends" in params else "REF-SYN-01",
                  "goal_version":"GOAL-SYN-01","input":params,**grade_case(params)}
        check(sid+"_expected_behavior",record["grade"]==expected)
        synthetic.append(record)
    # Analytical constant-service inequalities were derived without the
    # queue implementation. Include strict failures and equality boundaries.
    analytical_count = 0
    for b0 in (0,300,1000):
        for q in (500,2000,3500):
            for d in (.5,2):
                for h in (.5,1):
                    threshold = max((b0+q)/(d+h),(b0+q-1000)/d,0)
                    for scale in (.99,1,1.01):
                        c = threshold*scale
                        r = evaluate(profile(q,d,"uniform"),[(0,None,c)],b0,d+h)
                        exact_peak = max(b0,b0+q-c*d)
                        exact_clear = max(d,(b0+q)/c)
                        numerical_pass = r["peak_people"] <= 1000+EPS and r["clear_h"] <= d+h+EPS
                        assert abs(r["peak_people"]-exact_peak) < 1e-6
                        assert abs(r["clear_h"]-exact_clear) < 1e-6
                        assert numerical_pass == (scale >= 1)
                        analytical_count += 1
    check("independent_constant_service_threshold",True,analytical_count)
    batch = evaluate([],[(.5,None,1000)],1000,1)
    check("batch_clear_and_FIFO_wait",abs(batch["clear_h"]-1.5)<EPS and abs(batch["max_wait_h"]-1.5)<EPS and abs(batch["total_waiting_people_h"]-1000)<EPS)
    interrupted = evaluate([],[(0,.5,1000),(1,2,1000)],1000,1.5)
    check("finite_window_interruption",abs(interrupted["clear_h"]-1.5)<EPS and abs(interrupted["max_wait_h"]-1.5)<EPS)
    unfinished = evaluate([],[(0,.5,1000)],1000,1)
    check("no_invented_service_after_end",unfinished["clear_h"] is None and unfinished["max_wait_h"] is None and abs(unfinished["unserved_people"]-500)<EPS)
    idle = evaluate([(1,2,500)],[(0,1,1000),(1,None,500)],0,3)
    check("idle_capacity_not_stored",idle["peak_people"]==0 and idle["clear_h"]==2 and idle["max_wait_h"]==0)
    zero = grade_case(dict(q=0,d=0))
    check("zero_demand_no_division",zero["grade"]=="F0")
    check("negative_advance_is_allowed",grade_case(dict(q=2000,d=2,p=-.5))["grade"].startswith("F"))
    check("invalid_inputs_rejected",all(grade_case(p)["grade"]=="X-CONFIG" for p in [dict(q=1,d=0),dict(q=1,d=1,shapes=["typo"]),dict(q=1,d=1,ends=[-1,2,2]),dict(q=float('nan'),d=1)]),4)
    check("unknown_safety_not_safe_failure",grade_case(dict(q=1,d=1,safe=None))["grade"]=="X-DATA")
    check("multiple_blockers_preserved",grade_case(dict(q=1,d=1,safe=None,supported=False))["blockers"]==["X-DATA","X-STRUCTURE"])
    count = 0
    for q in (500,1500,2500,3500,6000):
        for d in (.5,1,2,4):
            for p in (0,.5,1):
                for f in (.5,1):
                    x=dict(q=q,d=d,p=p,factor=f)
                    g=int(grade_case(x)["grade"][1])
                    assert int(grade_case({**x,"q":q+500})["grade"][1]) >= g
                    assert int(grade_case({**x,"p":p+.5})["grade"][1]) <= g
                    assert int(grade_case({**x,"factor":f+.25})["grade"][1]) <= g
                    row=grade_case(x)
                    assert all(not a["pass"] or b["pass"] for a,b in zip(row["tiers"],row["tiers"][1:]))
                    count += 1
    check("monotonicity_and_nested_tiers",True,count*5)
    normal=grade_case(dict(q=2000,d=2))
    varied=grade_case(dict(q=2000,d=2,shapes=["uniform","front"]))
    check("enlarged_prediction_set_cannot_lower_tier",int(varied["grade"][1])>=int(normal["grade"][1]))
    r=evaluate(profile(2000,2,"front"),[(0,None,500),(1,None,500)],800,3)
    rs=evaluate([(a*60,b*60,c/60) for a,b,c in profile(2000,2,"front")],[(0,None,500/60),(60,None,500/60)],800,180)
    rp=evaluate(profile(20000,2,"front"),[(0,None,5000),(1,None,5000)],8000,3)
    check("time_and_people_unit_invariance",abs(rs["peak_people"]-r["peak_people"])<EPS and abs(rs["clear_h"]-r["clear_h"]*60)<EPS and abs(rs["max_wait_h"]-r["max_wait_h"]*60)<EPS and abs(rp["peak_people"]-10*r["peak_people"])<EPS and abs(rp["max_wait_h"]-r["max_wait_h"])<EPS,5)
    runs=[r for s in synthetic for t in s["tiers"] for r in t["runs"]]
    check("mass_balance",all(abs(r["arrived_people"]-r["served_people"]-r["unserved_people"])<1e-6 for r in runs),len(runs))
    sensitivity = []
    for s in synthetic:
        if not s["grade"].startswith("F"):
            continue
        tests=[{"K":k,"H":h,"grade":grade_case(s["input"],k,h)["grade"]} for k in (750,1000,1250) for h in (.5,1,2)]
        sensitivity.append({"id":s["id"],"base_grade":s["grade"],"grades_in_test_range":sorted({r["grade"] for r in tests}),"configurations":tests})
    real = [
        {"id":"SC-E01","title":"2023年12月降雪晚点接续疏运","source_ids":["S01"],"missing":["同口径Q_aff/B0/分时进入","各层剩余与增援有效能力","K/H","预测信息快照"],"structural_issue":"各方式方向及服务起止不齐"},
        {"id":"SC-E02","title":"2023年8月地震晚点接续疏运","source_ids":["S02"],"missing":["同口径Q_aff/B0/分时进入","有效能力及生效记录","K/H","预测信息快照"],"structural_issue":"单车次与个别车次完成不可代替整个群体"},
        {"id":"SC-E03","title":"2024年贝碧嘉台风限制与安置边界","source_ids":["S03","AV02","AV03","AV04","AV05","AV06","OP05","OP06"],"missing":["继续运输安全适用条件","现场需要接续疏运人群","分区和分方向供需","K/H"],"structural_issue":"方式限制、可达性与安置不能合池"},
        {"id":"SC-E04","title":"2014年大雾航空备降及转送","source_ids":["AV01"],"missing":["各目的方向人数和初始积压","分时供给与接令生效","K/H","预测信息快照"],"structural_issue":"机场/酒店/住所不同目的方向；历史网络不可使用后开线路"},
    ]
    for r in real:
        r.update(type="observed_material",grade="X-DATA",numeric_input=None,
                 supplemental_structure_review=True,independent_validation=False)
    library={"version":"LIB-INIT-01","date":"2026-10-11","rule_version":"RULE-01",
             "meaning":"minimum predefined feasible resource tier","actual_operating_standard":False,
             "calculation_mode":"fixed effective supply curve per tier, same curve for all allowed arrival profiles; no optimization over all policies",
             "user_confirmed":"grade meaning only","goal_assumption":"K=1000,H=1 are synthetic; individual waiting diagnostic",
             "reference":{"id":"REF-SYN-01","base_rate":500,"increment_rates":[500,1000],"activation_lag_h":1,"shared_bottleneck":False,"compatible_single_pool":True},
             "synthetic":synthetic,"observed_material":real}
    def write(path,data):
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding="utf-8")
    write(ROOT/'03_情景库/初始情景库-v1.json',library)
    write(OUT/'初始库验证结果.json',{"date":"2026-10-11","checks":checks,"synthetic_count":len(synthetic),"observed_material_count":len(real),"independent_empirical_accuracy":None})
    write(OUT/'目标参数敏感性.json',{"interpretation":"9 research configurations per computable scenario; not confidence intervals or calibrated thresholds","rows":sensitivity})
    lines=["# 初始情景库 v1","","版本LIB-INIT-01；日期2026年10月11日。18张合成卡用于规则覆盖与计算检查，4张真实材料卡保留来源和缺项；不合并为22起真实事件。","","[完整输入及逐层结果](初始情景库-v1.json)；[规则](分级规则与判级依据-v1.md)；[真实材料详情](描述性情景卡集-v1.md)。","","## 合成卡索引","","K=1000人、H=1小时、基础500人/小时、增援500及1000人/小时，到位历时1小时，均为假设。默认P1=1小时、B0=0、均匀输入，所有服务同方向且无共享瓶颈；除H10外不设服务结束。R的供给减半仅为有效率代理，不表示损失一半方式。","","| 卡号 | 检查目的 | 研究判级 | 与基准的关系 |","|---|---|---|---|"]
    lines += [f"| {s['id']} | {s['title']} | {s['grade']} | {s['axis_or_boundary']} |" for s in synthetic]
    lines += ["","## 基准卡逐层解释","","H01：2000人在2小时内均匀进入；基础及加强/联合有效供给分别500/1000/2000人每小时。V0峰值1000人，4小时完成，超过D+H=3小时，故失败；V1峰值0、2小时完成，故最低层F1。不是因为某条真实新闻显示动用了加强资源而倒推F1。","","H07总量不变，加入前置输入轨迹：V1最坏峰值1100人超过K，V2最坏峰值600人，因此F2。H10将基础服务结束设为1小时、两项增援结束为2小时，V1留下500人未完成，V2可完成，因此F2；不能把已经结束的服务无限延续。","","## 真实材料卡适用性","","| 卡号 | 事件材料 | 当前状态 | 缺项处理 |","|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['title']} | X-DATA | 保留来源；逐项列未知；不填假设数 |" for r in real]
    lines += ["","真实卡均参与方法设计，不能作为独立验证集。台风卡还需先核继续运输安全条件；未知不记作明确不安全。方向与瓶颈需结构审查，不能由X-DATA抹去。","","## 覆盖及选样依据","","五主轴P1、U、D、Q_aff、R分别由H05、H07、H06、H02—H04、H08作对照；H09/H17补B0，H10补服务日历，H11/H12补零期和零能力，H13—H16/H18补边界。此处18张由这些检查目的组成，不预先指定6—8类，不使用聚类占比解释发生概率。","","H08未覆盖完整空间/方向型R，H15/H16只是工具不适用的边界占位。连续维度覆盖、真实常见程度及交通网络有效性仍需后续证据。","","## 参数变化检查","","每张可计算卡检查K=750/1000/1250人与H=0.5/1/2小时的9组研究配置，见[完整结果](../06_实验验证/分级方法验证/目标参数敏感性.json)。变化区间用于显示目标选择的影响，不是虹桥核定范围。","","| 卡号 | 默认等级 | 这9组中的等级集合 |","|---|---|---|"]
    lines += [f"| {s['id']} | {s['base_grade']} | {', '.join(s['grades_in_test_range'])} |" for s in sensitivity]
    lines += ["","等候最长时间及累计人时见JSON；只对本单池FIFO假设有效，未列入主判级。服务未完成时最长等待不填有限值，保留未疏运人数与截至截止点的累计等候。","","重建：在`06_实验验证/分级方法验证/`运行`python -X utf8 build_library.py`。旧`verify_grading.py`及其10张SY卡保留为前次原型检验记录，不与本初始库重复计数。",""]
    (ROOT/'03_情景库/初始情景库-v1.md').write_text('\n'.join(lines),encoding="utf-8")
    print(json.dumps({"checks":len(checks),"comparisons":sum(c['comparisons'] for c in checks),"synthetic":len(synthetic),"real_material":len(real),"sensitivity_rows":len(sensitivity)*9,"grades":[(s['id'],s['grade']) for s in synthetic]},ensure_ascii=False))


if __name__ == '__main__':
    main()
