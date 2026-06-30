# macOS 音频排障

本文用于维护 macOS 源码运行时的音频相关故障，重点覆盖试听、配音渠道懒加载、Python 原生动态库和系统输出设备问题。

## 适用范围

适用于在 macOS 上使用 `uv run sp.py --lang zh` 启动桌面版后，遇到以下问题：

- 选择 Qwen3-TTS、Edge-TTS 等配音渠道后，点击试听没有声音。
- 日志出现 `soundfile`、`libsndfile.dylib`、`PortAudio`、`OutputStream`、`PaErrorCode -9986`。
- 系统声音正常，但 pyvideotrans 的试听播放失败。

本文不处理 TTS 接口鉴权、模型下载、网络连接、字幕生成质量或最终视频合成失败。

## 先理解音频链路

试听声音不是只依赖 TTS 渠道本身。一次试听通常会经过这些层级：

```text
TTS 渠道生成音频
-> Python 读取音频文件
-> soundfile 加载 libsndfile.dylib
-> sounddevice 调用 PortAudio
-> macOS Core Audio 打开输出设备
-> 扬声器或耳机播放
```

因此排障时先判断失败发生在哪一层：

| 现象 | 常见失败层级 | 处理入口 |
|---|---|---|
| `libsndfile.dylib` 找不到 | `soundfile` 原生库 | [修复 libsndfile 加载](#修复-libsndfile-加载) |
| `Error opening OutputStream` | 输出设备 / PortAudio | [修复 PortAudio 输出设备](#修复-portaudio-输出设备) |
| 设备列表为空 | macOS Core Audio 状态 | [刷新 macOS 音频服务](#刷新-macos-音频服务) |
| 只有蓝牙耳机失败 | 蓝牙设备输出流 | [切换到内建扬声器](#切换到内建扬声器) |

## 基础检查

先确认 Python 能正常启动并读取当前音频设备：

```bash
cd /Users/admin/Downloads/pyvideotrans_pro
.venv/bin/python -c "import sounddevice as sd; print(sd.default.device); print(sd.query_devices())"
```

正常输出应至少包含一个输出设备，例如：

```text
[0, 1]
> 0 MacBook Air麦克风, Core Audio (1 in, 0 out)
< 1 MacBook Air扬声器, Core Audio (0 in, 2 out)
```

这里的 `< 1` 表示当前默认输出设备是编号 `1`。设备编号会随系统状态变化，不要长期记死。

## 修复 libsndfile 加载

如果报错包含：

```text
ctypes.util.find_library() did not manage to locate a library called 'sndfile'
cannot load library '_soundfile_data/libsndfile.dylib'
```

先确认 Homebrew 依赖存在：

```bash
brew install libsndfile
```

再检查 `soundfile` 自带的动态库目录：

```bash
ls -la .venv/lib/python3.10/site-packages/_soundfile_data
```

如果目录里存在 `libsndfile_arm64.dylib`，优先补同目录链接：

```bash
ln -sf libsndfile_arm64.dylib .venv/lib/python3.10/site-packages/_soundfile_data/libsndfile.dylib
.venv/bin/python -c "import soundfile as sf; print(sf.__libsndfile_version__)"
```

能输出版本号，例如 `1.2.2`，说明 `soundfile` 已修复。

如果没有 `libsndfile_arm64.dylib`，再链接 Homebrew 的动态库：

```bash
mkdir -p .venv/lib/python3.10/site-packages/_soundfile_data
ln -sf /opt/homebrew/opt/libsndfile/lib/libsndfile.dylib .venv/lib/python3.10/site-packages/_soundfile_data/libsndfile.dylib
.venv/bin/python -c "import soundfile as sf; print(sf.__libsndfile_version__)"
```

临时启动也可以使用：

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib uv run sp.py --lang zh
```

如果已经通过软链接验证成功，平时直接使用：

```bash
uv run sp.py --lang zh
```

## 修复 PortAudio 输出设备

如果报错包含：

```text
Error opening OutputStream: Internal PortAudio error [PaErrorCode -9986]
Audio Unit: Invalid Property Value
```

说明 TTS 音频大概率已经生成，失败点在播放阶段。先查当前输出设备编号：

```bash
.venv/bin/python -c "import sounddevice as sd; print(sd.default.device); print(sd.query_devices())"
```

如果输出类似：

```text
[0, 1]
> 0 MacBook Air麦克风, Core Audio (1 in, 0 out)
< 1 MacBook Air扬声器, Core Audio (0 in, 2 out)
```

用当前输出设备编号测试播放。这里编号是 `1`：

```bash
.venv/bin/python -c "import numpy as np, sounddevice as sd; fs=44100; t=np.arange(fs)/fs; data=(0.1*np.sin(2*np.pi*440*t)).astype('float32'); sd.play(data, fs, device=1); sd.wait()"
```

能听到一秒提示音，说明 Python 播放链路可用。

## 切换到内建扬声器

蓝牙耳机、AirPlay、虚拟声卡有时会让 PortAudio 打开输出流失败。排障时先切到内建扬声器：

1. 打开 macOS `系统设置 -> 声音 -> 输出`。
2. 选择 `MacBook Air扬声器` 或内建扬声器。
3. 输入设备可选择 `MacBook Air麦克风`。
4. 退出 pyvideotrans 后重新启动：

```bash
uv run sp.py --lang zh
```

如果试听在内建扬声器正常，而蓝牙耳机失败，优先把这类问题归为蓝牙输出设备兼容问题。

## 刷新 macOS 音频服务

如果设备列表为空：

```text
[-1, -1]
Core Audio devices: []
```

先退出 pyvideotrans，然后刷新 Core Audio：

```bash
sudo killall coreaudiod
```

再到 `系统设置 -> 声音 -> 输出` 重新选择内建扬声器，并重新检查：

```bash
.venv/bin/python -c "import sounddevice as sd; print(sd.default.device); print(sd.query_devices())"
```

## 维护规则

- 先记录完整错误信息，再判断是 `soundfile/libsndfile` 还是 `sounddevice/PortAudio`。
- 新增案例时优先补充到对应章节，不要把所有错误堆到同一个命令清单。
- 写设备相关命令时，不要固定设备编号；必须提醒读者以 `sd.query_devices()` 当前输出为准。
- 修改 `.venv` 内软链接后，如果删除并重建 `.venv`，需要重新执行链接命令。
