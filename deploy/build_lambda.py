"""Build Linux CPython 3.12 deployment ZIP without Docker.

Run with Python/pip with network access. Download only binary wheels. A strict
250 MiB uncompressed gate prevents submitting an oversized Lambda package.
The model is an official YOLOv5 release asset, copied from the local code folder.
"""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import zipfile
root=pathlib.Path(__file__).resolve().parents[1]
build=root/'deploy/build'
build.mkdir(exist_ok=True)
subprocess.run([sys.executable,'-m','pip','install','--platform','manylinux_2_28_x86_64',
                '--platform','manylinux2014_x86_64','--implementation','cp',
                '--python-version','3.12','--only-binary=:all:','--no-compile',
                '--target',str(build),'-r',str(root/'code/requirements.txt')],check=True)
for name in ['detector.py','lambda_function.py','yolov5n.onnx']:
    shutil.copy2(root/'code'/name,build/name)
paths=[p for p in build.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
size=sum(p.stat().st_size for p in paths)
if size>250*1024**2:
    raise SystemExit(f'Package too large: {size} bytes. Do not deploy.')
archive=root/'deploy/lambda-package.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as out:
    for p in paths: out.write(p,p.relative_to(build))
record={'runtime':'python3.12','architecture':'x86_64','uncompressed_bytes':size,
        'compressed_bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'dependencies':(root/'code/requirements.txt').read_text().splitlines()}
(root/'test-results/package-build.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2))
