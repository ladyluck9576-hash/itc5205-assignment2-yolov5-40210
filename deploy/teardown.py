"""Delete only resources recorded by this project's deployment.

Export all evidence first. Default is dry run. Explicit --execute and the
student ID are required; this never deletes unrelated resources or roles.
"""
import argparse
import json
from pathlib import Path
import boto3
parser=argparse.ArgumentParser()
parser.add_argument('--execute',action='store_true')
parser.add_argument('--confirm-student-id')
args=parser.parse_args()
state_path=Path(__file__).with_name('deployment-state.json')
state=json.loads(state_path.read_text())
if not state['name'].startswith('gursevak-singh-40210-yolo-'):
    raise SystemExit('Unexpected resource namespace; refusing deletion')
print(json.dumps({k:state[k] for k in ('name','bucket','table','role','log_group')},indent=2))
if not args.execute:
    raise SystemExit('DRY RUN: export evidence, then supply --execute --confirm-student-id 40210')
if args.confirm_student_id!='40210': raise SystemExit('Student ID confirmation required')
session=boto3.Session(region_name=state['region'])
if session.client('sts').get_caller_identity()['Account']!=state['account']:
    raise SystemExit('AWS account mismatch; refusing deletion')
created=state['resources_created']
if 'api' in created: session.client('apigatewayv2').delete_api(ApiId=state['api_id'])
if 'function' in created: session.client('lambda').delete_function(FunctionName=state['name'])
if 'table' in created: session.client('dynamodb').delete_table(TableName=state['table'])
if 'logs' in created: session.client('logs').delete_log_group(logGroupName=state['log_group'])
if 'role' in created:
    iam=session.client('iam')
    iam.delete_role_policy(RoleName=state['role'],PolicyName='ScopedProjectAccess')
    iam.delete_role(RoleName=state['role'])
if 'bucket' in created:
    bucket=boto3.resource('s3',region_name=state['region']).Bucket(state['bucket'])
    bucket.objects.all().delete()
    bucket.delete()
state_path.with_name('cleanup-result.json').write_text(json.dumps({'status':'deleted','name':state['name']}))
print('Project resources deleted')
