# Linux GPU 远程开发环境安装与运行指南

本文用于长期维护 Linux GPU 服务器上的 `pyvideotrans_pro` 开发环境。它先建立环境心智模型，再给出最小可用安装路径、验证路径、模型缓存检查和常见排查。

## 文档职责

本文解决的问题：

- 判断一台 Linux GPU 服务器是否适合运行本项目。
- 从系统依赖、`uv`、项目依赖、PyTorch CUDA、WebUI 到本机浏览器访问，建立一条可重复执行的安装路径。
- 解释模型缓存、虚拟环境缓存和项目 `models/` 目录的边界。
- 给出常见问题的定位顺序，避免在 CUDA、依赖、端口和模型路径之间来回猜。

本文不解决：

- macOS 本机安装。本文只覆盖 Linux GPU 远程开发服务器。
- Windows 桌面版安装。
- Docker Compose 部署。当前源码部署主流程不依赖 Docker。
- 所有可选 TTS / ASR 渠道的一次性完整安装。长期建议是主流程跑通后按需追加。

## 先理解这套环境

这套环境不是“装一个 Python 包”这么简单。它由多个层次组成，每层出问题时排查入口不同：

```text
本机浏览器
  |
  |  http://127.0.0.1:7860
  v
本机 SSH tunnel
  |
  |  ssh -N -L 7860:127.0.0.1:7860 wangqiao@47.94.108.140
  v
远程服务器 WebUI 进程
  |
  |  CUDA_VISIBLE_DEVICES=0 uv run --extra webui webui.py --host 127.0.0.1 --port 7860
  v
项目虚拟环境 .venv
  |
  |  pyproject.toml / uv.lock / torch 2.7.1+cu128 / gradio
  v
GPU 与模型文件
  |
  |  NVIDIA Driver / PyTorch CUDA runtime / faster-whisper
  v
项目 models/ 模型缓存
```

排查时按层级看：

```text
命令找不到 -> shell PATH / uv 是否安装
包找不到   -> uv extra 是否安装，例如 webui -> gradio
CUDA 不可用 -> torch build / driver / CUDA_VISIBLE_DEVICES / 具体 CUDA 错误
页面打不开 -> WebUI 是否启动 / SSH tunnel 是否保持 / 本机端口是否冲突
模型找不到 -> 项目 models/ 路径 / model.bin 是否存在且非空
磁盘爆满   -> .venv、uv cache、项目 models/ 是否都在 /data
```

推荐路径是先跑通最小闭环：

```text
只读检查
  -> 配置 uv 和缓存目录
    -> uv sync --extra webui
      -> 验证 torch.cuda.is_available()
        -> 启动 WebUI
          -> SSH tunnel 本机访问
            -> 再按需追加其他 extra 或大模型
```

不要一开始执行 `uv sync --all-extras`。`all-extras` 会把 qwen、moss、chatterbox、dotnet/pythonnet 等可选依赖一次性拉进来，下载、编译和版本冲突风险都更高。

## 当前服务器结论

当前文档记录的服务器是：

| 项 | 值 |
|---|---|
| 服务器 | `ALY-BJ-chapter-ai-train-01` |
| SSH 地址 | `47.94.108.140` |
| 用户 | `wangqiao` |
| 项目目录 | `/data/wangqiao/pyvideotrans_pro` |
| 推荐入口 | 远程跑 WebUI / CLI，本机通过 SSH tunnel 访问 |

已验证结果：

| 检查项 | 当前结果 | 结论 |
|---|---:|---|
| OS | Ubuntu 22.04.5 LTS | OK |
| 架构 | x86_64 | OK |
| GPU | 2 x NVIDIA A10，每张约 23 GiB | 硬件 OK |
| NVIDIA Driver | 550.127.08 | 已实测可跑当前 PyTorch cu128 |
| `nvidia-smi` CUDA Version | 12.4 | 这是驱动支持信息，不等于本机必须安装 CUDA Toolkit 12.8 |
| Python | 3.10.12 | OK，项目要求 `>=3.10,<3.11` |
| `uv` | 0.11.25 | OK，安装在 `$HOME/.local/bin` |
| PyTorch | 2.7.1+cu128 | OK，`torch.cuda.is_available() == True` |
| `/` 磁盘 | 30G 可用 | 不放模型和虚拟环境 |
| `/data` 磁盘 | 302G 可用，已用 85% | 可用，但要控缓存和输出 |
| PyPI 网络 | HTTP 200 | OK |

关键判断：

```text
项目在 Linux 上通过 pyproject.toml / uv 使用 torch 2.7.1 + cu128。
当前 nvidia-smi 显示 CUDA Version 12.4，但 PyTorch cu128 已实测可用。
因此当前可继续使用 GPU + WebUI 最小依赖路线。
```

`nvidia-smi` 的 CUDA Version 是驱动支持信息，不是 PyTorch wheel 内置 CUDA runtime 的版本。只有在出现明确的 CUDA driver / initialization error，或 `torch.cuda.is_available()` 变成 `False` 时，才需要进一步评估驱动升级。

## 主流程：从服务器检查到 WebUI 可访问

### 1. 做只读检查

如果项目代码已经在服务器上，这个脚本是首选只读检查入口：

```bash
cd /data/wangqiao/pyvideotrans_pro
bash scripts/check_server_env.sh
```

如果还没有获取代码，先手动确认这些基础信息；获取代码后再运行上面的脚本：

```bash
cat /etc/os-release | head -5
uname -m
nvidia-smi
nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv
python3 --version
uv --version
df -h / /data
free -h
```

### 2. 准备工作目录

不要把虚拟环境、模型和缓存放到根分区：

```bash
mkdir -p /data/wangqiao
cd /data/wangqiao
pwd
df -h / /data
```

### 3. 检查系统依赖

先检查：

```bash
command -v ffmpeg || true
command -v ffprobe || true
ldconfig -p | grep -E 'libsndfile|libGL|libglib' || true
git --version
curl --version
```

缺失时再安装：

```bash
sudo apt update
sudo apt install -y ffmpeg libsndfile1 libgl1 libglib2.0-0 git curl
```

安装后复查：

```bash
ffmpeg -version | head -3
ffprobe -version | head -3
```

### 4. 安装并配置 uv

先检查：

```bash
uv --version
```

如果提示 `command not found`，再安装：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

当前服务器上 `uv` 安装在 `$HOME/.local/bin`。如果 shell 是 bash，写入 `~/.bashrc`：

```bash
cat >> ~/.bashrc <<'EOF'

# uv and user-local tools
export PATH="$HOME/.local/bin:$PATH"
EOF
source ~/.bashrc
uv --version
```

如果 shell 是 zsh，才写 `~/.zshrc`：

```bash
cat >> ~/.zshrc <<'EOF'

# uv and user-local tools
export PATH="$HOME/.local/bin:$PATH"
EOF
source ~/.zshrc
uv --version
```

判断当前 shell：

```bash
echo "$SHELL"
ps -p $$ -o comm=
```

### 5. 把缓存放到 /data

`uv` 的包缓存建议放到 `/data`，避免根分区被 wheel 和构建缓存占满。当前服务器 shell 是 bash，所以示例写入 `~/.bashrc`：

```bash
cat >> ~/.bashrc <<'EOF'

# pyvideotrans remote dev cache
export UV_CACHE_DIR=/data/wangqiao/.uv-cache
export XDG_CACHE_HOME=/data/wangqiao/.cache
EOF
source ~/.bashrc
mkdir -p "$UV_CACHE_DIR" "$XDG_CACHE_HOME"
echo "$UV_CACHE_DIR"
echo "$XDG_CACHE_HOME"
```

如果当前 shell 是 zsh，把同样的 `export` 写入 `~/.zshrc` 并执行 `source ~/.zshrc`。

注意：项目里的 faster-whisper 等模型下载路径以项目根目录 `models/` 为主，不应只看 `HF_HOME`。只要项目目录在 `/data/wangqiao/pyvideotrans_pro`，项目模型也会落在 `/data` 下。

### 6. 获取代码

如果服务器能直接访问仓库：

```bash
cd /data/wangqiao
git clone <本项目仓库地址> pyvideotrans_pro
cd pyvideotrans_pro
```

如果代码从本机上传，建议上传到：

```text
/data/wangqiao/pyvideotrans_pro
```

进入项目后检查：

```bash
pwd
ls -la pyproject.toml uv.lock
python3 --version
uv --version
```

确认项目 Python 和 PyTorch 源配置：

```bash
grep -n 'requires-python' pyproject.toml
grep -n 'pytorch-cu128' -A6 pyproject.toml
```

期望看到：

```text
requires-python = ">=3.10, <3.11"
url = "https://download.pytorch.org/whl/cu128"
```

### 7. 安装项目依赖

最小可用集是主依赖 + WebUI extra：

```bash
cd /data/wangqiao/pyvideotrans_pro
uv sync --extra webui
```

这里的 `--extra webui` 不是排除 WebUI，而是额外安装 WebUI 所需依赖。项目里：

```text
uv sync                -> 主依赖
uv sync --extra webui  -> 主依赖 + WebUI 依赖 gradio
```

`gradio-client` 是主依赖里的客户端包，不等于 WebUI 运行所需的 `gradio`。

### 8. 验证 PyTorch CUDA

```bash
CUDA_VISIBLE_DEVICES=0 uv run python - <<'PY'
import torch

print("torch:", torch.__version__)
print("torch cuda build:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
print("gpu count:", torch.cuda.device_count())
if torch.cuda.is_available():
    print("gpu 0:", torch.cuda.get_device_name(0))
PY
```

期望：

```text
torch: 2.7.1+cu128
torch cuda build: 12.8
cuda available: True
gpu 0: NVIDIA A10
```

如果第一次运行验证命令时看到 `Preparing packages... torch ...`，通常是 `uv run` 在补齐缺失包或完成上一次未完成的下载。等它跑完后再重复执行一次验证命令。

### 9. 启动 WebUI

优先确认 GPU 0 空闲：

```bash
nvidia-smi
```

启动：

```bash
cd /data/wangqiao/pyvideotrans_pro
uv run --extra webui python -c "import gradio as gr; print(gr.__version__)"
CUDA_VISIBLE_DEVICES=0 uv run --extra webui webui.py --host 127.0.0.1 --port 7860
```

这个服务器窗口保持打开。需要停止 WebUI 时，在这个窗口按 `Ctrl+C`。

另开一个服务器窗口时，可以检查 WebUI 是否还在：

```bash
ps -ef | grep -E 'webui.py|gradio' | grep -v grep
```

### 10. 本机浏览器访问 WebUI

在本机另开终端，建立 SSH tunnel：

```bash
ssh -N -L 7860:127.0.0.1:7860 wangqiao@47.94.108.140
```

保持 SSH 不关，本机浏览器打开：

```text
http://127.0.0.1:7860
```

如果本机 `7860` 已被占用，换成本机 `7861` 转发到服务器 `7860`：

```bash
ssh -N -L 7861:127.0.0.1:7860 wangqiao@47.94.108.140
```

然后打开：

```text
http://127.0.0.1:7861
```

默认不推荐直接暴露 `0.0.0.0`。如果确实必须让局域网直接访问，才考虑：

```bash
CUDA_VISIBLE_DEVICES=0 uv run --extra webui webui.py --host 0.0.0.0 --port 7860
```

## 可选流程

### 按需追加 extra

主流程跑通后，需要哪个本地可选渠道再追加哪个：

```bash
uv sync --extra webui --extra qwentts
uv sync --extra webui --extra qwenasr
uv sync --extra webui --extra mosstts
uv sync --extra webui --extra chatterbox
```

注意保留 `--extra webui`。`uv sync` 会让 `.venv` 对齐当前声明的依赖集合；如果之前装过某个 extra，后续 sync 时要把仍需保留的 extra 都写上。

### CLI 验证与批处理

查看可用配置：

```bash
uv run cli.py --list providers
uv run cli.py --list languages
uv run cli.py --list models
```

GPU 识别测试：

```bash
CUDA_VISIBLE_DEVICES=0 uv run cli.py --task stt --name "/data/wangqiao/demo.mp4" --model_name base --cuda
```

完整视频翻译示例：

```bash
CUDA_VISIBLE_DEVICES=0 uv run cli.py --task vtv --name "/data/wangqiao/demo.mp4" \
  --source_language_code zh-cn \
  --target_language_code en \
  --voice_role "en-US-GuyNeural" \
  --cuda
```

### 为什么不推荐服务器运行桌面版 sp.py

`sp.py` 是 PySide6 桌面程序，需要图形显示。服务器是 headless，X11/VNC 转发视频预览体验差，也会增加排障成本。

远端服务器推荐：

```text
WebUI：交互使用
CLI：批处理
```

## 模型与缓存

### 三类目录不要混淆

```text
.venv
  项目虚拟环境，通常在项目目录下

UV_CACHE_DIR
  uv 下载和构建缓存，建议放 /data/wangqiao/.uv-cache

项目 models/
  本项目模型缓存目录，例如 faster-whisper、部分 onnx 模型
```

`HF_HOME` 可以作为通用 Hugging Face 缓存认知，但本项目运行时会把项目模型下载到 `ROOT_DIR/models`。因此排查 faster-whisper 时优先看：

```text
/data/wangqiao/pyvideotrans_pro/models
```

### large-v3-turbo 路径

项目当前模型映射：

```text
large-v3-turbo -> mobiuslabsgmbh/faster-whisper-large-v3-turbo
```

项目内缓存目录：

```text
/data/wangqiao/pyvideotrans_pro/models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo
```

外部 Hugging Face 页面可能重定向到 `dropbox-dash/faster-whisper-large-v3-turbo`，但项目内目录仍按当前代码里的 `mobiuslabsgmbh` 名称生成。

### 检查模型是否已下载

在服务器上执行：

```bash
cd /data/wangqiao/pyvideotrans_pro
find models -maxdepth 2 -iname '*large-v3-turbo*' -print
ls -lh models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo
du -sh models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo
```

重点确认目录内存在：

```text
model.bin
config.json
tokenizer.json
vocabulary.json
preprocessor_config.json
```

快速判断 `model.bin` 是否存在且非空：

```bash
test -s models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/model.bin && echo "large-v3-turbo 已下载" || echo "large-v3-turbo 未完整下载"
```

也可以从本机直接查服务器：

```bash
ssh wangqiao@47.94.108.140 'cd /data/wangqiao/pyvideotrans_pro && ls -lh models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo && du -sh models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo'
```

## 验证清单

安装完成后最小验证：

```bash
cd /data/wangqiao/pyvideotrans_pro
uv run --extra webui python -c "import gradio as gr; print(gr.__version__)"
CUDA_VISIBLE_DEVICES=0 uv run python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

WebUI 进程验证：

```bash
ps -ef | grep -E 'webui.py|gradio' | grep -v grep
```

本机访问验证：

```text
http://127.0.0.1:7860
```

CLI 验证：

```bash
uv run cli.py --list models
CUDA_VISIBLE_DEVICES=0 uv run cli.py --task stt --name "/data/wangqiao/demo.mp4" --model_name base --cuda
```

磁盘与缓存验证：

```bash
df -h / /data
du -h -d 1 /data/wangqiao 2>/dev/null | sort -h | tail
du -sh /data/wangqiao/pyvideotrans_pro/.venv 2>/dev/null || true
du -sh /data/wangqiao/pyvideotrans_pro/models 2>/dev/null || true
du -sh "$UV_CACHE_DIR" 2>/dev/null || true
```

## 常见排查

### `uv: command not found`

检查：

```bash
ls -la "$HOME/.local/bin/uv"
echo "$PATH"
echo "$SHELL"
ps -p $$ -o comm=
```

如果 `uv` 已安装在 `$HOME/.local/bin/uv`，处理 PATH 即可，不要按 Ubuntu 提示执行 `sudo snap install astral-uv`。

### `ModuleNotFoundError: No module named 'gradio'`

原因是当前环境没有安装 `webui` extra。

处理：

```bash
cd /data/wangqiao/pyvideotrans_pro
uv sync --extra webui
uv run --extra webui python -c "import gradio as gr; print(gr.__version__)"
CUDA_VISIBLE_DEVICES=0 uv run --extra webui webui.py --host 127.0.0.1 --port 7860
```

### `torch.cuda.is_available()` 是 `False`

先看三件事：

```bash
nvidia-smi
CUDA_VISIBLE_DEVICES=0 uv run python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
CUDA_VISIBLE_DEVICES=0 uv run python -c "import torch; print(torch.cuda.device_count())"
```

如果只是 `nvidia-smi` 显示 CUDA Version `12.4`，这本身不是问题。要结合具体 PyTorch 输出和 CUDA initialization / driver error 判断。当前服务器已实测 `torch 2.7.1+cu128` 可用。

### 显存不足

先看占用：

```bash
nvidia-smi
```

当前记录里 GPU 1 曾占用约 19G，优先用 GPU 0：

```bash
CUDA_VISIBLE_DEVICES=0 uv run python -c "import torch; print(torch.cuda.get_device_name(0))"
```

必要时换小模型，例如 `base`，确认流程跑通后再换 `large-v3-turbo`。

### 本机打不开 WebUI

按顺序检查：

```text
1. 服务器 WebUI 进程是否还在
2. WebUI 是否监听 127.0.0.1:7860
3. 本机 SSH tunnel 终端是否保持打开
4. 本机 7860 是否被其他程序占用
5. 是否需要改用本机 7861 转发到服务器 7860
```

命令：

```bash
ssh -N -L 7861:127.0.0.1:7860 wangqiao@47.94.108.140
```

打开：

```text
http://127.0.0.1:7861
```

### 根分区快满

检查：

```bash
df -h / /data
du -h -d 1 "$HOME/.cache" 2>/dev/null | sort -h | tail
du -h -d 1 /data/wangqiao 2>/dev/null | sort -h | tail
du -sh /data/wangqiao/pyvideotrans_pro/.venv 2>/dev/null || true
du -sh /data/wangqiao/pyvideotrans_pro/models 2>/dev/null || true
```

重点确认 `.venv`、`models/`、`UV_CACHE_DIR` 都在 `/data` 路径下。

### `docker compose` 不可用

当前源码部署主流程不依赖 Docker，可以先忽略。后续如果要走容器部署，再单独补 Docker Compose plugin。

## 维护规则

维护本文时优先遵守：

- 新增问题先放到对应层级：系统、uv、项目依赖、CUDA/GPU、WebUI 访问、模型缓存、磁盘。
- 主流程只保留最小可用路径，不把所有可选 extra 混进主流程。
- 每个新增命令要说明它是只读检查、安装动作、启动动作还是排错动作。
- 如果服务器 IP、用户名、GPU 或目录发生变化，先更新“当前服务器结论”和 SSH tunnel 命令。
- 如果项目依赖声明变化，先检查 `pyproject.toml` 和 `uv.lock`，再更新本文命令。
