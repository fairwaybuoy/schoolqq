import hashlib,json,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent.parent
manifest=json.loads((root/'docs/ocr-checksums.json').read_text())
folder=root/'data/tessdata';folder.mkdir(parents=True,exist_ok=True)
for lang,expected in manifest['sha256'].items():
    path=folder/(lang+'.traineddata')
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==expected:continue
    url=f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{manifest["commit"]}/{lang}.traineddata'
    raw=urllib.request.urlopen(url,timeout=60).read()
    if hashlib.sha256(raw).hexdigest()!=expected:raise RuntimeError('OCR 数据校验失败；禁止继续使用')
    path.write_bytes(raw)
print('OCR 语言数据已核验')
