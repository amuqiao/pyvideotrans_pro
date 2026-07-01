# Linux GPU 开发环境安装检查与部署

本文用于在 Linux GPU 服务器上安装并运行本项目，重点是**先检查版本和容量，再决定安装路线**，避免一上来直接安装后才发现 CUDA、磁盘或 Python 环境不匹配。

- **目标服务器**：`ALY-BJ-chapter-ai-train-01`
- **当前用户**：`wangqiao`
- **建议工作目录**：`/data/wangqiao/pyvideotrans_pro`
- **推荐入口**：远程服务器跑 WebUI / CLI，本机浏览器或 SSH 隧道访问
- **不适用于**：macOS 本机安装，见 [环境安装](环境安装.md)

## 当前结论

根据 `check_server_env.sh` 和后续 PyTorch 验证结果，这台机器可以继续走 GPU 开发环境路线。注意：`nvidia-smi` 显示的 CUDA Version 是驱动支持信息，不等于必须本机安装 CUDA Toolkit 12.8；本项目通过 PyTorch wheel 使用 CUDA runtime。

| 检查项 | 当前结果 | 结论 |
|---|---:|---|
| OS | Ubuntu 22.04.5 LTS | OK |
| 架构 | x86_64 | OK |
| GPU | 2 x NVIDIA A10, 每张约 23 GiB | 硬件 OK |
| NVIDIA Driver | 550.127.08 | 已实测可跑当前 PyTorch cu128 |
| `nvidia-smi` CUDA Version | 12.4 | 低于 cu128，但 PyTorch 实测通过 |
| Python | 3.10.12 | OK，项目要求 `>=3.10,<3.11` |
| `uv` | 0.11.25 | OK，安装在 `$HOME/.local/bin` |
| PyTorch | 2.7.1+cu128 | OK，`torch.cuda.is_available() == True` |
| `/` 磁盘 | 30G 可用 | 不放模型和虚拟环境 |
| `/data` 磁盘 | 302G 可用，已用 85% | 可用，但要控缓存和输出 |
| PyPI 网络 | HTTP 200 | OK |

核心判断：

```text
项目 pyproject.toml 在 Linux 上默认安装 torch 2.7.1 + cu128。
当前服务器 nvidia-smi 显示 CUDA max 12.4，但 torch cu128 已实测可用。
因此：当前可以继续按 GPU + WebUI 最小依赖路线执行。
```

如果后续遇到 CUDA driver / initialization error，再考虑让管理员升级 NVIDIA driver。CUDA 12.8 GA 在 Linux x86_64 上对应的最低驱动是 `570.26`，而当前是 `550.127.08`；但本机当前 PyTorch 验证已通过，所以不需要为当前安装流程立即升级。

参考依据：

- 项目依赖：`pyproject.toml` 的 Linux torch source 指向 `https://download.pytorch.org/whl/cu128`。
- 驱动要求：NVIDIA CUDA Toolkit Release Notes 的 CUDA 12.8 GA driver 表，见 `https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html`。

## 先做只读检查

这些命令只读，不会安装、不改配置，先确认机器状态。

```bash
cd /data/wangqiao
bash check_server_env.sh
```

重点看这些字段：

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

当前服务器应重点确认：

```text
Driver Version: 550.127.08
CUDA Version: 12.4
GPU 0: NVIDIA A10, memory used about 1.5 GiB
GPU 1: NVIDIA A10, memory used about 19 GiB
Python 3.10.12
uv 0.11.25
torch 2.7.1+cu128
torch cuda build: 12.8
cuda available: True
/data available about 302G
```

## 决策路线

### 路线 A：当前推荐，最小依赖 + WebUI

适合目标：

- 先把项目跑起来
- 用浏览器访问 WebUI
- 验证 GPU 加速和基础识别/翻译/配音流程

当前推荐命令顺序：

```bash
cd /data/wangqiao/pyvideotrans_pro
uv sync --extra webui
CUDA_VISIBLE_DEVICES=0 uv run python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
CUDA_VISIBLE_DEVICES=0 uv run webui.py --host 127.0.0.1 --port 7860
```

这条路线安装的是：

```text
主依赖 + webui extra，也就是额外安装 gradio。
```

### 路线 B：按需追加可选渠道

适合目标：

- WebUI / CLI 主流程已经跑通
- 明确需要某个可选本地渠道
- 能接受更重的下载、编译或系统依赖排查

不要一开始执行：

```bash
uv sync --all-extras
```

原因：

```text
all-extras 会额外安装 qwen-tts、qwen-asr、moss-tts、chatterbox、dotnet/pythonnet 等可选依赖。
这些依赖更重，也更容易因为系统库、编译、网络、版本冲突卡住。
```

需要哪个再单独追加：

```bash
uv sync --extra webui --extra qwentts
uv sync --extra webui --extra qwenasr
uv sync --extra webui --extra mosstts
uv sync --extra webui --extra chatterbox
```

注意保留 `--extra webui`。`uv sync` 会让 `.venv` 对齐当前声明的依赖集合；如果之前装过某个 extra，后续 sync 时要把仍需保留的 extra 都写上。

### 路线 C：驱动异常时再升级

适合情况：

- `torch.cuda.is_available()` 是 `False`
- 出现 CUDA driver / initialization error
- 同样命令在这台机器上不再能识别 GPU

这时再让管理员评估升级 NVIDIA driver。当前不需要为了已通过的 PyTorch 验证提前升级。

## 安装前检查

先确认不要把环境装到根分区：

```bash
pwd
df -h / /data
echo "$HOME"
```

推荐目录：

```bash
mkdir -p /data/wangqiao
cd /data/wangqiao
```

确认 Python 版本：

```bash
python3 --version
python --version
```

期望：

```text
Python 3.10.x
```

确认系统工具：

```bash
git --version
curl --version
ffmpeg -version | head -3
```

如果 `ffmpeg` 已存在，可以先不安装系统依赖。缺什么再装什么。

## 安装系统依赖

先检查：

```bash
command -v ffmpeg || true
command -v ffprobe || true
ldconfig -p | grep -E 'libsndfile|libGL|libglib' || true
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

## 安装 uv

先检查：

```bash
uv --version
```

如果提示 `command not found`，再安装：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

当前服务器实际安装结果是：

```text
installing to /home/wangqiao/.local/bin
uv
uvx
```

因此不要使用旧路径 `source "$HOME/.cargo/env"`。这台服务器当前 shell 是 `bash`，推荐把 `$HOME/.local/bin` 写入 `~/.bashrc`：

```bash
cat >> ~/.bashrc <<'EOF'

# uv and user-local tools
export PATH="$HOME/.local/bin:$PATH"
EOF
```

让当前 shell 立即生效：

```bash
source ~/.bashrc
uv --version
```

如果当前 shell 是 zsh，才写 `~/.zshrc`：

```bash
echo "$SHELL"
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

看到 `bash` 就维护 `~/.bashrc`；看到 `zsh` 再维护 `~/.zshrc`。

## 把缓存放到 /data

模型、wheel、虚拟环境缓存不要写根分区。先检查当前值：

```bash
echo "UV_CACHE_DIR=$UV_CACHE_DIR"
echo "HF_HOME=$HF_HOME"
echo "XDG_CACHE_HOME=$XDG_CACHE_HOME"
```

建议写入 `~/.bashrc`：

```bash
cat >> ~/.bashrc <<'EOF'

# pyvideotrans remote dev cache
export UV_CACHE_DIR=/data/wangqiao/.uv-cache
export HF_HOME=/data/wangqiao/.cache/huggingface
export XDG_CACHE_HOME=/data/wangqiao/.cache
EOF
```

使其生效：

```bash
source ~/.bashrc
mkdir -p "$UV_CACHE_DIR" "$HF_HOME" "$XDG_CACHE_HOME"
echo "$UV_CACHE_DIR"
echo "$HF_HOME"
echo "$XDG_CACHE_HOME"
```

## 获取代码

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

进入项目后先检查项目配置：

```bash
pwd
ls -la pyproject.toml uv.lock
python3 --version
uv --version
```

确认 Python 要求：

```bash
grep -n 'requires-python' pyproject.toml
grep -n 'pytorch-cu128' -A6 pyproject.toml
```

期望看到：

```text
requires-python = ">=3.10, <3.11"
url = "https://download.pytorch.org/whl/cu128"
```

## 安装项目依赖

### 推荐安装：主依赖 + WebUI

先确认在项目目录：

```bash
cd /data/wangqiao/pyvideotrans_pro
pwd
```

安装最小可用集：

```bash
uv sync --extra webui
```

这里的 `--extra webui` 不是排除 WebUI，而是**额外安装 WebUI 所需依赖**。项目里 `webui` extra 当前对应 `gradio`：

```text
uv sync              -> 主依赖
uv sync --extra webui -> 主依赖 + WebUI 依赖 gradio
```

这已经足够启动 WebUI、验证 torch、跑常规识别/翻译/配音流程。

不建议一开始安装所有 extra：

```bash
uv sync --all-extras
```

`--all-extras` 会额外安装 qwen-tts、qwen-asr、moss-tts、chatterbox、dotnet/pythonnet 等可选依赖。这些依赖更重，也更容易因为系统库、编译、网络、版本冲突卡住。

如果后续明确需要某个可选渠道，再按需追加，并保留已需要的 extra：

```bash
uv sync --extra webui --extra qwentts
uv sync --extra webui --extra qwenasr
uv sync --extra webui --extra mosstts
uv sync --extra webui --extra chatterbox
```

### 验证 PyTorch CUDA

安装完成后验证 torch：

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

如果第一次运行验证命令时看到 `Preparing packages... torch ...`，这通常是 `uv run` 在补齐缺失包或完成上一次未完成的下载，符合预期。等它跑完后再重复执行一次验证命令即可。

### 驱动升级判断

当前服务器已经实测：

```text
torch: 2.7.1+cu128
torch cuda build: 12.8
cuda available: True
gpu 0: NVIDIA A10
```

因此当前不需要为了本项目安装流程立即升级 NVIDIA driver。只有在后续出现 CUDA driver / initialization error，或 `torch.cuda.is_available()` 变成 `False` 时，再让管理员评估升级驱动。

## 启动 WebUI

GPU 验证通过后，优先锁定空闲的 GPU 0：

```bash
nvidia-smi
```

如果 GPU 0 空闲，启动：

```bash
cd /data/wangqiao/pyvideotrans_pro
CUDA_VISIBLE_DEVICES=0 uv run webui.py --host 127.0.0.1 --port 7860
```

这个服务器窗口保持打开即可。需要停止 WebUI 时，在这个窗口按 `Ctrl+C`。

另开一个服务器窗口时，可以用下面命令查看 WebUI 是否还在：

```bash
ps -ef | grep -E 'webui.py|gradio' | grep -v grep
```

## 本机浏览器访问

在本机另开一个终端，建立 SSH tunnel：

```bash
ssh -L 7860:localhost:7860 wangqiao@<服务器地址>
```

保持 SSH 不关，本机浏览器打开：

```text
http://localhost:7860
```

如果必须让局域网直接访问，才考虑：

```bash
uv run webui.py --host 0.0.0.0 --port 7860
```

默认不推荐直接暴露 `0.0.0.0`。

## CLI 验证

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

## 常见排查

### `uv: command not found`

检查：

```bash
ls -la "$HOME/.local/bin/uv" "$HOME/.local/bin/env"
echo "$PATH"
echo "$SHELL"
ps -p $$ -o comm=
```

当前服务器上 uv 安装在 `$HOME/.local/bin`。如果当前 shell 是 bash，处理：

```bash
cat >> ~/.bashrc <<'EOF'

# uv and user-local tools
export PATH="$HOME/.local/bin:$PATH"
EOF
source ~/.bashrc
uv --version
```

如果当前 shell 是 zsh，才写 `~/.zshrc`：

```bash
cat >> ~/.zshrc <<'EOF'

# uv and user-local tools
export PATH="$HOME/.local/bin:$PATH"
EOF
source ~/.zshrc
uv --version
```

不要按 Ubuntu 提示执行 `sudo snap install astral-uv`。这里不是没安装 uv，而是 PATH 还没生效。

### `torch.cuda.is_available()` 是 `False`

先看驱动：

```bash
nvidia-smi
uv run python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

如果输出是 `2.7.1+cu128`，但 `nvidia-smi` 仍是 CUDA `12.4`，优先升级驱动，不要继续猜。

### 显存不足

当前输出显示 GPU 1 已占用约 19G，优先用 GPU 0：

```bash
nvidia-smi
CUDA_VISIBLE_DEVICES=0 uv run python -c "import torch; print(torch.cuda.get_device_name(0))"
```

必要时换小模型，例如 `base`，确认流程跑通后再换 `large-v3`。

### 根分区快满

检查：

```bash
df -h / /data
du -h -d 1 "$HOME/.cache" 2>/dev/null | sort -h | tail
du -h -d 1 /data/wangqiao 2>/dev/null | sort -h | tail
```

重点确认：

```bash
echo "$UV_CACHE_DIR"
echo "$HF_HOME"
echo "$XDG_CACHE_HOME"
```

这些目录应在 `/data/wangqiao` 下。

### `docker compose` 不可用

当前 Docker 有安装，但 `docker compose` 不可用。本项目源码部署主流程不依赖 Docker，可以先忽略。

如果后续要走容器部署，再单独补 Docker Compose plugin。

## 为什么不用桌面版 sp.py

`sp.py` 是 PySide6 桌面程序，需要图形显示。服务器是 headless，X11/VNC 转发视频预览体验差，也增加排障成本。

远端服务器推荐：

```text
WebUI：交互使用
CLI：批处理
```

本机原生桌面版另见 [环境安装](环境安装.md)。
