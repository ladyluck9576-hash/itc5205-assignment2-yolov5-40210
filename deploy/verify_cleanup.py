"""Read-only verification that all recorded project resources are absent."""
import json
from pathlib import Path
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError
root=Path(__file__).resolve().parents[1]
state=json.loads((root/'deploy/deployment-state.json').read_text())
session=boto3.Session(region_name=state['region'])
checks=[('api','apigatewayv2','get_api',{'ApiId':state['api_id']}),
    ('function','lambda','get_function_configuration',{'FunctionName':state['name']}),
    ('table','dynamodb','describe_table',{'TableName':state['table']}),
    ('role','iam','get_role',{'RoleName':state['role']}),
    ('bucket','s3','head_bucket',{'Bucket':state['bucket']})]
results=[]
for name,service,method,args in checks:
    try:
        getattr(session.client(service),method)(**args)
        results.append({'resource':name,'status':'STILL PRESENT'})
    except ClientError as exc:
        code=exc.response['Error']['Code']
        results.append({'resource':name,'status':'ABSENT' if code in ['NotFoundException','ResourceNotFoundException','NoSuchEntity','404','NoSuchBucket'] else 'UNVERIFIED','aws_code':code})
groups=session.client('logs').describe_log_groups(logGroupNamePrefix=state['log_group'])['logGroups']
results.append({'resource':'log_group','status':'STILL PRESENT' if any(x['logGroupName']==state['log_group'] for x in groups) else 'ABSENT'})
record={'verified_at':datetime.now(timezone.utc).isoformat(),'resources':results,
    'all_absent':all(x['status']=='ABSENT' for x in results)}
(root/'test-results/cleanup-verification.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2))
if not record['all_absent']:raise SystemExit(1)
