# 视频API执行与边界

本包没有默认服务商、URL或模型。`scripts/video_api.py`是一个限定协议的执行器，不是任意API万能客户端。必须由Agent对照用户服务商的真实文档填写配置；只有接口格式吻合才运行。

## 支持的协议：video_async_json_v1

- HTTPS，Bearer鉴权；只读GET返回模型列表，可用配置中的点号选择器定位列表和模型ID。
- JSON POST提交一个视频任务，字段由配置映射`model`、`prompt`和单张`image URL`，其他参数为文档明确的顶层字段。
- 可选multipart上传，文件字段固定`file`，JSON返回可定位的HTTPS素材URL。
- 提交返回任务ID；GET状态路径包含`{id}`；状态值分成pending/succeeded/failed三组；成功响应包含可定位的单条HTTPS视频URL。
- 下载地址必须可直接获取视频，不向媒体主机转发API Key。为避免凭证跨主机，当前执行器拒绝HTTP重定向；需要重定向、签名请求鉴权、非Bearer、POST轮询、SSE、base64结果、多参考数组或特殊嵌套请求的服务不在此适配器范围。
- 点号选择器只读取对象，例如`data.id`；不支持列表索引。请求字段是精确顶层字段名，不自动解释点号嵌套结构。

若用户已有能完成该服务的专用MCP/官方工具，可使用其真实schema走API通道，记录`protocol=provider_connector`和工具能力证据；API Key与插件认证按实际服务要求处理。不要因自带工具就宣称REST适配器支持同一协议。未有工具且协议不匹配，报告不支持并停止，另行获得适配开发授权才扩展。

## 配置与检查

参看 [配置模板](../assets/video-api-profile.example.json)，它有意缺少可运行地址、模型和证据，不能直接提交。用户只需给地址、Key、模型；Agent从文档补精确参数和路径，不让小白编写JSON。`evidence`是核对记录，不是脚本自动认证文档真实性。

`parameters`只支持枚举或带上下界的number/integer；包含required=true则每个请求必须填写。参考角色、格式/字节/像素限制必须来自所选模型资料。不从星幕复制默认10秒/720p。

```powershell
python <skill>/scripts/video_api.py check CONFIG.json RECEIPT.json
python <skill>/scripts/video_api.py submit CONFIG.json RECEIPT.json REQUEST.json NEW_ATTEMPT_DIR
python <skill>/scripts/video_api.py submit CONFIG.json RECEIPT.json REQUEST.json NEW_ATTEMPT_DIR --execute
python <skill>/scripts/video_api.py status ATTEMPT_DIR
python <skill>/scripts/video_api.py download ATTEMPT_DIR NEW_OUTPUT.mp4
```

check只读查询准确模型，回执绑定配置hash和Key指纹，配置或Key变化后重查。submit不带execute仅本地检查；execute仍需符合用户的实际生成和上传授权，脚本本身不是授权器。报价/预算依真实服务，若无估价接口说明未知，不能套其他平台价格。收到confirmation_required必须依实际阈值处理，不换工具规避。

REQUEST至少包含`prompt`、`parameters`；有参考时增加绝对`reference_image`和`reference_role`。续拍标记`needs_continuity=true`，无实际参考帧则拒绝。例：

```json
{"prompt":"保持参考画面中的人物、衣服和房间，继续下一动作。","parameters":{"duration":10},"reference_image":"D:/MyVideo/Temp/junction.png","reference_role":"first_frame","needs_continuity":true}
```

只有实际服务支持这些字段、角色和值时才能采用此例。模板没有授权的真实地址或模型。

## 恢复与交付

- 提交前创建新attempt目录，写入意图；同一个目录不可再次提交。上传失败与提交后无ID的unknown分开记录，unknown先核对服务记录，绝不自动新建任务重发。
- 有ID只恢复查询；单次status不启动新任务。按服务建议间隔有限轮询，unknown或最终失败时停止并说明。
- 下载失败只重新收集成功任务，不能重新生成；私有attempt包含结果URL，不打印签名链接，不提交GitHub。不要把恢复所需的URL从状态文件删掉。
- 脚本只验证下载视频首帧可解码，仍需共享流程检查完整解码、实际规格、同脸、服装、场景、接点、台词、音轨和BGM。
- API方式不改变中间帧规则：前段剪到参考帧，下一段按匹配的首帧/参考角色接续；接口字段存在不保证身份稳定。

本版本完成离线协议模拟测试，未使用新的私人API跑付费样片。历史ZZAI MCP实测是该服务连接器证据，不证明此REST协议在所有提供商可用。

## 审片台的 API 设置

上文的环境变量和 JSON 协议供独立命令行调用使用。审片台还支持方舟兼容的异步视频任务，在工作台设置中填写地址、模型和 Key，或选择自定义异步 JSON 配置。页面通过 Windows DPAPI 保存凭据；检查连接和生成视频是两个独立操作。
