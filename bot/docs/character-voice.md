# macOS 本地角色语音

阿洛娜和普拉娜使用独立的 GPT-SoVITS 声学权重、用户提供的国服配音参考、参考台词和音频哈希。这里的“国服参考”说明参考录音的来源；合成结果是 AI 语音，并非游戏官方发布或认证的模型。当前方案使用社区已训练权重结合参考音频推理，没有把几秒录音称作重新训练完成的模型。

## 本机数据与来源

本机数据根目录为 `~/Library/Application Support/WemacAuto/Arona/character_voice`，不随 Git 或软件源码上传：

- `runtime/bin/python3`：独立 Python 3.11 推理环境，与桌面软件环境隔离。
- `GPT-SoVITS`：官方源码固定提交 `4fd57b0ea776d396f202e13be180b4c02e4dd957`，源文件下载哈希见 `source-manifest.json`。
- `models/arona`：当前使用 `normal_e8_s1536.pth` 角色声学权重。
- `models/plana`：当前使用 `plana_e8_s232.pth` 角色声学权重。
- `models/base`：共用 v2 GPT `s1-v2.ckpt`、中文 RoBERTa 与 CNHuBERT；下载校验见 `model_manifest.json`。角色社区 GPT 权重保留供研究，正式配置使用通过短句和长句验证的基础 GPT，避免只读开头随后长时间静音的问题。
- `references/arona`、`references/plana`：从用户新 M4A 提取的参考 WAV 及片段来源记录，不改动原始录音。
- `profiles/arona.json`、`profiles/plana.json`：独立角色配置、参考台词、音频及权重 SHA-256、推理环境和合成验证状态。普拉娜兼容旧版 `profile.json`，新配置优先。

来源：[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)、[阿洛娜权重](https://huggingface.co/xingguangcuican6666/arona-sovits)、[普拉娜权重](https://huggingface.co/xingguangcuican6666/plana-gptsovits-v2)、[基础模型](https://huggingface.co/lj1995/GPT-SoVITS)。各模型遵循其发布者许可；阿洛娜模型页标注 GPL-3.0，普拉娜模型页标注 MIT。模型权重不放入 Git；在线安装版在安装时下载公开权重，个人参考录音需自行配置。

## 验证和使用

使用 `scripts/prepare_character_reference.py` 先检查音轨，再截取 3–10 秒的单人语音。输出的参考来源记录始终是 `validated:false`，不等同于模型验证。正式角色配置必须通过实际新句子合成检查，才可设置 `validated:true`。音色相似度另记为 `voice_similarity_reviewed`，合成成功不会自动当作人工试听认可。

语音预设的角色 ID 必须为 `arona` 或 `plana`，引擎为 `gpt_sovits`；人格设置分别选中对应音色。切换角色先结束原推理工作进程，再加载目标角色，防止串用参考或同时占用两套模型内存。模型及参考音频留在本机；合成文字不发到云端 TTS。

当前使用 CPU、完整精度推理；可在角色配置中显式开启 BERT 动态量化。语速与音量可调，保持参考声线时使用 `+0%`、`+0Hz`、`+0%`，清晰度处理默认为 0。语音回复中的中英混合昵称优先朗读中文部分；其余英文字母显式转换为中文字母读法，再交给中文前端，避免因英文昵称回退文字或静默漏读。这是中文字母读法，音色本身仍使用中文推理。

“试听”只在本机播放。消息使用该音色时，先本地合成 PCM、编码 24 kHz SILK，再经微信内部函数发送；不需要虚拟声卡，也不操作微信界面。停止机器人会结束角色推理工作进程。

输出会检查音频有效性及异常长静音；发现异常时只在本机换一个随机种子重试一次，仍失败则交给现有文字回退。重试发生在发送前，不会重复上传消息。

依赖版本记录在 `requirements-character-voice.lock`；参考提取工具依赖见 `requirements-reference-audio.txt`。参考文件或权重发生变化时，重新校验并合成后再启用。工作进程日志位于数据根目录的 `worker.log`。
