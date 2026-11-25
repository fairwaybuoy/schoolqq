"""仅首次生成本机配置，不覆盖用户已有 .env。"""
import secrets
from pathlib import Path
p=Path('.env')
if not p.exists():
    template=Path('.env.example').read_text()
    template=template.replace('CHANGE_ME_APP_TOKEN',secrets.token_urlsafe(32)).replace('CHANGE_ME_ONEBOT_TOKEN',secrets.token_urlsafe(32))
    p.write_text(template);p.chmod(0o600)
    print('已创建 .env；访问口令请在本机文件中查看，不打印到日志。')
else:print('保留现有 .env')
