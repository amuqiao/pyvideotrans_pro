# AI 配音流程与数据结构

> 本文负责说明 AI 配音流水线中每一步的输入、输出、交接对象和关键数据字段，让读者知道为什么应使用统一任务表，而不是让每个环节直接操作 SRT。

## 文档定位

这是一份流程扫盲文档，承接 [AI配音新手总览.md](AI配音新手总览.md)。

如果你还不清楚 `speaker_id`、`reference_audio`、`tts_audio`、`vocals` 和 `background` 的区别，先读总览。工具路线和资料链接见 [AI配音工具选型与资料索引.md](AI配音工具选型与资料索引.md)。

## 核心原则

AI 配音流程应围绕一张中间任务表推进。

```text
SRT 负责字幕表达
dubbing_tasks 负责流程状态
音频文件负责媒体资产
MP4 负责最终封装
```

如果每一步都直接改 SRT，后续很难追踪说话人、音色参考、生成音频、时长误差和处理状态。统一任务表可以把“每条字幕的生产状态”固定下来。

## `dubbing_tasks` 主表

推荐把每条字幕转成一条任务记录。

|字段|说明|
|---|---|
|`index`|字幕序号，用于对齐源 SRT、翻译 SRT 和处理结果|
|`source_start / source_end`|源字幕时间|
|`target_start / target_end`|目标配音时间预算，通常先沿用翻译 SRT 时间|
|`source_text`|源语种文本|
|`target_text_raw`|原始翻译文本|
|`target_text_adjusted`|为 TTS 控长、断句、规范术语后的文本|
|`speaker_id`|说话人识别结果|
|`speaker_name`|可选，说话人展示名|
|`reference_audio`|当前任务使用的音色参考文件|
|`reference_text`|reference audio 对应文本，部分 TTS 模型需要|
|`tts_audio`|TTS 原始生成片段|
|`aligned_tts_audio`|对齐、补静音或轻度变速后的片段，用于最终混音|
|`slot_duration`|目标时间槽时长|
|`tts_duration`|实际生成音频时长|
|`speed_factor`|后处理变速比例|
|`status`|当前任务状态，例如 `ok`、`needs_rewrite`、`needs_regen`、`too_long`|

这张表的价值在于：每一步都只更新自己负责的字段，下一步从稳定字段继续处理。

## 流程一：字幕对齐成任务表

输入：

- 源语种 SRT
- 翻译后 SRT

输出：

- 初始化后的 `dubbing_tasks`

关键动作：

1. 按 `index` 对齐源字幕和翻译字幕。
2. 写入 `source_start / source_end`、`target_start / target_end`。
3. 写入 `source_text` 和 `target_text_raw`。
4. 计算 `slot_duration`。

这一阶段先不急着改写文本。它的任务是把“字幕文件”变成“可被后续环节处理的任务记录”。

## 流程二：说话人识别

输入：

- 源 SRT
- MP4 或抽取后的音频
- 初始化后的 `dubbing_tasks`

输出：

- 写回 `speaker_id`
- 可选写回 `speaker_name`

关键动作：

1. 对源字幕行做说话人归属。
2. 按 `index` 把识别结果写回任务表。
3. 形成 speaker registry，记录角色、首次出现时间和字幕数量等信息。

这里要注意：`speaker_id` 只表达归属，不表达音色质量。它只是后续选择 reference audio 的依据。

## 流程三：翻译文本控长

输入：

- `target_text_raw`
- `slot_duration`
- 可选的角色、语气和术语约束

输出：

- `target_text_adjusted`
- 可选更新 `status`

关键动作：

1. 根据时间槽估算目标文本是否过长。
2. 对明显超预算的句子做压缩改写。
3. 保留关键事实、否定、数字、称谓、语气和专名。
4. 不随意改变字幕 `index`。

这一阶段的目标不是重新翻译，而是让翻译文本适合 TTS。越早控制长度，后面越少依赖大比例变速。

## 流程四：音轨分离

输入：

- 原始 MP4

输出：

- `vocals.wav`
- `background.wav`

关键动作：

1. 从 MP4 抽取音轨。
2. 分离人声和背景声。
3. 统一中间音频格式和采样率。

`vocals.wav` 主要服务 reference audio 截取和清理；`background.wav` 服务最终混音。不要把二者混成同一个资产。

## 流程五：Reference Audio 处理

输入：

- `vocals.wav`
- `speaker_id`
- 源字幕时间轴

输出：

- `reference_audio`
- 可选 `reference_text`

关键动作：

1. 按 speaker 聚合同一角色的干净片段。
2. 裁掉首尾静音。
3. 过滤过短、多人重叠、背景声过重的片段。
4. 做响度归一化和必要的清理。
5. 将可用 reference 写回对应任务。

多角色视频优先使用 speaker-level reference。line-level reference 虽然直观，但短句和噪声会让音色逐句漂移。

## 流程六：音色克隆 TTS

输入：

- `target_text_adjusted`
- `reference_audio`
- 可选 `reference_text`
- 语言、风格、语速参数

输出：

- `tts_audio`
- `tts_duration`

关键动作：

1. 逐条任务生成目标语种音频。
2. 记录生成文件路径。
3. 测量生成音频时长。
4. 将实际时长写回任务表。

TTS 生成完成不等于配音完成。生成结果还必须回到时间轴里检查。

## 流程七：音频对齐后处理

输入：

- `target_start / target_end`
- `slot_duration`
- `tts_audio`
- `tts_duration`

输出：

- 对齐后的配音片段
- `aligned_tts_audio`
- `speed_factor`
- 更新后的 `status`

处理顺序建议：

1. 如果 `tts_duration <= slot_duration`，按 `target_start` 放置，尾部补静音。
2. 如果轻微超出，做轻度 time-stretch。
3. 如果严重超出，回到文本控长并重生成。
4. 如果相邻片段重叠，检查是否需要局部重排或回到文本阶段。

这一阶段不覆盖 `tts_audio`。`tts_audio` 保留 TTS 原始生成结果，`aligned_tts_audio` 记录后处理后的可混音片段，这样后续排查音质、时长和变速问题时可以回看原始生成结果。

不要把所有超时都交给变速。变速是修正手段，不是文本控长的替代品。

## 流程八：混音与视频封装

输入：

- 由 `aligned_tts_audio` 拼接成的目标配音轨
- `background.wav`
- 原始 MP4 画面

输出：

- 最终 dubbed MP4

关键动作：

1. 将对齐后的目标语音合成一条配音轨。
2. 与背景声混音。
3. 做响度统一和必要的背景 ducking。
4. 将最终音频封装回原视频画面。
5. 如果总时长轻微超出，再处理视频尾帧或回到前序环节调整。

## 交接检查

流程文档只负责确认每个阶段是否有稳定交接对象。进入工具选型前，至少检查：

1. `index` 能否稳定连接源字幕、翻译字幕和处理结果。
2. `speaker_id` 是否已经能支撑 reference audio 分配。
3. `target_text_adjusted` 是否已经和时间预算一起检查。
4. `tts_audio` 与 `aligned_tts_audio` 是否分开保存。
5. `background.wav` 是否能和最终目标配音轨混音。

MVP、生产路线、工具选择和阶段风险统一在 [AI配音工具选型与资料索引.md](AI配音工具选型与资料索引.md) 中维护。

## 继续阅读

- 总览入口：[AI配音新手总览.md](AI配音新手总览.md)
- 工具与资料：[AI配音工具选型与资料索引.md](AI配音工具选型与资料索引.md)
- 完整来源报告：[AI 配音全流程调研报告.md](<AI 配音全流程调研报告.md>)
