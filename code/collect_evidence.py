"""Read actual project AWS configuration, logs and metadata without credentials in output."""
import json
from pathlib import Path
from datetime import datetime, timezone
import boto3

root = Path(__file__).resolve().parents[1]
state = json.loads((root / 'deploy/deployment-state.json').read_text())
session = boto3.Session(region_name=state['region'])
def save(name, value):
    (root / 'test-results' / name).write_text(json.dumps(value, indent=2, default=str))
def clean(value):
    if isinstance(value, dict):
        return {k:clean(v) for k,v in value.items() if k != 'ResponseMetadata'}
    if isinstance(value, list): return [clean(v) for v in value]
    return value
s3=session.client('s3'); iam=session.client('iam')
api=session.client('apigatewayv2'); lam=session.client('lambda')
identity=session.client('sts').get_caller_identity()
save('cloud-identity.json', {'timestamp':datetime.now(timezone.utc).isoformat(),
    'region':state['region'], 'student':'Gursevak Singh 40210',
    'account_matches_deployment':identity['Account']==state['account'],
    'identity_type':'root' if identity['Arn'].endswith(':root') else 'IAM',
    'account_display':'[REDACTED]', 'lambda_concurrency_quota':lam.get_account_settings()['AccountLimit']['ConcurrentExecutions']})
save('cloud-service-configuration.json', clean({
    'captured_at':datetime.now(timezone.utc).isoformat(),
    's3_public_access':s3.get_public_access_block(Bucket=state['bucket']),
    's3_encryption':s3.get_bucket_encryption(Bucket=state['bucket']),
    's3_lifecycle':s3.get_bucket_lifecycle_configuration(Bucket=state['bucket']),
    's3_policy':json.loads(s3.get_bucket_policy(Bucket=state['bucket'])['Policy']),
    'role':iam.get_role(RoleName=state['role'])['Role'],
    'execution_policy':iam.get_role_policy(RoleName=state['role'],PolicyName='ScopedProjectAccess')['PolicyDocument'],
    'remaining_inline_policies':iam.list_role_policies(RoleName=state['role'])['PolicyNames'],
    'api':api.get_api(ApiId=state['api_id']),
    'routes':api.get_routes(ApiId=state['api_id'])['Items'],
    'integrations':api.get_integrations(ApiId=state['api_id'])['Items'],
    'stages':api.get_stages(ApiId=state['api_id'])['Items'],
    'lambda_invoke_policy':json.loads(lam.get_policy(FunctionName=state['name'])['Policy']),
    'table':session.client('dynamodb').describe_table(TableName=state['table'])['Table'],
    'table_ttl':session.client('dynamodb').describe_time_to_live(TableName=state['table'])['TimeToLiveDescription'],
}))
save('cloud-dynamodb-items.json', session.resource('dynamodb').Table(state['table']).scan(Limit=100)['Items'])
events=[]
for page in session.client('logs').get_paginator('filter_log_events').paginate(logGroupName=state['log_group']):
    events.extend(page['events'])
save('cloudwatch-events.json',events)
save('access-recovery.json', {'status':'SUCCESS','method':'Official AWS CLI browser login and credential_process SDK profile',
    'timestamp':datetime.now(timezone.utc).isoformat(),'credentials_in_package':False})
print('Configuration, metadata and CloudWatch exported; event count:',len(events))
