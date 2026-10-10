"""Provision only this project's named resources after explicit cost approval.

Use an authenticated AWS profile or AWS CloudShell. No credentials are written.
The deployment refuses collisions: it never adopts an existing project name.
"""
import argparse
import json
import pathlib
import time
from datetime import datetime, timezone
import boto3

root=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--approve-budget-usd',type=float,required=True)
parser.add_argument('--region',default='us-east-1',choices=['us-east-1'])
args=parser.parse_args()
if not 0<args.approve_budget_usd<=1:
    raise SystemExit('This demo requires explicit approval for a maximum USD 1 scope')
session=boto3.Session(region_name=args.region)
identity=session.client('sts').get_caller_identity()
account=identity['Account']
suffix=datetime.now(timezone.utc).strftime('%m%d%H%M%S')
name=f'gursevak-singh-40210-yolo-{suffix}'
bucket=f'{name}-{account[-4:]}'
table=f'{name}-metadata'
role=f'{name}-execution'
loggroup=f'/aws/lambda/{name}'
tags={'StudentName':'Gursevak Singh','StudentID':'40210','Project':'ITC5205-Assignment2'}
state={'region':args.region,'name':name,'bucket':bucket,'table':table,'role':role,
       'log_group':loggroup,'account':account,'created_at':datetime.now(timezone.utc).isoformat(),
       'approved_budget_usd':args.approve_budget_usd,'resources_created':[]}
def save():
    (root/'deploy/deployment-state.json').write_text(json.dumps(state,indent=2))
save()
s3=session.client('s3'); iam=session.client('iam'); logs=session.client('logs')
ddb=session.client('dynamodb'); lam=session.client('lambda'); api=session.client('apigatewayv2')
archive=root/'deploy/lambda-package.zip'
if not archive.is_file(): raise SystemExit('Run build_lambda.py first')
s3.create_bucket(Bucket=bucket)
state['resources_created'].append('bucket'); save()
s3.put_public_access_block(Bucket=bucket,PublicAccessBlockConfiguration={
    'BlockPublicAcls':True,'IgnorePublicAcls':True,'BlockPublicPolicy':True,'RestrictPublicBuckets':True})
s3.put_bucket_encryption(Bucket=bucket,ServerSideEncryptionConfiguration={
    'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
s3.put_bucket_tagging(Bucket=bucket,Tagging={'TagSet':[{'Key':k,'Value':v} for k,v in tags.items()]})
s3.put_bucket_lifecycle_configuration(Bucket=bucket,LifecycleConfiguration={'Rules':[
    {'ID':'DemoExpiry','Status':'Enabled','Filter':{'Prefix':'output/'},'Expiration':{'Days':7}}]})
s3.put_bucket_policy(Bucket=bucket,Policy=json.dumps({'Version':'2012-10-17','Statement':[
    {'Sid':'DenyInsecureTransport','Effect':'Deny','Principal':'*','Action':'s3:*',
     'Resource':[f'arn:aws:s3:::{bucket}',f'arn:aws:s3:::{bucket}/*'],
     'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]}))
for path in (root/'images/inputs').glob('*.jpg'):
    s3.upload_file(str(path),bucket,'input/'+path.name,ExtraArgs={'ContentType':'image/jpeg'})
s3.put_object(Bucket=bucket,Key='input/corrupt.jpg',Body=b'intentionally invalid image for failure test')
logs.create_log_group(logGroupName=loggroup,tags=tags)
logs.put_retention_policy(logGroupName=loggroup,retentionInDays=7)
state['resources_created'].append('logs'); save()
ddb.create_table(TableName=table,KeySchema=[{'AttributeName':'request_id','KeyType':'HASH'}],
    AttributeDefinitions=[{'AttributeName':'request_id','AttributeType':'S'}],
    BillingMode='PAY_PER_REQUEST',Tags=[{'Key':k,'Value':v} for k,v in tags.items()])
state['resources_created'].append('table'); save()
ddb.get_waiter('table_exists').wait(TableName=table)
ddb.update_time_to_live(TableName=table,TimeToLiveSpecification={'Enabled':True,'AttributeName':'expires_at'})
trust={'Version':'2012-10-17','Statement':[{'Effect':'Allow',
       'Principal':{'Service':'lambda.amazonaws.com'},'Action':'sts:AssumeRole'}]}
created=iam.create_role(RoleName=role,AssumeRolePolicyDocument=json.dumps(trust),
    Tags=[{'Key':k,'Value':v} for k,v in tags.items()])
state['resources_created'].append('role'); save()
policy={'Version':'2012-10-17','Statement':[
    {'Sid':'ReadInput','Effect':'Allow','Action':'s3:GetObject','Resource':f'arn:aws:s3:::{bucket}/input/*'},
    {'Sid':'DistinguishMissingInput','Effect':'Allow','Action':'s3:ListBucket',
     'Resource':f'arn:aws:s3:::{bucket}','Condition':{'StringLike':{'s3:prefix':['input/*']}}},
    {'Sid':'WriteOutputs','Effect':'Allow','Action':'s3:PutObject','Resource':f'arn:aws:s3:::{bucket}/output/*'},
    {'Sid':'WriteMetadata','Effect':'Allow','Action':'dynamodb:PutItem',
     'Resource':f'arn:aws:dynamodb:{args.region}:{account}:table/{table}'},
    {'Sid':'WriteOwnLogs','Effect':'Allow','Action':['logs:CreateLogStream','logs:PutLogEvents'],
     'Resource':f'arn:aws:logs:{args.region}:{account}:log-group:{loggroup}:*'}]}
(root/'deploy/execution-policy.json').write_text(json.dumps(policy,indent=2))
(root/'deploy/trust-policy.json').write_text(json.dumps(trust,indent=2))
iam.put_role_policy(RoleName=role,PolicyName='ScopedProjectAccess',PolicyDocument=json.dumps(policy))
s3.upload_file(str(archive),bucket,'deploy/lambda-package.zip')
time.sleep(12)  # IAM role propagation, not an assertion of readiness.
function=lam.create_function(FunctionName=name,Runtime='python3.12',Architectures=['x86_64'],
    Role=created['Role']['Arn'],Handler='lambda_function.handler',Timeout=25,MemorySize=2048,
    EphemeralStorage={'Size':512},Code={'S3Bucket':bucket,'S3Key':'deploy/lambda-package.zip'},
    Environment={'Variables':{'BUCKET':bucket,'TABLE':table,'ORT_THREADS':'1'}},Tags=tags)
state['resources_created'].append('function'); save()
lam.get_waiter('function_active_v2').wait(FunctionName=name)
try:
    lam.put_function_concurrency(FunctionName=name,ReservedConcurrentExecutions=2)
    state['reserved_concurrency']=2
except lam.exceptions.InvalidParameterValueException as exc:
    state['reserved_concurrency']='Unavailable under account quota; API throttle remains enabled'
new_api=api.create_api(Name=name,ProtocolType='HTTP',Tags=tags,
    Description='Gursevak Singh 40210 authenticated object detection')
state.update(api_id=new_api['ApiId'],endpoint=new_api['ApiEndpoint']+'/detect')
state['resources_created'].append('api'); save()
integration=api.create_integration(ApiId=state['api_id'],IntegrationType='AWS_PROXY',
    IntegrationUri=function['FunctionArn'],PayloadFormatVersion='2.0',TimeoutInMillis=29000)
route=api.create_route(ApiId=state['api_id'],RouteKey='POST /detect',AuthorizationType='AWS_IAM',
    Target='integrations/'+integration['IntegrationId'])
api.create_stage(ApiId=state['api_id'],StageName='$default',AutoDeploy=True,
    DefaultRouteSettings={'ThrottlingBurstLimit':2,'ThrottlingRateLimit':2})
lam.add_permission(FunctionName=name,StatementId='ApiGatewayProjectRoute',Action='lambda:InvokeFunction',
    Principal='apigateway.amazonaws.com',
    SourceArn=f"arn:aws:execute-api:{args.region}:{account}:{state['api_id']}/*/POST/detect")
state.update(route_id=route['RouteId'],integration_id=integration['IntegrationId'],
             function_arn=function['FunctionArn'],authorization='AWS_IAM',memory_mb=2048)
save()
print(json.dumps({k:v for k,v in state.items() if k!='account'},indent=2))
