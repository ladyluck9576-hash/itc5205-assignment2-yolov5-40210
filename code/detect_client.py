"""Single signed request using an existing temporary AWS SDK profile."""
import argparse, json, urllib.request, urllib.error
from pathlib import Path
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
parser=argparse.ArgumentParser()
parser.add_argument('--key',required=True)
args=parser.parse_args()
state=json.loads((Path(__file__).resolve().parents[1]/'deploy/deployment-state.json').read_text())
session=boto3.Session(region_name=state['region'])
body=json.dumps({'bucket':state['bucket'],'key':args.key})
request=AWSRequest(method='POST',url=state['endpoint'],data=body,headers={'Content-Type':'application/json'})
SigV4Auth(session.get_credentials().get_frozen_credentials(),'execute-api',state['region']).add_auth(request)
try:
    with urllib.request.urlopen(urllib.request.Request(state['endpoint'],data=body.encode(),headers=dict(request.headers),method='POST'),timeout=35) as response:
        print('HTTP',response.status)
        print(json.dumps(json.loads(response.read()),indent=2))
except urllib.error.HTTPError as error:
    print('HTTP',error.code)
    print(error.read().decode())
    raise SystemExit(1)
