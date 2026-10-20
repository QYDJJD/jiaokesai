"""Data schema for named modes on a directed, time-expanded transport network."""
import math, datetime, copy

VERSION='NETWORK-MILP-02'
SCHEMA='NETWORK-CARD-02'
LIMITS={'nodes':12,'links':36,'modes':12,'pools':16,'groups':8,'profiles':8,'periods':96,'body_bytes':2_000_000}
EPS=1e-6

def numeric(v):return type(v) in (int,float) and math.isfinite(v)
def calendar(value,periods):
    return [float(value)]*periods if numeric(value) else list(value)

def validate(card):
    if not isinstance(card,dict) or card.get('schema_version')!=SCHEMA:raise ValueError('需要通用多方式网络情景卡 NETWORK-CARD-02')
    if not isinstance(card.get('scenario_id'),str) or not card['scenario_id'].strip():raise ValueError('请填写情景编号')
    p=card.get('parameters',{});f=card.get('five_dimensions',{})
    def num(obj,key,label,minimum=0,integer=False,nullable=False):
        v=obj.get(key)
        if nullable and v is None:return
        if not numeric(v) or v<minimum or (integer and int(v)!=v):raise ValueError(label+'须为'+('非负整数' if integer and minimum==0 else '有效数值'))
    for key,label in [('step_minutes','时间步'),('entry_steps','进入时段数'),('deadline_minutes','到达目的节点截止'),('budget_yuan','预约预算'),('queue_limit_people','全网络候客上限')]:num(p,key,label,integer=key in ('step_minutes','entry_steps'))
    if p['step_minutes'] not in (5,10,15,20,30):raise ValueError('时间步可选5、10、15、20或30分钟')
    if p['deadline_minutes']%p['step_minutes'] or not 1<=p['deadline_minutes']/p['step_minutes']<=LIMITS['periods']:raise ValueError('目的节点截止须对齐时间步，时域为1至96段')
    T=int(p['deadline_minutes']/p['step_minutes'])
    if not 1<=p['entry_steps']<=T:raise ValueError('进入时段数应在1与总时段数之间')
    num(p,'standing_person_minutes_limit','全网络站立负担上限',nullable=True)
    num(p,'origin_departure_deadline_minutes','离开起点截止',nullable=True)
    if p.get('origin_departure_deadline_minutes') is not None and p['origin_departure_deadline_minutes']>p['deadline_minutes']:raise ValueError('离开起点截止不得晚于目的节点截止')
    if not numeric(f.get('information_lead_minutes')):raise ValueError('信息提前量须为有效数值；开始后得知可填负数')
    try:
        when=datetime.datetime.fromisoformat(p['start_time'])
        if when.tzinfo is None:raise ValueError()
    except (ValueError,TypeError,KeyError):raise ValueError('开始时间须包含时区')
    records={}
    for field in ('nodes','modes','pools','links','groups','profiles'):
        rows=card.get(field)
        if not isinstance(rows,list) or len(rows)>LIMITS[field] or (not rows and field not in ('pools','links')):raise ValueError('节点、方式、资源池、线路、群体或过程数量不符合第一版规模')
        ids=[]
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'].strip() or not isinstance(row.get('label'),str) or not row['label'].strip():raise ValueError('各条目须有非空编号与中文名称')
            ids.append(row['id'])
        if len(set(ids))!=len(ids):raise ValueError(field+'存在重复编号')
        records[field]={r['id']:r for r in rows}
    def cal(value,label):
        vals=calendar(value,T) if numeric(value) or isinstance(value,list) else []
        if len(vals)!=T or any(not numeric(v) or v<0 for v in vals):raise ValueError(label+f'须为非负常数或完整的{T}段数组')
    for node in card['nodes']:
        num(node,'queue_limit_people','节点候客上限');num(node,'waiting_area_m2','节点有效面积',minimum=1e-9)
        num(node,'waiting_density_limit','节点候客密度上限',nullable=True)
        cal(node.get('boarding_capacity'),'节点登乘能力');cal(node.get('receiving_capacity'),'节点接收能力')
    for mode in card['modes']:
        if mode.get('control') not in ('fixed','adjustable'):raise ValueError('方式须选择既定服务或可协调增援')
        if mode.get('comfort') not in ('seats','unmeasured'):raise ValueError('舒适口径须选择坐席与站立，或未测度')
        num(mode,'standing_density_limit','方式站立密度上限')
        num(mode,'standing_person_minutes_limit','方式累计站立上限',nullable=True)
        if type(mode.get('enabled',True)) is not bool:raise ValueError('方式启用状态须为布尔值')
    for pool in card['pools']:
        if pool.get('kind') not in ('vehicle','quota'):raise ValueError('资源池须为周转车辆或分时服务名额')
        for key,label in [('available_units','可用单位数'),('total_units_limit','全程投放次数'),('seats','每单位座位'),('legal_capacity','每单位核定容量')]:num(pool,key,label,integer=True)
        for key,label in [('standing_area_m2','每单位站立面积'),('prepare_minutes','准备时间'),('close_minutes','资源服务结束'),('turnaround_minutes','周转时间')]:num(pool,key,label)
        if any(pool[k]>2880 for k in ('prepare_minutes','close_minutes','turnaround_minutes')):raise ValueError('资源相对时刻或准备时长不能超过2880分钟，请检查单位')
        if pool['available_units']>2000 or pool['total_units_limit']>20000:raise ValueError('资源池数量超过平台规模，请检查单位')
        if pool['seats']>pool['legal_capacity']:raise ValueError('每单位座位不得超过核定容量')
        if pool['kind']=='vehicle' and pool.get('home_node') not in records['nodes']:raise ValueError('周转资源池须指定返回的基地节点')
    for link in card['links']:
        if link.get('from') not in records['nodes'] or link.get('to') not in records['nodes'] or link['from']==link['to']:raise ValueError('线路起终点须为两个已有节点')
        if link.get('mode_id') not in records['modes']:raise ValueError('线路引用的运输方式不存在')
        for key,label in [('travel_minutes','线路运行时间'),('boarding_minutes','线路登乘时间'),('return_minutes','返回基地运行时间'),('unit_cost_yuan','单位预约费用'),('service_start_minutes','最早离站'),('service_end_minutes','最晚离站')]:num(link,key,label)
        if link['travel_minutes']<=0:raise ValueError('线路运行或换乘时间须大于0，防止同一时刻虚假换乘')
        if any(link[k]>2880 for k in ('travel_minutes','boarding_minutes','return_minutes','service_start_minutes','service_end_minutes')):raise ValueError('线路时长或窗口不能超过2880分钟，请检查单位')
        for key,label in [('fixed_capacity','既定服务容量'),('fixed_seats','既定服务座位'),('fixed_standing_area_m2','既定服务站立面积'),('max_units','线路每段增援单位上限')]:cal(link.get(key),label)
        if any(abs(v-round(v))>EPS for v in calendar(link['max_units'],T)):raise ValueError('每段增援单位上限须为整数')
        # A cancelled/reduced service can retain its seat-calendar declaration;
        # the effective available seats are always capped by service capacity.
        pid=link.get('pool_id');pool=records['pools'].get(pid)
        if pid and pool is None:raise ValueError('线路引用的资源池不存在')
        if any(calendar(link['max_units'],T)):
            if pool is None:raise ValueError('可增援线路须指定资源池')
            if records['modes'][link['mode_id']]['control']!='adjustable':raise ValueError('既定服务方式不能擅自新增班次；请在取得协调条件后选择可协调增援')
        if pool and pool['kind']=='vehicle' and pool['home_node']!=link['from']:raise ValueError('同一周转池的线路须从其基地出发；不同基地请建立不同资源池')
        if link['service_end_minutes']<link['service_start_minutes']:raise ValueError('线路结束时刻不能早于开始')
    for group in card['groups']:
        if group.get('origin') not in records['nodes'] or group.get('destination') not in records['nodes'] or group['origin']==group['destination']:raise ValueError('旅客群体须有不同的已有起点与目的节点')
        if not isinstance(group.get('allowed_modes'),list) or not group['allowed_modes'] or any(m not in records['modes'] for m in group['allowed_modes']):raise ValueError('须为每个人群选择可接受的已有方式')
        num(group,'initial_people','群体初始人数');num(group,'queue_limit_people','群体起点候客上限',nullable=True)
    for profile in card['profiles']:
        values=profile.get('arrivals',{})
        if not isinstance(values,dict) or set(values)!=set(records['groups']):raise ValueError('每条进入过程须逐一覆盖所有旅客群体')
        for arr in values.values():
            if not isinstance(arr,list) or len(arr)!=p['entry_steps'] or any(not numeric(v) or v<0 for v in arr):raise ValueError('各群体进入量须逐段覆盖进入时段，且为非负有效人数')
    for facility in card.get('facilities',[]):
        if not isinstance(facility.get('links'),list) or any(a not in records['links'] for a in facility['links']):raise ValueError('共享设施引用了不存在的线路')
        cal(facility.get('capacity'),'共享设施能力')
    for facility in card.get('occupancy_facilities',[]):
        if not isinstance(facility.get('id'),str) or not isinstance(facility.get('links'),list) or any(a not in records['links'] for a in facility['links']):raise ValueError('登乘占用设施的编号或线路引用无效')
        num(facility,'available_units','可供增援使用的并发登乘位',integer=True)
    return records

def lags(card,link):
    step=card['parameters']['step_minutes']
    return math.ceil(link['boarding_minutes']/step),math.ceil(link['travel_minutes']/step)

def totals(card):
    return {s['id']:sum(sum(v) for v in s['arrivals'].values())+sum(g['initial_people'] for g in card['groups']) for s in card['profiles']}

def five_summary(card):
    p=card['parameters'];values=list(totals(card).values());new=[v-sum(g['initial_people'] for g in card['groups']) for v in values]
    return {'信息提前量':card['five_dimensions']['information_lead_minutes'],
       '到达不确定性':f'{len(values)}条显式进入过程；总量和群体份额可随过程变化，未赋概率',
       '进入持续分钟':p['entry_steps']*p['step_minutes'],
       '新增待接续人数':{'最少':min(new),'最多':max(new)},
       '方式与空间服务状态':'由方式启用、逐段线路容量、节点能力和资源池窗口共同表达'}

def capacity(card,link,t):
    p=card['parameters'];T=int(p['deadline_minutes']/p['step_minutes']);m=next(m for m in card['modes'] if m['id']==link['mode_id'])
    b,ride=lags(card,link);depart=(t+b)*p['step_minutes']
    enabled=m.get('enabled',True) and link['service_start_minutes']-EPS<=depart<=link['service_end_minutes']+EPS
    fixed=calendar(link['fixed_capacity'],T)[t] if enabled else 0
    seats=min(fixed,calendar(link['fixed_seats'],T)[t]);area=calendar(link['fixed_standing_area_m2'],T)[t] if enabled else 0
    if m['comfort']=='seats':fixed=min(fixed,seats+area*m['standing_density_limit'])
    unit=0.;unit_seats=0.;maximum=0
    pool=next((r for r in card['pools'] if r['id']==link.get('pool_id')),None)
    if pool:
        unit=pool['legal_capacity'];unit_seats=pool['seats']
        if m['comfort']=='seats':unit=min(unit,unit_seats+pool['standing_area_m2']*m['standing_density_limit'])
        end=(t+b)*p['step_minutes']
        if pool['kind']=='vehicle':end+=(ride*p['step_minutes']+link['return_minutes']+pool['turnaround_minutes'])
        ready=max(0,pool['prepare_minutes']-card['five_dimensions']['information_lead_minutes'])
        if enabled and t*p['step_minutes']+EPS>=ready and end<=pool['close_minutes']+EPS:
            maximum=int(calendar(link['max_units'],T)[t])
    if (t+b+ride)>T:fixed=0;maximum=0
    return fixed,seats,unit,unit_seats,maximum
