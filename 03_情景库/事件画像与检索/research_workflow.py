"""模块A研究原型：来源可追溯的候选指标。在线提供器为可注入接口。"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import engine

VERSION = 'EVIDENCE-WORKFLOW-01'
# 规则为演示线索；命中原文只能提出调查项，不能证明历史数值适用于当前事件。
RULES = (
    {'id':'metro_extension','name':'轨交延时可行性','terms':['延时运营','延时加开'], 'fixed_fields':['metro_status']},
    {'id':'bus_service','name':'公交可用运力与发车计划','terms':['公交','夜宵线'], 'fixed_fields':['resource_inventory']},
    {'id':'taxi_service','name':'出租车到达率与蓄车状态','terms':['出租','蓄车'], 'fixed_fields':['resource_inventory']},
    {'id':'safety_capacity','name':'候车空间与安全条件','terms':['滞留','隔离区'], 'fixed_fields':['safety_status']},
    {'id':'arrival_profile','name':'旅客分时到达过程','terms':['晚点到达','晚点抵沪'], 'fixed_fields':['arrival_profile']},
)

def query_terms(portrait):
    engine.validate(portrait)
    terms = []
    for name in ('event_type','cause','location','time_period'):
        item = engine.field(portrait,name)
        if item['status'] != 'unknown' and isinstance(item['value'],str):
            term=engine.canonical(name,item['value'])
            if len(term)<=80 and re.fullmatch(r'[\w\u4e00-\u9fff /—-]+',term): terms.append(term)
    return terms

class MockProvider:
    """测试适配器：读取由调用方提供的演示文档，不联网。"""
    kind='mock'
    def __init__(self,documents): self.documents=deepcopy(documents)
    def search(self,terms): return deepcopy(self.documents)

def recommend(portrait, provider, fixed_indicators=()):
    terms=query_terms(portrait)
    if getattr(provider,'kind',None) not in ('mock','online') or not callable(getattr(provider,'search',None)):
        raise ValueError('提供器需声明mock或online并实现search')
    fixed=set(fixed_indicators); candidates={}; rejected=[]
    for doc in provider.search(terms):
        for key in ('url','title','publication_date','collected_at','text','publisher'):
            if not isinstance(doc.get(key),str) or not doc[key].strip(): raise ValueError('证据缺少字段：'+key)
        if not doc['url'].startswith(('https://','http://')): raise ValueError('来源链接必须为HTTP(S)')
        try:
            dt=datetime.fromisoformat(doc['collected_at'])
            if dt.utcoffset() is None: raise ValueError()
            datetime.strptime(doc['publication_date'],'%Y-%m-%d')
        except ValueError: raise ValueError('发布日期或采集时间格式无效') from None
        if len(doc['text'])>200000: raise ValueError('文档正文超出20万字符')
        for rule in RULES:
            positions=[(doc['text'].find(term),term) for term in rule['terms'] if term in doc['text']]
            if not positions: continue
            if rule['id'] in fixed:
                rejected.append({'indicator_id':rule['id'],'reason':'该具体指标已在固定清单中'});continue
            start,term=min(positions); end=start+len(term)
            evidence={'source_url':doc['url'],'title':doc['title'],'publisher':doc['publisher'],
                      'publication_date':doc['publication_date'],'collected_at':doc['collected_at'],
                      'quote':doc['text'][start:end], 'start':start,'end':end,
                      'text_sha256':hashlib.sha256(doc['text'].encode('utf-8')).hexdigest(),
                      'provider_kind':provider.kind,'source_status':'演示文本，未验证原页' if provider.kind=='mock' else '机器提取，待人工核原页',
                      'credibility':'未评定；须人工检查发布主体和原文'}
            broader_known = any(engine.field(portrait,f)['status']!='unknown' for f in rule['fixed_fields'])
            c=candidates.setdefault(rule['id'],{'indicator_id':rule['id'],'name':rule['name'],
                'reason':'来源文本出现相关线索，建议确认当前事件的对应条件；不迁移历史数值。',
                'broader_field_present':broader_known,
                'detail_note':'已有相关字段，请核实是否包含本项细节' if broader_known else '相关字段尚未填写',
                'current_value':None,'confirmation':'pending','evidence':[]})
            if not any(e['source_url']==evidence['source_url'] and e['quote']==evidence['quote'] for e in c['evidence']): c['evidence'].append(evidence)
    return {'version':VERSION,'query_terms':terms,'provider':provider.kind,'recommendations':list(candidates.values()),
            'dedup_notes':rejected,'notice':'指标与权重为规则演示，待人工核对来源及适用性。'}

def confirm(candidate, current_value, actor, confirmed_at):
    if not isinstance(current_value,str) or not current_value.strip() or not isinstance(actor,str) or not actor.strip():
        raise ValueError('需填写本次事件值和确认人')
    try:
        if datetime.fromisoformat(confirmed_at).utcoffset() is None: raise ValueError()
    except (ValueError,TypeError): raise ValueError('确认时间需含时区') from None
    if candidate.get('confirmation')!='pending' or not candidate.get('evidence'): raise ValueError('候选状态或证据无效')
    result=deepcopy(candidate);result.update(confirmation='confirmed',current_value=current_value,confirmed_by=actor,confirmed_at=confirmed_at)
    return result
