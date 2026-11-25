import asyncio,json
from datetime import datetime
from pathlib import Path
from PIL import Image
import pytesseract
from .extract import Extractor,candidate

class Worker:
    def __init__(self,settings,db):self.settings=settings;self.db=db;self.extractor=Extractor(settings,db)
    def ocr(self,filename):
        if Path(filename).name!=filename:raise ValueError('非法图片路径')
        with Image.open(self.db.path/'images'/filename) as image:
            if image.width*image.height>16000000:raise ValueError('图片像素过大')
            config='--psm 6'
            if self.settings.tessdata_dir:config+=' --tessdata-dir '+self.settings.tessdata_dir
            return pytesseract.image_to_string(image,lang=self.settings.ocr_lang,config=config,timeout=20).strip()
    async def once(self):
        row=self.db.claim()
        if not row:return False
        mid=row['id'];p=json.loads(row['payload']);text=p.get('text','');issues=[]
        try:
            for seg in p.get('segments',[]):
                d=seg['data'];typ=seg['type']
                if typ=='image':
                    if not d.get('local_file'):issues.append('群图片未下载：请上传截图；不自动抓取图片 URL')
                    else:
                        result=await asyncio.to_thread(self.ocr,d['local_file'])
                        if not result:raise ValueError('OCR 未识别文字')
                        text+='\n'+result
                elif typ in ('forward','node'):
                    nodes=d.get('nodes',[]) if typ=='forward' else [d]
                    if not nodes:issues.append('合并转发节点未提供')
                    for node in nodes[:30]:
                        if isinstance(node,dict) and isinstance(node.get('content'),str):text+='\n'+node['content'][:4000]
                        elif isinstance(node,dict) and isinstance(node.get('content'),list):
                            text+='\n'+''.join(str(x.get('data',{}).get('text','')) for x in node['content'] if isinstance(x,dict) and x.get('type')=='text')[:4000]
                        else:issues.append('转发节点未解析')
                elif typ not in ('text','reply','at'):issues.append('附件/消息类型未解析：'+typ)
            if p.get('reply_to'):
                ref=p.get('reply_text')
                if ref is None:
                    found=self.db.conn.execute('SELECT text FROM messages WHERE account_id=? AND group_id=? AND message_id=?',(p['account_id'],p['group_id'],p['reply_to'])).fetchone()
                    if found:ref=found[0]
                if ref and ref!='[原文已删除]':text+='\n[引用原文]\n'+ref
                else:issues.append('引用内容缺失')
            # OCR 及实际节点先持久化，模型故障不丢数据。
            if text!=row['text']:
                with self.db.conn:self.db.conn.execute('UPDATE messages SET text=? WHERE id=?',(text,mid))
            if not candidate(text,False):
                self.db.finish(mid,'review' if issues else 'ignored','；'.join(issues) or None);return True
            if not text.strip():self.db.finish(mid,'review','；'.join(issues) or '未解析图片或转发');return True
            ex=await self.extractor.extract(text,datetime.fromisoformat(row['sent_at']),self.db.context(row['group_id'],row['account_id']))
            if not ex.is_event:
                self.db.finish(mid,'review' if issues else 'ignored','；'.join(issues) or None);return True
            ex.review_reasons=list(dict.fromkeys(ex.review_reasons+issues))
            row['text']=text
            # OCR/转发后的完全相同正文也参与幂等重复判断。
            import hashlib
            row['fingerprint']=hashlib.sha256(text.strip().encode()).hexdigest()
            with self.db.conn:self.db.conn.execute('UPDATE messages SET fingerprint=? WHERE id=?',(row['fingerprint'],mid))
            self.db.apply(row,ex)
        except Exception as e:
            from .extract import ModelFailure
            reason=str(e) if isinstance(e,ModelFailure) else '处理失败：'+type(e).__name__+'，请检查 OCR/输入并重试'
            self.db.fail(mid,reason,self.settings.max_attempts)
        return True
    async def run(self):
        while True:
            if not await self.once():await asyncio.sleep(.25)
