# 上游调查与选型

调查时间：2026-10-12，逐一浅克隆后阅读 README、LICENSE、依赖清单、消息入口与部署配置，并读取 GitHub issue 列表及相关正文。GitHub API 受当前网络策略拒绝，因此采用 Git HTTPS 与 GitHub 网页，未将 API 失败误判为仓库不存在。完整实际调查 SHA 见 `upstream-review.json`。

| 项目 | 许可证 / 维护证据 | 本工程选择、缺口与理由 |
| --- | --- | --- |
| [NapCatQQ](https://github.com/NapNeko/NapCatQQ) | **Limited Redistribution License，非 MIT**；README 描述混合许可与授权限制。2026-10-12 有消息与转发修复提交。 | 作为用户独立配置的外部协议端；**不复制、修改、打包其源码或镜像**。账号登录/普通群接入必须真实验证。issue [#2085](https://github.com/NapNeko/NapCatQQ/issues/2085) 涉及风控、掉线、登录失败。不能据项目存在保证账号可用，也不提供验证码绕过。请先阅读其许可并确认个人使用条件。 |
| [NoneBot2](https://github.com/nonebot/nonebot2) | MIT；调查分支 2.5.0，2026-10-12 有 changelog 提交。依赖 Python ≥3.10、Pydantic、异步驱动。 | 实际安装 **2.4.3**，按官方 `init/register_adapter/on_message` 插件模式搭建小工程，不 fork 框架。仅加载本工程只读接收插件；FastAPI 驱动挂载网页 API。[#2435](https://github.com/nonebot/nonebot2/issues/2435) 为适配器规范 RFC，说明应检查驱动能力和异常。 |
| [adapter-onebot](https://github.com/nonebot/adapter-onebot) | MIT；版本 **2.4.6**，最近提交 2026-10-09，Pydantic <3，NoneBot ≥2.2。 | 实际安装 **2.4.6**。源码确认 `/onebot/v11/ws` 反向 WS、`Authorization: Bearer` 校验，普通 GroupMessageEvent 不要求 @。[#81](https://github.com/nonebot/adapter-onebot/issues/81) 请求多账号动态 token 钩子，不意味着现有单 token 鉴权缺失。本工程单用户单账号，已验证无 token 拒绝。 |
| [YouRen1320/qqbot](https://github.com/YouRen1320/qqbot) | MIT；2026-09-28 最新文档提交；依赖 NoneBot 2.3.3、适配器 2.4.6、litellm 1.53.9、视频下载与自维护等。 | **不作为底座，不 fork**。真实入口 `plugins/chat/__init__.py` 同时导入 admin、group_events、maintain_commands，并注册 scheduler、主动发言/复读等副作用。README 快速验证仅建议 @ 对话；Compose 默认公开 NapCat 6099、含可选视频服务、未固定 latest 镜像。拆除耦合范围大于独立插件。[PR #1](https://github.com/YouRen1320/qqbot/pull/1) 补充安全与自维护测试；调查 issue 列表未发现独立的群通知日程方案。未复制其业务代码。 |
| [FullCalendar](https://github.com/fullcalendar/fullcalendar) | 标准组件 MIT；调查分支 7.1.1，2026-10-05 更新。 | 实际锁定 **6.1.19** core/daygrid/timegrid/luxon3，免费标准组件；不用 Scheduler/Premium。用 vanilla JS + Vite，避免为日历引入完整前端框架。[#8082](https://github.com/fullcalendar/fullcalendar/issues/8082) 报告 7.0 ResizeObserver 回归；不能推论所有版本都受影响。本工程月/周切换、窄屏已浏览器实测。 |

采用 SQLite 自带事务与持久处理队列；图片用 Tesseract 现有引擎；ICS 用 icalendar 6.3.1；Pydantic 校验模型输出；没有重写 QQ 协议、日历、OCR 或调度器。第一版没有需要引入调度器的后台通知功能。

NapCat 不包含在本工程 Compose 中，是有意留下的外部接入边界。没有可测试的账号或扫码条件，因此本工程不声称验证了某个 NapCat release 的真实登录。调查 SHA 只表示阅读的版本，不表示已运行那个版本。

固定依赖用 `uv.lock`、带哈希的 `requirements.lock` 和 `web/package-lock.json`；Docker 基础镜像固定 digest。传递依赖许可保留在 `licenses/`，实际包版本由锁文件确定。没有进行完整第三方安全审计；项目活跃或安装成功不等于安全审计通过。
