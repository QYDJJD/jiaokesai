"""Rational cumulative-flow oracle. Imports no grading/search implementation.

Backlog = X(t) - min(0, inf_{0<=u<=t} X(u)), X=B0+A-S.
This independently checks the declared continuous, work-conserving queue.
It is not observed data, external validation or a vehicle simulation.
"""
from fractions import Fraction as F


def number(x):
    return F(str(x)).limit_denominator(10**9)


def rational_segments(segments):
    return [(number(a),None if b is None else number(b),number(c)) for a,b,c in segments]


def integral(segments,t):
    return sum((max(F(0),min(t,b if b is not None else t)-a)*c for a,b,c in segments),F(0))


def rate(segments,t):
    return sum((c for a,b,c in segments if a<=t and (b is None or t<b)),F(0))


class CumulativeQueue:
    def __init__(self,arrivals,supplies,initial=0):
        self.arr=rational_segments(arrivals);self.cap=rational_segments(supplies);self.b0=number(initial)
        self.points=sorted({F(0),*[v for curve in (self.arr,self.cap) for a,b,c in curve for v in (a,b) if v is not None]})
        self.total=self.b0+sum(((b-a)*c for a,b,c in self.arr),F(0))

    def queue(self,t):
        t=number(t)
        def x(u):return self.b0+integral(self.arr,u)-integral(self.cap,u)
        running_min=min(F(0),x(t),*[x(u) for u in self.points if u<=t])
        return x(t)-running_min

    def result(self,deadline):
        peak=max(self.queue(t) for t in self.points)
        last_arrival=max((b for a,b,c in self.arr if c>0),default=F(0))
        left=self.queue(last_arrival);clear=F(0) if self.total==0 else (last_arrival if left==0 else None)
        if clear is None:
            times=sorted({last_arrival,*[t for t in self.points if t>last_arrival]})
            for a,b in zip(times,times[1:]):
                c=rate(self.cap,(a+b)/2)
                if c>0 and left<=c*(b-a):
                    clear=a+left/c;break
                left-=c*(b-a)
            if clear is None:
                c=rate(self.cap,times[-1]+1)
                if c>0:clear=times[-1]+left/c
        final=self.queue(self.points[-1]) if clear is None else F(0)
        return {'peak_people':peak,'clear_h':clear,'residual_at_deadline_people':self.queue(deadline),
                'unserved_people':final,'served_people':self.total-final,'arrived_people':self.total}


def arrival_curve(q,d,shape):
    q,d=number(q),number(d)
    if not q:return []
    if shape=='uniform':return [(0,d,q/d)]
    if shape=='front':return [(0,d/4,q*F(4,5)/(d/4)),(d/4,d,q*F(1,5)/(d*F(3,4)))]
    if shape=='back':return [(0,d*F(3,4),q*F(1,5)/(d*F(3,4))),(d*F(3,4),d,q*F(4,5)/(d/4))]
    raise ValueError('unknown profile')


def reference_single_grade(p,k=1000,h=1):
    blockers=[]
    if p.get('safe') is False:blockers.append('X-SAFE')
    if p.get('known',True) is False or p.get('safe',True) is None:blockers.append('X-DATA')
    if p.get('supported',True) is False:blockers.append('X-STRUCTURE')
    if blockers:return blockers[0]
    q,d=p['q'],p['d']
    if q<0 or d<0 or (q>0 and d==0):return 'X-CONFIG'
    start=max(0,1-number(p.get('p',1)));factor=number(p.get('factor',1))
    ends=p.get('ends',[None,None,None]);b0=p.get('b0',0)
    resources=[(0,ends[0],500*factor),(start,ends[1],500*factor),(start,ends[2],1000*factor)]
    for layer in range(3):
        caps=[s for s in resources[:layer+1] if s[1] is None or s[1]>s[0]]
        rows=[CumulativeQueue(arrival_curve(q,d,shape),caps,b0).result(number(d)+number(h))
              for shape in p.get('shapes',['uniform'])]
        if all(r['peak_people']<=number(k) and r['clear_h'] is not None and r['clear_h']<=number(d)+number(h) for r in rows):
            return 'F'+str(layer)
    return 'F3'


def reference_directional_grade(c):
    blockers=[]
    if c.get('safe') is False:blockers.append('X-SAFE')
    if c.get('known',True) is False or c.get('safe',True) is None:blockers.append('X-DATA')
    if c.get('supported',True) is False:blockers.append('X-STRUCTURE')
    if blockers:return blockers[0]
    try:
        dirs=c['directions'];resources=c['resources'];groups=c.get('groups',[])
        ids=[r['id'] for r in resources];pools=[r['pool_id'] for r in resources]
        if len(ids)!=len(set(ids)) or len(pools)!=len(set(pools)):raise ValueError('identity')
        if any(r['layer'] not in (0,1,2) or any(d not in dirs for d in r['directions']) for r in resources):raise ValueError('eligibility')
        rd={r['id']:r for r in resources};passed=[]
        for p in c['plans']:
            by_res={rid:[] for rid in ids};by_dir={d:[] for d in dirs}
            for a in p['allocations']:
                r=rd[a['resource_id']];d=a['direction']
                if d not in r['directions'] or r['layer']>p['introduced_layer']:raise ValueError('allocation')
                by_res[r['id']]+=a['segments'];by_dir[d]+=a['segments']
            times=sorted({F(0),*[number(t) for curve in list(by_res.values())+[r['capacity'] for r in resources]+[g['capacity'] for g in groups]
                          for a,b,v in curve for t in (a,b) if t is not None]})
            probes=[(a+b)/2 for a,b in zip(times,times[1:])]+[times[-1]+1]
            for t in probes:
                uses={rid:rate(rational_segments(seg),t) for rid,seg in by_res.items()}
                if any(uses[rid]>rate(rational_segments(rd[rid]['capacity']),t) for rid in ids):raise ValueError('resource capacity')
                if any(sum((uses[rid] for rid in g['resource_ids']),F(0))>rate(rational_segments(g['capacity']),t) for g in groups):raise ValueError('shared capacity')
            ok=True
            for omega in c['joint_profiles']:
                qs={d:CumulativeQueue(arrival_curve(x['q'],x['d'],omega['shapes'][d]),by_dir[d],x['b0']) for d,x in dirs.items()}
                rows={d:q.result(number(dirs[d]['d'])+number(dirs[d]['h'])) for d,q in qs.items()}
                ok &= all(r['peak_people']<=number(dirs[d]['k']) and r['clear_h'] is not None and
                          r['clear_h']<=number(dirs[d]['d'])+number(dirs[d]['h']) for d,r in rows.items())
                for g in c.get('waiting_groups',[]):
                    probes=sorted({t for d in g['directions'] for t in qs[d].points})
                    # Each queue is convex between these physical breakpoints,
                    # so the sum's maximum is attained at an endpoint.
                    ok &= max(sum((qs[d].queue(t) for d in g['directions']),F(0)) for t in probes)<=number(g['k'])
            if ok:passed.append(p['introduced_layer'])
        return 'F'+str(min(passed,default=3))
    except (KeyError,ValueError,ZeroDivisionError):return 'X-CONFIG'
