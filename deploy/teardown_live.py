"""Manual fallback for exactly one live run, including scaling and scheduler.

Default dry run performs no AWS calls. Run with the live state, --execute and
--confirm-student-id 40210 only after evidence export or after scheduled expiry.
"""
import argparse,json
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from cleanup_lambda import handler

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--confirm-student-id')
    args=parser.parse_args(); state=json.loads(args.state.read_text())
    plan=handler({'state':state},None)
    print(json.dumps(plan,indent=2))
    if not args.execute: return
    if args.confirm_student_id!='40210':raise SystemExit('Student confirmation required')
    session=boto3.Session(region_name=state['region'])
    if session.client('sts').get_caller_identity()['Account']!=state['account']:raise SystemExit('Account mismatch')
    try:session.client('scheduler').delete_schedule(Name=state['schedule_name'])
    except ClientError as exc:
        if exc.response['Error']['Code']!='ResourceNotFoundException':raise
    result=handler({'state':state,'confirm':'40210'},None)
    iam=session.client('iam')
    for method,kwargs in [('delete_role_policy',{'RoleName':state['cleanup_role'],'PolicyName':'CleanupOnlyThisProject'}),
                          ('delete_role',{'RoleName':state['cleanup_role']})]:
        try:getattr(iam,method)(**kwargs)
        except ClientError as exc:
            if exc.response['Error']['Code']!='NoSuchEntity':raise
    out=args.state.parent.parent/'test-results/cleanup-result.json'
    out.write_text(json.dumps(result,indent=2))
    print('Exact recorded live-run deletion requests accepted; verify absence independently.')
if __name__=='__main__':main()
