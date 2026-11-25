# 源码来源与许可

业务代码为本工程独立实现，没有 fork/rewrite 框架本体或复制 qqbot 的闲聊/群管理逻辑。

- NoneBot2：https://github.com/nonebot/nonebot2，实际运行发行包 2.4.3，MIT。
- OneBot 适配器：https://github.com/nonebot/adapter-onebot，实际运行 2.4.6，MIT。
- FullCalendar：https://github.com/fullcalendar/fullcalendar，标准免费模块 6.1.19，MIT，许可随构建依赖保留。
- FastAPI：https://github.com/fastapi/fastapi，0.116.1，MIT。
- Pydantic：https://github.com/pydantic/pydantic，实际 2.14.1；pydantic-settings 2.10.1，MIT。
- icalendar：https://github.com/collective/icalendar，6.3.1，BSD-2-Clause。
- Tesseract：https://github.com/tesseract-ocr/tesseract，当前机器 5.5.0；引擎 Apache-2.0，不改写引擎。
- OCR 中文/英文数据：https://github.com/tesseract-ocr/tessdata_fast，实际本机使用 commit `87416418657359cb625c412a48b6e1d6d41c29bd`；Apache-2.0。TLS 下载及 SHA256 校验见 `docs/ocr-checksums.json`。
- pytesseract：https://github.com/madmaze/pytesseract，0.3.13，Apache-2.0。
- Pillow：https://github.com/python-pillow/Pillow，11.3.0，HPND/PIL 许可，详情在 licenses。
- Luxon：https://github.com/moment/luxon，3.7.2，MIT；用于上海时区前端日历。
- Vite：https://github.com/vitejs/vite，6.4.1，MIT。
- Playwright：https://github.com/microsoft/playwright，1.55.0，Apache-2.0，仅前端验收。

外部可选协议端 NapCat：https://github.com/NapNeko/NapCatQQ，限制性/混合许可。**未将其源码或镜像再分发到本工程**；调查许可证文本以 `licenses/NapCat-LICENSE-review-only.txt` 供审查。请直接阅读上游许可，不要把它当成 MIT 项目。实际调查 commit、近期提交、部署审查与相关 issue 见 `docs/selection.md`、`docs/upstream-review.json`。

`licenses/` 保留实际安装发行包提供的许可证；版权仍属于相应上游作者。全部 Python 与 JS 实际依赖版本以锁文件为准。没有对所有依赖作安全审计的声明。
