"""HTTP-to-worker regression for the sensitivity interface."""
from pathlib import Path
import json, sys, tempfile, threading, time, unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'04_建模/交互验证平台'))
from server import Store, Handler, ThreadingHTTPServer
from core import templates

class SensitivityPlatformChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True;self.server.store=Store(self.temp.name)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        for key in list(self.server.store.active):self.server.store.cancel(key)
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path,body=None):
        data=None if body is None else json.dumps(body).encode('utf-8')
        with urlopen(Request(self.url+path,data=data,headers={'Content-Type':'application/json'}),timeout=10) as r:
            return r.status,r.read()
    def test_worker_and_result_with_baseline_snapshot(self):
        status,html=self.request('/sensitivity');self.assertEqual(status,200);self.assertIn('开始比较',html.decode('utf-8'))
        card=templates()['tiny'];card['parameters']['budget_yuan']=100
        variants=[{'name':'预算','changes':[{'target':'parameters','field':'budget_yuan','value':200}]}]
        status,data=self.request('/api/sensitivity',{'card':card,'variants':variants,'seconds':5})
        self.assertEqual(status,202);key=json.loads(data)['id']
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            _,data=self.request('/api/runs/'+key);state=json.loads(data)
            if state['state']!='running':break
            time.sleep(.1)
        logs=''
        for name in ('worker.log','error.log'):
            p=self.server.store.runs/key/name
            if p.exists():logs+=p.read_text(encoding='utf-8',errors='replace')
        self.assertEqual(state['state'],'completed',(state,logs))
        _,data=self.request('/api/runs/'+key+'/result');rows=json.loads(data)['scenarios']
        self.assertEqual([r['worst_unserved'] for r in rows],[6,0]);self.assertEqual(rows[1]['certified_reduction_people'],6)
        self.assertEqual(self.server.store.list_runs(),[])
    def test_rejects_empty_and_excessive_work(self):
        card=templates()['tiny']
        for body in ({'card':card,'variants':[]}, {'card':card,'variants':[{}]*5},
                     {'card':card,'variants':[{'name':'a','changes':[{}]}],'seconds':100}):
            with self.assertRaises(HTTPError) as err:self.request('/api/sensitivity',body)
            self.assertEqual(err.exception.code,400)
            err.exception.close()

if __name__=='__main__':unittest.main()
