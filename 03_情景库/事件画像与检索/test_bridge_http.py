import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'04_建模/交互验证平台'))
from server import Store, Handler, ThreadingHTTPServer

class BridgeHttpChecks(unittest.TestCase):
    def test_local_bridge_and_safety_rejection(self):
        portrait = json.loads((HERE/'demo-合成画像.json').read_text(encoding='utf-8'))
        bundle = json.loads((HERE/'demo-合成参数包.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.store = Store(tmp)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            def send():
                body = json.dumps({'portrait':portrait,'bundle':bundle}).encode('utf-8')
                return urlopen(Request(base+'/api/portrait-bridge', data=body, headers={'Content-Type':'application/json'}))
            try:
                self.assertEqual(urlopen(base+'/portrait-bridge').status, 200)
                self.assertEqual(urlopen(base+'/scenario-demo').status, 200)
                req = Request(base+'/api/portrait-retrieval', data=json.dumps({'portrait':portrait}).encode('utf-8'), headers={'Content-Type':'application/json'})
                retrieval = json.load(urlopen(req))['results']
                self.assertNotIn('HQ-E01', [row['case_id'] for row in retrieval])
                self.assertTrue(any(row['case_id']=='HQ-E02' for row in retrieval))
                self.assertEqual(json.load(send())['provenance']['version'], 'BRIDGE-02')
                portrait['fields']['safety_status'] = {'status':'unknown','value':None}
                with self.assertRaises(HTTPError) as error: send()
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
            finally:
                server.shutdown(); server.server_close(); thread.join()

if __name__ == '__main__': unittest.main()
