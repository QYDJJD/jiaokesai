"""Platform checks: input safety, manual plans, subprocess and export round-trip."""
from pathlib import Path
import sys, unittest, copy, json, tempfile, zipfile, csv, io, threading, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'04_建模/交互验证平台'))
from core import tiny_card, templates, check_input, make_manual_plan, evaluate, write_exports, clock
from server import Store, Handler, ThreadingHTTPServer

SETTINGS={'mode':'optimize','objective':'wait','seconds':5}
MANUAL={'bus':[{'direction_id':'D1','vehicle_id':'车1','departure_minute':30},
               {'direction_id':'D1','vehicle_id':'车1','departure_minute':60}],'taxi':[]}

class PlatformChecks(unittest.TestCase):
    def test_valid_templates_and_negative_information(self):
        for card in templates().values():self.assertTrue(check_input(card)['valid'])
        card=tiny_card();card['five_dimensions']['information_lead_minutes']=-60
        self.assertTrue(check_input(card)['valid'])

    def test_missing_and_malformed_inputs_are_actionable(self):
        for value in [None,[],{}, {'parameters':{},'directions':[]}]:self.assertFalse(check_input(value)['valid'])
        for mutate in [lambda c:c['parameters'].update(bus_fleet_size=True),
                       lambda c:c['directions'][0].update(share='1'),
                       lambda c:c['arrival_profiles'][0].update(hourly_people=[float('nan')]),
                       lambda c:c['parameters'].update(bus_boarding_minutes=0)]:
            c=tiny_card();mutate(c);self.assertFalse(check_input(c)['valid'])

    def test_total_and_direction_share_mismatch(self):
        c=tiny_card();c['five_dimensions']['new_onward_passengers']=13
        self.assertFalse(check_input(c)['valid'])
        c=tiny_card();c['directions'][0]['share']=.8;self.assertFalse(check_input(c)['valid'])

    def test_size_limit_and_invalid_datetime(self):
        c=tiny_card();c['parameters']['start_time']='not-a-time';self.assertFalse(check_input(c)['valid'])
        c=tiny_card();c['parameters']['step_minutes']=5;c['parameters']['deadline_minutes']=1000
        self.assertFalse(check_input(c)['valid'])

    def test_manual_pass_matches_hand_calculation(self):
        r=evaluate(tiny_card(),{'mode':'manual'},MANUAL)
        self.assertEqual(r['status'],'passed');a=r['audit']['profiles'][0]
        self.assertEqual(a['total_wait_person_minutes'],240)
        self.assertEqual(a['mean_wait_minutes'],20)

    def test_manual_legal_but_incomplete_is_not_passed(self):
        manual=copy.deepcopy(MANUAL);manual['bus'].pop()
        r=evaluate(tiny_card(),{'mode':'manual'},manual)
        self.assertEqual(r['status'],'failed_targets');a=r['audit']['profiles'][0]
        self.assertEqual(a['deadline_remaining_people'],6)
        self.assertIsNone(a['mean_wait_minutes'])

    def test_manual_collision_and_taxi_units_rejected(self):
        manual=copy.deepcopy(MANUAL);manual['bus'][1]['departure_minute']=40
        with self.assertRaisesRegex(ValueError,'手工排班'):make_manual_plan(tiny_card(),manual)
        with self.assertRaisesRegex(ValueError,'整数倍'):make_manual_plan(tiny_card(),{'bus':[],'taxi':[{'direction_id':'D1','start_minute':0,'people':3}]})

    def test_zero_budget_is_infeasible_not_timeout(self):
        c=tiny_card();c['parameters']['budget_yuan']=0
        r=evaluate(c,SETTINGS);self.assertEqual(r['status'],'infeasible');self.assertIsNone(r.get('audit'))
        self.assertEqual(r['solution']['phase_primary']['status'],2)

    def test_export_zip_roundtrip_and_html_escaping(self):
        c=tiny_card();c['platform']['title']='<script>alert(1)</script>'
        r=evaluate(c,{'mode':'manual'},MANUAL)
        with tempfile.TemporaryDirectory() as name:
            exports=write_exports(name,r)
            with zipfile.ZipFile(Path(name)/'完整验证包.zip') as archive:
                self.assertEqual(len(archive.namelist()),8)
                restored=json.loads(archive.read('输入情景卡.json'))
                self.assertTrue(check_input(restored)['valid'])
                html=archive.read('验证报告.html').decode()
                self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert(1)</script>',html)
                rows=list(csv.DictReader(io.StringIO(archive.read('过程指标与对照.csv').decode('utf-8-sig'))))
                self.assertEqual(rows[1]['平均等待分钟'],'')

    def test_cross_day_clock(self):
        c=tiny_card();c['parameters']['start_time']='2026-10-20T23:30:00+08:00'
        self.assertEqual(clock(c,60),'10-21 00:30')

    def test_restart_marks_unfinished_job(self):
        with tempfile.TemporaryDirectory() as name:
            store=Store(name);key='a'*32;(store.runs/key).mkdir()
            (store.runs/key/'progress.json').write_text('{"state":"running"}',encoding='utf-8')
            restored=Store(name);self.assertEqual(restored.progress(key)['state'],'interrupted')

class HTTPChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.server.daemon_threads=True;cls.server.store=Store(cls.temp.name)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        for key in list(cls.server.store.active):cls.server.store.cancel(key)
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def request(self,path,data=None,headers=None):
        body=None if data is None else json.dumps(data).encode()
        req=Request(self.url+path,data=body,headers={'Content-Type':'application/json',**(headers or {})})
        with urlopen(req,timeout=20) as response:return response.status,response.read(),response.headers

    def test_http_save_validate_worker_and_download(self):
        card=tiny_card();status,data,_=self.request('/api/cards',{'card':card});self.assertEqual(status,201)
        saved=json.loads(data);_,data,_=self.request('/api/cards/'+saved['id']);self.assertEqual(json.loads(data)['card'],card)
        _,data,_=self.request('/api/validate',{'card':card,'settings':SETTINGS});self.assertTrue(json.loads(data)['valid'])
        _,data,_=self.request('/api/runs',{'card':card,'settings':SETTINGS});key=json.loads(data)['id']
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            _,data,_=self.request('/api/runs/'+key);progress=json.loads(data)
            if progress['state']!='running':break
            time.sleep(.1)
        logs=''
        if progress['state']!='completed':
            for name in ('worker.log','error.log'):
                file=self.server.store.runs/key/name
                if file.exists():logs+=file.read_text(encoding='utf-8',errors='replace')[-3000:]
        self.assertEqual(progress['state'],'completed',(progress,logs))
        _,data,_=self.request('/api/runs/'+key+'/result');r=json.loads(data);self.assertEqual(r['status'],'passed')
        from urllib.parse import quote
        _,package,headers=self.request('/api/runs/'+key+'/files/'+quote('完整验证包.zip'))
        self.assertIn('attachment',headers['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(package)) as archive:self.assertEqual(json.loads(archive.read('输入情景卡.json')),card)

    def test_origin_and_traversal_are_rejected(self):
        with self.assertRaises(HTTPError) as caught:self.request('/api/validate',{'card':tiny_card()},headers={'Origin':'https://example.com'})
        self.assertEqual(caught.exception.code,403)
        with self.assertRaises(HTTPError) as caught:self.request('/api/runs/'+'a'*32+'/files/../../server.py')
        self.assertEqual(caught.exception.code,404)

    def test_busy_job_and_cancel(self):
        _,data,_=self.request('/api/runs',{'card':templates()['hongqiao'],'settings':{**SETTINGS,'seconds':35}});key=json.loads(data)['id']
        try:
            with self.assertRaises(HTTPError) as caught:self.request('/api/runs',{'card':tiny_card(),'settings':SETTINGS})
            self.assertEqual(caught.exception.code,409)
        finally:self.request('/api/runs/'+key+'/cancel',{})
        _,data,_=self.request('/api/runs/'+key);self.assertEqual(json.loads(data)['state'],'cancelled')

if __name__=='__main__':
    started=time.perf_counter();suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    outcome=unittest.TextTestRunner(verbosity=2).run(suite)
    summary={'tests':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'seconds':round(time.perf_counter()-started,3),
             'scope':'平台输入、手工执行、无解、异步进程、存档导出、来源与路径边界；不新增真实事件实证'}
    (Path(__file__).parent/'平台检查结果.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if outcome.wasSuccessful() else 1)
