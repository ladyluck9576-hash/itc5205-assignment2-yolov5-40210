"""Offline fault-injection tests. These are NOT evidence of cloud deployment."""
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
os.environ.update(AWS_DEFAULT_REGION='us-east-1', AWS_EC2_METADATA_DISABLED='true',
                  AWS_ACCESS_KEY_ID='offline-test-only', AWS_SECRET_ACCESS_KEY='offline-test-only',
                  BUCKET='gursevak-singh-40210-test', TABLE='')
from botocore.exceptions import ClientError
import lambda_function as lf
from detector import Detector, nms
import numpy as np

class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.ctx = SimpleNamespace(aws_request_id='offline-test-request')
        self.store = Mock()
        self.store.get_object.return_value = {'ContentLength':3,'Body':io.BytesIO(b'jpg')}
        self.model = Mock()
        self.model.detect.return_value = (b'annotated', {'detections':[], 'inference_ms':1})
        self.p1 = patch.object(lf,'s3',self.store); self.p1.start()
        self.p2 = patch.object(lf,'_detector',self.model); self.p2.start()
        self.addCleanup(self.p1.stop); self.addCleanup(self.p2.stop)
    def call(self, data=None, body=None):
        return lf.handler({'body':body if body is not None else json.dumps(data or {
            'bucket':os.environ['BUCKET'],'key':'input/bus.jpg'})},self.ctx)
    def test_success_persists_image_and_completion_json(self):
        result = self.call()
        self.assertEqual(result['statusCode'],200)
        self.assertEqual(self.store.put_object.call_count,2)
        self.assertTrue(self.store.put_object.call_args.kwargs['Key'].endswith('.json'))
    def test_malformed_json(self):
        self.assertEqual(self.call(body='{broken')['statusCode'],400)
        self.store.get_object.assert_not_called()
    def test_foreign_bucket(self):
        self.assertEqual(self.call({'bucket':'other','key':'input/bus.jpg'})['statusCode'],400)
    def test_traversal(self):
        self.assertEqual(self.call({'bucket':os.environ['BUCKET'],'key':'input/../bus.jpg'})['statusCode'],400)
    def test_foreign_prefix(self):
        self.assertEqual(self.call({'bucket':os.environ['BUCKET'],'key':'output/bus.jpg'})['statusCode'],400)
    def test_unsupported_extension(self):
        self.assertEqual(self.call({'bucket':os.environ['BUCKET'],'key':'input/file.txt'})['statusCode'],400)
    def test_missing_object(self):
        self.store.get_object.side_effect = ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
        self.assertEqual(self.call()['statusCode'],404)
    def test_oversized_input(self):
        self.store.get_object.return_value['ContentLength']=lf.MAX_BYTES+1
        self.assertEqual(self.call()['statusCode'],413)
        self.model.detect.assert_not_called()
    def test_invalid_image(self):
        self.model.detect.side_effect=ValueError('Invalid image')
        self.assertEqual(self.call()['statusCode'],415)
        self.store.put_object.assert_not_called()
    def test_model_runtime_failure(self):
        self.model.detect.side_effect=RuntimeError('offline injected model failure')
        result=self.call()
        self.assertEqual(result['statusCode'],500)
        self.assertNotIn('injected',result['body'])
    def test_write_access_denied_never_returns_success(self):
        self.store.put_object.side_effect=ClientError({'Error':{'Code':'AccessDenied'}},'PutObject')
        self.assertEqual(self.call()['statusCode'],500)
    def test_second_write_failure_leaves_no_success_response(self):
        self.store.put_object.side_effect=[{},ClientError({'Error':{'Code':'AccessDenied'}},'PutObject')]
        self.assertEqual(self.call()['statusCode'],500)
        self.assertEqual(self.store.put_object.call_count,2)
    def test_retries_use_deterministic_output_keys(self):
        first=json.loads(self.call()['body'])['output']
        self.store.get_object.return_value['Body']=io.BytesIO(b'jpg')
        second=json.loads(self.call()['body'])['output']
        self.assertEqual(first,second)
    def test_non_object_body_rejected(self):
        self.assertEqual(self.call(body='[]')['statusCode'],400)

class ModelTests(unittest.TestCase):
    def test_same_class_overlapping_boxes_suppressed(self):
        self.assertEqual(nms(np.array([[0,0,10,10],[1,1,10,10],[20,20,30,30]]),
                             np.array([.9,.8,.7])),[0,2])
    def test_real_model_rejects_invalid_image(self):
        with self.assertRaises(ValueError):
            Detector().detect(b'not an image')

if __name__=='__main__':
    unittest.main(verbosity=2)
