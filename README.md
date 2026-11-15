# Aronabot-MacOS

macOS 版阿洛娜机器人，基于 Wemac-auto 内部函数后台监听和发送。

- 管理员群指令 `/singlechat @昵称` / `/singlechat wxid_xxx`，退出 `/singlechat off` 或 `/endsinglechat`。
- 明确语音请求需要执行语音工具，不能用文字问候冒充语音。
- 跨聊天背景记忆与当前会话上下文分离。
- 本地资料检索增强与带来源的游戏资料导入。

完整用法：[群聊路由与记忆](bot/docs/group-routing-memory.md)、[角色语音](bot/docs/character-voice.md)、[pkg 构建](packaging/README.md)。

本仓库不包含账号、API Key、聊天记录、私人录音、训练数据库、模型权重或微信客户端。当前适配微信 4.2.0 (270348)、Apple Silicon。

## SDK 文档

# Wemac-auto

[中文说明](README.zh-CN.md)

macOS WeChat automation through **internal native functions only**. Version 0.3
removes the UI backend, mouse/keyboard simulation, clipboard reading and window
management. `WeChat`, `WeChatAuMac`, `WeChatNative` and `NativeSession` now refer to
the native session class and require an explicit version-pinned profile.

The Python package and executable retain the names `wechat_aumac` and
`wechat-aumac`. Install with `python3 -m pip install -e '.[hook]'` on Apple Silicon
macOS. The analyzed client is WeChat 4.2.0, build 270348. Native access requires a
locally prepared research copy, exact core/helper fingerprints and checked function
heads. WeChat binaries, account data, local profiles and captured payloads are not
shipped in this repository.

Incoming messages are observed from the native sync parser while WeChat remains
in the background. Replies use native submission and server responses. Reading
returns the bounded observed session cache, rather than the entire historical
database. Native card XML is inspected for embedded links across card subtypes;
mini-program routes remain routes when the payload contains no web URL.

Text, PNG, GIF, short MP4 and AMR-NB voice sends have recorded server validation.
Quoted replies use the type-57 AppMsg path. See the current validation scope and
limitations in [the native API](docs/native-api.md). Moments timeline/detail reads
are validated; commenting has been validated on an explicitly chosen post, including
readback of the exact author and comment. Like/unlike APIs remain experimental
until their live writes are validated. Publishing is never performed by setup,
watching, reading or tests.

```bash
./wechat-aumac native-status --profile research/native-profile-isolated.json
./wechat-aumac native-watch --profile research/native-profile-isolated.json --chat INTERNAL_CHAT_ID
# Sends real replies only in the selected chat, once by default:
./wechat-aumac native-reply --profile research/native-profile-isolated.json \
  --chat INTERNAL_CHAT_ID --text 'hello' --max-replies 1
```

A second app can be prepared with a separate bundle ID, sandbox container, app
group, helper identifiers and URL scheme. See [account isolation](docs/account-isolation.md).
Session selection uses the executable path and optional PID, allowing distinct
clients to run concurrently. Log the second app into a different account manually.

Run offline unit tests with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

See [native API](docs/native-api.md), [setup and stability](docs/background-send.md),
[research files](research/README.md) and [Moments entrypoints](docs/moments-entrypoints.md).

## Native SNS images and desktop voice compatibility

Single-image Moments publishing and exact-post comments now use the selected client’s native CDN/SNS functions. See [usage, bounds and validation](docs/native-sns-images.md). The bot includes a Moments page and supports diary illustrations. Voice output uses 24 kHz Tencent SILK with matching metadata, verified audible on desktop.
