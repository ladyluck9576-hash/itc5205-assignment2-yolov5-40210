"""Bounded live AWS verification: maximum 24 calls, concurrency at most two.

Requires the deployment-state.json written by deploy_aws.py and temporary
credentials from an authenticated AWS profile/CloudShell. Does not print auth.
"""
import base64
import concurrent.futures
import json
import pathlib
import statistics
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

root=pathlib.Path(__file__).resolve().parents[1]
state=json.loads((root/'deploy/deployment-state.json').read_text())
session=boto3.Session(region_name=state['region'])
credentials=session.get_credentials().get_frozen_credentials()
lam=session.client('lambda'); s3=session.client('s3'); logs=session.client('logs')
records=[]; invocations=[]
def timestamp(): return datetime.now(timezone.utc).isoformat()
def request(key='input/bus.jpg',signed=True,raw=None):
    time.sleep(0.7)  # Keep ordinary calls within the two-RPS API throttle.
    body=raw if raw is not None else json.dumps({'bucket':state['bucket'],'key':key})
    headers={'Content-Type':'application/json'}
    if signed:
        aws=AWSRequest(method='POST',url=state['endpoint'],data=body,headers=headers)
        SigV4Auth(credentials,'execute-api',state['region']).add_auth(aws)
        headers=dict(aws.headers.items())
    started=time.perf_counter()
    req=urllib.request.Request(state['endpoint'],data=body.encode(),headers=headers,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=35) as response:
            status=response.status; text=response.read().decode()
    except urllib.error.HTTPError as exc:
        status=exc.code; text=exc.read().decode()
    result={'timestamp':timestamp(),'key':key,'signed':signed,'http_status':status,
            'latency_ms':round((time.perf_counter()-started)*1000,2),
            'request_body':body,'response':json.loads(text)}
    records.append(result)
    print(json.dumps(result),flush=True)
    return result
def invoke(key='input/bus.jpg'):
    started=time.perf_counter()
    response=lam.invoke(FunctionName=state['name'],LogType='Tail',Payload=json.dumps({
        'body':json.dumps({'bucket':state['bucket'],'key':key})}).encode())
    result={'timestamp':timestamp(),'memory_mb':lam.get_function_configuration(
        FunctionName=state['name'])['MemorySize'],
        'latency_ms':round((time.perf_counter()-started)*1000,2),
        'payload':json.loads(response['Payload'].read()),
        'logs':base64.b64decode(response.get('LogResult','')).decode()}
    invocations.append(result)
    print(json.dumps(result),flush=True)
    return result
started=timestamp()
try:
    invoke()  # First initialized process and direct Lambda proof.
    for name in ['bus.jpg','dog.jpg','zidane.jpg']:
        result=request('input/'+name)
        if result['http_status']!=200: raise RuntimeError('End-to-end case failed')
        output=result['response']['output']
        stem=pathlib.Path(name).stem
        s3.download_file(state['bucket'],output['image_key'],str(root/f'images/outputs/cloud-{stem}.jpg'))
        s3.download_file(state['bucket'],output['json_key'],str(root/f'images/outputs/cloud-{stem}.json'))
    request(signed=False)
    request('input/missing.jpg')
    request('input/corrupt.jpg')
    request('input/unsupported.txt')
    request(raw='{bad json')
    for _ in range(3): request()
    for memory in [1024,2048]:
        lam.update_function_configuration(FunctionName=state['name'],MemorySize=memory)
        lam.get_waiter('function_updated_v2').wait(FunctionName=state['name'])
        for _ in range(3): invoke()
    batch_start=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        concurrent_results=list(pool.map(lambda name:request('input/'+name),['bus.jpg','dog.jpg']))
    batch_seconds=time.perf_counter()-batch_start
    concurrency={'requests':2,'workers':2,'elapsed_seconds':round(batch_seconds,3),
        'throughput_rps':round(2/batch_seconds,3),
        'successes':sum(r['http_status']==200 for r in concurrent_results),
        'throttled':sum(r['http_status']==429 for r in concurrent_results)}
    (root/'test-results/cloud-concurrency.json').write_text(json.dumps(concurrency,indent=2))
    # Safe project-only failure: temporarily deny its execution role writes.
    iam=session.client('iam')
    deny={'Version':'2012-10-17','Statement':[{'Effect':'Deny','Action':'s3:PutObject',
          'Resource':f"arn:aws:s3:::{state['bucket']}/output/*"}]}
    iam.put_role_policy(RoleName=state['role'],PolicyName='TemporaryWriteFailureTest',
                        PolicyDocument=json.dumps(deny))
    try:
        time.sleep(12)
        failure=request()
        failure['case']='temporary project-only S3 write denial'
    finally:
        iam.delete_role_policy(RoleName=state['role'],PolicyName='TemporaryWriteFailureTest')
    time.sleep(12)
    request()
finally:
    (root/'test-results/cloud-http-tests.json').write_text(json.dumps(records,indent=2))
    (root/'test-results/cloud-lambda-tests.json').write_text(json.dumps(invocations,indent=2))
    (root/'test-results/cloud-run-window.json').write_text(json.dumps({'started':started,'ended':timestamp()}))
    (root/'test-results/cloud-s3-objects.json').write_text(json.dumps(
        s3.list_objects_v2(Bucket=state['bucket']).get('Contents',[]),default=str,indent=2))
    function=lam.get_function_configuration(FunctionName=state['name'])
    for field in ['ResponseMetadata','Role','Environment']: function.pop(field,None)
    (root/'test-results/cloud-function-configuration.json').write_text(json.dumps(function,default=str,indent=2))
    try:
        events=logs.filter_log_events(logGroupName=state['log_group'],limit=500)['events']
        (root/'test-results/cloudwatch-events.json').write_text(json.dumps(events,indent=2))
    except Exception as exc:
        print('CloudWatch collection unavailable:',type(exc).__name__)
print('Bounded cloud verification complete')
