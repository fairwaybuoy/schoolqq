"""只读 NoneBot 插件，无 send_*、群管理、自动加入或自维护。"""
import json
from datetime import datetime
from nonebot import get_driver,on_message,on_notice
from nonebot.adapters.onebot.v11 import Bot,GroupMessageEvent,GroupRecallNoticeEvent
from .models import MessageIn,Segment,TZ


def install(settings,db):
    driver=get_driver()
    @driver.on_bot_connect
    async def connect(bot:Bot):
        db.runtime('connected','true');db.runtime('last_connect',datetime.now(TZ).isoformat())
        try:
            groups=await bot.get_group_list()
            membership={g:any(str(x['group_id'])==g for x in groups) for g in settings.groups}
            db.runtime('membership',json.dumps(membership))
        except Exception:db.runtime('membership',json.dumps({'error':'群列表接口不可用，请手动核对'}))
    @driver.on_bot_disconnect
    async def disconnect(bot:Bot):
        db.runtime('connected','false');db.runtime('last_disconnect',datetime.now(TZ).isoformat());db.runtime('gap','已断线：断线期间可能漏消息；重连后可按需读取群历史，无法保证完整')
    receive=on_message(priority=1,block=False)
    @receive.handle()
    async def message(bot:Bot,event:GroupMessageEvent):
        group=str(event.group_id)
        if group not in settings.groups:return
        segments=[Segment(type=x.type,data=x.data) for x in event.original_message]
        ref=next((str(s.data['id']) for s in event.original_message if s.type=='reply' and 'id'in s.data),None)
        reply_text=None
        if event.reply:ref=str(event.reply.message_id);reply_text=event.reply.message.extract_plain_text()
        m=MessageIn(account_id=bot.self_id,group_id=group,message_id=str(event.message_id),sent_at=datetime.fromtimestamp(event.time,TZ),source='qq',text=event.original_message.extract_plain_text(),segments=segments,reply_to=ref,reply_text=reply_text)
        db.ingest(m,settings.groups)
        if not any(x.type=='at' for x in event.original_message):
            marker=json.loads(db.runtime('plain_message_probe') or '{}');marker[group]={'received_at':datetime.now(TZ).isoformat(),'message_id':m.message_id,'account_id':bot.self_id};db.runtime('plain_message_probe',json.dumps(marker))
    notice=on_notice(priority=1,block=False)
    @notice.handle()
    async def recalled(bot:Bot,event:GroupRecallNoticeEvent):
        if str(event.group_id) in settings.groups:db.recall(bot.self_id,str(event.group_id),str(event.message_id))

