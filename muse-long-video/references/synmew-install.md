# 星幕画布接入

解压 Windows 分享包，执行「安装Skill.cmd」即可离线审片。安装器自带基础运行环境。

要生成视频时，在自己的电脑安装并启动星幕画布，登录自己的账号并打开工作区。审片台右上「组件设置 → 配置星幕」会让用户选择本机 SynMewInfiniteCanvas.exe，输入本机端口及配对信息。令牌只在本机输入。按提示重新打开工作台，通过只读检查后再生成。

用户选择自带 API 时，按 [API 执行](api-execution.md) 配置长视频 Skill。审片台直接使用所选生成通道。

## 首次调用的检查入口

本机`CODEX_HOME/muse-long-video.local.json`保存媒体根目录与独立环境Python路径，不保存Token。先读取它；用记录中的python调用Skill脚本，而不是默认系统Python。

```powershell
python <skill>/scripts/setup_synmew.py --check
python <skill>/scripts/setup_synmew.py --probe
```

`--check`只读配置和依赖；`--probe`短暂启动星幕自身的MCP子进程，完成三项只读检查后退出，只终止自己启动的子进程，不关闭用户的星幕窗口。不得将probe通过描述为Muse扣费生成成功。

新手通常用Windows安装助手。高级用户可先预览，再明确应用：

```powershell
python <skill>/scripts/setup_synmew.py --exe D:/Apps/SynMew/SynMewInfiniteCanvas.exe --workspace D:/AI-Work --port 18765
python <skill>/scripts/setup_synmew.py --exe D:/Apps/SynMew/SynMewInfiniteCanvas.exe --workspace D:/AI-Work --port 18765 --apply --probe
```

18765是本机经验值，不覆盖应用显示的实际端口；exe路径以用户选择为准。预览不写配置；首次新增会在本地隐藏提示中要求Token。现有有效配置可以复用。

## 分发边界

- 分享包不含发布者的exe、项目、缓存、人物素材、API Key、MCP配对Token、账户状态及`*.local.json`。
- 默认只支持Windows的安装助手；没有承诺Mac/Linux可以运行Windows星幕exe。剪辑脚本本身可用绝对路径，但其他系统的星幕分发与接入要另核实。
- 本包不是Codex插件市场安装包，解压Skill不会自动注册MCP；需运行安装助手或由助手在授权下配置。
- 用户电脑上的组织策略可能禁止MCP/脚本或联网安装，此时报告具体阻塞，不绕过组织限制。
- 若将来发布者明确授权并提供已核验的离线安装包，可另外做离线合集并记录版本和校验和；不要从作者已登录的应用目录直接复制分发。

## 验证状态

历史版本曾完成只读工作区查询。当前机器须通过本机配对检查。新增安装助手需分别报告：临时配置测试、真实MCP握手、全新机器安装、Muse实际生成四层证据；不以其中一项代替全部。

Codex STDIO配置依据：[MCP说明](https://developers.openai.com/codex/mcp)。星幕参数依据本机已安装程序与工作连接；不宣称所有历史/未来星幕版本完全相同。
