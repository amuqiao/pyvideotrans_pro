# AI 配音工具选型与资料索引

> 本文负责把 AI 配音各阶段涉及的工具、模型、API 和资料链接整理成新手可查的索引，帮助读者知道每类资料先读什么、用来解决什么问题。

## 文档定位

这是一份资料索引和选型扫盲文档。

阅读顺序建议：

1. 先读 [AI配音新手总览.md](AI配音新手总览.md)，建立整体对象。
2. 再读 [AI配音流程与数据结构.md](AI配音流程与数据结构.md)，理解流程交接。
3. 最后用本文按阶段查资料。

完整调研来源见 [AI 配音全流程调研报告.md](<AI 配音全流程调研报告.md>)。

## 阶段选型总览

|阶段|本地开源路线|API 路线|优先判断|
|---|---|---|---|
|字幕控长|规则 + LLM|LLM API|优先解决明显超长句，收益高、成本低|
|人声分离|Demucs / UVR / MDX-Net|LALAL.AI / ElevenLabs Audio Isolation|有本地算力可先本地；重视接入速度可用 API|
|说话人识别|pyannote / ECAPA|已有说话人识别 API|优先使用能直接输出字幕行级 `speaker_id` 的能力|
|Reference 处理|VAD / FFmpeg / speaker embedding|forced alignment API|核心是干净、一致、长度合适，不是堆更多音频|
|音色克隆 TTS|F5-TTS / CosyVoice2 / GPT-SoVITS / Fish Speech / OpenVoice|ElevenLabs / Fish Audio / Azure / Cartesia|MVP 可先验证效果；长期看成本、隐私和授权|
|对齐后处理|FFmpeg / Rubber Band / MFA / WhisperX|ElevenLabs Forced Alignment|轻度变速可以，严重超时应回到文本控长|
|视频修复|freeze frame / Wav2Lip|商业 lip-sync / dubbing 服务|没有强口型要求时先不把 lip-sync 作为主路径|

## 关键风险

1. 翻译文本没有控长，TTS 生成后只能强行变速，音质和自然度都会受损。
2. 人声分离残留背景声，会污染 reference audio。
3. 多人重叠会影响说话人识别和 reference 质量。
4. line-level reference 太短，容易导致逐句音色漂移。
5. global reference 只适合单人视频，多角色视频会混合角色音色。
6. TTS 生成音频与视频时间轴存在天然差异，必须做对齐和质量检查。
7. 普通 TTS、音色克隆 TTS、voice conversion 和端到端 dubbing API 是不同能力，不应混为一类。

## 资料索引

### 1. 字幕控长与配音同步

推荐先读：[Jointly Optimizing Translations and Speech Timing to Improve Isochrony in Automatic Dubbing](https://arxiv.org/abs/2302.12979)

用途：理解“翻译文本”和“语音时长”为什么要一起优化，这是配音同步的核心问题。

- [Controlling the Output Length of Neural Machine Translation](https://arxiv.org/abs/1910.10408)：理解翻译输出长度控制，帮助减少 TTS 超时长。
- [SubER: A Metric for Automatic Evaluation of Subtitle Quality](https://arxiv.org/abs/2205.05805)：理解字幕文本、断句和 timing 如何一起影响字幕质量。
- [Direct Speech Translation for Automatic Subtitling](https://arxiv.org/abs/2209.13192)：理解自动字幕系统中的翻译、分段、时间戳和显示约束。

### 2. 音轨分离与人声清理

推荐先读：[Demucs GitHub](https://github.com/facebookresearch/demucs)

用途：最快了解本地人声和背景音分离工具的安装、模型和使用入口。

- [Demucs: Deep Extractor for Music Sources with extra unlabeled data remixed](https://arxiv.org/abs/1909.01174)：了解 Demucs 早期模型原理。
- [Hybrid Spectrogram and Waveform Source Separation](https://arxiv.org/abs/2111.03600)：理解频谱和波形混合建模的分离路线。
- [Hybrid Transformers for Music Source Separation](https://arxiv.org/abs/2211.08553)：理解 HTDemucs 的 Transformer 分离方案。
- [LALAL.AI API](https://www.lalal.ai/api/)：查看云端 stem splitting、降噪和人声清理能力。
- [ElevenLabs Audio Isolation](https://elevenlabs.io/docs/api-reference/audio-isolation)：查看云端音频隔离和 reference audio 清理能力。

### 3. 说话人识别

推荐先读：[pyannote.audio: neural building blocks for speaker diarization](https://arxiv.org/abs/1911.01255)

用途：理解 speaker diarization 如何把音频片段分配给不同说话人，这是生成 `speaker_id` 的主问题。

- [ECAPA-TDNN](https://arxiv.org/abs/2005.07143)：理解 speaker embedding 和 speaker verification，用于校验 reference 是否同一人。

### 4. VAD 与强制对齐

推荐先读：[WhisperX](https://arxiv.org/abs/2303.00747)

用途：理解 word-level timestamps 和 forced alignment，适合做配音时间轴 QA，不负责直接生成 `speaker_id`。

- [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/en/latest/)：查看更严格的音素或词级强制对齐工具。
- [aeneas](https://github.com/readbeyond/aeneas)：查看完整文本与音频同步工具。
- [ElevenLabs Forced Alignment](https://elevenlabs.io/docs/api-reference/forced-alignment)：查看厂商 API 的 character 和 word timing 能力。
- [Tradition or Innovation: A Comparison of Modern ASR Methods for Forced Alignment](https://arxiv.org/abs/2406.19363)：比较现代 ASR 方法在 forced alignment 上的表现。

### 5. 开源音色克隆与 TTS 模型

推荐先读：[F5-TTS](https://arxiv.org/abs/2410.06885)

用途：先理解 zero-shot TTS、reference audio 和语速控制的基本路线。

- [CosyVoice](https://arxiv.org/abs/2407.05407)：了解多语言 zero-shot TTS，尤其适合中文和多语言场景。
- [CosyVoice2](https://arxiv.org/abs/2412.10117)：了解 streaming、低延迟和大规模多语言 TTS 改进。
- [OpenVoice](https://arxiv.org/abs/2312.01479)：了解短音频 instant voice cloning 和跨语言风格控制。
- [Fish Speech](https://arxiv.org/abs/2411.01156)：了解 FishAudio 开源多语言 TTS 和 voice cloning 模型。
- [Fish Audio S2 Technical Report](https://arxiv.org/abs/2603.08823)：了解 Fish Audio S2 的 multi-speaker、instruction control 和 streaming 能力。
- [Fish Speech GitHub](https://github.com/fishaudio/fish-speech)：查看 Fish Speech 开源代码、权重和推理工程入口。

### 6. 云端 TTS 与音色克隆 API

推荐先读：[ElevenLabs IVC](https://elevenlabs.io/docs/api-reference/voices/add)

用途：理解云端 instant voice clone 的接口形态，和端到端 dubbing API 区分开。

- [Fish Audio](https://fish.audio/)：查看 FishAudio 云端 TTS、voice cloning 和多语言 voiceover 能力。
- [Azure Custom Neural Voice](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/custom-neural-voice)：理解企业级 custom voice 的授权、录音样本、训练和部署流程。
- [Cartesia Clone Voice](https://docs.cartesia.ai/api-reference/voices/clone)：查看通过 API 创建并复用 voice clone 的接口。
- [OpenAI Text-to-Speech](https://platform.openai.com/docs/guides/text-to-speech)：用于不做原声克隆时的稳定可控 TTS。

### 7. 端到端配音 API

推荐先读：[ElevenLabs Dubbing](https://elevenlabs.io/docs/api-reference/dubbing/create)

用途：了解最接近端到端视频或音频 dubbing 的 API 入口。它和单独的 TTS、voice clone、forced alignment API 不是同一层能力。

### 8. 音频变速与时间轴后处理

推荐先读：[FFmpeg atempo](https://ffmpeg.org/ffmpeg-filters.html#atempo)

用途：了解最基础、最容易接入的音频 tempo 调整工具。

- [Rubber Band Library](https://breakfastquay.com/rubberband/)：查看更高质量的 time-stretch 和 pitch-shift 工具。

### 9. 视频口型与画面修复

推荐先读：[Wav2Lip](https://arxiv.org/abs/2008.10010)

用途：理解配音后口型修复的基础方案。

- [Diff2Lip](https://arxiv.org/abs/2308.09716)：了解扩散模型路线的 lip-sync 视频质量改进。

## 使用本文的判断方式

新手不要从模型名开始选型。更稳的判断顺序是：

1. 先确定当前卡在哪个流程阶段。
2. 再判断问题是文本、音频、说话人、TTS、对齐还是封装。
3. 最后只查看对应阶段的资料。

如果问题是“整条链路怎么运转”，回到 [AI配音流程与数据结构.md](AI配音流程与数据结构.md)。如果问题是“这个主题到底是什么”，回到 [AI配音新手总览.md](AI配音新手总览.md)。
