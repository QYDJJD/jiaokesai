"""One process per run: solver timeouts cannot freeze the local web server."""
from pathlib import Path
import json, os, sys, traceback, importlib.metadata, datetime

def now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')

def atomic(path,value):
    path=Path(path);temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    os.replace(temp,path)

def run(folder):
    folder=Path(folder);request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    def progress(stage):atomic(folder/'progress.json',{'state':'running','stage':stage,'updated_at':now()})
    try:
        if request.get('kind')=='sensitivity':
            from core import ROOT
            sys.path.insert(0,str(ROOT/'04_建模/多方式网络优化'))
            from resource_sensitivity import compare
            progress('正在逐一比较基准和资源情景；较大网络可能需要等待')
            result=compare(request['card'],request['variants'],seconds=request['settings']['seconds'])
            result['run_id']=folder.name
            atomic(folder/'result.json',result)
            atomic(folder/'progress.json',{'state':'completed','stage':'比较计算已完成','updated_at':now(),'artifacts':[]})
            return
        from core import evaluate, write_exports
        result=evaluate(request['card'],request['settings'],request.get('manual'),progress)
        result['runtime']={n:importlib.metadata.version(n) for n in ('numpy','scipy')}
        result['run_id']=folder.name
        atomic(folder/'result.json',result)
        artifacts=write_exports(folder,result)
        atomic(folder/'progress.json',{'state':'completed','stage':'计算与独立复核已完成','updated_at':now(),
                                     'result_status':result['status'],'artifacts':artifacts})
    except Exception as exc:
        (folder/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        atomic(folder/'progress.json',{'state':'error','stage':'运行未完成','updated_at':now(),
                                     'message':str(exc) or type(exc).__name__})
        raise

if __name__=='__main__':run(sys.argv[1])
