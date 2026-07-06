# pyVideoTrans 使用与二次开发导览

本文用一条主线解释 pyVideoTrans：它如何把音视频输入变成翻译后的视频、字幕或音频，以及开发者应从哪里扩展识别、翻译、配音和任务流程。

## 本文负责什么

本文负责建立项目心智模型，帮助读者回答这些问题：

- 使用者：我输入一个 MP4、源语种和目标语种后，项目内部经历了哪些阶段，最后会产出什么。
- 使用者：STT、STS、TTS、VTV、WebUI、CLI、桌面端分别对应主流程的哪一部分。
- 开发者：入口、配置、任务编排、渠道实现和媒体处理分别在什么位置。
- 开发者：新增 ASR、翻译、TTS 渠道时，应看哪些文件，遵守什么输入输出约定。

本文不负责完整安装教程、CLI 参数手册、WebUI 操作手册和每个第三方渠道的鉴权细节。相关内容优先看：

- [README](../README.md)
- [CLI 文档](../docs/cli.md)
- [WebUI 文档](../docs/webui.md)
- [架构说明](../docs/architecture.md)
- [FAQ](../docs/faq.md)

## 先建立心智模型

pyVideoTrans 可以先理解为一个“音视频翻译流水线调度器”。

最核心的使用模型是：

```text
输入：
  音视频文件，例如 MP4
  源语种，例如 zh-cn
  目标语种，例如 en
  可选：识别模型、翻译渠道、配音渠道、配音角色、字幕类型、CUDA、背景音处理

输出：
  翻译后的视频文件
  可选同时输出：源语言字幕、目标语言字幕、源语言音频、目标语言配音、分离出的人声/背景声
```

内部主线是：

```text
用户选择
  -> TaskCfg 标准化参数
  -> Task 类决定要跑哪些阶段
  -> ASR / translator / TTS 渠道执行核心能力
  -> FFmpeg / 音频工具处理媒体文件
  -> 输出字幕、音频或视频
```

把一个完整视频翻译任务展开，就是：

```text
video.mp4
  -> 预处理：拆出音频、无声视频，可选分离人声和背景声
  -> ASR：识别源语言字幕
  -> 翻译：生成目标语言字幕
  -> TTS：生成目标语言配音
  -> 对齐：处理配音时长、字幕时间轴、视频或音频速度
  -> 合成：把视频、字幕、配音、背景音合成最终结果
```

### 五个核心对象

| 对象 | 通俗解释 | 主要代码位置 |
|---|---|---|
| 入口 | 用户从哪里发起任务：桌面、CLI、WebUI | `sp.py`、`cli.py`、`webui.py` |
| 配置 | 用户选择被整理成标准任务参数 | `videotrans/task/taskcfg.py` |
| 任务 | 决定执行哪些阶段、按什么顺序推进 | `videotrans/task` |
| 渠道 | ASR、翻译、TTS 的具体实现 | `videotrans/recognition`、`videotrans/translator`、`videotrans/tts` |
| 媒体产物 | 音频、字幕、无声视频、最终视频等文件 | `target_dir`、`cache_folder` |

### 最容易混淆的边界

```text
GUI / CLI / WebUI
  不是三套业务逻辑，而是三种入口。
  它们都复用 videotrans/task 的任务类。

完整视频翻译
  是主流程。
  STT、STS、TTS 是主流程的拆分能力。

模型能力
  不是全部。
  最终效果还受 FFmpeg、字幕时间轴、配音时长、背景音、人声分离和合成参数影响。

中间文件
  不是全部稳定持久产物。
  cache_folder 成功结束后可能被清理；target_dir 中的输出文件才更适合作为用户可见结果。
```

## 主流程：完整视频翻译

完整视频翻译由 `videotrans/task/trans_create.py` 里的 `TransCreate` 编排，配置类是 `TaskCfgVTT`。

主阶段顺序是：

```text
TransCreate.__post_init__()
  -> prepare()
  -> recogn()
  -> diariz()
  -> trans()
  -> dubbing()
  -> align()
  -> recogn2pass()
  -> assembling()
  -> task_done()
```

| 阶段 | 做什么 | 常见输入 | 常见输出 |
|---|---|---|---|
| `__post_init__` | 初始化路径、阶段开关、输出目录和缓存目录 | `TaskCfgVTT` | `source_sub`、`target_sub`、`source_wav`、`target_wav`、`targetdir_mp4` 等路径 |
| `prepare` | 拆音视频、生成无声视频、可选人声/背景声分离 | 原始 MP4 / 音频 | `source_wav`、`novoice_mp4`、`vocal.wav`、`instrument.wav` |
| `recogn` | 识别源语言字幕 | `source_wav` 或已有源字幕 | 源语言 SRT |
| `diariz` | 可选说话人分离 | 音频、字幕时间轴 | `speaker.json` |
| `trans` | 翻译字幕 | 源语言 SRT | 目标语言 SRT |
| `dubbing` | 生成目标语言配音 | 目标语言字幕、配音角色 | 分段音频、目标语言配音 |
| `align` | 对齐配音、字幕和视频时长 | 配音音频、字幕、无声视频 | 调整后的目标字幕、配音或视频 |
| `recogn2pass` | 可选对配音再次识别，生成更贴近配音的字幕 | 目标语言配音 | 重写后的目标字幕 |
| `assembling` | 合成最终视频 | 视频、配音、背景音、字幕 | 最终视频 |
| `task_done` | 收尾、移动结果、清理缓存、通知完成 | 任务状态 | 成功信号和用户可见输出 |

并不是每个任务都会执行所有阶段。`TransCreate` 会根据配置决定是否跳过阶段：

```text
should_recogn    是否需要识别
should_trans     是否需要翻译
should_dubbing   是否需要配音
should_separate  是否需要人声/背景声分离
should_hebing    是否需要合成视频
should_recogn2   是否需要对配音二次识别
```

因此完整流程更准确地说是“可裁剪的流水线”：

```text
有已有字幕
  -> 可以跳过 recogn

只提取/翻译字幕
  -> 可以跳过 dubbing / align / assembling

不配音
  -> 可以只输出字幕或合成字幕视频

输入是纯音频
  -> 不走视频合成

开启 recogn2pass
  -> 配音后再识别一次，目标字幕可能被重写
```

## 分支流程：主流程如何被拆分

CLI 里有四类任务，可以把它们看成完整视频翻译主流程的拆分版本。

| 任务 | 类 | 配置类 | 识别 | 翻译 | 配音 | 对齐 | 合成 |
|---|---|---|---|---|---|---|---|
| `stt` | `SpeechToText` | `TaskCfgSTT` | 是 | 否 | 否 | 否 | 否 |
| `sts` | `TranslateSrt` | `TaskCfgSTS` | 否 | 是 | 否 | 否 | 否 |
| `tts` | `DubbingSrt` | `TaskCfgTTS` | 否 | 否 | 是 | 是 | 否 |
| `vtv` | `TransCreate` | `TaskCfgVTT` | 可选 | 可选 | 可选 | 可选 | 可选 |

### STT：只生成字幕

```text
音频/视频
  -> prepare()
  -> recogn()
  -> diariz()
  -> task_done()
```

用途：把音视频转成源语言 SRT。对应 CLI 任务是 `stt`。

### STS：只翻译字幕

```text
已有 SRT
  -> prepare()
  -> trans()
  -> task_done()
```

用途：把已有字幕翻译成目标语言字幕。对应 CLI 任务是 `sts`。

### TTS：只把字幕变成配音

```text
已有 SRT
  -> prepare()
  -> dubbing()
  -> align()
  -> task_done()
```

用途：把字幕逐条生成音频，并按字幕时间轴对齐。对应 CLI 任务是 `tts`。

### VTV：完整视频翻译

```text
音视频
  -> prepare()
  -> recogn()
  -> diariz()
  -> trans()
  -> dubbing()
  -> align()
  -> recogn2pass()
  -> assembling()
  -> task_done()
```

用途：从原始音视频一路走到翻译后视频。对应 CLI 任务是 `vtv`，也是 WebUI 当前主要覆盖的任务。

### 可选增强阶段

| 能力 | 属于哪个阶段 | 说明 |
|---|---|---|
| 人声/背景声分离 | `prepare` | 开启后生成 `vocal.wav`、`instrument.wav`，识别和合成可复用 |
| 降噪 | `recogn` 前处理 | 对识别音频做降噪，提高 ASR 输入质量 |
| 说话人分离 | `diariz` | VTV 主流程主要生成 `speaker.json`；STT 场景可把说话人前缀写回字幕 |
| LLM 重新断句 | `recogn` / `recogn2pass` | 可能改变字幕切分和时间轴 |
| 配音自动加速 | `align` | 配音过长时调整音频速度 |
| 视频自动慢速 | `align` | 配音过长时拉长视频 |
| 二次识别 | `recogn2pass` | 用配音音频再生成一次目标语言字幕 |

这些能力不是主流程的必选项。文档或开发时不要把它们写成“必定执行”。

## 三个运行入口

项目有三个用户入口。它们收集参数的方式不同，但核心都转成 `TaskCfg*`，再调用 `videotrans/task` 的任务类。

```text
桌面 GUI
  -> 表单/按钮/队列
  -> TaskCfg
  -> videotrans/task

CLI
  -> argparse 参数
  -> TaskCfg
  -> videotrans/task

WebUI
  -> Gradio 表单
  -> TaskCfgVTT
  -> TransCreate 顺序调用
```

| 入口 | 文件 | 适合场景 | 调度方式 |
|---|---|---|---|
| 桌面端 GUI | `sp.py` | 本机图形化使用、完整桌面功能、批量任务 | GUI 批量模式使用 worker 队列；单视频模式在 Qt 线程里顺序调用任务阶段 |
| 命令行 CLI | `cli.py` | 服务器、自动化、批处理脚本 | `argparse` 解析后直接调用对应任务类 |
| 浏览器 WebUI | `webui.py` | 远程服务器、局域网访问、轻量页面操作 | Gradio 收集参数后构造 `TaskCfgVTT`，顺序调用 `TransCreate` |

注意：不要把三者理解成“都进入同一个队列”。更准确的说法是：

```text
三者复用同一任务层。
GUI 批量更依赖 worker 队列。
CLI 和 WebUI 主要是顺序调用任务阶段。
```

## 任务配置与运行状态

任务配置集中在 `videotrans/task/taskcfg.py`。

| 配置类 | 用途 |
|---|---|
| `TaskCfgBase` | 输入文件、输出目录、缓存目录、源语言、目标语言、CUDA 等通用字段 |
| `TaskCfgSTT` | 识别渠道、模型名、识别语言、降噪、说话人识别等 |
| `TaskCfgSTS` | 字幕翻译渠道 |
| `TaskCfgTTS` | TTS 渠道、音色、语速、音量、音调、音频对齐等 |
| `TaskCfgVTT` | 完整视频翻译参数，组合 STT / STS / TTS，并增加字幕嵌入、背景音、人声分离、二次识别等 |

`BaseTask` 在 `videotrans/task/_base.py`，它定义阶段方法和公共能力：

```text
prepare()
recogn()
diariz()
trans()
dubbing()
align()
assembling()
task_done()
```

具体子类决定每个阶段实际做什么：

| 任务类 | 文件 | 角色 |
|---|---|---|
| `TransCreate` | `videotrans/task/trans_create.py` | 完整视频翻译主流程 |
| `SpeechToText` | `videotrans/task/speech2text.py` | 只做语音识别 |
| `TranslateSrt` | `videotrans/task/translate_srt.py` | 只做字幕翻译 |
| `DubbingSrt` | `videotrans/task/dubbing.py` | 只做字幕配音和音频对齐 |

运行时状态主要在 `videotrans/configure/config.py` 的 `app_cfg` 中，例如队列、执行模式、停止状态、全局参数和运行信号。

## 输出文件和中间文件

可以先按两个目录理解：

```text
target_dir
  用户更可能看到和下载的输出目录。
  包含字幕、音频、最终视频、可复用的人声/背景声等。

cache_folder
  当前任务的临时工作目录。
  存放阶段中间文件，成功结束后可能被清理。
```

常见文件含义：

| 文件 | 通俗解释 | 常见来源 |
|---|---|---|
| `zh-cn.srt` | 源语言字幕 | `recogn` |
| `en.srt` | 目标语言字幕 | `trans` |
| `source_wav` | 缓存目录中的识别用源音频 | `prepare` |
| `target_wav` | 缓存目录中的目标语言配音工作文件 | `dubbing` / `align` |
| `zh-cn.m4a` | 用户可见的源语言音频输出 | `assembling` / 收尾 |
| `en.m4a` | 用户可见的目标语言配音输出 | `assembling` / 收尾 |
| `vocal.wav` | 分离出的人声 | `prepare` 的人声分离 |
| `instrument.wav` | 分离出的背景音 | `prepare` 的背景声分离 |
| `novoice.mp4` | 分离音频后的无声视频 | `prepare` |
| `will_embed.m4a` | 准备嵌入视频的最终音频 | `assembling` |
| 最终 `.mp4` | 合成后的视频 | `assembling` |

不要把所有中间文件都当成稳定接口。二次开发时更应该依赖 `TaskCfg*` 字段和任务阶段产物，而不是随意假设某个临时文件一定存在。

## 三类插件式能力

项目最重要的扩展点是三类渠道：

```text
recognition  语音识别 ASR
translator   字幕翻译
tts          语音合成 TTS
```

三者的组织方式很像：

```text
包的 __init__.py
  -> 定义渠道编号
  -> 在 _ID_NAME_DICT 注册 ChannelProvider
  -> 指定展示名称、实现模块 imp、配置 key_name、设置窗口 win
  -> run() 根据渠道编号动态加载实现类
  -> 实现类继承对应 Base*
```

动态加载入口在 `videotrans/__init__.py` 的 `get_class()`。

### ASR：把声音听成文字

| 项 | 位置 |
|---|---|
| 注册表 | `videotrans/recognition/__init__.py` |
| 基类 | `videotrans/recognition/_base.py` |
| 代表实现 | `videotrans/recognition/_whisper.py`、`_recognapi.py` |

ASR 负责把音频变成带时间轴的字幕列表。典型输出是 `SrtItem` 或等价字典结构。

### translator：把字幕翻译成目标语言

| 项 | 位置 |
|---|---|
| 注册表 | `videotrans/translator/__init__.py` |
| 基类 | `videotrans/translator/_base.py` |
| 代表实现 | `videotrans/translator/_google.py`、`_chatgpt.py`、`_transapi.py` |

翻译层接收源语言字幕列表或 SRT 文本，返回目标语言字幕。主流程会用 `BaseTask.check_target_sub()` 尽量把翻译结果拉回源字幕时间轴。

### TTS：把字幕重新念出来

| 项 | 位置 |
|---|---|
| 注册表 | `videotrans/tts/__init__.py` |
| 基类 | `videotrans/tts/_base.py` |
| 代表实现 | `videotrans/tts/_edgetts.py`、`_qwenttslocal.py`、`_ttsapi.py` |

TTS 层接收 `queue_tts`，逐条或批量生成音频文件。后续 `align` 阶段依赖这些音频继续处理时长和字幕时间轴。

## 二次开发路径

### 新增识别渠道

推荐顺序：

```text
1. 阅读 videotrans/recognition/_base.py
2. 选择一个相近实现作为参考，例如 _whisper.py 或 _recognapi.py
3. 新增实现文件，例如 _myasr.py
4. 在 videotrans/recognition/__init__.py 注册渠道编号和 ChannelProvider
5. 如果需要 API key 或 URL，补 key_name / win 配置
6. 用最小音频验证输出字幕结构和时间轴
```

重点契约：

```text
输入：音频文件、语言、模型、缓存目录、CUDA 等参数
输出：带 line/time/start_time/end_time/text 等字段的字幕列表
```

### 新增翻译渠道

推荐顺序：

```text
1. 阅读 videotrans/translator/_base.py
2. 参考 _google.py、_chatgpt.py 或 _transapi.py
3. 新增实现文件，例如 _mytranslator.py
4. 在 videotrans/translator/__init__.py 注册渠道编号和 ChannelProvider
5. 确认批量翻译、失败重试、API key 或本地 URL 配置
6. 用两三条 SRT 验证行数、顺序和时间轴回填
```

重点契约：

```text
输入：源字幕列表、源语言代码、目标语言代码
输出：目标语言字幕列表
要求：尽量保持和源字幕一一对应；如果行数变化，要理解 check_target_sub 的回填逻辑
```

### 新增 TTS 渠道

推荐顺序：

```text
1. 阅读 videotrans/tts/_base.py
2. 参考 _edgetts.py、_qwenttslocal.py 或 _ttsapi.py
3. 新增实现文件，例如 _mytts.py
4. 在 videotrans/tts/__init__.py 注册渠道编号和 ChannelProvider
5. 如果音色随语言变化，确认角色列表和 UI 配置
6. 用短 SRT 验证每条音频生成、文件路径、时长和 align 阶段
```

重点契约：

```text
输入：queue_tts、voice_role、rate、volume、pitch、语言等
输出：每条字幕对应的音频文件，供 align 汇总和对齐
```

### 新增入口参数或界面配置

新增配置时不要只改一个入口。通常要检查：

```text
TaskCfg 是否需要新增字段
CLI 是否需要 argparse 参数
WebUI 是否需要表单控件和参数组装
GUI 是否需要控件、默认值和参数保存
配置是否需要进入 params / settings
测试是否覆盖默认值和参数传递
```

### 修改主流程阶段

修改 `TransCreate` 前先判断改动属于哪类：

```text
阶段顺序
  影响 prepare/recogn/trans/dubbing/align/assembling 的调用关系，风险最高。

阶段开关
  影响 should_recogn/should_trans/should_dubbing/should_hebing/should_recogn2。

阶段内部能力
  例如新增降噪、人声分离、字幕后处理，风险集中在该阶段。

输出文件
  影响 target_dir、cache_folder、最终视频和可下载文件。
```

主流程改动要优先用短音视频做最小验证，再扩大到真实样本。

## 代码地图与阅读顺序

### 按职责看目录

| 路径 | 职责 |
|---|---|
| `sp.py` | 桌面 GUI 启动入口 |
| `cli.py` | 命令行入口，`stt/sts/tts/vtv` 四类任务 |
| `webui.py` | Gradio WebUI 入口 |
| `videotrans/task` | 核心任务流程、worker、批量任务、音画字幕对齐 |
| `videotrans/recognition` | 语音识别渠道 |
| `videotrans/translator` | 翻译渠道 |
| `videotrans/tts` | 配音和语音合成渠道 |
| `videotrans/configure` | 全局配置、运行时队列、异常、常量、信号中心 |
| `videotrans/process` | VAD、降噪、说话人分离、子进程任务等底层处理 |
| `videotrans/util` | FFmpeg、字幕、下载、GPU、角色、网络请求等工具函数 |
| `videotrans/mainwin` | 桌面主窗口逻辑和动作绑定 |
| `videotrans/ui` | PySide6 界面代码 |
| `videotrans/winform` | 配置窗口和渠道设置窗口 |
| `docs` | 用户文档和架构说明 |
| `tests` | pytest 测试 |
| `pyproject.toml` | 项目依赖和 uv 配置 |
| `uv.lock` | 锁定后的依赖版本 |

### 按目标选择阅读路径

理解主流程：

```text
cli.py / webui.py
  -> videotrans/task/taskcfg.py
  -> videotrans/task/_base.py
  -> videotrans/task/trans_create.py
```

理解 CLI 拆分任务：

```text
cli.py
  -> videotrans/task/speech2text.py
  -> videotrans/task/translate_srt.py
  -> videotrans/task/dubbing.py
  -> videotrans/task/trans_create.py
```

理解桌面端批量处理：

```text
sp.py
  -> videotrans/mainwin/main_win.py
  -> videotrans/task/only_one.py
  -> videotrans/task/mult_video.py
  -> videotrans/task/job.py
```

新增渠道：

```text
videotrans/recognition/__init__.py + _base.py
videotrans/translator/__init__.py + _base.py
videotrans/tts/__init__.py + _base.py
```

排查媒体处理：

```text
videotrans/task/trans_create.py
  -> videotrans/util/help_ffmpeg.py
  -> videotrans/process
```

## 环境与依赖要点

本项目要求 Python `>=3.10, <3.11`，依赖由 `pyproject.toml` 和 `uv.lock` 管理。

最小理解即可：

```text
uv sync
  安装主依赖

uv sync --extra webui
  安装 WebUI 依赖，例如 gradio

uv sync --extra webui --extra qwentts
  在 WebUI 中使用本地 Qwen3-TTS 时需要保留 webui 并追加 qwentts
```

完整安装和远程 GPU 运行说明不在本文展开。

## 维护规则

维护本文时遵守：

- 新增内容先判断属于使用主流程、分支流程、入口、配置、渠道扩展还是代码地图。
- 主流程只讲稳定阶段，不把每个第三方渠道的参数细节塞进来。
- 分支流程要说明它是主流程的裁剪、增强还是独立工具。
- 二次开发内容要给出入口文件、基类、注册点和最小验证方式。
- 和安装、CLI 参数、WebUI 操作细节重复的内容，优先链接到对应文档，不在本文长期维护两份。
