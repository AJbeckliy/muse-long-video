# 本地审片台

读取当前 CODEX_HOME（默认 ~/.codex）中的 muse-long-video.local.json。review_studio 是本机启动入口，workspace_root 是项目根目录。双击入口打开本机页面。逐段审核时，由用户决定续拍与重跑。先检查已成视频，保存版本和按帧剪点。基础安装支持导入固定帧率且带音轨的 MP4、逐帧选择、连播与合成。星幕与本机声音功能按需配置。

自带 API 支持方舟兼容视频任务协议及可导入的 video_async_json_v1 接口配置。API Key 在本机以 Windows DPAPI 加密；先只读验证，再按用户确认提交。普通收集重试只查原任务。
