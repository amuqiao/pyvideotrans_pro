# AI 配音单 MP4 输入流程

本文把“单个原始 MP4 + 目标语种 -> 目标语种配音 MP4”拆成可执行的工程流程。它不是概念介绍，而是用于产品、算法、后端、音频和质检协作的流程规格：每一步都必须有明确输入、输出、验收标准和返工入口。

## 1. 文档职责

### 1.1 目标

输入：

```text
原始 MP4
目标语种
```

输出：

```text
目标语种最终配音 MP4
目标语种字幕
全链路处理报告
可追溯的句级任务表
```

本文负责定义：

- 从 MP4 到最终配音成片的主流程。
- 每一步的输入、处理、输出和验收标准。
- 说话人识别、角色绑定、reference audio 的落地方式。
- 实现参考中的开源工具链和 GitHub 项目索引。
- 质量门禁、人工复核点和返工路径。

本文不负责定义：

- 具体模型训练方案。
- 商业 TTS、翻译、云转码服务的采购决策。
- 具体 UI 交互稿。
- 人工配音团队的排班和录音棚流程。

## 2. 完整视图

先不要把它理解成“一个 AI 模型把 MP4 变成配音视频”。更准确的理解是：

```text
这是一条媒体工程流水线：
先把 MP4 拆成可处理的音频、文本、说话人和背景声，
再把每句台词变成可追溯的配音任务，
最后生成目标语音、放回原时间轴、混音并封装成新 MP4。
```

最重要的心智模型：

```text
视频文件不是主工单。
字幕文件也不是主工单。

真正贯穿全流程的是 tasks/dubbing_tasks.json。
每个步骤都在补全、检查或消费这张句级任务表。
```

### 2.1 一句话流程

```text
MP4
  -> 输入校验
  -> 抽取音轨
  -> 人声/背景分离
  -> ASR 与源字幕校正
  -> 说话人分离
  -> 角色绑定
  -> reference audio 选取
  -> 创建唯一主工单 tasks/dubbing_tasks.json
  -> 翻译与配音文本控长
  -> TTS 生成
  -> 时间轴对齐
  -> 混音
  -> MP4 封装
  -> 成片质检与返工
```

### 2.2 四层认知模型

整条链路可以分成四层。每一层解决的问题不同，产物也不同：

| 层级 | 核心问题 | 主要产物 | 主要技术 |
|---|---|---|---|
| 媒体层 | MP4 能不能被稳定处理，音频和背景怎么拆出来 | `source_audio.wav`、`vocals.wav`、`background.wav` | FFmpeg、ffprobe、UVR/Demucs |
| 理解层 | 原视频里说了什么、谁在说、什么时候说 | `source_segments_reviewed.json`、`speaker_turns.json`、`speaker_profiles.json` | WhisperX/faster-whisper、pyannote.audio、VAD、人工校对 |
| 生成层 | 目标语种怎么说、用谁的声音说、每句音频在哪里 | `dubbing_tasks.json`、`generated/segments/*.wav` | 翻译模型/LLM、OpenVoice/CosyVoice/GPT-SoVITS/F5-TTS |
| 成片层 | 新语音怎么放回视频，怎么保留背景声并交付 | `aligned_voice.wav`、`final_audio.wav`、`final_dubbed.mp4` | Rubber Band、音频混音、FFmpeg、QA 脚本 |

### 2.3 可视化文字视图

```text
用户输入
  |
  |-- input/source.mp4
  |-- target_language
  |-- 可选：source_language / speaker_count_hint / role_map / delivery_profile
  v

[0 输入校验]
  输入：source.mp4 + 配置
  技术：ffprobe / FFmpeg
  输出：media_report.json + export_manifest.json 初版
  作用：确认视频、音频、时长、音轨都能被后续步骤使用
  |
  v

[1 抽取音轨]
  输入：source.mp4
  技术：FFmpeg
  输出：media/source_audio.wav
  作用：把 MP4 里的目标音轨变成模型可处理的 WAV
  |
  v

[2 人声/背景分离]
  输入：source_audio.wav
  技术：UVR / Demucs / source separation 模型
  输出：media/vocals.wav + media/background.wav
  作用：vocals 用于识别和克隆，background 用于最终混音
  |
  +--> 文本理解分支
  |      |
  |      v
  |    [3 ASR 识别原文]
  |      输入：vocals.wav
  |      技术：WhisperX / faster-whisper
  |      输出：source_segments.json
  |      作用：知道每句话是什么
  |      |
  |      v
  |    [4 源字幕校正]
  |      输入：source_segments.json
  |      技术：人工校对 + forced alignment
  |      输出：source_segments_reviewed.json
  |      作用：得到可信的原文和时间槽
  |
  +--> 说话人分支
         |
         v
       [5 说话人分离]
         输入：vocals.wav
         技术：VAD + pyannote.audio
         输出：speaker_turns.json
         作用：知道每段话属于哪个 speaker
         |
         v
       [6 角色绑定]
         输入：speaker_turns + 可选视频证据/role_map
         技术：音频 diarization + 人脸/active speaker + 人工确认
         输出：speaker_profiles.json
         作用：确定 speaker 类型、角色名、配音策略

文本理解分支 + 说话人分支汇合
                |
                v

[7 Reference Audio 选取]
  输入：vocals.wav + speaker_turns.json + speaker_profiles.json
  技术：音频切片 + 人工抽听 + 质量检查
  输出：speakers/references/*.wav + reference_report.json
  作用：给 voice clone 准备干净参考音频
                |
                v

[8 创建唯一主工单]
  输入：source_segments_reviewed.json + speaker_turns.json + speaker_profiles.json
  技术：Python 编排 + JSON/SQLite/PostgreSQL
  输出：tasks/dubbing_tasks.json
  作用：把“哪句台词、哪个时间槽、哪个 speaker、用什么策略”合成一张任务表
                |
                v

[9 翻译与控长]
  输入：dubbing_tasks.source_text + target_language + 术语/角色口吻要求
  技术：翻译模型/LLM + 人工校对 + 文本时长估算
  输出：写回 target_text_raw / target_text_adjusted / target_text_status
  作用：让目标语种文本既准确，又适合在原时间槽里读出来
                |
                v

[10 TTS / 音色克隆]
  输入：target_text_adjusted + speaker_profiles + reference_audio
  技术：OpenVoice / CosyVoice / GPT-SoVITS / F5-TTS
  输出：generated/segments/*.wav + tts_report.json
  作用：为每条任务生成句级目标语音
                |
                v

[11 时间轴对齐]
  输入：generated/segments/*.wav + dubbing_tasks 时间槽
  技术：音频拼接 + 静音填充 + Rubber Band 小幅变速
  输出：generated/aligned_voice.wav + alignment_report.json
  作用：把每句目标语音放回原视频对应时间
                |
                v

[12 混音]
  输入：aligned_voice.wav + background.wav
  技术：响度控制 + 动态范围处理 + 音频混音
  输出：generated/final_audio.wav + mix_report.json
  作用：把目标人声和原背景音乐/环境声合成最终音轨
                |
                v

[13 MP4 封装]
  输入：原视频流 + final_audio.wav + target.srt
  技术：FFmpeg
  输出：export/final_dubbed.mp4 + export_manifest.json
  作用：把新音轨和字幕封装回可播放视频
                |
                v

[14 成片质检]
  输入：final_dubbed.mp4 + dubbing_tasks.json + 全链路报告
  技术：自动检查脚本 + 人工抽检
  输出：qa_report.json + 通过成片或返工任务列表
  作用：确认语义、角色、音色、对齐、混音和封装都达标
```

### 2.4 每步输入输出与技术组合速览

| 步骤 | 输入 | 输出 | 推荐技术组合 | 新手要抓住的重点 |
|---|---|---|---|---|
| Step 0 输入校验 | `source.mp4`、目标语种和配置 | `media_report.json`、`export_manifest.json` 初版 | ffprobe + FFmpeg + Python | 先确认文件可处理，不要让坏输入进入后续流程 |
| Step 1 抽取音轨 | `source.mp4` | `source_audio.wav` | FFmpeg | 后续模型主要吃 WAV，不直接吃 MP4 |
| Step 2 人声分离 | `source_audio.wav` | `vocals.wav`、`background.wav` | UVR / Demucs | 人声用于识别和克隆，背景用于最终混音 |
| Step 3 ASR | `vocals.wav` | `source_segments.json`、`source.srt` | WhisperX / faster-whisper | 得到“每句话 + 时间戳” |
| Step 4 源字幕校正 | `source_segments.json` | `source_segments_reviewed.json` | 人工校对 + forced alignment | ASR 不是最终事实，必须清理时间轴和错字 |
| Step 5 说话人分离 | `vocals.wav`、源字幕 | `speaker_turns.json`、`segment_speaker_links.json` | VAD + pyannote.audio | diarization 只得到匿名 `speaker_id`，不是角色名 |
| Step 6 角色绑定 | speaker turns、可选视频证据/角色表 | `speaker_profiles.json` | diarization + active speaker + 人工确认 | 决定每个 speaker 用什么配音策略 |
| Step 7 Reference 选取 | `vocals.wav`、speaker profiles | `references/*.wav`、`reference_report.json` | 音频切片 + 人工抽听 | 音色克隆质量很依赖干净 reference |
| Step 8 创建主工单 | 字幕、speaker、profile | `dubbing_tasks.json` | Python + JSON/SQLite/PostgreSQL | 后续所有步骤围绕这张表写回状态 |
| Step 9 翻译控长 | `source_text`、目标语种、术语表 | 更新 `target_text_*` 字段、`target_draft.srt` | 翻译模型/LLM + 人工校对 | 配音文本不是直译，要适合朗读和时间槽 |
| Step 10 TTS 生成 | 目标文本、speaker、reference | `generated/segments/*.wav` | OpenVoice / CosyVoice / GPT-SoVITS / F5-TTS | 每句生成独立音频，便于重做和定位 |
| Step 11 时间轴对齐 | 句级 WAV、原时间槽 | `aligned_voice.wav` | 音频拼接 + Rubber Band | 轻微超时可处理，严重超时要回到文本或 TTS |
| Step 12 混音 | `aligned_voice.wav`、`background.wav` | `final_audio.wav` | 音频混音 + 响度检测 | 目标语音要清楚，背景声也要自然 |
| Step 13 封装 | 原视频流、最终音轨、字幕 | `final_dubbed.mp4`、`target.srt` | FFmpeg | 视频画面通常复用，主要替换或新增音轨 |
| Step 14 质检 | 成片、任务表、报告 | `qa_report.json`、返工列表 | QA 脚本 + 人工抽检 | 失败项必须能回到具体 `task_id` 或步骤 |

### 2.5 技术栈组合怎么选

如果先做 MVP，可以把技术栈理解成以下组合：

```text
Python 编排
  + FFmpeg / ffprobe 处理媒体
  + WhisperX 或 faster-whisper 做 ASR
  + pyannote.audio 做说话人分离
  + UVR 或 Demucs 做人声/背景分离
  + 翻译模型或 LLM 做目标文本
  + OpenVoice / CosyVoice / GPT-SoVITS / F5-TTS 做 TTS 或音色克隆
  + Rubber Band 做小幅变速
  + JSON/SQLite/PostgreSQL 保存任务表和报告
  + Web 审核台或表格导出承接人工复核
```

如果只想先跑通闭环，优先保证这三件事：

| 优先级 | 必须稳定 | 原因 |
|---|---|---|
| 1 | `tasks/dubbing_tasks.json` 的字段和状态 | 没有主工单，后续无法追溯、返工和质检 |
| 2 | `source_segments_reviewed.json` 的文本和时间戳 | 源字幕错了，翻译、TTS、对齐都会被放大出错 |
| 3 | `speaker_profiles.json` 和 reference audio | speaker 绑定错了，最终会出现角色声音混乱 |

### 2.6 主干数据链

主干数据链：

```text
source.mp4
  -> source_audio.wav
  -> source_segments.json
  -> source_segments_reviewed.json

source_segments_reviewed.json
  + speaker_turns.json
  + speaker_profiles.json
  -> tasks/dubbing_tasks.json

tasks/dubbing_tasks.json
  -> 持续写入 target_text、tts_audio_path、alignment、review_status
  -> generated/segments/*.wav
  -> aligned_voice.wav
  -> final_audio.wav
  -> final_dubbed.mp4
```

并行分析链：

```text
source_audio.wav -> vocals.wav + background.wav
source_audio.wav -> speaker_turns.json -> speaker_profiles.json
video_frames     -> face_tracks.json -> active_speaker_links.json -> speaker_profiles.json
```

`tasks/dubbing_tasks.json` 是唯一主工单。后续步骤只更新这个文件中的字段和状态，不再引入互相竞争的 `translated_tasks`、`rendered_tasks` 作为新主表。需要审计历史时，可以在 `reports/` 中保存快照，但快照不是后续服务的契约输入。

## 3. 交付物标准

### 3.1 输入标准

| 输入项 | 必填 | 标准 |
|---|---:|---|
| `source.mp4` | 是 | 可解码，至少包含一条音轨和一条视频轨 |
| `target_language` | 是 | 使用稳定语言码，例如 `en-US`、`ja-JP`、`zh-CN` |
| `source_language` | 否 | 未提供时允许自动检测，但检测结果必须写入报告 |
| `speaker_count_hint` | 否 | 已知角色数量时提供，用于约束 diarization |
| `role_map` | 否 | 已有人物名或角色名时提供，用于 speaker 到角色映射 |
| `delivery_profile` | 否 | 例如是否保留原音轨、是否内嵌字幕、目标响度标准 |

### 3.2 输出标准

| 输出项 | 标准 |
|---|---|
| `final_dubbed.mp4` | 可播放；视频时长与原视频一致；目标语种音轨存在；无明显音画不同步 |
| `target.srt` | 与目标语音内容基本一致；时间戳不倒序、不重叠 |
| `qa_report.json` | 记录通过项、失败项、返工项、抽检片段 |
| `export_manifest.json` | 记录输入文件、模型版本、工具版本、生成时间、主要中间产物路径 |
| `dubbing_tasks.json` | 每句台词可追溯到原始时间槽、说话人、翻译文本、生成音频和状态 |

### 3.3 推荐目录结构

```text
job_0001/
  input/
    source.mp4
  media/
    source_audio.wav
    vocals.wav
    background.wav
  transcript/
    source_segments.json
    source.srt
    target_draft.srt
    target.srt
  speakers/
    speaker_turns.json
    speaker_profiles.json
    references/
      speaker_001_reference.wav
  tasks/
    dubbing_tasks.json
  generated/
    segments/
    aligned_voice.wav
    final_audio.wav
  export/
    final_dubbed.mp4
    export_manifest.json
  reports/
    media_report.json
    asr_report.json
    diarization_report.json
    reference_report.json
    alignment_report.json
    mix_report.json
    qa_report.json
```

## 4. 核心数据结构

### 4.1 `dubbing_tasks.json`

`dubbing_tasks` 是整条链路唯一主工单。不要只靠 SRT 文件向后传递，因为 SRT 无法稳定承载 speaker、置信度、reference、生成音频、返工状态等字段。

字段按阶段逐步补全，不要求 Step 8 创建时一次性填满。后续服务读取和写回的仍然是同一个 `tasks/dubbing_tasks.json`。

每条任务建议包含：

| 字段 | 类型 | 说明 | 写入阶段 | 条件 |
|---|---|---|---|---|
| `task_id` | string | 句级任务唯一 ID | Step 8 | 必填 |
| `source_start_ms` | int | 原视频中该句开始时间 | Step 8 | 必填 |
| `source_end_ms` | int | 原视频中该句结束时间 | Step 8 | 必填 |
| `source_duration_ms` | int | 原时间槽长度 | Step 8 | 必填 |
| `source_text` | string | ASR 或人工校正后的原文 | Step 8 | 必填 |
| `source_asr_confidence` | number | ASR 置信度或质量分 | Step 8 | 可空，但低置信度必须写入报告 |
| `speaker_id` | string | 匿名说话人 ID，例如 `speaker_001` | Step 8 | 必填 |
| `speaker_confidence` | number | speaker 绑定置信度 | Step 8 | 可空，但低置信度必须复核 |
| `overlap_speech` | boolean | 是否疑似多人重叠 | Step 8 | 必填 |
| `speaker_type` | enum | `dialogue`、`narrator`、`offscreen`、`crowd`、`unknown` | Step 8 | 必填 |
| `binding_status` | enum | `approved`、`needs_human_review`、`rejected` | Step 8 | 必填 |
| `render_strategy` | enum | `voice_clone`、`generic_voice`、`manual_voice`、`subtitle_only`、`skip` | Step 8 | 必填 |
| `reference_audio_id` | string | 使用的 reference audio | Step 8 | `render_strategy=voice_clone` 时必填 |
| `target_text_raw` | string | 初始翻译文本 | Step 9 | 进入配音或字幕交付时必填 |
| `target_text_adjusted` | string | 控长、断句后的配音文本 | Step 9 | 进入 TTS 时必填 |
| `target_text_status` | enum | `pending_review`、`approved`、`rework` | Step 9 | 必填 |
| `tts_audio_path` | string | 句级 TTS 音频路径 | Step 10 | 自动或人工生成语音后必填 |
| `tts_duration_ms` | int | TTS 原始生成时长 | Step 10 | 进入对齐时必填 |
| `fit_status` | enum | `fit`、`minor_speed_change`、`text_rework_required`、`skipped` | Step 11 | 必填 |
| `review_status` | enum | `pending`、`passed`、`failed` | Step 14 | 必填 |
| `error_reason` | string | 失败原因 | 任意失败步骤 | 失败时必填 |

示例：

```json
{
  "task_id": "seg_000042",
  "source_start_ms": 81230,
  "source_end_ms": 84210,
  "source_duration_ms": 2980,
  "source_text": "I know what you mean.",
  "source_asr_confidence": 0.94,
  "speaker_id": "speaker_002",
  "speaker_confidence": 0.88,
  "overlap_speech": false,
  "speaker_type": "dialogue",
  "binding_status": "approved",
  "render_strategy": "voice_clone",
  "target_text_raw": "我明白你的意思。",
  "target_text_adjusted": "我懂你的意思。",
  "target_text_status": "approved",
  "reference_audio_id": "speaker_002_ref_main",
  "tts_audio_path": "generated/segments/seg_000042.wav",
  "tts_duration_ms": 2760,
  "fit_status": "fit",
  "review_status": "pending"
}
```

### 4.2 `speaker_profiles.json`

`speaker_profiles` 负责描述“这个匿名 speaker 怎么配音”。

| 字段 | 说明 |
|---|---|
| `speaker_id` | 匿名说话人 ID |
| `role_name` | 人工确认后的角色名；无法确认时保持为空 |
| `speaker_type` | `dialogue`、`narrator`、`offscreen`、`crowd`、`unknown` |
| `binding_status` | `approved`、`needs_human_review`、`rejected` |
| `render_strategy` | `voice_clone`、`generic_voice`、`manual_voice`、`subtitle_only`、`skip` |
| `reference_audio_id` | 默认 reference audio；仅 `voice_clone` 策略强制要求 |
| `reference_audio_path` | reference 文件路径；仅 `voice_clone` 策略强制要求 |
| `clean_speech_ms` | 可用于克隆的干净单人语音总时长 |
| `quality_flags` | 例如 `music_bleed`、`overlap_risk`、`short_reference` |

### 4.3 `export_manifest.json`

最终交付必须能追溯版本：

```json
{
  "job_id": "job_0001",
  "source_file": "input/source.mp4",
  "target_language": "zh-CN",
  "tools": {
    "media": "ffmpeg",
    "asr": "whisperx",
    "diarization": "pyannote.audio",
    "separation": "uvr_or_demucs",
    "tts": "cosyvoice_or_openvoice",
    "time_stretch": "rubberband"
  },
  "outputs": {
    "video": "export/final_dubbed.mp4",
    "subtitle": "transcript/target.srt",
    "qa_report": "reports/qa_report.json"
  }
}
```

## 5. 主流程步骤

### Step 0. 创建任务与输入校验

| 项目 | 标准 |
|---|---|
| 输入 | `source.mp4`、`target_language`、可选 `source_language`、`speaker_count_hint`、`role_map` |
| 处理 | 校验文件存在、可读、可解码；读取媒体元数据；记录任务 ID |
| 输出 | `media_report.json`、`export_manifest.json` 初版 |
| 验收 | 视频轨和音轨都存在；总时长可读取；文件校验值已记录 |
| 不通过处理 | 无音轨、无法解码、时长不可读时阻断任务；多音轨时要求确认目标音轨 |

`media_report.json` 至少包含：

```json
{
  "duration_ms": 123456,
  "video_streams": 1,
  "audio_streams": 1,
  "selected_audio_stream": "0:a:0",
  "sample_rate": 48000,
  "channels": 2
}
```

### Step 1. 抽取音轨与规范化音频

| 项目 | 标准 |
|---|---|
| 输入 | `source.mp4`、`media_report.json` |
| 处理 | 用 FFmpeg 抽取选定音轨；生成后续模型使用的 WAV |
| 输出 | `media/source_audio.wav` |
| 验收 | 音频时长与视频时长一致；无截断；采样率、声道符合后续模型要求 |
| 不通过处理 | 抽取失败或时长漂移明显时阻断；不得用空音频继续后续步骤 |

推荐规范：

```text
容器：WAV
编码：PCM
采样率：16 kHz 或 48 kHz，按模型要求固定
声道：mono 用于 ASR/diarization；stereo 可保留给混音参考
```

### Step 2. 人声分离

| 项目 | 标准 |
|---|---|
| 输入 | `source_audio.wav` |
| 处理 | 分离对白人声和背景声 |
| 输出 | `vocals.wav`、`background.wav`、`separation_report.json` |
| 验收 | 两条音频与原音频等长；关键对白抽检结果为 `pass`；`background.wav` 原人声残留抽检未触发 `voice_residue` |
| 不通过处理 | 人声或背景严重污染时标记高风险；影响 reference 时必须人工复核 |

注意：人声分离不是为了“消除所有背景”，而是为了：

- 用 `vocals.wav` 提高 ASR、说话人识别、reference audio 截取质量。
- 用 `background.wav` 在最终混音时保留音乐、环境声和音效。

### Step 3. ASR 与源字幕生成

| 项目 | 标准 |
|---|---|
| 输入 | `vocals.wav`，必要时也参考 `source_audio.wav` |
| 处理 | 识别原语种文本；生成句级、词级或短语级时间戳 |
| 输出 | `source_segments.json`、`source.srt`、`asr_report.json` |
| 验收 | 每段都有 `start_ms`、`end_ms`、`text`；时间戳单调递增；没有大段未识别对白 |
| 不通过处理 | 低置信度、专有名词、重叠说话、噪声片段进入人工校对；ASR 失败不得直接翻译 |

`source_segments.json` 示例：

```json
{
  "segment_id": "seg_000001",
  "start_ms": 1280,
  "end_ms": 3620,
  "text": "We need to leave now.",
  "words": [
    {"word": "We", "start_ms": 1280, "end_ms": 1420},
    {"word": "need", "start_ms": 1430, "end_ms": 1660}
  ],
  "confidence": 0.91
}
```

### Step 4. 源字幕校正与时间轴整理

| 项目 | 标准 |
|---|---|
| 输入 | `source_segments.json`、`source.srt` |
| 处理 | 合并过短片段；拆分过长片段；修正明显错字和时间戳 |
| 输出 | `source_segments_reviewed.json`、`source_reviewed.srt` |
| 验收 | 单句时间槽合理；字幕不倒序；句子适合后续翻译和配音 |
| 不通过处理 | 时间戳不可靠时回到 ASR/forced alignment；文本不可靠时人工校对 |

建议质量线：

- 过短片段：小于 500 ms 的独立对白应检查是否需要合并。
- 过长片段：超过 12 s 的长句应优先拆分。
- 空白间隔：长静音不能被误并入上一句台词。
- 重叠说话：必须保留 `overlap_speech=true` 标记。

### Step 5. 说话人分离与字幕绑定

| 项目 | 标准 |
|---|---|
| 输入 | `vocals.wav`、`source_segments_reviewed.json`、可选 `speaker_count_hint` |
| 处理 | VAD、speaker embedding、speaker clustering、speaker turn 生成；按时间重叠把每句字幕绑定到 `speaker_id` |
| 输出 | `speaker_turns.json`、`segment_speaker_links.json`、`diarization_report.json` |
| 验收 | 每条对白任务都有 `speaker_id`；同一 `speaker_id` 音色稳定；重叠语音明确标记 |
| 不通过处理 | speaker 数量异常、同一角色被拆成多个 speaker、多个角色被合并时人工复核 |

字幕绑定规则建议：

```text
对每个字幕片段，计算它与所有 speaker_turn 的时间重叠比例。
重叠比例最高的 speaker 作为候选 speaker_id。
如果最高重叠比例不足阈值，或前两名接近，则标记 needs_human_review。
如果片段内存在多个 speaker 明显重叠，则 overlap_speech=true。
```

### Step 6. 角色识别与角色绑定

| 项目 | 标准 |
|---|---|
| 输入 | `speaker_turns.json`、`source_segments_reviewed.json`、可选 `video_frames`、`face_tracks.json`、`role_map` |
| 处理 | 将匿名 `speaker_id` 映射到 `role_name`，并设置 `speaker_type`、`binding_status`、`render_strategy` |
| 输出 | `speaker_profiles.json`、`role_binding_report.json` |
| 验收 | 主要 speaker 都有明确处理策略；无法确认角色名时不伪造角色名 |
| 不通过处理 | 画外音、旁白、群体声、镜头外对白无法确认时保持类型标记，并按处置矩阵选择阻断、人工接管或字幕交付 |

这里必须区分三件事：

```text
说话人分离：这段音频是谁说的，输出匿名 speaker_id。
人物身份识别：这个 speaker_id 对应画面中的哪个人。
配音角色绑定：这个 speaker_id 应该使用哪个 reference audio 或 voice profile。
```

音频 diarization 不能自动知道“张三”“女主”“旁白”。要得到角色名，需要以下证据之一：

- 用户提供 `role_map`。
- 人工听审后给 `speaker_id` 命名。
- 视频中有稳定人脸轨迹，并通过 active speaker detection 判断谁在说话。
- 上下文文本中有可靠称谓，但仍需要人工确认。

### Step 7. Reference Audio 选取

| 项目 | 标准 |
|---|---|
| 输入 | `vocals.wav`、`speaker_turns.json`、`speaker_profiles.json` |
| 处理 | 仅为 `render_strategy=voice_clone` 的 speaker 截取干净、单人、足够长的参考音频 |
| 输出 | `references/*.wav`、`reference_report.json`、更新后的 `speaker_profiles.json` |
| 验收 | reference 不含其他人声音；背景音乐和环境噪声不过重；长度满足所选 TTS 模型要求 |
| 不通过处理 | reference 太短、多人重叠、音乐污染重时人工重新选择；没有合格素材时改为 `manual_voice`、`generic_voice`、`subtitle_only` 或 `rejected` |

Reference 选择标准：

| 项目 | 推荐标准 |
|---|---|
| 单人纯净度 | 不含其他 speaker 重叠 |
| 累计时长 | 主要角色尽量准备 15-60 s 干净语音；具体下限按 TTS 模型要求 |
| 单段长度 | 优先选择 3-10 s 的自然句 |
| 情绪 | 优先中性、稳定；特殊情绪可单独建 reference |
| 背景污染 | 背景音乐、音效、人群声明显时标记 `music_bleed` |

### Step 8. 生成 `dubbing_tasks`

| 项目 | 标准 |
|---|---|
| 输入 | `source_segments_reviewed.json`、`speaker_turns.json`、`speaker_profiles.json` |
| 处理 | 合并文本、时间轴、speaker、角色绑定和渲染策略信息 |
| 输出 | `tasks/dubbing_tasks.json` |
| 验收 | 每条任务有时间槽、源文本、speaker、`speaker_type`、`binding_status`、`render_strategy` 和状态字段 |
| 不通过处理 | 缺字段、时间倒序、speaker 缺失时阻断；`voice_clone` 策略缺 reference 时阻断 TTS |

这一步是后续所有自动化和人工返工的定位基础。任何问题都应该能定位到 `task_id`。

### Step 9. 翻译与配音文本控长

| 项目 | 标准 |
|---|---|
| 输入 | `dubbing_tasks.source_text`、`target_language`、术语表、角色口吻要求 |
| 处理 | 翻译；按配音用途改写；控制长度、断句、称谓和语气 |
| 输出 | 更新后的 `tasks/dubbing_tasks.json`、`target_draft.srt`、`translation_report.json` |
| 验收 | 语义不丢失；目标文本适合朗读；预计时长适配原时间槽；术语和人名一致 |
| 不通过处理 | 过长、语义不确定、称谓混乱、专名错误时人工复核；不得随意删句掩盖超时 |

控长规则：

```text
如果目标文本预计时长 <= 原时间槽：通过。
如果轻微超长：优先改写文本，再考虑小幅变速。
如果严重超长：必须回到翻译文本重写，不允许强行压缩。
```

### Step 10. TTS / 音色克隆生成

| 项目 | 标准 |
|---|---|
| 输入 | `target_text_adjusted`、`speaker_id`、`render_strategy`、条件必填的 `reference_audio_path`、`target_language` |
| 处理 | 按 `render_strategy` 生成或接收目标语种配音；记录模型、参数、生成耗时 |
| 输出 | `generated/segments/*.wav`、更新后的 `tasks/dubbing_tasks.json`、`tts_report.json` |
| 验收 | TTS 回检无核心词缺失；人工抽检 `pronunciation_status=pass`；音色和 reference 一致；无爆音、截断、语言混杂 |
| 不通过处理 | 漏读、错读、音色漂移、情绪错误时重生成；多次失败后返回文本改写或人工处理 |

TTS 生成记录至少包含：

```json
{
  "task_id": "seg_000042",
  "speaker_id": "speaker_002",
  "model": "example_tts_model",
  "reference_audio_id": "speaker_002_ref_main",
  "text": "我懂你的意思。",
  "output_path": "generated/segments/seg_000042.wav",
  "duration_ms": 2760,
  "status": "generated"
}
```

### Step 11. 时间轴对齐与时长适配

| 项目 | 标准 |
|---|---|
| 输入 | `generated/segments/*.wav`、`tasks/dubbing_tasks.json` |
| 处理 | 将句级语音放回原时间槽；短句补静音；轻微超长可小幅变速；严重超长返工 |
| 输出 | `aligned_voice.wav`、更新后的 `tasks/dubbing_tasks.json`、`alignment_report.json` |
| 验收 | 人声轨与视频等长；句间无异常重叠；变速倍率写入报告；人工抽检 `time_stretch_status=pass`；开始点贴合画面节奏 |
| 不通过处理 | 大幅超时、连续台词挤压、嘴型动作严重不匹配时回到 Step 9 或 Step 10 |

推荐门禁：

| 情况 | 动作 |
|---|---|
| TTS 时长短于时间槽 | 按原起点放置，必要时尾部补静音 |
| TTS 时长轻微超过时间槽 | 允许小幅变速，并在报告中记录倍率 |
| TTS 时长明显超过时间槽 | 返回翻译控长或重新生成 |
| 连续句互相重叠 | 优先重排断句和文本，不强行堆叠 |

### Step 12. 混音

| 项目 | 标准 |
|---|---|
| 输入 | `aligned_voice.wav`、`background.wav`、原始音轨响度参考 |
| 处理 | 调整人声响度、背景响度、淡入淡出和动态范围 |
| 输出 | `final_audio.wav`、`mix_report.json` |
| 验收 | 目标语音可懂度抽检 `pass`；背景声抽检 `pass`；无 `voice_residue`、`clipping`、`volume_jump` 失败标记 |
| 不通过处理 | 原声残留明显、背景过干、配音压过关键音效时返回分离或混音环节 |

混音报告至少包含：

```json
{
  "voice_track": "generated/aligned_voice.wav",
  "background_track": "media/background.wav",
  "output": "generated/final_audio.wav",
  "peak_status": "pass",
  "human_review_required": false
}
```

### Step 13. MP4 封装输出

| 项目 | 标准 |
|---|---|
| 输入 | 原始视频流、`final_audio.wav`、最终 `tasks/dubbing_tasks.json`、可选 `target_draft.srt` |
| 处理 | 从最终任务表导出 `target.srt`；替换或新增目标语种音轨；按交付要求封装字幕；保留或转码视频 |
| 输出 | `export/final_dubbed.mp4`、`transcript/target.srt`、`export_manifest.json` |
| 验收 | 文件可播放；目标音轨存在；视频时长一致；音画同步；字幕可加载 |
| 不通过处理 | 音轨缺失、封装失败、时长漂移、播放器兼容问题时重新封装 |

### Step 14. 成片质检与返工

| 项目 | 标准 |
|---|---|
| 输入 | `final_dubbed.mp4`、全链路报告、最终 `tasks/dubbing_tasks.json` |
| 处理 | 检查文本、说话人、音色、对齐、混音、封装 |
| 输出 | `qa_report.json`、通过成片或返工任务列表 |
| 验收 | 关键角色音色抽检 `pass`；关键语义抽检 `pass`；无大段错配、漏配、原声残留或音画不同步 |
| 不通过处理 | 每个问题必须定位到 `task_id` 或时间段，并返回对应步骤修复 |

## 6. 角色识别落地方案

### 6.1 角色识别不是单一模型问题

“角色识别”在配音流程里应拆成四层：

| 层级 | 问题 | 典型输出 |
|---|---|---|
| 语音活动检测 | 哪些时间段有人说话 | `speech_segments` |
| 说话人分离 | 哪些语音片段属于同一个匿名人 | `speaker_001`、`speaker_002` |
| 人物身份识别 | 匿名 speaker 对应画面中的谁 | `face_track_003`、`role_name` |
| 配音绑定 | 这个 speaker 用哪个音色生成目标语音 | `reference_audio_id` |

因此，系统不能把 diarization 的 `speaker_001` 直接当成“角色 A”。`speaker_001` 只是匿名说话人，需要后续角色绑定。

### 6.2 音频侧流程

```text
vocals.wav
  -> VAD 找出有语音的时间段
  -> 提取 speaker embedding
  -> 聚类成 speaker_id
  -> 输出 speaker_turns
  -> 按时间重叠绑定 source_segments
```

`speaker_turns.json` 示例：

```json
{
  "speaker_id": "speaker_001",
  "start_ms": 1200,
  "end_ms": 3600,
  "confidence": 0.87,
  "overlap_speech": false
}
```

### 6.3 视频侧增强流程

当视频中出现多人物对话、同声重叠、镜头内多人时，仅靠音频容易错。可增加视频侧证据：

```text
source.mp4
  -> 抽帧
  -> 人脸检测与跟踪
  -> active speaker detection
  -> face_track_id 与 speaker_id 对齐
  -> 人工确认 role_name
```

视频侧只能增强判断，不应自动覆盖音频侧结论。出现冲突时，输出 `needs_human_review`。

### 6.4 角色绑定输出标准

每个主要 speaker 必须同时得到三类字段：

| 字段 | 作用 | 示例 |
|---|---|---|
| `speaker_type` | 说明这个 speaker 是什么类型 | `dialogue`、`narrator`、`offscreen`、`crowd`、`unknown` |
| `binding_status` | 说明角色绑定是否可信 | `approved`、`needs_human_review`、`rejected` |
| `render_strategy` | 说明最终如何生成或处理这段声音 | `voice_clone`、`generic_voice`、`manual_voice`、`subtitle_only`、`skip` |

这三个字段相互独立。`crowd` 是 speaker 类型，不等于失败；`rejected` 是绑定状态，不等于必须删除；`voice_clone` 才要求 reference audio。

### 6.5 异常 speaker 处置矩阵

| speaker 情况 | 允许策略 | 是否可自动出片 | 交付规则 |
|---|---|---:|---|
| 主要对白角色，reference 合格 | `voice_clone` | 是 | 正常进入 TTS |
| 主要对白角色，reference 不合格 | `manual_voice` | 否 | 阻断自动出片，转人工配音或重新选 reference |
| 旁白 / 画外音，角色名不重要 | `voice_clone`、`generic_voice`、`manual_voice` | 视策略而定 | 可不绑定画面人物，但必须有稳定声音策略 |
| 群体声 / 多人重叠 | `subtitle_only`、`skip`、`manual_voice` | 通常否 | 不做单人音色克隆；若影响理解，转人工处理 |
| 无法确认 speaker 且影响主线理解 | `manual_voice` | 否 | 阻断自动出片 |
| 无法确认 speaker 但不影响理解 | `subtitle_only`、`skip` | 是 | 必须在 `qa_report` 记录 |

`render_strategy=skip` 只能用于非对白、无语义或明确不交付的片段。对主要对白使用 `skip` 必须写入 `error_reason` 并阻断成片通过。

## 7. 实现参考：技术栈与开源项目索引

本节是实现参考，不是流程契约。正文规范只要求能力，例如“能输出词级或句级时间戳”“能输出 speaker turns”“能回写 `tasks/dubbing_tasks.json`”。具体项目可以替换，但替换后必须保持相同输入、输出和质量门禁。

资料核验日期：2026-06-23。项目状态会变化，落地前应再次核验 license、模型权重授权、维护状态和硬件要求。

### 7.1 推荐技术栈分层

| 层 | 推荐选择 | 职责 |
|---|---|---|
| 编排语言 | Python | 串联 ASR、diarization、TTS、音频处理 |
| 媒体处理 | FFmpeg / ffprobe | 抽音轨、转码、封装、媒体探测 |
| 中间数据 | JSONL + SQLite/PostgreSQL | 存 `dubbing_tasks`、speaker、报告 |
| 文件存储 | 本地目录或对象存储 | 存 WAV、MP4、中间产物 |
| GPU 推理 | PyTorch / ONNX Runtime / CTranslate2 | ASR、diarization、TTS、分离模型 |
| 任务队列 | Celery / RQ / Temporal / 自研队列 | 长任务、重试、状态追踪 |
| 质检入口 | Web 审核台或表格导出 | 人工校对字幕、speaker、reference 和成片 |

### 7.2 GitHub 项目索引

| 模块 | 项目 | 地址 | 作用 | 选型注意 |
|---|---|---|---|---|
| 媒体处理 | FFmpeg | https://github.com/FFmpeg/FFmpeg | 抽取音轨、转码、混流、封装 | 必须固定命令模板和版本 |
| 媒体探测 | ffprobe | https://ffmpeg.org/ffprobe.html | 读取容器、流、时长、采样率 | 用于输入校验和交付校验 |
| ASR | OpenAI Whisper | https://github.com/openai/whisper | 多语种 ASR、语言识别、翻译任务 | 原生时间戳粒度有限 |
| ASR 加速 | faster-whisper | https://github.com/SYSTRAN/faster-whisper | CTranslate2 Whisper 推理，支持词级时间戳和 VAD | 适合批量转写和部署优化 |
| ASR + 对齐 + diarization | WhisperX | https://github.com/m-bain/whisperX | ASR、词级时间戳、speaker diarization 串联 | diarization 仍需复核 |
| VAD | Silero VAD | https://github.com/snakers4/silero-vad | 语音活动检测 | 适合前置切段和静音过滤 |
| 说话人分离 | pyannote.audio | https://github.com/pyannote/pyannote-audio | 本地 diarization pipeline、speaker turns | 需要关注 Hugging Face token、模型条款 |
| 说话人识别/多模态 | 3D-Speaker | https://github.com/modelscope/3D-Speaker | speaker verification、recognition、diarization，含音频/视频 recipes | 更偏研究/工具包，需要工程封装 |
| Active Speaker Detection | TalkNet-ASD | https://github.com/TaoRuijie/TalkNet-ASD | 判断画面中哪张脸在说话 | 用于视频侧增强，不替代人工角色确认 |
| Target ASD | TS-TalkNet | https://github.com/Jiang-Yidi/TS-TalkNet | 结合目标 speaker embedding 的 active speaker detection | 研究项目，工程化成本更高 |
| 人声分离 | Ultimate Vocal Remover GUI | https://github.com/Anjok07/ultimatevocalremovergui | 集成多种 vocal remover/source separation 模型 | GUI 项目，服务化需额外封装 |
| 人声分离 | Demucs | https://github.com/facebookresearch/demucs | 音乐源分离，可分离 vocals/background | 原 Meta 仓库已归档，不应作为长期唯一依赖 |
| 翻译 | NLLB / fairseq branch | https://github.com/facebookresearch/fairseq/tree/nllb | 200+ 语言机器翻译模型和资料 | fairseq 仓库已归档；NLLB 模型 license 需核验 |
| 翻译 | OPUS-MT | https://github.com/Helsinki-NLP/Opus-MT | 开源翻译模型和服务 | 语言对覆盖不均，需按目标语种评估 |
| Speech translation | Seamless Communication | https://github.com/facebookresearch/seamless_communication | speech/text translation、S2ST、ASR | 适合研究和端到端方案评估 |
| TTS / voice clone | OpenVoice | https://github.com/myshell-ai/OpenVoice | instant voice cloning、跨语种音色克隆 | 关注语言覆盖和音色相似度 |
| TTS / voice clone | CosyVoice | https://github.com/FunAudioLLM/CosyVoice | 多语种/跨语种 zero-shot voice cloning | 中文和多语种场景可重点评估 |
| TTS / voice clone | F5-TTS | https://github.com/SWivid/F5-TTS | flow matching TTS | 适合评估自然度和推理成本 |
| TTS / few-shot | GPT-SoVITS | https://github.com/RVC-Boss/GPT-SoVITS | zero-shot/few-shot TTS、WebUI 工具 | 中文生态强，服务化需治理参数和队列 |
| 变速/变调 | Rubber Band | https://github.com/breakfastquay/rubberband | time-stretching、pitch-shifting | GPL/商业授权要提前确认 |

### 7.3 MVP 组合建议

如果目标是先做可验证 MVP，可从以下组合开始：

```text
FFmpeg
  + faster-whisper 或 WhisperX
  + pyannote.audio
  + UVR 或 Demucs
  + OpenVoice / CosyVoice / GPT-SoVITS 中选一个
  + Rubber Band
  + JSON/SQLite 任务表
```

MVP 不要求每个环节最优，但必须做到：

- 每个中间产物可落盘。
- 每条配音可追溯到 `task_id`。
- 每个 `speaker_id` 有 reference 记录。
- 每个失败项能返回对应步骤。

## 8. 质量门禁与返工规则

质量门禁分两类：

```text
自动门禁：用脚本或报告字段判定 pass / fail。
人工门禁：由审核人判定，但必须写入 pass / fail、reason_code、target_step。
```

推荐默认门禁：

| 门禁 | 判定方式 | 失败输出 |
|---|---|---|
| 时间戳 | 所有 `source_start_ms < source_end_ms`，任务按时间递增 | `reason_code=invalid_timeline` |
| speaker 绑定 | 每条对白任务有 `speaker_id`、`binding_status`、`render_strategy` | `reason_code=missing_speaker_binding` |
| voice clone reference | `render_strategy=voice_clone` 时必须有可读取 reference 文件 | `reason_code=missing_reference_audio` |
| 文本控长 | `fit_status` 不得为 `text_rework_required` | `reason_code=duration_overflow` |
| TTS 回检 | 对生成音频做 ASR 回检，核心词缺失时失败 | `reason_code=tts_content_mismatch` |
| 对齐 | `aligned_voice.wav` 与原视频时长差异必须在项目阈值内 | `reason_code=duration_mismatch` |
| 混音 | `mix_report.peak_status=pass`，且人工抽检无明显削波或爆音 | `reason_code=mix_quality_failed` |
| 字幕 | 最终 `target.srt` 从最终任务表导出，不使用翻译阶段 draft | `reason_code=subtitle_not_final` |

| 阶段 | 问题 | 检测方式 | 处理动作 |
|---|---|---|---|
| 输入 | MP4 无音轨 | `media_report.audio_streams=0` | 阻断任务 |
| 输入 | 多音轨不确定 | 多条 audio stream | 人工选择目标音轨 |
| ASR | 大段漏识别 | 静音/VAD 与 ASR 片段不匹配 | 回到 ASR 或人工校对 |
| ASR | 时间戳漂移 | 词级对齐偏差大 | 重新对齐或修字幕 |
| 翻译 | 目标文本过长 | 预计 TTS 时长超过时间槽 | 回到翻译控长 |
| 翻译 | 术语/人名不一致 | 术语表检查 | 人工校对 |
| 说话人 | 同一角色多个 speaker | 音色相似但 cluster 分裂 | 合并 speaker 或人工确认 |
| 说话人 | 多角色混成一个 speaker | speaker 内部音色不一致 | 拆分 speaker 或人工确认 |
| Reference | 多人重叠 | `overlap_speech=true` | 重新截取 |
| Reference | 背景污染重 | `music_bleed` 标记 | 人工挑选或降级为不可自动克隆 |
| TTS | 漏词/错词 | 文本和识别回检不一致 | 重生成或改写文本 |
| TTS | 音色漂移 | 与 reference 主观或 embedding 差异大 | 更换 reference 或模型参数 |
| 对齐 | TTS 严重超时 | `tts_duration_ms > source_duration_ms` 且超出门限 | 返回翻译或重生成 |
| 混音 | 原声残留明显 | 人工听审或声纹残留检测 | 回到分离/混音 |
| 封装 | 音画不同步 | 抽查关键点 | 重新对齐或封装 |

## 9. 人工复核点

必须人工复核的情况：

- ASR 低置信度片段。
- 人名、品牌名、术语、数字、金额。
- 重叠说话。
- speaker 数量与内容明显不符。
- `speaker_id` 到角色名的自动映射。
- reference audio 被音乐、环境声或其他人声污染。
- TTS 多次漏读、错读、音色漂移。
- 成片中出现明显原声残留或音画不同步。

人工复核输出不得只写“已看过”。必须写入结构化结果：

```json
{
  "task_id": "seg_000042",
  "reviewer": "human",
  "decision": "rework",
  "target_step": "translation",
  "reason": "target text too long for original slot"
}
```

## 10. 验收清单

### 10.1 流程级验收

- `source_audio.wav` 与原视频时长一致。
- `source_segments_reviewed.json` 无倒序时间戳。
- `dubbing_tasks.json` 每条任务都有 `speaker_id`。
- 主要 speaker 都有 `speaker_profiles`。
- 主要 speaker 都有合格 reference 或明确 `rejected` 原因。
- `target_text_adjusted` 已通过控长检查。
- 所有 TTS 片段都有生成状态和时长。
- `aligned_voice.wav` 与原视频时长一致。
- `final_audio.wav` 无削波、无明显音量跳变。
- `final_dubbed.mp4` 可播放，目标音轨存在。

### 10.2 成片级验收

- 主要语义准确，没有大段误译或漏译。
- 角色声音不混乱，同一角色音色稳定。
- 口型或动作节奏没有明显错位。
- 背景音乐、环境声、音效自然保留。
- 原语种人声残留不影响观看。
- 字幕与配音内容一致。
- 所有失败项都能定位到 `task_id` 或时间段。

## 11. 最小可落地版本

最小版本不需要一次性解决所有高难度问题，但必须具备以下能力：

```text
1. 单 MP4 输入校验
2. 音轨抽取
3. ASR 生成源字幕
4. diarization 生成 speaker_id
5. dubbing_tasks 落盘
6. 人工修正字幕和 speaker
7. reference audio 人工确认
8. 翻译和控长
9. TTS 生成
10. 时间轴对齐
11. 背景混音
12. MP4 封装
13. qa_report 输出
```

这个版本的关键不是“全自动”，而是每一步都能解释、能复核、能返工。只有先把工件和质量门禁做扎实，后续替换更强的 ASR、diarization、TTS 或翻译模型才不会破坏整条流程。
