"""Maximum 50 HTTP calls, four workers, 60-second admission window; no retries.

Uses existing temporary SDK credentials. Never writes signed headers to disk.
The burst deliberately exercises the existing 2 rps / burst 2 API limit.
This is a bounded demonstration, not a high-volume capacity study.
"""
import argparse, concurrent.futures, json, math, threading, time
import urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    state=json.loads(args.state.read_text())
    if not state['name'].startswith('gursevak-singh-40210-yolo-'):
        raise SystemExit('Unexpected project namespace')
    session=boto3.Session(region_name=state['region'])
    if session.client('sts').get_caller_identity()['Account']!=state['account']:
        raise SystemExit('Account mismatch')
    credentials=session.get_credentials().get_frozen_credentials()
    started_utc=datetime.now(timezone.utc).isoformat()
    begin=time.perf_counter(); deadline=begin+60
    lock=threading.Lock(); results=[]; issued=0
    def request(phase, key='input/bus.jpg', signed=True):
        nonlocal issued
        with lock:
            if issued>=50 or time.perf_counter()>=deadline-1:
                return
            issued+=1; sequence=issued
        body=json.dumps({'bucket':state['bucket'],'key':key}).encode()
        req=AWSRequest(method='POST',url=state['endpoint'],data=body,headers={'Content-Type':'application/json'})
        if signed: SigV4Auth(credentials,'execute-api',state['region']).add_auth(req)
        started=time.perf_counter(); status=None; response={}
        try:
            with urllib.request.urlopen(urllib.request.Request(state['endpoint'],data=body,
                headers=dict(req.headers),method='POST'),timeout=min(27,max(1,deadline-started))) as stream:
                status=stream.status; response=json.loads(stream.read())
        except urllib.error.HTTPError as exc:
            status=exc.code
            try: response=json.loads(exc.read())
            except (ValueError,UnicodeError): response={'error':'HTTP error response not JSON'}
        except Exception as exc:
            response={'transport_error':type(exc).__name__}
        row={'sequence':sequence,'phase':phase,'key':key,'signed':signed,'http_status':status,
             'started_offset_seconds':round(started-begin,4),
             'finished_offset_seconds':round(time.perf_counter()-begin,4),
             'latency_ms':round((time.perf_counter()-started)*1000,2),'response':response,
             'timestamp':datetime.now(timezone.utc).isoformat()}
        with lock: results.append(row)
    for key in ['input/bus.jpg','input/dog.jpg','input/zidane.jpg']:
        request('distinct-image-baseline',key); time.sleep(.55)
    request('unsigned-rejection',signed=False)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(request,'four-worker-burst') for _ in range(16)]
        for future in futures: future.result()
    # Moderate paced phase: avoid mistaking API admission rejection for Lambda scaling.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[]
        for i in range(24):
            if time.perf_counter()>=deadline-2: break
            futures.append(pool.submit(request,'paced-two-rps',['input/bus.jpg','input/dog.jpg','input/zidane.jpg'][i%3]))
            time.sleep(.55)
        for future in futures: future.result()
    for _ in range(6):
        if time.perf_counter()>=deadline-2: break
        time.sleep(.6); request('post-burst-recovery')
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'bounded-http-tests.json').write_text(json.dumps(sorted(results,key=lambda x:x['sequence']),indent=2))
    values=sorted(x['latency_ms'] for x in results if x['http_status']==200)
    summary={'started_at_utc':started_utc,'finished_at_utc':datetime.now(timezone.utc).isoformat(),'http_calls':len(results),
             'maximum_authorized_calls':50,'maximum_workers':4,'admission_window_seconds':60,
             'elapsed_seconds':round(time.perf_counter()-begin,3),
             'status_counts':{str(code):sum(x['http_status']==code for x in results) for code in set(x['http_status'] for x in results)},
             'successful_latency_p50_ms':values[math.ceil(len(values)*.5)-1] if values else None,
             'successful_latency_p95_ms':values[math.ceil(len(values)*.95)-1] if values else None,
             'no_automatic_retries':True,'not_high_volume':True,
             'note':'Client overlap alone does not prove simultaneous Lambda execution. Correlate server logs and ConcurrentExecutions metric.'}
    (args.output/'bounded-summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
