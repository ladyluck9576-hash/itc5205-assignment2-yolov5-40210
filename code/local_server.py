"""Loopback-only application for real local verification, not AWS evidence."""
import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Lock
from detector import Detector
root=Path(__file__).resolve().parents[1]
model=Detector()
lock=Lock()
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(root),**kwargs)
    def do_POST(self):
        if self.path!='/api/detect': self.send_error(404); return
        if int(self.headers.get('Content-Length','0'))>1024: self.send_error(413); return
        try:
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            name=data.get('image')
            if name not in ('bus.jpg','dog.jpg','zidane.jpg'): raise ValueError('Unknown sample')
            with lock:
                annotated,result=model.detect((root/'images/inputs'/name).read_bytes())
            (root/'images/outputs'/name).write_bytes(annotated)
            result.update(input=name,environment='LOCAL CPU verification only',student='Gursevak Singh 40210')
            payload=json.dumps(result).encode()
            self.send_response(200); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)
        except Exception as exc:
            self.send_error(400,type(exc).__name__)
print('Gursevak Singh 40210 local verification http://127.0.0.1:8520/code/viewer.html',flush=True)
ThreadingHTTPServer(('127.0.0.1',8520),Handler).serve_forever()
