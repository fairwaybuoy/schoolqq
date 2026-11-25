// 只注册 WebUI 页面。群消息仍由本机 Python 服务通过现有 OneBot 连接处理。
export const plugin_init = async (ctx) => {
  ctx.router.page({
    title: '班讯 · 核对与日程',
    path: 'dashboard',
    htmlFile: 'webui/index.html',
    icon: '📅',
    description: '核对班级通知、回补群历史并查看日历'
  });
};
