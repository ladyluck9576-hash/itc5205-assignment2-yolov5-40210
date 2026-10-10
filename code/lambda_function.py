"""Private S3 object detection handler for API Gateway HTTP API v2.

Authorization is enforced by AWS_IAM on the API Gateway route. Only the
configured bucket/input prefix is accepted; callers cannot choose outputs.
"""
import base64
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from detector import Detector

logger = logging.getLogger()
logger.setLevel(logging.INFO)
config = Config(retries={'max_attempts': 3, 'mode': 'standard'})
s3 = boto3.client('s3', config=config)
ddb = boto3.client('dynamodb', config=config)
_detector = None
_first_call = True
MAX_BYTES = 8 * 1024 * 1024

def response(status, data):
    return {'statusCode': status, 'headers': {'content-type': 'application/json',
            'cache-control': 'no-store'}, 'body': json.dumps(data)}

def handler(event, context):
    global _detector, _first_call
    started = time.perf_counter()
    request_id = context.aws_request_id
    cold = _first_call
    _first_call = False
    phase = 'validate'
    try:
        raw = event.get('body', '{}')
        if event.get('isBase64Encoded'):
            raw = base64.b64decode(raw, validate=True).decode('utf-8')
        if not isinstance(raw, str) or len(raw) > 4096:
            raise ValueError('Request body must be JSON with at most 4096 characters')
        data = json.loads(raw)
        bucket, key = data.get('bucket'), data.get('key')
        if bucket != os.environ['BUCKET']:
            raise ValueError('Bucket is outside the configured project')
        if not isinstance(key, str) or not key.startswith('input/') or '..' in key or len(key)>512:
            raise ValueError('Key must be a project input/ object without traversal')
        if not key.lower().endswith(('.jpg', '.jpeg', '.png')):
            raise ValueError('Supported extensions are jpg, jpeg and png')
        phase = 'read'
        obj = s3.get_object(Bucket=bucket, Key=key)
        if obj['ContentLength'] > MAX_BYTES:
            return response(413, {'status':'error','request_id':request_id,'error':'Image exceeds 8 MiB'})
        image = obj['Body'].read(MAX_BYTES + 1)
        if len(image)>MAX_BYTES:
            return response(413, {'status':'error','request_id':request_id,'error':'Image exceeds 8 MiB'})
        digest = hashlib.sha256(image + b'yolov5n-v7-conf025').hexdigest()[:32]
        # Deterministic keys make repeated writes idempotent. Each request is
        # still measured and metadata is recorded under its unique request ID.
        output_image, output_json = f'output/{digest}.jpg', f'output/{digest}.json'
        phase = 'inference'
        if _detector is None:
            _detector = Detector()
        annotated, result = _detector.detect(image)
        result.update({'status':'success','request_id':request_id,'input':{'bucket':bucket,'key':key},
                       'output':{'bucket':bucket,'image_key':output_image,'json_key':output_json},
                       'timestamp':datetime.now(timezone.utc).isoformat(),'cold_process':cold})
        phase = 'write'
        s3.put_object(Bucket=bucket, Key=output_image, Body=annotated, ContentType='image/jpeg',
                      ServerSideEncryption='AES256')
        result['execution_ms'] = round((time.perf_counter()-started)*1000,2)
        s3.put_object(Bucket=bucket, Key=output_json, Body=json.dumps(result).encode(),
                      ContentType='application/json', ServerSideEncryption='AES256')
        # The JSON is the completion marker. A failed JSON write leaves an
        # incomplete image object, but never returns success. A retry overwrites it.
        table = os.getenv('TABLE')
        if table:
            phase = 'metadata'
            try:
                ddb.put_item(TableName=table, Item={
                    'request_id':{'S':request_id}, 'input_key':{'S':key},
                    'objects':{'S':json.dumps(result['detections'])},
                    'timestamp':{'S':result['timestamp']},'status':{'S':'success'},
                    'execution_ms':{'N':str(result['execution_ms'])},
                    'expires_at':{'N':str(int(time.time())+7*86400)}})
                result['metadata_status'] = 'saved'
            except ClientError:
                result['metadata_status'] = 'failed'
                logger.error(json.dumps({'event':'metadata_failure','request_id':request_id}))
        logger.info(json.dumps({'event':'detection_complete','request_id':request_id,
                     'status':'success','detections':len(result['detections']),
                     'execution_ms':result['execution_ms'],'cold_process':cold}))
        return response(200, result)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        if phase != 'validate' and phase != 'inference':
            logger.error(json.dumps({'event':'configuration_error','request_id':request_id,'phase':phase}))
            return response(500, {'status':'error','request_id':request_id,'error':'Configuration failure'})
        return response(400 if phase=='validate' else 415,
                        {'status':'error','request_id':request_id,'error':str(exc)})
    except ClientError as exc:
        code = exc.response['Error']['Code']
        status = 404 if phase=='read' and code in ('NoSuchKey','404') else 500
        logger.error(json.dumps({'event':'aws_error','request_id':request_id,'phase':phase,'code':code}))
        return response(status, {'status':'error','request_id':request_id,
                                'error':'Input not found' if status==404 else 'Storage operation failed'})
    except Exception as exc:
        logger.error(json.dumps({'event':'processing_error','request_id':request_id,
                                'phase':phase,'type':type(exc).__name__}))
        return response(500, {'status':'error','request_id':request_id,'error':'Processing failed'})
