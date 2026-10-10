"""Run the same real inference core locally, without simulating AWS deployment."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from detector import Detector

root = Path(__file__).resolve().parents[1]
detector = Detector()
records = []
for path in sorted((root/'images/inputs').glob('*.jpg')):
    data = path.read_bytes()
    annotated, result = detector.detect(data)
    result.update({'input':path.name,'environment':'local Windows CPU',
                   'timestamp':datetime.now(timezone.utc).isoformat(),
                   'input_sha256':hashlib.sha256(data).hexdigest()})
    (root/'images/outputs'/path.name).write_bytes(annotated)
    (root/'images/outputs'/f'{path.stem}.json').write_text(json.dumps(result,indent=2))
    records.append(result)
    print(path.name, len(result['detections']), 'objects', result['inference_ms'], 'ms',
          [item['label'] for item in result['detections']])
(root/'test-results/local-inference.json').write_text(json.dumps(records,indent=2))
