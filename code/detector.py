"""YOLOv5n v7.0 CPU inference using the official ONNX export.

Preprocessing uses RGB letterbox and NCHW normalization. Postprocessing uses
objectness times class probability and class-aware nonmaximum suppression.
No PyTorch installation is required to execute the exported model.
"""
import ast
import io
import os
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
import onnxruntime as ort

Image.MAX_IMAGE_PIXELS = 20_000_000
COCO = ('person,bicycle,car,motorcycle,airplane,bus,train,truck,boat,traffic light,'
        'fire hydrant,stop sign,parking meter,bench,bird,cat,dog,horse,sheep,cow,'
        'elephant,bear,zebra,giraffe,backpack,umbrella,handbag,tie,suitcase,frisbee,'
        'skis,snowboard,sports ball,kite,baseball bat,baseball glove,skateboard,'
        'surfboard,tennis racket,bottle,wine glass,cup,fork,knife,spoon,bowl,banana,'
        'apple,sandwich,orange,broccoli,carrot,hot dog,pizza,donut,cake,chair,couch,'
        'potted plant,bed,dining table,toilet,tv,laptop,mouse,remote,keyboard,'
        'cell phone,microwave,oven,toaster,sink,refrigerator,book,clock,vase,'
        'scissors,teddy bear,hair drier,toothbrush').split(',')

def nms(boxes, scores, threshold=0.45):
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        others = order[1:]
        intersection = np.maximum(0, np.minimum(boxes[i, 2:], boxes[others, 2:]) -
                                  np.maximum(boxes[i, :2], boxes[others, :2])).prod(1)
        areas = np.maximum(0, boxes[:, 2:] - boxes[:, :2]).prod(1)
        iou = intersection / np.maximum(areas[i] + areas[others] - intersection, 1e-9)
        order = others[iou <= threshold]
    return keep

class Detector:
    def __init__(self, model_path=None, threads=None):
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads or int(os.getenv('ORT_THREADS', '1'))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_path or Path(__file__).with_name('yolov5n.onnx')),
            sess_options=options, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.dtype = np.float16 if self.session.get_inputs()[0].type == 'tensor(float16)' else np.float32
        metadata = self.session.get_modelmeta().custom_metadata_map
        self.names = ast.literal_eval(metadata['names']) if 'names' in metadata else COCO

    def detect(self, image_bytes, confidence=0.25):
        start = time.perf_counter()
        try:
            with Image.open(io.BytesIO(image_bytes)) as source:
                if source.format not in ('JPEG', 'PNG'):
                    raise ValueError('Only JPEG and PNG images are supported')
                image = ImageOps.exif_transpose(source).convert('RGB')
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('Invalid or oversized image') from exc
        w, h = image.size
        scale = min(640 / w, 640 / h)
        nw, nh = round(w * scale), round(h * scale)
        pad_x, pad_y = (640 - nw) // 2, (640 - nh) // 2
        canvas = Image.new('RGB', (640, 640), (114, 114, 114))
        canvas.paste(image.resize((nw, nh), Image.Resampling.BILINEAR), (pad_x, pad_y))
        tensor = (np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0).astype(self.dtype)
        inference_start = time.perf_counter()
        rows = self.session.run(None, {self.input_name: tensor})[0][0].astype(np.float32)
        inference_ms = (time.perf_counter() - inference_start) * 1000
        rows = rows[rows[:, 4] > confidence]
        detections = []
        if len(rows):
            class_scores = rows[:, 5:] * rows[:, 4:5]
            classes = class_scores.argmax(1)
            scores = class_scores.max(1)
            selected = scores >= confidence
            rows, classes, scores = rows[selected], classes[selected], scores[selected]
            boxes = np.concatenate((rows[:, :2] - rows[:, 2:4]/2,
                                    rows[:, :2] + rows[:, 2:4]/2), axis=1)
            indices = []
            for class_id in np.unique(classes):
                group = np.flatnonzero(classes == class_id)
                indices.extend(group[nms(boxes[group], scores[group])].tolist())
            for i in sorted(indices, key=lambda j: -float(scores[j]))[:100]:
                x1, y1, x2, y2 = boxes[i]
                box = [round(float(np.clip((x1-pad_x)/scale, 0, w))),
                       round(float(np.clip((y1-pad_y)/scale, 0, h))),
                       round(float(np.clip((x2-pad_x)/scale, 0, w))),
                       round(float(np.clip((y2-pad_y)/scale, 0, h)))]
                detections.append({'class_id': int(classes[i]),
                                   'label': self.names[int(classes[i])],
                                   'confidence': round(float(scores[i]), 4), 'box': box})
        draw = ImageDraw.Draw(image)
        for item in detections:
            draw.rectangle(item['box'], outline='#00d878', width=max(2, w//300))
            label = f"{item['label']} {item['confidence']:.2f}"
            x, y = item['box'][:2]
            text_box = draw.textbbox((x, y), label)
            draw.rectangle(text_box, fill='#003322')
            draw.text((x, y), label, fill='white')
        out = io.BytesIO()
        image.save(out, format='JPEG', quality=92)
        return out.getvalue(), {'model': 'YOLOv5n v7.0 ONNX', 'image_size': [w, h],
                               'detections': detections, 'inference_ms': round(inference_ms, 2),
                               'processing_ms': round((time.perf_counter()-start)*1000, 2)}
