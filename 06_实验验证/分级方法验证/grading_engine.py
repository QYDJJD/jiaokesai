"""Exact piecewise fluid queue for RESEARCH resource tiers, not dispatch.

Units: people, hours, people/hour. One compatible FIFO pool, divisible
service, no abandonment, shared bottleneck, direction or safety inference.
Supply segments are (start, end-or-None, rate); arrivals have finite ends.
"""
import math

EPS = 1e-8


def nonnegative(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0


def validate_segments(segments, supply=False):
    for start, end, rate in segments:
        if not nonnegative(start) or not nonnegative(rate):
            raise ValueError("negative/non-finite segment")
        if end is None:
            if not supply:
                raise ValueError("arrival end required")
        elif not nonnegative(end) or end <= start:
            raise ValueError("end must exceed start")


def profile(q, d, shape):
    if not nonnegative(q) or not nonnegative(d) or (q > 0 and d == 0):
        raise ValueError("use initial backlog for an instantaneous batch")
    if shape not in ("uniform", "front", "back"):
        raise ValueError("unknown arrival shape")
    if q == 0:
        return []
    if shape == "uniform":
        return [(0, d, q/d)]
    if shape == "front":
        return [(0, d/4, .8*q/(d/4)), (d/4, d, .2*q/(.75*d))]
    return [(0, .75*d, .2*q/(.75*d)), (.75*d, d, .8*q/(d/4))]


def _inverse_linear(segments, rank):
    """Inverse cumulative curve within the open rank interval containing rank."""
    for t0, t1, x0, x1 in segments:
        if x1 > x0 and x0 < rank < x1:
            slope = (t1-t0)/(x1-x0)
            return t0-x0*slope, slope
    raise ValueError("rank not served")


def evaluate(arrivals, supplies, initial=0, deadline=1, include_trace=False):
    validate_segments(arrivals)
    validate_segments(supplies, supply=True)
    if not nonnegative(initial) or not nonnegative(deadline):
        raise ValueError("invalid backlog/deadline")
    total = initial + sum((b-a)*r for a,b,r in arrivals)
    points = {0.0, float(deadline)}
    points.update(t for a,b,r in arrivals for t in (a,b))
    points.update(t for a,b,r in supplies for t in (a,b) if t is not None)
    times = sorted(points)
    # After the last breakpoint only permanent supply remains. This bound
    # guarantees enough time to finish, without inventing post-end service.
    permanent = sum(r for a,b,r in supplies if b is None)
    if permanent > 0 and total > 0:
        times.append(times[-1]+total/permanent+1)
    backlog = peak = float(initial)
    arrived = float(initial)
    served = area = 0.0
    residual = initial if deadline == 0 else None
    area_deadline = 0.0 if deadline == 0 else None
    atrace = [(0,0,0,float(initial))] if initial else []
    strace = []
    queue_trace = [[0.0,float(initial)]]
    for a,b in zip(times,times[1:]):
        mid = (a+b)/2
        rate = sum(r for x,y,r in arrivals if x <= mid < y)
        cap = sum(r for x,y,r in supplies if x <= mid and (y is None or mid < y))
        dt = b-a
        split = backlog/(cap-rate) if cap > rate and backlog > EPS else None
        chunks = [(a,b)]
        if split is not None and EPS < split < dt-EPS:
            chunks = [(a,a+split),(a+split,b)]
        for left,right in chunks:
            duration = right-left
            nxt = max(0.0, backlog+(rate-cap)*duration)
            delivered = backlog+rate*duration-nxt
            atrace.append((left,right,arrived,arrived+rate*duration))
            strace.append((left,right,served,served+delivered))
            area += (backlog+nxt)*duration/2
            arrived += rate*duration
            served += delivered
            backlog = nxt
            queue_trace.append([right,backlog])
            peak = max(peak,backlog)
        if abs(b-deadline) < EPS:
            residual, area_deadline = backlog, area
    complete = served >= total-EPS
    clear = 0.0 if total == 0 else None
    if complete and total > 0:
        for a,b,x,y in strace:
            if y >= total-EPS and y > x:
                clear = a+(total-x)*(b-a)/(y-x)
                break
    wait_max = 0.0 if total == 0 else None
    if complete and total > 0:
        # Inverse arrival and departure curves are linear between mass
        # breakpoints. Check both limiting endpoints, including arrival gaps.
        ranks = sorted({0.0,total,*[max(0,min(total,x)) for seg in atrace+strace for x in seg[2:]]})
        wait_max = 0.0
        for low,high in zip(ranks,ranks[1:]):
            if high-low < EPS:
                continue
            rank = (low+high)/2
            ai,aslope = (0,0) if rank < initial else _inverse_linear(atrace,rank)
            si,sslope = _inverse_linear(strace,rank)
            wait_max = max(wait_max,si-ai+(sslope-aslope)*low,si-ai+(sslope-aslope)*high)
    result = {"peak_people":peak,"clear_h":clear,"residual_at_deadline_people":residual,
            "max_wait_h":wait_max,"waiting_people_h_to_deadline":area_deadline,
            "total_waiting_people_h":area if complete else None,
            "arrived_people":total,"served_people":served,"unserved_people":max(0,total-served)}
    if include_trace:
        result['queue_trace'] = queue_trace
    return result


def supply_tiers(p=1, factor=1, ends=None):
    start = max(0,1-p)
    resources = [(0, None if ends is None else ends[0],500*factor),
                 (start,None if ends is None else ends[1],500*factor),
                 (start,None if ends is None else ends[2],1000*factor)]
    # An offer whose window closes before it becomes effective adds nothing.
    return [[s for s in resources[:n] if s[1] is None or s[1] > s[0]] for n in (1,2,3)]


def grade_case(params, k=1000, h=1):
    # Known ineligibility precedes missing data; missing and unsupported
    # structure can coexist, so preserve ALL blockers in the record.
    blockers = []
    if params.get("safe") is False:
        blockers.append("X-SAFE")
    if params.get("known",True) is False or params.get("safe",True) is None:
        blockers.append("X-DATA")
    if params.get("supported",True) is False:
        blockers.append("X-STRUCTURE")
    if blockers:
        return {"grade":blockers[0],"blockers":blockers,"tiers":[]}
    try:
        if not nonnegative(k) or not nonnegative(h):
            raise ValueError("invalid service goal")
        q,d,b0 = params["q"],params["d"],params.get("b0",0)
        p,factor = params.get("p",1),params.get("factor",1)
        if not nonnegative(b0) or not nonnegative(factor) or isinstance(p,bool) or not isinstance(p,(int,float)) or not math.isfinite(p):
            raise ValueError("invalid reference parameters")
        ends = params.get("ends")
        if ends is not None and (len(ends) != 3 or any(x is not None and not nonnegative(x) for x in ends)):
            raise ValueError("invalid service windows")
        shapes = params.get("shapes",["uniform"])
        if not shapes:
            raise ValueError("empty uncertainty set")
        arrivals = [(s,profile(q,d,s)) for s in shapes]
        tiers = supply_tiers(p,factor,params.get("ends"))
        validate_segments([s for tier in tiers for s in tier],supply=True)
        result = []
        for j,supply in enumerate(tiers):
            runs = []
            for shape,arr in arrivals:
                row = evaluate(arr,supply,b0,d+h)
                failures = []
                if row["peak_people"] > k+EPS:
                    failures.append("peak_over_K")
                if row["clear_h"] is None:
                    failures.append("unfinished_after_service_ends_or_no_supply")
                elif row["clear_h"] > d+h+EPS:
                    failures.append("clear_after_D_plus_H")
                runs.append({"shape":shape,**row,"pass":not failures,"failures":failures})
            result.append({"tier":"V"+str(j),"supply_segments":supply,
                           "pass":all(r["pass"] for r in runs),"runs":runs})
        g = next((j for j,r in enumerate(result) if r["pass"]),3)
        return {"grade":"F"+str(g),"blockers":[],"goals":{"K_people":k,"H_hours":h,"deadline_h":d+h},"tiers":result}
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        return {"grade":"X-CONFIG","blockers":["X-CONFIG"],"reason":str(exc),"tiers":[]}
