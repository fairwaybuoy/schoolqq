import asyncio,hashlib,json,secrets,time,zipfile,tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI,APIRouter,Depends,HTTPException,Request,Response,UploadFile,File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from PIL import Image
from .models import MessageIn,EditIn,AssociateIn,SplitIn,Extracted
from .history import HistoryRequest,backfill
from .store import Store,Conflict,dump
from .worker import Worker
from .ics import export_ics

ROOT=Path(__file__).parent.parent

class BodyLimit:
    """同时限制无 Content-Length 的 multipart / JSON，不依赖浏览器校验。"""
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method'] not in ('POST','PUT','PATCH'):
            return await self.app(scope,receive,send)
        chunks=[];size=0
        while True:
            event=await receive()
            if event['type']=='http.disconnect':return
            part=event.get('body',b'');size+=len(part)
            if size>7*1024*1024:return await Response('上传超过 7MB',413)(scope,receive,send)
            chunks.append(part)
            if not event.get('more_body'):break
        body=b''.join(chunks);used=False
        async def replay():
            nonlocal used
            if not used:used=True;return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        await self.app(scope,replay,send)


def create_app(settings,db=None,manage_worker=True):
    db=db or Store(settings.data_dir);worker=Worker(settings,db)
    sessions={};login_attempts={}
    history_lock=asyncio.Lock()
    frame_ancestors = "'none'"
    if settings.napcat_webui_port is not None:
        frame_ancestors = f'http://127.0.0.1:{settings.napcat_webui_port}'
    @asynccontextmanager
    async def lifespan(app):
        task=None
        if manage_worker:db.recover();db.purge(settings.retention_days);task=asyncio.create_task(worker.run())
        yield
        if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
    app=FastAPI(title='QQ 班级通知日程助手',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(BodyLimit)
    app.state.db=db;app.state.worker=worker
    @app.middleware('http')
    async def guard(request,call_next):
        if request.headers.get('content-length','0').isdigit() and int(request.headers.get('content-length','0'))>7*1024*1024:return Response('上传超过 7MB',413)
        host=request.headers.get('host','').split(':')[0]
        if host not in ('localhost','127.0.0.1','testserver','assistant'):return Response('无效 Host',400)
        if request.method not in ('GET','HEAD') and request.headers.get('origin'):
            from urllib.parse import urlsplit
            if urlsplit(request.headers['origin']).netloc!=request.headers.get('host'):return Response('跨站请求拒绝',403)
        r=await call_next(request)
        r.headers['X-Content-Type-Options']='nosniff';r.headers['Referrer-Policy']='no-referrer';r.headers['Cache-Control']='no-store'
        r.headers['X-SchoolQQ']='assistant'
        r.headers['Content-Security-Policy']=f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors {frame_ancestors}; base-uri 'none'"
        return r
    def auth(request:Request):
        bearer=request.headers.get('authorization','')
        if bearer.startswith('Bearer ') and secrets.compare_digest(bearer[7:],settings.app_token):return
        sid=request.cookies.get('schedule_session','')
        if sessions.get(sid,0)>time.time():return
        raise HTTPException(401,'请使用本机 .env 中 APP_TOKEN 登录')
    async def read_json(request,limit=2*1024*1024):
        body=bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body)>limit:raise HTTPException(413,'导入超过 2MB')
        try:return json.loads(body)
        except Exception:raise HTTPException(422,'JSON 格式错误') from None
    @app.post('/api/login')
    async def login(request:Request):
        ip=request.client.host if request.client else 'local';arr=[x for x in login_attempts.get(ip,[]) if x>time.time()-60]
        if len(arr)>=10:raise HTTPException(429,'登录频率过高，请稍后')
        arr.append(time.time());login_attempts[ip]=arr
        body=await read_json(request,4096)
        if not isinstance(body,dict) or not isinstance(body.get('token'),str) or not secrets.compare_digest(body['token'],settings.app_token):raise HTTPException(401,'访问口令不正确')
        sid=secrets.token_urlsafe(32);sessions[sid]=time.time()+12*3600
        for k in list(sessions):
            if sessions[k]<time.time():sessions.pop(k,None)
        r=Response('{}',media_type='application/json');r.set_cookie('schedule_session',sid,httponly=True,samesite='strict',max_age=43200);return r
    router=APIRouter(prefix='/api',dependencies=[Depends(auth)])
    @router.post('/logout')
    def logout(request:Request):
        sessions.pop(request.cookies.get('schedule_session',''),None);r=Response('{}',media_type='application/json');r.delete_cookie('schedule_session');return r
    @router.get('/status')
    async def status():return {**db.stats(),'groups':sorted(settings.groups),'timezone':settings.timezone,'model_enabled':bool(settings.model_base_url and settings.model),'model_daily_calls':settings.model_daily_calls,'model_calls_today':db.budget(datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date().isoformat()),'privacy':'仅筛选后的必要通知片段发送至配置模型；云模型将接收这些片段。可配置本地兼容端点。','ocr':'Tesseract 本地 OCR；群图片 URL 不自动抓取，须上传截图'}
    @router.post('/history/backfill')
    async def history_backfill(body:HistoryRequest):
        if body.group_id not in settings.groups or not body.group_id.isdecimal():
            raise HTTPException(403,'只能读取配置白名单中的真实 QQ 群')
        if history_lock.locked():raise HTTPException(409,'已有一次历史读取正在进行')
        async with history_lock:
            from nonebot import get_bots
            bots=list(get_bots().values())
            if len(bots)!=1:raise HTTPException(409,'请先连接一个 QQ 账号再读取历史')
            bot=bots[0]
            try:
                groups=await bot.get_group_list()
                if not any(str(g.get('group_id'))==body.group_id for g in groups):
                    raise HTTPException(403,'当前 QQ 账号不在该群，不能读取历史')
                cursor=None
                if body.older:
                    cursor = db.history_cursor(str(bot.self_id), body.group_id)
                    if cursor is None:
                        raise HTTPException(409,'这个群还没有已读取的消息，请先读取最近历史')
                result=await backfill(bot,db,body.group_id,body.limit,cursor)
            except HTTPException:raise
            except Exception as exc:
                # 不把 OneBot 原始错误（可能含 token 或群消息）返回到页面。
                raise HTTPException(502,'读取群历史失败，请检查 NapCat 历史消息接口及后台日志') from exc
            return result
    @router.get('/events')
    async def events(include_history: bool = True):return db.events(include_history=include_history)
    @router.get('/events/{eid}')
    async def event(eid:str):
        r=db.event(eid)
        if not r:raise HTTPException(404,'活动不存在')
        return r
    @router.patch('/events/{eid}')
    async def edit(eid:str,body:EditIn):
        try:return db.edit(eid,body)
        except KeyError:raise HTTPException(404,'活动不存在') from None
        except Conflict as e:raise HTTPException(409,str(e)) from None
    @router.post('/events/{eid}/associate')
    async def associate(eid:str,body:AssociateIn):
        e=db.event(eid)
        if not e:raise HTTPException(404)
        if e['version']!=body.expected_version:raise HTTPException(409,'请刷新版本')
        row=db.conn.execute('SELECT * FROM messages WHERE id=?',(body.message_id,)).fetchone()
        if not row or not row['extracted'] or row['event_id']:raise HTTPException(422,'仅可关联未关联的已提取消息')
        try:db.apply(dict(row),Extracted.model_validate_json(row['extracted']),eid)
        except Conflict as e:raise HTTPException(409,str(e)) from None
        return db.event(eid)
    @router.post('/events/{eid}/split')
    async def split(eid:str,body:SplitIn):
        e=db.event(eid)
        if not e or e['version']!=body.expected_version:raise HTTPException(409,'请刷新版本')
        ids={x['id'] for x in e['sources']}
        if not set(body.message_ids)<=ids or set(body.message_ids)==ids:raise HTTPException(422,'需选择部分来源，原活动至少保留一条')
        import uuid
        new_id=str(uuid.uuid4())
        with db.conn:
            db._save(new_id,e['group_id'],e['account_id'],body.event.model_dump(mode='json'),1,'人工拆分',None)
            for mid in body.message_ids:db.conn.execute('UPDATE messages SET event_id=? WHERE id=?',(new_id,mid))
            db._save(eid,e['group_id'],e['account_id'],e['data'],e['version']+1,'人工拆分部分来源',None,e['locked'],False,e['ignored'])
        return db.event(new_id)
    @router.post('/import')
    async def import_messages(request:Request):
        raw=await read_json(request);raw=raw if isinstance(raw,list) else [raw]
        if len(raw)>500:raise HTTPException(413,'每批最多 500 条')
        try:messages=[MessageIn.model_validate(x) for x in raw]
        except ValidationError:raise HTTPException(422,'消息格式错误：需要字符串 ID、带时区 sent_at 和 group_id，参见样例') from None
        return [db.ingest(m,settings.groups) for m in messages]
    @router.post('/import-jsonl')
    async def import_jsonl(request:Request):
        body=bytearray()
        async for p in request.stream():
            body.extend(p)
            if len(body)>2*1024*1024:raise HTTPException(413)
        try:ms=[MessageIn.model_validate_json(line) for line in body.decode('utf8').splitlines() if line.strip()]
        except Exception:raise HTTPException(422,'JSONL 每行必须是一条标准消息') from None
        if len(ms)>500:raise HTTPException(413)
        return [db.ingest(m,settings.groups) for m in ms]
    @router.post('/demo')
    async def demo():
        return [db.ingest(MessageIn.model_validate(x),settings.groups) for x in json.loads((ROOT/'examples/messages.json').read_text())]
    @router.post('/images')
    async def upload(request:Request,file:UploadFile=File(...)):
        group=request.query_params.get('group_id','');sent=request.query_params.get('sent_at','')
        if group not in settings.groups:raise HTTPException(403,'群不在白名单')
        if file.content_type not in ('image/png','image/jpeg','image/webp'):raise HTTPException(415,'仅支持 PNG/JPEG/WebP 截图')
        raw=await file.read(5*1024*1024+1)
        if len(raw)>5*1024*1024:raise HTTPException(413,'图片不超过 5MB')
        import io
        try:
            im=Image.open(io.BytesIO(raw))
            if im.format not in ('PNG','JPEG','WEBP') or im.width*im.height>16000000:raise ValueError()
            im.load()
        except Exception:raise HTTPException(422,'无效图片或像素超过 1600 万') from None
        name=hashlib.sha256(raw).hexdigest()+'.png';folder=db.path/'images';folder.mkdir(exist_ok=True)
        try:m=MessageIn(account_id='local',group_id=group,message_id='image-'+secrets.token_hex(8),sent_at=sent,source='image',segments=[{'type':'image','data':{'local_file':name}}])
        except ValidationError:raise HTTPException(422,'发送时间必须带时区') from None
        im.save(folder/name,format='PNG');return db.ingest(m,settings.groups)
    @router.get('/images/{filename}')
    async def image(filename:str):
        if Path(filename).name!=filename or not filename.endswith('.png'):raise HTTPException(404)
        p=db.path/'images'/filename
        if not p.is_file():raise HTTPException(404)
        return FileResponse(p,media_type='image/png')
    @router.get('/queue')
    async def queue():return db.pending()
    @router.post('/messages/{mid}/new')
    async def new_event(mid:int,body:Extracted):
        row=db.conn.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
        if not row or row['event_id'] or row['state'] not in ('review','failed'):raise HTTPException(422,'仅可将未关联消息人工建为活动')
        body.action='new';body.target_title=None
        row=dict(row);row['fingerprint']=None
        eid=db.apply(row,body)
        return db.event(eid)
    @router.post('/messages/{mid}/retry')
    async def retry(mid:int):db.retry(mid);return {'ok':True}
    @router.post('/messages/{mid}/ignore')
    async def ignore(mid:int):
        r=db.conn.execute('SELECT state FROM messages WHERE id=?',(mid,)).fetchone()
        if not r:raise HTTPException(404)
        if r[0]=='processing':raise HTTPException(409,'正在处理，请稍后')
        db.finish(mid,'ignored');return {'ok':True}
    @router.delete('/messages/{mid}/raw')
    async def delete_raw(mid:int):
        try:return {'deleted':db.purge(mid=mid)}
        except Conflict as e:raise HTTPException(409,str(e)) from None
    @router.post('/retention')
    async def retention():return {'deleted':db.purge(settings.retention_days)}
    @router.get('/calendar/{kind}.ics')
    async def ics(kind:str):
        if kind not in ('deadlines','activities'):raise HTTPException(404)
        return Response(export_ics(db.events(include_history=False),kind),media_type='text/calendar',headers={'Content-Disposition':f'attachment; filename="{kind}.ics"'})
    @router.get('/export')
    async def export():
        raw={'events':db.events(),'messages':[{**dict(x),'payload':json.loads(x['payload'])} for x in db.conn.execute('SELECT * FROM messages')]}
        return Response(dump(raw),media_type='application/json',headers={'Content-Disposition':'attachment; filename="schedule-export.json"'})
    @router.get('/backup')
    async def backup():
        with tempfile.TemporaryDirectory(dir=db.path) as tmp:
            p=Path(tmp);db.backup(p/'schedule.sqlite3')
            import io
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
                z.write(p/'schedule.sqlite3','schedule.sqlite3')
                for f in (db.path/'images').glob('*.png'):z.write(f,'images/'+f.name)
            return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="schedule-backup.zip"'})
    app.include_router(router)
    dist = ROOT / ('windows/ui' if settings.bundled_ui else 'web/dist')
    if dist.exists():app.mount('/',StaticFiles(directory=dist,html=True),name='web')
    return app

