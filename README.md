# Muse 长视频 Skill：星幕画布 / 自带 API

把一个故事拆成多段视频，挑选清晰中间帧继续生成，再按真实接点剪成完整长片。

**先选择生成方式，再检查环境。** 同一套规划、参考帧、剪辑和验收流程，可使用星幕，也可使用自带的兼容视频API。接口兼容不等于一定保脸或无缝接续，成片仍需检查。

## 2026-11-16 更新

- 新增星幕/API选择，不再强制安装星幕。
- API使用自己的地址、私密Key和准确模型，不绑定服务商。
- 视频API执行器支持限定协议的只读检查、上传、提交、查询、下载与恢复。
- 升级备份移出技能扫描目录；测试不再额外依赖NumPy。

## 安装

仓库地址：https://github.com/AJbeckliy/muse-long-video 。可点击 **Code → Download ZIP** 下载并解压。

把解压后的整个包交给能操作本机文件和脚本的AI助手，告诉它：

> 从 https://github.com/AJbeckliy/muse-long-video 安装Muse长视频Skill，Skill入口在仓库的 muse-long-video 子目录。先问我用星幕还是自己的API，按照选择配置。API模式不要安装或启动星幕。先检查环境，不生成视频。

Windows也可双击`install-windows.cmd`。需可用的Python 3.10/3.11 x64（[Python下载](https://www.python.org/downloads/windows/)），安装助手会创建独立剪辑环境。

### 星幕画布

1. [下载星幕](https://pan.quark.cn/s/cf3c1e40528d#/list/share)，安装并登录自己的账号。
2. 安装助手选“1”，选择程序和媒体目录，用自己星幕提供的配对信息；已有连接复用。
3. 真实连接检查通过后，核对Muse权限和余额，再制作。

网盘由发布者提供，未核验其中安装包版本。配对Token只存本机，生成消耗自己的额度。

### 自带API

1. 安装助手选“2”，无需星幕，不修改星幕MCP。
2. 提供API地址、文档、准确模型名称；Key通过安全输入或本机`MUSE_VIDEO_API_KEY`环境变量配置，不发到聊天。
3. 助手核对鉴权、上传、参数、轮询、参考帧和音频能力，做只读检查；兼容后才按制作授权生成。

本包支持限定的`video_async_json_v1`协议，或用户已有的适用专用连接器。**不是所有“兼容OpenAI”的API都支持视频，也不是所有视频API都支持参考帧接续。** 不匹配则说明原因并停止，不自动换服务或模型。

选“3”只安装共享文件，稍后选择。已有通道默认沿用，需要切换时明确告诉助手；高级用户可传`setup_windows.ps1 -Backend api`或`-Backend starcanvas`覆盖保存偏好。

## 使用

> 用 $muse-long-video，把这个剧情做成30秒长视频。人物用我的图，先给分段脚本，沿用已选通道。

> 用 $muse-long-video，从这条视频合适的中间帧续拍，保持人物、服装和场景。

> 用 $muse-long-video，只剪辑已有片段，不调用生成。

流程：剧情脚本 → 分段生成 → 中间帧续拍 → 按帧剪辑 → 原声/BGM → 验收交付。

交付MP4、实际提示词、剪辑表与制作记录；不自动发布，不默认交剪映工程。媒体目录由使用者选择，不要求H盘。

## 文档与验证

- [Skill入口](muse-long-video/SKILL.md)
- [通道选择](muse-long-video/references/backend-selection.md)
- [API协议和限制](muse-long-video/references/api-execution.md)
- [星幕接入](muse-long-video/references/synmew-install.md)
- [验证范围](muse-long-video/references/validation.md)

包内不含作者密钥、配对信息、人物素材、项目媒体、Python或星幕安装器。共享脚本依赖PyAV、Pillow和FFmpeg辅助包；配置解析用tomli，助手会联网安装。

已做本机离线测试及原星幕只读连接实测。新增REST协议未跑线上付费视频，全新电脑安装尚未完整实测。勿宣传任意API通用或安装后无需配置。
