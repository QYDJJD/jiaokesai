"""Synthetic feasibility checks for scenario grading; no Hongqiao calibration.

Python 3 standard library only. Re-run: python verify_grading.py
Continuous fluid queues are integrated exactly at all rate change points.
All people, hours, resource rates and limits below are hypothetical.
"""
from pathlib import Path
import json

OUT = Path(__file__).resolve().parent
EPS = 1e-8
K = 1000.0
H = 1.0
TIERS = ((), ((500.0, 1.0),), ((500.0, 1.0), (1000.0, 1.0)))


def evaluate(arrivals, supplies, initial=0.0):
    """Segments are (start, end, people/hour); supply starts persist.

    Unlimited FIFO continuous divisible service, no reneging or shelter.
    Supplies have no shared bottleneck. Valid only for compatible demand.
    """
    end = max((b for a, b, r in arrivals), default=0.0)
    if initial == 0 and sum((b-a)*r for a,b,r in arrivals) == 0:
        return {"peak": 0.0, "clear": 0.0, "residual": 0.0}
    times = sorted({0.0, end, end + H, *(x for a,b,r in arrivals for x in (a,b)), *(t for t,c in supplies)})
    backlog = initial
    peak = backlog
    clear = None
    residual = None
    for a,b in zip(times, times[1:]):
        mid = (a+b)/2
        rate = sum(r for x,y,r in arrivals if x <= mid < y)
        capacity = sum(c for t,c in supplies if t <= mid)
        if a >= end and clear is None:
            if backlog <= EPS:
                clear = a
            elif capacity > 0 and backlog/capacity <= b-a+EPS:
                clear = a + backlog/capacity
        backlog = max(0.0, backlog + (rate-capacity)*(b-a))
        peak = max(peak, backlog)
        if abs(b-(end+H)) < EPS:
            residual = backlog
    if clear is None:
        cap = sum(c for t,c in supplies)
        if backlog <= EPS:
            clear = times[-1]
        elif cap > 0:
            clear = times[-1]+backlog/cap
    return {"peak": peak, "clear": clear, "residual": residual}


def profile(q, d, shape="uniform"):
    if shape == "front":
        return [(0.0, d/4, q*.8/(d/4)), (d/4, d, q*.2/(d*.75))]
    return [(0.0, d, q/d)]


def grade(q, d, p=1.0, loss=1.0, shapes=("uniform",), safe=True, known=True):
    if not safe:
        return {"grade": "X-SAFE", "tiers": []}
    if not known:
        return {"grade": "X-DATA", "tiers": []}
    results=[]
    for level, offers in enumerate(TIERS):
        supplies=[(0.0, 500.0*loss)] + [(max(0.0,tau-p), c*loss) for c,tau in offers]
        runs=[evaluate(profile(q,d,s), supplies) for s in shapes]
        passed=all(r["peak"]<=K+EPS and r["clear"] is not None and r["clear"]<=d+H+EPS for r in runs)
        results.append({"level": level, "pass": passed, "peak": max(r["peak"] for r in runs), "clear": None if any(r["clear"] is None for r in runs) else max(r["clear"] for r in runs)})
    selected=next((r["level"] for r in results if r["pass"]), 3)
    return {"grade": "F"+str(selected), "tiers": results}


def run():
    scenarios=[
        ("SY01", "小需求", dict(q=500,d=2)),
        ("SY02", "基准", dict(q=2000,d=2)),
        ("SY03", "需求增大", dict(q=3500,d=2)),
        ("SY04", "本地参考资源不足", dict(q=7000,d=2)),
        ("SY05", "SY03无提前量", dict(q=3500,d=2,p=0)),
        ("SY06", "SY02到达集中", dict(q=2000,d=.5)),
        ("SY07", "SY02预测集合扩大", dict(q=2000,d=2,shapes=("uniform","front"))),
        ("SY08", "SY02有效供给减半", dict(q=2000,d=2,loss=.5)),
        ("SY09", "安全前提不满足", dict(q=2000,d=2,safe=False)),
        ("SY10", "关键数据未知", dict(q=2000,d=2,known=False)),
    ]
    records=[{"id":i,"purpose":name,"input":params,**grade(**params)} for i,name,params in scenarios]
    checks=[]
    def check(name, ok, count=1):
        checks.append({"name":name,"comparisons":count,"pass":bool(ok)})
        if not ok:
            raise AssertionError(name)
    # Independent closed-form solution, not another copy of integration.
    batch=evaluate([],[(.5,1000)],initial=1000)
    check("single_batch_closed_form", abs(batch["clear"]-1.5)<EPS and abs(batch["peak"]-1000)<EPS)
    uniform=evaluate(profile(2000,2),[(0,500)])
    check("uniform_closed_form", abs(uniform["peak"]-1000)<EPS and abs(uniform["clear"]-4)<EPS)
    # Time and passenger/rate unit scaling must preserve internal grade.
    check("people_unit_invariance", all(grade(2000,2)["tiers"][j]["pass"] == (evaluate(profile(2000*10,2),[(0,500*10)]+[(max(0,tau-1),c*10) for c,tau in TIERS[j]])["peak"] <= K*10+EPS and evaluate(profile(2000*10,2),[(0,500*10)]+[(max(0,tau-1),c*10) for c,tau in TIERS[j]])["clear"] <= 3+EPS) for j in range(3)),3)
    scaled=evaluate([(a*60,b*60,r/60) for a,b,r in profile(2000,2)],[(0,500/60)])
    check("time_unit_invariance",abs(scaled["peak"]-uniform["peak"])<EPS and abs(scaled["clear"]-uniform["clear"]*60)<EPS)
    check("zero_demand",grade(0,2)["grade"]=="F0" and evaluate(profile(0,2),[(0,500)])["clear"]==0)
    demand_count=prep_count=supply_count=nested_count=0
    demand_ok=prep_ok=supply_ok=nested_ok=True
    grid=[]
    for q in (500,1500,2500,3500,6000):
        for d in (.5,1,2,4):
            for p in (0,.5,1):
                for loss in (.5,1):
                    row=grade(q,d,p,loss)
                    grid.append({"q":q,"d":d,"p":p,"supply_factor":loss,**row})
                    g=int(row["grade"][1])
                    demand_ok &= int(grade(q+500,d,p,loss)["grade"][1]) >= g
                    prep_ok &= int(grade(q,d,p+.5,loss)["grade"][1]) <= g
                    supply_ok &= int(grade(q,d,p,loss+.25)["grade"][1]) <= g
                    demand_count+=1;prep_count+=1;supply_count+=1
                    for low,high in zip(row["tiers"],row["tiers"][1:]):
                        nested_ok &= not low["pass"] or high["pass"]
                        nested_count+=1
    check("demand_scaling_monotonicity",demand_ok,demand_count)
    check("earlier_supply_monotonicity",prep_ok,prep_count)
    check("more_supply_monotonicity",supply_ok,supply_count)
    check("nested_reference_tiers",nested_ok,nested_count)
    uncertainty=grade(2000,2,shapes=("uniform","front"))
    check("uncertainty_set_inclusion",int(uncertainty["grade"][1])>=int(grade(2000,2)["grade"][1]))
    check("zero_supply_finite_output",grade(2000,2,loss=0)["grade"]=="F3")
    check("safety_and_missing_gates",grade(1,1,safe=False)["grade"]=="X-SAFE" and grade(1,1,known=False)["grade"]=="X-DATA",2)
    check("four_internal_levels_reachable",{r["grade"] for r in records if r["grade"].startswith("F")}=={"F0","F1","F2","F3"},4)
    # Counterexample to tau averaging: equal final rate and mean start time.
    early_late=evaluate([],[(0,500),(2,500)],initial=1000)
    mean=evaluate([],[(1,1000)],initial=1000)
    check("average_lag_loses_information",abs(early_late["clear"]-2)<EPS and abs(mean["clear"]-2)<EPS and abs(evaluate(profile(1500,1),[(0,500),(2,500)])["peak"]-1000)<EPS and abs(evaluate(profile(1500,1),[(1,1000)])["peak"]-1500)<EPS)
    output={"evidence_type":"SYNTHETIC; not observed Hongqiao data", "assumptions":{"K_people":K,"H_hours":H,"base_rate":500,"tier_increments":TIERS,"no_shared_bottleneck":True},"scenarios":records,"grid_rows":len(grid),"checks":checks,"mean_lag_peak_counterexample":[1000,1500],"original_lambda_counterexample":{"backlog":1000,"capacity":1000,"tau_hours":[.5,1,2],"lambda":[2,1,.5],"true_batch_clear_hours":[1.5,2,3]}}
    (OUT/'验证结果.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'参数网格结果.json').write_text(json.dumps(grid,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({"scenarios":[(r['id'],r['grade']) for r in records],"grid_rows":len(grid),"checks":checks},ensure_ascii=False))


if __name__ == '__main__':
    run()
