# 什亭之匣 macOS

Windows 项目 [Aronabot-voice](https://github.com/HaoyeShen/Aronabot-voice) 的 macOS 迁移，业务与界面固定到 v1.3.1 提交 `06748b714d6111274622d9b4535bf9a4e9bf8d28`。微信传输统一使用本项目 Wemac-auto 的内部函数后端。

迁移正在验收。具体范围、已有验证和剩余接口见 [功能核对表](docs/macos-feature-matrix.md)，全部 9 次 Release 见 [发布记录核对](docs/upstream-release-audit.md)，完整更新历史见 [CHANGELOG](CHANGELOG.md)。不能将业务层离线测试通过等同于所有微信接口已经完成实机验收。

## 运行

在仓库根目录运行：

```sh
python3 -m venv .venv-bot
.venv-bot/bin/python -m pip install -r bot/requirements-macos.txt
.venv-bot/bin/python bot/run.py
```

安装包完成配置后，可从桌面快捷方式启动；首次使用需要配置自己的模型 API 和监听对象。窗口关闭按钮会隐藏窗口并继续运行；菜单栏图标提供显示窗口、启动机器人、停止机器人、退出软件。再次启动快捷方式会唤回已运行的窗口。

命令行也支持：

```sh
.venv-bot/bin/python bot/run.py --headless
.venv-bot/bin/python bot/run.py --check
.venv-bot/bin/python bot/run.py --ui-smoke
PYTHONPATH=src:bot .venv-bot/bin/python bot/scripts/test_suite.py
.venv-bot/bin/python bot/scripts/create_mac_app.py
```

在设置中选择本机独立微信的原生 profile，监听对象必须唯一绑定微信内部 ID。该 profile 包含本机路径、版本校验和原生函数指令校验，需要本机生成，不能直接套用其他用户的 profile。只对配置的监听对象自动回复。读取聊天、发送内容及微信运行时验证均不要求将微信切到前台。

## 配置和资源

数据保存在 `~/Library/Application Support/WemacAuto/Arona`，API Key 保存在 macOS 钥匙串，配置文件只保存凭据引用。数据目录包括聊天记忆、RAG 知识库、人格、语音、状态收据和日志；不加入 Git。

保留 Edge TTS 和本地 GPT-SoVITS 的配置能力，并增加 DeepSeek TTS。DeepSeek 通用女声音色 `stella` 是近似音，并非游戏角色原声；该接口暂不支持变速和变调。语音先合成为 PCM，再编码为 24 kHz SILK，由微信内部函数发送。SILK 编码器为本机构建的 Skype 参考实现，安装包已包含；旧 AMR 发送接口保留。GPT-SoVITS 的源码、参考音频、权重和模型环境依照原项目设计单独安装，不包含在代码分发中。

Mac 版保留首页动画、摸头互动、14 个界面页面、每聊天独立 Agent、跨聊天记忆的双向选择加入、管理员操作、新闻、主动分享、人格、RAG、本地模型及兼容 API、用量统计与日志。回复规则按用户后续要求调整：普通消息只抽取配置概率，命中后生成回复；@机器人、命中配置关键词必回复。连续追问不再绕过概率，也不进行模型回复对象筛选；持续上下文保留。自动回复关闭、手动暂停、免打扰和过期消息保护仍有效。回复的语音、图片、表情与搜索操作由模型在工具和实际候选范围内选择。

默认自动朋友圈互动和日记发布关闭；在设置中可以预览并显式开启。测试不会自动变成长期定时发布配置。发布、评论、点赞和其他发送接口均核对明确目标，结果未知时不得自动补发。

## 许可

代码与原项目许可及角色图片的使用说明均保留，见 [LICENSE](LICENSE)、[WecVoice 来源许可](LICENSE.WecVoice-auto) 和 [UPSTREAM](UPSTREAM.md)。原文档中的 `.bat`、Windows UIA、DPAPI、VB-CABLE 与 Windows 安装步骤仅作为上游历史参考，Mac 版不使用这些微信控制方式。
