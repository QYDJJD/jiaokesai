"""Offline-first localhost platform. No third-party web framework or CDN."""
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, unquote
import json, mimetypes, uuid, re, os, sys, subprocess, threading, time, argparse, shutil
from core import ROOT, VERSION, LIMITS, NETWORK_LIMITS, templates, check_input, read_settings, make_manual_plan, human_error, now,convert_card
from worker import atomic

HERE=Path(__file__).resolve().parent
ID=re.compile(r'^[a-f0-9]{32}$')
ARTIFACTS={'输入情景卡.json','完整计算结果.json','验证报告.html','公交排班.csv','出租预约.csv','过程指标与对照.csv','分时核算明细.csv','复现说明.txt','完整验证包.zip','运力预约.csv','方式与线路使用.csv','逐节点核算.csv'}
TERMINAL={'completed','error','cancelled','timeout','interrupted'}

class Store:
    def __init__(self,path):
        self.root=Path(path).resolve();self.cards=self.root/'cards';self.runs=self.root/'runs'
        self.cards.mkdir(parents=True,exist_ok=True);self.runs.mkdir(parents=True,exist_ok=True)
        self.lock=threading.Lock();self.active={}
        for folder in self.runs.iterdir():
            if folder.is_dir() and ID.fullmatch(folder.name):
                progress=self.progress(folder.name)
                if progress.get('state')=='running':atomic(folder/'progress.json',{'state':'interrupted','stage':'服务重启前的计算未确认完成','updated_at':now()})

    def progress(self,key):
        path=self.runs/key/'progress.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def list_runs(self):
        rows=[]
        for folder in sorted(self.runs.iterdir(),key=lambda p:p.name,reverse=True):
            if not folder.is_dir() or not ID.fullmatch(folder.name):continue
            try:
                request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
                rows.append({'id':folder.name,'title':request['card'].get('platform',{}).get('title',request['card'].get('scenario_id','事件')),
                             'created_at':request['created_at'],'mode':request['settings']['mode'],**self.progress(folder.name)})
            except (OSError,ValueError,KeyError):continue
        return sorted(rows,key=lambda row:row['created_at'],reverse=True)[:100]

    def start(self,request):
        with self.lock:
            if self.active:raise RuntimeError('已有计算正在运行，请等待或先取消。')
            key=uuid.uuid4().hex;folder=self.runs/key;folder.mkdir()
            request={**request,'created_at':now()};atomic(folder/'request.json',request)
            atomic(folder/'progress.json',{'state':'running','stage':'已启动，正在构建模型','updated_at':now()})
            log=(folder/'worker.log').open('wb')
            kwargs={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
            environment=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
            process=subprocess.Popen([sys.executable,'-X','utf8',str(HERE/'worker.py'),str(folder)],cwd=ROOT,
                                     stdout=log,stderr=log,env=environment,**kwargs)
            self.active[key]=process
            threading.Thread(target=self.watch,args=(key,process,log,request['settings']['seconds']*4+90),daemon=True).start()
            return key

    def watch(self,key,process,log,timeout):
        try:
            try:process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.terminate();process.wait(timeout=10)
                atomic(self.runs/key/'progress.json',{'state':'timeout','stage':'超过整次运行上限，已停止；不能据此认定无解','updated_at':now()})
            with self.lock:
                progress=self.progress(key)
                if progress.get('state')=='running':atomic(self.runs/key/'progress.json',{'state':'error','stage':f'计算进程提前结束（退出码{process.returncode}），请查看运行日志','updated_at':now()})
        finally:
            log.close()
            with self.lock:self.active.pop(key,None)

    def cancel(self,key):
        with self.lock:
            process=self.active.get(key)
            if process and process.poll() is None:
                process.terminate();process.wait(timeout=10)
                atomic(self.runs/key/'progress.json',{'state':'cancelled','stage':'用户已取消本次运行','updated_at':now()})
                self.active.pop(key,None)
                return True
            return False

class Handler(BaseHTTPRequestHandler):
    server_version='JiaokesaiLocal/1'
    def log_message(self,fmt,*args):pass

    def send(self,status,body,kind='application/json; charset=utf-8',download=None):
        if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if download:
            from urllib.parse import quote
            self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(download))
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass

    def allowed(self):
        host=self.headers.get('Host','')
        expected={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if host not in expected:self.send(403,{'error':'仅允许本机访问'});return False
        origin=self.headers.get('Origin')
        if origin and origin not in {'http://'+h for h in expected}:self.send(403,{'error':'不接受其他网站发起的请求'});return False
        return True

    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<=LIMITS['body_bytes']:raise ValueError('输入文件为空或超过2MB')
        value=json.loads(self.rfile.read(size).decode('utf-8-sig'))
        if not isinstance(value,dict):raise ValueError('请求必须为对象')
        return value

    def do_GET(self):
        if not self.allowed():return
        try:
            path=unquote(urlsplit(self.path).path);parts=path.strip('/').split('/');store=self.server.store
            if path=='/api/health':return self.send(200,{'product':'jiaokesai-platform','version':VERSION,'active_runs':list(store.active),'local_only':True})
            if path=='/api/schema':return self.send(200,{'schema_version':'NETWORK-CARD-02','limits':NETWORK_LIMITS,'entities':['nodes','modes','pools','links','groups','profiles','facilities','occupancy_facilities'],'legacy_card_supported':True})
            if path=='/api/templates':return self.send(200,templates())
            if path=='/api/cards':
                values=[]
                for file in store.cards.glob('*.json'):
                    record=json.loads(file.read_text(encoding='utf-8'));values.append({k:record[k] for k in ('id','title','saved_at')})
                return self.send(200,sorted(values,key=lambda r:r['saved_at'],reverse=True))
            if len(parts)==3 and parts[:2]==['api','cards'] and ID.fullmatch(parts[2]):
                file=store.cards/(parts[2]+'.json')
                return self.send(200,json.loads(file.read_text(encoding='utf-8'))) if file.exists() else self.send(404,{'error':'找不到保存的情景卡'})
            if path=='/api/runs':return self.send(200,store.list_runs())
            if len(parts)>=3 and parts[:2]==['api','runs'] and ID.fullmatch(parts[2]):
                folder=store.runs/parts[2]
                if not folder.is_dir():return self.send(404,{'error':'找不到运行记录'})
                if len(parts)==3:return self.send(200,{'id':parts[2],**store.progress(parts[2])})
                if len(parts)==4 and parts[3]=='result':
                    file=folder/'result.json'
                    return self.send(200,json.loads(file.read_text(encoding='utf-8'))) if file.exists() and store.progress(parts[2]).get('state')=='completed' else self.send(409,{'error':'本次计算尚未完成'})
                if len(parts)==5 and parts[3]=='files' and parts[4] in ARTIFACTS:
                    file=folder/parts[4]
                    if not file.exists() or store.progress(parts[2]).get('state')!='completed':return self.send(404,{'error':'文件尚未生成'})
                    kind=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                    return self.send(200,file.read_bytes(),kind+(' ;charset=utf-8' if kind.startswith('text/') else ''),None if file.suffix=='.html' else file.name)
            name='index.html' if path=='/' else path.lstrip('/')
            if name not in {'index.html','app.js','style.css'}:return self.send(404,{'error':'页面不存在'})
            file=HERE/'web'/name;kind={'html':'text/html','js':'text/javascript','css':'text/css'}[file.suffix[1:]]
            return self.send(200,file.read_bytes(),kind+'; charset=utf-8')
        except (ValueError,KeyError,TypeError) as exc:return self.send(400,{'error':human_error(exc)})
        except OSError:return self.send(500,{'error':'本地文件读取失败，请检查服务日志'})

    def do_POST(self):
        if not self.allowed():return
        try:
            path=urlsplit(self.path).path;parts=path.strip('/').split('/');store=self.server.store
            if path=='/api/shutdown':
                if store.active:return self.send(409,{'error':'请先等待或取消正在运行的计算'})
                self.send(200,{'ok':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            if len(parts)==4 and parts[:2]==['api','runs'] and parts[3]=='cancel' and ID.fullmatch(parts[2]):return self.send(200,{'cancelled':store.cancel(parts[2])})
            body=self.body()
            if path=='/api/validate':
                checked=check_input(body.get('card'))
                if checked['valid']:
                    settings=read_settings(body.get('settings',{}))
                    if settings['mode']=='manual':
                        try:make_manual_plan(body['card'],body.get('manual',{}))
                        except ValueError as exc:checked['valid']=False;checked['errors'].append({'field':'manual','message':str(exc)})
                return self.send(200,checked)
            if path=='/api/convert':return self.send(200,{'card':convert_card(body.get('card',{})),'note':'已转换为通用网络；保留离开起点截止，另增目的节点截止，须重新计算。原记录未修改。'})
            if path=='/api/cards':
                card=body.get('card')
                if not isinstance(card,dict):raise ValueError('请提供情景卡')
                key=uuid.uuid4().hex;record={'id':key,'saved_at':now(),'title':str(card.get('platform',{}).get('title',card.get('scenario_id','未命名事件')))[:200],'card':card}
                atomic(store.cards/(key+'.json'),record);return self.send(201,{k:v for k,v in record.items() if k!='card'})
            if path=='/api/runs':
                card=body.get('card');checked=check_input(card)
                if not checked['valid']:return self.send(422,{'error':'输入未通过核对','validation':checked})
                settings=read_settings(body.get('settings',{}));manual=body.get('manual',{})
                if settings['mode']=='manual':make_manual_plan(card,manual)
                key=store.start({'card':card,'settings':settings,'manual':manual})
                return self.send(202,{'id':key})
            return self.send(404,{'error':'接口不存在'})
        except RuntimeError as exc:return self.send(409,{'error':str(exc)})
        except (ValueError,KeyError,TypeError,OverflowError) as exc:return self.send(400,{'error':human_error(exc)})
        except OSError:return self.send(500,{'error':'本地保存或运行失败，请检查服务日志'})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);parser.add_argument('--data-dir',default=str(ROOT/'06_实验验证/平台运行记录'));parser.add_argument('--check-runtime',action='store_true')
    args=parser.parse_args()
    if args.check_runtime:print('Runtime ready: '+VERSION);return
    store=Store(args.data_dir)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True;server.store=store
    atomic(store.root/'service.json',{'pid':os.getpid(),'port':args.port,'version':VERSION,'started_at':now()})
    print(f'交科赛研究平台 http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever(poll_interval=.3)
    finally:
        for key in list(store.active):store.cancel(key)
        server.server_close()

if __name__=='__main__':main()
