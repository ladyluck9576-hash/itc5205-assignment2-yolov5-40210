# Gursevak Singh 40210 deployment and operation

## Verified scope

The actual AWS deployment processed three images and passed the planned positive
and negative cases. Seventeen HTTP requests and seven direct Lambda invocations
were recorded, with 23 REPORT records (the unsigned API call did not reach Lambda).
All project resources were deleted after evidence export; cleanup-verification.json
confirms their absence. The recorded endpoint is historical. The code contains no credentials.

## Cost boundary

The inspected account reported a PAID plan and zero remaining plan credits.
The user approved a cumulative maximum USD 1 across all assignment runs on 10 October 2026. This is not a fresh USD 1 allowance for a redeployment. This is a spending
authorization, not an AWS-enforced billing cap. No EC2, NAT gateway, ECR,
provisioned concurrency or sustained load test is provisioned by these scripts.
The normal test sequence is fixed and bounded to 22 calls, plus a separate two-call cold-start probe (24 total),
with at most two concurrent requests. The Lambda timeout is 25 seconds.
At 2 GiB, even 24 invocations at the timeout consume at most 1200 GB-seconds;
this is a compute-usage bound, not a final bill. Check Lambda, S3, API Gateway,
DynamoDB and CloudWatch prices and the account's current usage before rerunning.
Persistent data/log storage continues to accrue usage until expiration or teardown.

## Prerequisites

- An authenticated AWS CLI/SDK profile or AWS CloudShell in us-east-1.
- IAM rights to create the project bucket, role, log group, Lambda, HTTP API and
  DynamoDB table, pass the execution role, and collect the resulting evidence.
- Python 3 with pip for building; Linux CPython 3.12 x86_64 wheels are downloaded.
- The supplied official YOLOv5n v7.0 ONNX model and the supplied sample images.
- Do not supply keys in chat, commit credentials or disable MFA.

## Reproduce

Before rerunning, verify actual AWS Console access and the remaining cumulative budget. Preserve the original deployment and evidence and work from a separate copy named for the new run. Never overwrite historical deployment-state.json or cloud records. From that separate copy, run:

```text
python -m pip install boto3
python deploy/build_lambda.py
python deploy/deploy_aws.py --approve-budget-usd 1 --region us-east-1
python code/cloud_tests.py
python code/cold_start_probe.py
python code/collect_evidence.py
python code/analyze_evidence.py
```

The existing lambda-package.zip can be used instead of rebuilding if its SHA256
matches test-results/package-build.json. The build uses official PyPI binary
wheels and refuses an uncompressed package above 250 MiB. The observed package
is larger than 50 MB compressed, so the script uploads it through private S3.
For exact dependency versions, see requirements-lock.txt. Runtime imports are
tested in the actual Lambda invocation, not by trying to import Linux binaries
on Windows. A dependency conflict warning about unrelated local packages does
not establish a conflict inside this isolated deployment directory.

The deploy script creates unique timestamped student-prefixed resources, writes
deployment-state.json incrementally, blocks all public S3 access, uses SSE-S3,
requires HTTPS, and creates a Lambda-only execution trust policy. Do not rerun
the deploy script merely to retry a failed test: it creates another unique set
of resources. Use the saved state and diagnose the existing deployment.

## API contract

POST /detect uses AWS_IAM authorization and AWS Signature Version 4 for the
execute-api service in us-east-1. The signed body contains the exact project
bucket name and an input/ object key. Use detect_client.py for one request and cloud_tests.py as the executable test
reference; it reads temporary credentials through boto3 without printing them.
Clients require execute-api:Invoke on this API's POST /detect route.

JPEG and PNG inputs are accepted, up to 8 MiB and the Pillow pixel safety limit.
The body is limited by the handler to 4096 characters. Binary images are placed
in S3 rather than passed inside the API payload. Output locations are selected
by the server. Successful responses contain status, request_id, detections,
bounding boxes, confidence values, input/output keys and measured timings.
Status codes include 200, 400, 404, 413, 415 and 500. AWS authorization or route
throttling can produce 403 or 429 before the handler executes.

## Evidence and tests

cloud_tests.py performs three image cases, unsigned access rejection, malformed
and unsupported inputs, repeated requests, a two-memory comparison and two-worker
concurrency. It temporarily denies only this role's output writes, removes the
temporary deny in a finally block and then tests recovery. Run this only in the
dedicated project environment, when no other project work uses that role.
If interrupted, check that TemporaryWriteFailureTest was removed before rerunning.

CloudWatch REPORT lines contain duration, billed duration and maximum memory.
INIT_START or Init Duration supports cold-start findings. The application's
cold_process flag only identifies the first handler call in a Python process;
it does not replace AWS initialization evidence. A slow response alone is not
proof of a cold start. Treat results as inconclusive when the required logs
are unavailable or account quotas prevent the configured experiment.

Capture console screenshots separately: scoped role/policy, private bucket,
Lambda runtime/code/test, API route/auth/integration, S3 inputs/outputs/JSON,
DynamoDB metadata, CloudWatch logs/metrics and optimization/concurrency results.
The reference screenshot dimensions are 1917 x 985 pixels. Use direct application
captures, move the pointer away, hide unrelated overlays and retain original files.
Do not present a local viewer screenshot as an AWS screenshot.

## Troubleshooting

- AccessDenied on input: verify bucket, prefix and the execution policy.
- Missing objects can return AccessDenied if ListBucket visibility is restricted;
  inspect the genuine error before changing permissions.
- Import errors: check CPython 3.12, x86_64, Linux wheel ABI and archive root.
- InvalidArgument from ONNX: the official release uses float16 input; the core
  detects this type and casts the normalized tensor accordingly.
- API 403: verify SigV4 region/service, temporary credential expiry and caller rights.
- API 429: back off; do not increase load to bypass the demonstration's bounds.
- Inference timeout: inspect REPORT duration and memory, then compare a bounded
  memory setting. Do not add EC2 or provisioned concurrency without approval.
- Output write failure: no success response is returned. JSON acts as the final
  completion marker; a partial annotated image may remain and is overwritten on retry.
- Metadata failure: S3 remains the primary result store; response metadata_status
  reports failure and the log records it without exposing a token or image contents.

## Teardown

First export screenshots, raw logs, state and all cloud image/JSON outputs.
Preview the exact resource names:

```text
python deploy/teardown.py
```

After confirming the evidence is exported, delete only the saved deployment:

```text
python deploy/teardown.py --execute --confirm-student-id 40210
```

The script verifies the student namespace and current AWS account before any
deletion. It removes this API, function, table, log group, inline role policy,
execution role and bucket objects/bucket. Deletion is permanent. A local cleanup
result is written only after those calls succeed. If a partial deployment never
reached the inline role policy creation, inspect the saved resources_created list
and remove only the resources actually created. Never delete unrelated AWS work.

## Authentication used in this demonstration

The official AWS CLI browser login created a temporary local login profile.
The installed SDK used credential_process to call AWS CLI export-credentials.
Set region on the login profile to prevent NoRegion during refresh. Never print
exported credentials or copy the login cache into this package.

The available deploying/test principal was root. The Lambda execution role is
scoped, but a repeat deployment should use a dedicated deployment role and a
separate least-privilege execute-api caller. Root login is not a recommended
production operating pattern.

## Observed limitations

Initial Console control was unstable. The Lady profile later connected and a
separate verification deployment supplied genuine AWS Management Console captures.
cloud_evidence.html remains a viewer of saved SDK, HTTP and CloudWatch records.
The requested 1917 x 985 override failed; genuine captures preserve supported
native dimensions. Originals remain local; redacted copies and their provenance
are supplied. The two-worker batch is not a high-volume scaling experiment.
Reserved concurrency was rejected with an account quota of 10.
DynamoDB on-demand and Lambda automatic scaling were used without explicit
scaling policies. Model-failure injection was performed offline only.

The core is the official YOLOv5 ONNX export. EC2, PyTorch and OpenCV were not used;
this deviates from the literal example environment wording in the assessment.
The user prohibited EC2 within this budget. Review that choice with the lecturer.

After teardown, run python deploy/verify_cleanup.py for read-only absence checks.
