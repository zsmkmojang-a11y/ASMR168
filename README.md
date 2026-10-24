# 一伯六十八的ASMR听译间

视频/音频原文件 + 原发布链接 → 提取简介 → 提取音轨 → 本地原文识别及切分 → 中文翻译与文本校对 → 试听复核与 SRT 导出。

**这是辅助翻译工具，不能替代人工全程翻译。** 语音识别、断句和机器译文都可能有遗漏或错误；发布字幕前请由译者完整听音、校对原文与译文、检查时间轴及上下文。项目的工作流程灵感来自 [VoiceTransl（聆译）](https://github.com/shinnpuru/VoiceTransl)。

## 启动

在此目录打开 PowerShell：

```powershell
.\start.ps1
```

浏览器打开 http://127.0.0.1:8765 。程序仅监听本机。首次启动会自动显示使用教程，完成后可从右上角“使用教程”再次打开。

本地构建的 Windows 安装包位于 `release/ASMR168-Setup-1.1.0.exe`。安装后从开始菜单启动，不需要单独安装 Python。安装包不包含 FFmpeg 和离线识别模型；首次启动后在首页“运行组件”分别点击下载，来源为 [Gyan FFmpeg Essentials](https://www.gyan.dev/ffmpeg/builds/) 和 [Systran faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)。FFmpeg 下载时按发布方 SHA-256 文件校验，模型下载完成后尝试加载校验。下载后分别存放在 `%LOCALAPPDATA%\ASMR168\bin` 与 `models\small`，后续可离线识别。任务与教程状态也在该用户数据目录，卸载不会删除。翻译密钥可写在首次启动自动生成的 `app.env` 中；保存后重启应用。原视频仍由用户选择本机路径。

Windows 也可双击 `start.cmd` 启动，避免 PowerShell 脚本执行策略限制。或者直接执行：

```powershell
.\.venv\Scripts\python.exe server.py
```

首次安装或迁移电脑：先安装 Python 3.10+ 和 FFmpeg（包含 ffprobe，加入 PATH），然后执行：

```powershell
python -m venv .venv
python -m pip --python .venv\Scripts\python.exe install -r requirements.txt
```

若创建虚拟环境时 ensurepip 失败，执行 `python -m venv --without-pip .venv`，再使用上面的 `pip --python` 命令。WebUI 与服务端本身只用 Python 标准库，没有前端构建步骤。

## 配置翻译

兼容 `/chat/completions` 的接口均可配置。服务启动前，在同一个 PowerShell 中设置：

```powershell
$env:ASMR_API_KEY = '你的密钥'
$env:ASMR_API_BASE = 'https://你的服务地址/v1'
$env:ASMR_TRANSLATION_MODEL = '服务商提供的模型名称'
.\start.ps1
```

也可以在 WebUI 的“识别与翻译设置”中填写接口和模型；密钥仅从服务端环境变量读取，不写进任务或页面。不要把真实密钥提交到仓库。localhost / 127.0.0.1 的本地模型接口可不填密钥。远程接口要求 HTTPS。

**翻译会发送原文字幕和截断到 6000 字符的简介给指定接口，可能产生服务商费用。原视频和音轨不发送给翻译接口。** 没有配置翻译时，可选择“原文识别与切分”，随后手工填写中文并保存导出。修改接口或翻译模型后需新建任务；只补充环境变量密钥时，重启服务后可继续原任务。

## 使用

1. 输入原视频的完整路径，或选择文件（会复制到 `data/uploads/`，大文件优先用路径）。支持常见视频及音频格式。
2. 填写原发布链接。使用 yt-dlp 读取标题、作者及简介，不下载视频。平台不支持、需要登录或网络失败时，会在日志中提示，使用手工补充简介继续。
3. 选择原文语言、处理终点；默认日语 → 简体中文。识别默认 CPU/int8。安装版请先从“运行组件”下载模型，也可指定已有本地模型目录；不会在任务执行时暗中下载。源码版会优先复用本机模型缓存，未缓存时使用 small 并由 faster-whisper 下载。GPU 需自行安装兼容 CUDA/cuDNN。
4. 开始处理。多个任务串行执行，避免模型争抢内存。切分使用词级时间戳，按标点、停顿、长度、时长断句，然后逐条翻译，保持双语对应。过长的单词或译文不会强行按字符伪造时间，会进入复核清单。
5. 在工作区逐句试听，编辑原文、中文、开始/结束秒数，勾选“已确认”。切分时先分别在原文和译文放置光标，再点“切分”；手工切分时间按比例估算，须试听调整。可删除误识别句。
6. 点“保存并导出”，下载原文、中文、双语 SRT 或 JSON 复核清单。双语顺序为原文在上、中文在下。下载文件反映最后一次保存，空中文不会伪装成翻译结果。

### ASMR 的限制

- VAD 默认开启以减少静音幻觉，但耳语也可能被过滤。发现漏句时关闭 VAD 新建任务，或换更大的模型。
- 低置信度片段仅标记，不直接删除，避免误删轻声台词。模型也可能对纯音效产生高置信度错误，所有字幕默认待人工复核。
- 翻译服务做的是**文本校对**，没有听音能力。修改过的原文保留原始识别供对照，不能替代人工校听。
- 简介只用于术语参考，不作为字幕原文。ASMR“烤肉”指翻译制作，不限定视频内容为食物。
- 当前提取第一条音轨为 16 kHz 单声道 WAV，供识别与试听使用；原片中的双耳立体声音轨不变。不包含压制字幕、视频剪辑或 ASS 样式。

## 命令行

```powershell
.\.venv\Scripts\python.exe pipeline.py 'D:\视频\原片.mp4' --url 'https://原发布链接' --language ja --until transcribe
.\.venv\Scripts\python.exe pipeline.py --resume 任务编号 --until export
```

阶段：`metadata`、`audio`、`transcribe`、`translate`、`export`。阶段成功后才记录完成；同一个任务继续运行时跳过完成阶段，翻译按 20 条一批保存，失败只重试未完成批次。语音识别中途失败需要重跑识别阶段。

`--restart translate` 等选项用于从指定阶段重新执行及使后续阶段失效；会清空译文和人工确认，重新识别还会覆盖人工编辑，请先备份任务目录。WebUI 不提供破坏性重跑按钮。

每个任务位于 `data/<任务编号>/`，包含 `job.json`、`metadata.json`、`media.json`、`audio.wav`、`asr.json`、`segments.json`、三个 SRT 和 `review.json`。原视频文件保持不变。生成物和日志保留在本机，需自行备份及清理。

### 中断恢复

正常失败后可以直接“继续全流程”。若强制结束进程、关机等导致遗留 `.running` 文件：先确认旧服务及 CLI 均已停止，再仅删除对应任务目录的 `.running` 文件并重启服务。保留锁是为了防止两个进程同时覆盖字幕。不要在任务运行时删除锁。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用临时目录，覆盖时间精度、切分、无音轨失败、断点续跑、HTTP 输入校验、导出和模拟翻译接口，不调用收费服务。运行时真实依赖以及模型效果另行验证。

可选浏览器回归脚本为 `tests/browser_check.py`，需额外安装 Playwright 并有 Microsoft Edge；本机服务启动后执行。它使用 `tests/artifacts/sample.wav` 短音频创建测试任务，并注入明确标记的字幕样例，测试编辑、切分、保存、下载、无效时间拒绝、试听及 390 px 布局。样例字幕不代表识别结果。真实识别另用原音频的 12 秒片段验证，自动结果仍须听音复核。

依赖接口依据：[faster-whisper 官方文档](https://github.com/SYSTRAN/faster-whisper)、[yt-dlp 官方接口](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py)。
