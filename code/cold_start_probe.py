"""Two signed HTTP requests after an explicit Lambda configuration change.

This controlled experiment is not a claim about idle-time cold-start frequency.
Run only within the approved bounded test budget.
"""
import json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
root=Path(__file__).resolve().parents[1]
s=json.loads((root/'deploy/deployment-state.json').read_text())
session=boto3.Session(region_name=s['region']); lam=session.client('lambda')
variables=lam.get_function_configuration(FunctionName=s['name'])['Environment']['Variables']
variables['EVIDENCE_RUN']=datetime.now(timezone.utc).isoformat()
lam.update_function_configuration(FunctionName=s['name'],Environment={'Variables':variables})
lam.get_waiter('function_updated_v2').wait(FunctionName=s['name'])
results=[]
for i in range(2):
    time.sleep(1)
    body=json.dumps({'bucket':s['bucket'],'key':'input/bus.jpg'})
    req=AWSRequest(method='POST',url=s['endpoint'],data=body,headers={'Content-Type':'application/json'})
    SigV4Auth(session.get_credentials().get_frozen_credentials(),'execute-api',s['region']).add_auth(req)
    start=time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(s['endpoint'],data=body.encode(),headers=dict(req.headers),method='POST'),timeout=35) as response:
        results.append({'sequence':i+1,'timestamp':datetime.now(timezone.utc).isoformat(),
            'http_status':response.status,'response':json.loads(response.read()),
            'latency_ms':round((time.perf_counter()-start)*1000,2)})
(root/'test-results/cloud-api-cold-probe.json').write_text(json.dumps({
    'method':'Two HTTP requests following an explicit environment configuration update',
    'configuration_marker':variables['EVIDENCE_RUN'],'requests':results},indent=2))
print([(r['http_status'],r['latency_ms'],r['response']['request_id']) for r in results])
