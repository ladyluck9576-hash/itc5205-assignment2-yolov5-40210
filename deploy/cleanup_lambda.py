"""Scheduled cleanup for one recorded 40210 run; dry run by default.

Its execution role names only the recorded project resources. The scheduler
is a one-time UTC schedule configured to delete itself after invocation.
"""
import boto3
from botocore.exceptions import ClientError

def handler(event, context):
    state=event['state']
    name=state['name']
    if not name.startswith('gursevak-singh-40210-yolo-'):
        raise ValueError('Unexpected namespace')
    expected={'bucket':name+'-'+state['account'][-4:], 'table':name+'-metadata',
              'role':name+'-execution', 'log_group':'/aws/lambda/'+name,
              'cleanup_function':name+'-cleanup', 'cleanup_role':name+'-cleanup-role',
              'scheduler_role':name+'-scheduler-role'}
    if any(state.get(key)!=value for key,value in expected.items()):
        raise ValueError('Resource does not belong to the recorded project')
    if event.get('confirm')!='40210':
        return {'dry_run':True,'resources':expected,'api_id':state['api_id']}
    session=boto3.Session(region_name=state['region'])
    done=[]
    missing={'NotFoundException','ResourceNotFoundException','NoSuchEntity','NoSuchBucket','ObjectNotFoundException'}
    def call(client, action, **kwargs):
        try: getattr(session.client(client),action)(**kwargs)
        except ClientError as exc:
            if exc.response['Error']['Code'] not in missing: raise
        done.append(action)
    resource='table/'+state['table']
    call('application-autoscaling','delete_scaling_policy',ServiceNamespace='dynamodb',ResourceId=resource,
         ScalableDimension='dynamodb:table:WriteCapacityUnits',PolicyName=name+'-write-target')
    call('application-autoscaling','deregister_scalable_target',ServiceNamespace='dynamodb',ResourceId=resource,
         ScalableDimension='dynamodb:table:WriteCapacityUnits')
    if state.get('scaling_alarm_names'):
        call('cloudwatch','delete_alarms',AlarmNames=state['scaling_alarm_names'])
    call('apigatewayv2','delete_api',ApiId=state['api_id'])
    call('lambda','delete_function',FunctionName=name)
    call('dynamodb','delete_table',TableName=state['table'])
    s3=session.client('s3')
    try:
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=state['bucket']):
            keys=[{'Key':obj['Key']} for obj in page.get('Contents',[])]
            if keys:
                response=s3.delete_objects(Bucket=state['bucket'],Delete={'Objects':keys,'Quiet':True})
                if response.get('Errors'): raise RuntimeError('S3 deletion errors')
        s3.delete_bucket(Bucket=state['bucket']); done.append('delete_bucket')
    except ClientError as exc:
        if exc.response['Error']['Code'] not in missing: raise
    call('logs','delete_log_group',logGroupName=state['log_group'])
    # Removing our own policy would revoke subsequent cleanup permissions.
    # A separate local verification follow-up removes this last, non-billable role.
    for role,policy in [(state['role'],'ScopedProjectAccess'),
                        (state['scheduler_role'],'InvokeOnlyCleanup')]:
        call('iam','delete_role_policy',RoleName=role,PolicyName=policy)
        call('iam','delete_role',RoleName=role)
    call('lambda','delete_function',FunctionName=state['cleanup_function'])
    call('logs','delete_log_group',logGroupName='/aws/lambda/'+state['cleanup_function'])
    return {'cleanup':'deletion requests accepted','actions':done,
            'remaining_nonbillable_role_for_followup':state['cleanup_role'],
            'note':'DynamoDB deletion is asynchronous; verify absence independently.'}
