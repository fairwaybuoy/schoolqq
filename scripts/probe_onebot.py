"""本地合成 OneBot 探针；不会登录 QQ，绝不能作为真实 QQ 联调证据。"""
import asyncio,json,os,secrets,subprocess,sys,tempfile,time
from pathlib import Path
import httpx,websockets

async def main():
    app_token=secrets.token_urlsafe(32);ws_token=secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory() as data:
        env={**os.environ,'APP_TOKEN':app_token,'ONEBOT_ACCESS_TOKEN':ws_token,'DATA_DIR':data,'GROUP_WHITELIST':'10001','PORT':'8081','MODEL_BASE_URL':'','MODEL':''}
        p=subprocess.Popen([sys.executable,'-m','app.main'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        client=httpx.AsyncClient(base_url='http://127.0.0.1:8081/assistant/api',headers={'Authorization':'Bearer '+app_token},trust_env=False)
        async def ready():
            for _ in range(80):
                try:
                    r=await client.get('/status')
                    if r.status_code==200:return
                except httpx.HTTPError:pass
                if p.poll() is not None:raise RuntimeError('探针服务启动失败')
                await asyncio.sleep(.1)
            raise RuntimeError('启动超时')
        try:
            await ready()
            # 无鉴权的连接必须拒绝。
            try:
                async with websockets.connect('ws://127.0.0.1:8081/onebot/v11/ws',additional_headers={'X-Self-ID':'90001'},proxy=None):
                    raise AssertionError('WebSocket 未鉴权')
            except websockets.exceptions.InvalidStatus:pass
            async with websockets.connect('ws://127.0.0.1:8081/onebot/v11/ws',additional_headers={'X-Self-ID':'90001','Authorization':'Bearer '+ws_token},proxy=None) as ws:
                action=json.loads(await asyncio.wait_for(ws.recv(),5));assert action['action']=='get_group_list'
                await ws.send(json.dumps({'status':'ok','retcode':0,'data':[{'group_id':10001,'group_name':'合成探针群'}],'echo':action['echo']}))
                async def send(group,id,text):
                    await ws.send(json.dumps({'time':1791770400,'self_id':90001,'post_type':'message','message_type':'group','sub_type':'normal','group_id':group,'user_id':20002,'message_id':id,'message':[{'type':'text','data':{'text':text}}],'raw_message':text,'font':0,'sender':{'user_id':20002,'nickname':'模拟同学','card':'','sex':'unknown','age':20,'area':'','level':'','role':'member','title':''}},ensure_ascii=False))
                await send(10001,1,'商赛 2026年10月18日 18:00 截止报名，2026年10月25日 14:00 比赛')
                await send(20000,2,'外群比赛 2026年10月18日 截止报名')
                for _ in range(70):
                    rows=(await client.get('/events')).json()
                    if len(rows)==1:break
                    await asyncio.sleep(.1)
                assert len(rows)==1,rows
                st=(await client.get('/status')).json();assert st['membership']=={'10001':True};assert '10001'in st['plain_message_probe'];assert rows[0]['sources'][0]['payload']['source']=='qq'
                assert rows[0]['group_id']=='10001'
                assert rows[0]['sources'][0]['payload']['segments'][0]['type']=='text'
            await asyncio.sleep(.3)
            assert not (await client.get('/status')).json()['connected']
            p.terminate();p.wait(timeout=5)
            p=subprocess.Popen([sys.executable,'-m','app.main'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            await ready();rows=(await client.get('/events')).json();assert len(rows)==1;assert len(rows[0]['sources'])==1
            print('PASS 合成 OneBot 反向 WebSocket：鉴权、群成员只读查询、普通未 @ 消息、外群过滤、断线状态、重启持久化。未连接真实 QQ。')
        finally:
            await client.aclose()
            if p.poll() is None:p.terminate();p.wait(timeout=5)

if __name__=='__main__':asyncio.run(main())
