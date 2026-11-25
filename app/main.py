import asyncio,sys,os
os.umask(0o077)
import nonebot
from nonebot.adapters.onebot.v11 import Adapter
from nonebot.log import logger
from .config import Settings
from .store import Store
from .api import create_app
from .qq_plugin import install

settings=Settings()
# 禁止框架调试日志打印完整群消息；本服务以 API 状态页报告错误类型。
logger.remove();logger.add(sys.stderr,level='CRITICAL')
nonebot.init(driver='~fastapi',host=settings.host,port=settings.port,onebot_access_token=settings.onebot_access_token,log_level='CRITICAL')
driver=nonebot.get_driver();driver.register_adapter(Adapter)
db=Store(settings.data_dir);db.recover();db.purge(settings.retention_days)
api=create_app(settings,db,manage_worker=False)
driver.server_app.mount('/assistant',api)
install(settings,db)
task=None
@driver.on_startup
async def start():
    global task
    task=asyncio.create_task(api.state.worker.run())
@driver.on_shutdown
async def stop():
    if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
if __name__=='__main__':nonebot.run()
