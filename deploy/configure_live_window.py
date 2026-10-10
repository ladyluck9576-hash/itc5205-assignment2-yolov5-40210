"""Configure bounded DynamoDB scaling and AWS-native cleanup, not provisioned Lambda.

Run after deploy_aws.py in a separate working copy. State and receipts stay there.
The USD 1 limit is cumulative; this script is not a billing cap.
"""
import argparse, io, json, time, zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import boto3

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--confirm-student-id',choices=['40210'],required=True)
    args=parser.parse_args(); state=json.loads(args.state.read_text())
    if not state['name'].startswith('gursevak-singh-40210-yolo-'): raise SystemExit('Wrong project')
    session=boto3.Session(region_name=state['region'])
    if session.client('sts').get_caller_identity()['Account']!=state['account']: raise SystemExit('Account mismatch')
    name=state['name']; region=state['region']; account=state['account']
    iam=session.client('iam'); lam=session.client('lambda'); logs=session.client('logs')
    ddb=session.client('dynamodb'); aas=session.client('application-autoscaling')
    out=args.state.parent.parent/'test-results'; out.mkdir(exist_ok=True)
    def save(): args.state.write_text(json.dumps(state,indent=2))
    ddb.update_table(TableName=state['table'],BillingMode='PROVISIONED',ProvisionedThroughput={'ReadCapacityUnits':1,'WriteCapacityUnits':1})
    ddb.get_waiter('table_exists').wait(TableName=state['table'])
    resource='table/'+state['table']; dimension='dynamodb:table:WriteCapacityUnits'
    aas.register_scalable_target(ServiceNamespace='dynamodb',ResourceId=resource,ScalableDimension=dimension,MinCapacity=1,MaxCapacity=2)
    policy=aas.put_scaling_policy(PolicyName=name+'-write-target',ServiceNamespace='dynamodb',ResourceId=resource,
        ScalableDimension=dimension,PolicyType='TargetTrackingScaling',TargetTrackingScalingPolicyConfiguration={
            'TargetValue':70.,'PredefinedMetricSpecification':{'PredefinedMetricType':'DynamoDBWriteCapacityUtilization'},
            'ScaleInCooldown':60,'ScaleOutCooldown':60})
    targets=aas.describe_scalable_targets(ServiceNamespace='dynamodb',ResourceIds=[resource])
    state['scaling_alarm_names']=[x['AlarmName'] for x in policy.get('Alarms',[])]
    state['cleanup_function']=name+'-cleanup'; state['cleanup_role']=name+'-cleanup-role'
    state['scheduler_role']=name+'-scheduler-role'; state['schedule_name']=name+'-expires'
    state['expires_at_utc']=(datetime.now(timezone.utc)+timedelta(hours=24)).replace(microsecond=0).isoformat()
    save()
    (out/'dynamodb-scaling-policy.json').write_text(json.dumps({'policy':policy,'targets':targets},indent=2,default=str))
    trust={'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'lambda.amazonaws.com'},'Action':'sts:AssumeRole'}]}
    cleanup_role=iam.create_role(RoleName=state['cleanup_role'],AssumeRolePolicyDocument=json.dumps(trust))['Role']['Arn']
    cleanup_arn=f"arn:aws:lambda:{region}:{account}:function:{state['cleanup_function']}"
    cleanup_log='/aws/lambda/'+state['cleanup_function']
    cleanup_policy={'Version':'2012-10-17','Statement':[
        {'Effect':'Allow','Action':['apigateway:DELETE'],'Resource':f"arn:aws:apigateway:{region}::/apis/{state['api_id']}"},
        {'Effect':'Allow','Action':['lambda:DeleteFunction'],'Resource':[state['function_arn'],cleanup_arn]},
        {'Effect':'Allow','Action':['dynamodb:DeleteTable'],'Resource':f"arn:aws:dynamodb:{region}:{account}:table/{state['table']}"},
        {'Effect':'Allow','Action':['s3:ListBucket','s3:DeleteBucket'],'Resource':f"arn:aws:s3:::{state['bucket']}"},
        {'Effect':'Allow','Action':['s3:DeleteObject'],'Resource':f"arn:aws:s3:::{state['bucket']}/*"},
        {'Effect':'Allow','Action':['iam:DeleteRole','iam:DeleteRolePolicy'],'Resource':[f'arn:aws:iam::{account}:role/{x}' for x in [state['role'],state['cleanup_role'],state['scheduler_role']]]},
        {'Effect':'Allow','Action':['logs:DeleteLogGroup'],'Resource':[f'arn:aws:logs:{region}:{account}:log-group:{x}:*' for x in [state['log_group'],cleanup_log]]},
        {'Effect':'Allow','Action':['logs:CreateLogStream','logs:PutLogEvents'],'Resource':f'arn:aws:logs:{region}:{account}:log-group:{cleanup_log}:*'},
        {'Effect':'Allow','Action':['application-autoscaling:DeleteScalingPolicy','application-autoscaling:DeregisterScalableTarget'],
         'Resource':targets['ScalableTargets'][0]['ScalableTargetARN']},
        {'Effect':'Allow','Action':['cloudwatch:DeleteAlarms'],'Resource':[x['AlarmARN'] for x in policy.get('Alarms',[])]}
    ]}
    iam.put_role_policy(RoleName=state['cleanup_role'],PolicyName='CleanupOnlyThisProject',PolicyDocument=json.dumps(cleanup_policy))
    scheduler_trust={'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'scheduler.amazonaws.com'},
        'Action':'sts:AssumeRole','Condition':{'StringEquals':{'aws:SourceAccount':account}}}]}
    scheduler_role=iam.create_role(RoleName=state['scheduler_role'],AssumeRolePolicyDocument=json.dumps(scheduler_trust))['Role']['Arn']
    iam.put_role_policy(RoleName=state['scheduler_role'],PolicyName='InvokeOnlyCleanup',PolicyDocument=json.dumps({
        'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':'lambda:InvokeFunction','Resource':cleanup_arn}]}))
    logs.create_log_group(logGroupName=cleanup_log); logs.put_retention_policy(logGroupName=cleanup_log,retentionInDays=1)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(Path(__file__).with_name('cleanup_lambda.py'),'cleanup_lambda.py')
    time.sleep(12)
    lam.create_function(FunctionName=state['cleanup_function'],Runtime='python3.12',Role=cleanup_role,
        Handler='cleanup_lambda.handler',Code={'ZipFile':buffer.getvalue()},Timeout=120,MemorySize=128)
    lam.get_waiter('function_active_v2').wait(FunctionName=state['cleanup_function'])
    dry=lam.invoke(FunctionName=state['cleanup_function'],InvocationType='RequestResponse',Payload=json.dumps({'state':state}).encode())
    dry_result=json.loads(dry['Payload'].read())
    if dry.get('FunctionError') or not dry_result.get('dry_run'): raise RuntimeError('Cleanup dry run failed')
    when=datetime.fromisoformat(state['expires_at_utc']).strftime('%Y-%m-%dT%H:%M:%S')
    scheduler=session.client('scheduler')
    scheduler.create_schedule(Name=state['schedule_name'],ScheduleExpression='at('+when+')',ScheduleExpressionTimezone='UTC',
        FlexibleTimeWindow={'Mode':'OFF'},State='ENABLED',ActionAfterCompletion='DELETE',Target={
        'Arn':cleanup_arn,'RoleArn':scheduler_role,'Input':json.dumps({'confirm':'40210','state':state}),
        'RetryPolicy':{'MaximumEventAgeInSeconds':3600,'MaximumRetryAttempts':3}})
    receipt={'dry_run':dry_result,'schedule':scheduler.get_schedule(Name=state['schedule_name']),
             'cleanup_policy':cleanup_policy,'expires_at_utc':state['expires_at_utc'],
             'note':'AWS-native schedule confirmed. Deletion has not yet occurred; verify after expiry. The local follow-up removes the final non-billable cleanup role. Shared DynamoDB service-linked role is not deleted.'}
    (out/'scheduled-cleanup.json').write_text(json.dumps(receipt,indent=2,default=str))
    print(json.dumps({'schedule_enabled':True,'expires_at_utc':state['expires_at_utc'],'dynamodb_write_capacity_range':[1,2],'target_percent':70}))
if __name__=='__main__': main()
