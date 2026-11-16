# 星幕画布接入与分享安装

**只有用户选择星幕时才执行本文。** API用户跳过星幕步骤，见 [通道选择](backend-selection.md) 和 [API执行](api-execution.md)。Windows安装助手先选通道，也支持仅装共享文件、稍后再选。

## 交付形态

Windows分享包包含Skill、安装助手、依赖清单和MCP只读检测，不含星幕程序本体、不含Python安装包或离线依赖轮子。星幕的MCP服务由其自身`SynMewInfiniteCanvas.exe --mcp-server`提供，安装助手只做注册，不另装一个来源不明的MCP服务器。

发布者指定的星幕下载入口：[夸克网盘](https://pan.quark.cn/s/cf3c1e40528d#/list/share)。此链接由用户提供；自动检索未能读取网盘目录，因此未核验其中安装包版本、签名或提取码。不要用同名搜索结果代替它，不自动下载执行未知安装包。链接失效时联系分享者。

## 给使用者的步骤

1. 解压整个分享包，不要直接在压缩包内运行脚本。
2. 从上述入口下载星幕画布，安装到自己的电脑；打开应用，登录自己的账号，确认能使用Muse。生成消耗使用者自己的账户余额。
3. 优先复用已有可用连接。新增时使用星幕实际提供的本机端口和配对Token；不要猜测必须存在某个“开启MCP”开关。配对Token不是视频服务API Key。
4. 双击分享包根目录`install-windows.cmd`。阅读提示后选择星幕exe和媒体存储目录，填写本机端口，在密码输入提示中粘贴本机配对Token。Token不会回显，也不要发到聊天里。
5. 安装助手要求可用的Python 3.10+（优先3.10/3.11 x64）；没有Python时先到[Python官网](https://www.python.org/downloads/windows/)安装。它创建独立环境，联网安装PyAV、Pillow和FFmpeg辅助包，不改系统Python的包。
6. 助手复制Skill至`CODEX_HOME/skills`（未指定时为用户目录`.codex/skills`），已有Skill备份至扫描目录外的`CODEX_HOME/skill-backups`；仅星幕模式新增缺失的`mcp_servers.synmew-canvas`配置，已有同名不同配置则停止并提示审查。不会更改模型服务、推理档位或其他MCP。
7. 配置成功不等于连接成功：助手还执行初始化、工具枚举及只读工作区查询。失败时先打开星幕、检查配对与项目，再重试只读检测；不自动生成测试视频。
8. 把结果交给当前助手，确认连接、模型权限、参考图及输出位置后再制作。若当前宿主尚未发现新增原生工具，再按其真实机制重新加载；已有可用工具或直接执行通道时不要求重复配置或新开对话。

安装时输入的配对信息保存在使用者自己的Codex配置中；配置备份同样可能含凭证，只留在使用者本机，不回传、不装进分享包。更新配对Token或迁移安装路径后，旧配置需要单独核对，助手不静默覆盖它。

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

本机已有星幕配置已完成真实只读工作区查询。新增安装助手需分别报告：临时配置测试、真实MCP握手、全新机器安装、Muse实际生成四层证据；不以其中一项代替全部。

Codex STDIO配置依据：[MCP说明](https://developers.openai.com/codex/mcp)。星幕参数依据本机已安装程序与工作连接；不宣称所有历史/未来星幕版本完全相同。
