# Wemac-auto macOS 分享安装包

运行 `.venv-bot/bin/python packaging/build_pkg.py` 生成 `dist/Wemac-auto-0.3.0-arm64.pkg`。构建需要本机 PyInstaller、已验证的原生 helper 和无账号信息的函数布局；构建不更改运行中的微信。

## 安装流程

1. 打开 pkg，系统 Installer 显示安装进度，将安装助手放到 `/Applications`。
2. 安装结束自动打开助手；也可手动打开「Wemac-auto 安装助手」。选择原版微信与安装目录的上级文件夹，或直接编辑完整目录。
3. 点击一次「开始安装」，显示检查、复制、身份隔离、逐组件重签名、校验、程序安装的阶段进度。助手以登录用户运行，不以 root 创建微信账号容器。
4. 完成后打开目标目录中的 `WeChat-Wemac.app` 登录，再打开 `Wemac-auto.app` 设置自己的模型 API 与监听对象。

仅支持 Apple Silicon、macOS 13+、原版 WeChat 4.2.0（270348）及已固定核心指纹。原版微信本体不分发；通过收件人的本机安装创建副本。不启动、终止或重启微信。不覆盖原安装、账号目录、API 配置。目标必须为新目录且可由用户写入；建议 `~/Applications/Wemac-auto`。复制与重签名在临时同盘目录完成，再提交到目标目录。

## 包内容与个人资源

包含独立 Python/Tk 运行时、桌面机器人全部业务模块、SDK 源码与接口、原生 Frida、图片/表情解码模块、引用/撤回/朋友圈接口、AMR 编码器、静态界面素材和角色语音推理脚本。默认数据从空白创建；联网模型和联网近似音仍需要网络。

不包含开发者聊天数据库、账户、API Key、Keychain、测试目标、私人参考录音、缓存、微信本体。GPT-SoVITS 公开模型与可移植独立 Python 推理环境会自动安装到用户数据目录的 `character_voice`。按安装目录中 `sdk/bot-docs/character-voice.md` 配置收件人自己的参考录音、台词和角色 profile，再通过合成验证启用；未提供参考录音时使用默认近似音。暂未完成的上游功能不会因打包而获得支持。

## 签名与验收

应用采用本地 ad-hoc 签名；当前没有 Developer ID Installer / Application 证书，因此 pkg 无开发者签名且未公证。收件人的 macOS 可能阻止打开，需要由收件人按系统提示决定是否允许；安装器不关闭 Gatekeeper、不更改 SIP。

可用 `pkgutil --expand-full` 检查载荷；随包提供 SHA-256。`--package-check` 只检查冻结程序依赖，既不连接微信也不发送消息。测试应使用空临时目录与假微信夹具，不能在已有独立微信账号上覆盖试装。
