# ITC5205 Assignment 2: AWS image object identification

Gursevak Singh, student 40210.

Official YOLOv5n v7.0 ONNX inference on CPU in AWS Lambda, IAM-authenticated HTTP API Gateway, private S3 image/JSON outputs, DynamoDB metadata and CloudWatch execution logs.

This repository contains reproducible source. Credentials, raw account records, unredacted Console captures and local AWS state are excluded. Never commit credential files.

## Local use

Install `code/requirements.txt`, then run `python code/local_server.py` and open the printed local address. Sample images and the official ONNX model are included for reproduction. Use the supplied unit tests before deployment.

## AWS reproduction

Read `deploy/README.md`. Build with `python deploy/build_lambda.py`; sign in through your own temporary AWS SDK profile. Deploy only with explicit cost approval in a separate working copy. The demonstration limit is cumulative USD 1, not an enforced AWS billing cap. No EC2, NAT, provisioned concurrency or sustained load tests are used.

The first two actual deployments were removed after evidence export. A later 24-hour demonstration is recorded in the assignment report. POST /detect uses AWS_IAM; a browser address-bar visit is not an authenticated detection request.

`code/bounded_scaling_test.py` admits at most 50 HTTP calls with four workers within 60 seconds. This does not establish high-volume capacity. `deploy/configure_live_window.py` configures DynamoDB write target tracking (1-2 units, 70%) and a one-time AWS-native cleanup schedule. Lambda uses managed on-demand scaling.

## Provenance and limitations

Model: https://github.com/ultralytics/yolov5/releases/tag/v7.0 . Samples: official YOLOv5 bus and zidane images and Darknet dog image. Model/project dependencies retain their upstream licenses; no relicensing of upstream assets is implied.

The ONNX runtime path differs from the assessment's literal EC2/PyTorch wording. Three demonstration images are not an accuracy study. Two bicycle boxes occur in the dog scene; no mAP or accuracy percentage is claimed. Recorded presentation and final LMS submission are student actions.
