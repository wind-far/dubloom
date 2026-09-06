# Dubloom（织声）

Dubloom Studio 是一个面向个人创作者与小团队的本地视频译制工作台。

它可以把单个 YouTube、Bilibili 或本地视频转换成目标语言版本：导入视频、识别并翻译内容，在逐句校审工作台中调整译文、时间码、说话人和发音配置，再按任务选择输出保留原音的硬字幕视频、无硬字幕的配音视频，或同时包含硬字幕与配音的视频。配音模式还会分离人声与背景音、生成配音并完成混音，最终视频可在网页中播放和下载。

支持 **YouTube 英文 -> 中文**、**Bilibili 中文 -> 英文**，以及本地视频的 **英文 -> 中文**、**日文 -> 中文**、**中文 -> 英文** 三种翻译方向。日译中方向已通过自动化参数链路和回归测试，尚未使用真实日语媒体完成模型效果验收。

English README: [README.en.md](README.en.md)

## 快速开始

### 1. 准备运行环境

已验证和推荐的运行方式：

- **Windows 10/11 + PowerShell 5.1+**：推荐开发环境，也是本文档优先覆盖的平台。
- **Linux / WSL2 / macOS**：后端和前端命令按 POSIX shell 给出；CUDA、FFmpeg、PyTorch/音频依赖需要按各平台实际环境安装。
- **CUDA GPU**：推荐用于完整视频处理。`DEVICE=cpu` 可以运行部分流程，但完整转写、分离、TTS 会非常慢；`DEVICE=mps` 会让 Whisper 自动退回 CPU 以避开 MPS float64 限制。

基础依赖：

- Python 3.12。
- Node.js 20+。
- FFmpeg / ffprobe，并确保命令在 `PATH` 中可用。
- 可访问 YouTube 的代理（处理 YouTube 视频时需要）
- Netscape 格式的 YouTube Cookie（处理 YouTube 视频时推荐配置）
- OpenAI 兼容 Chat Completions API 的 base URL、API key 和模型名

首次运行会下载或加载较大的 ASR、TTS、音频处理模型，请预留磁盘空间和网络时间。

平台注意事项：

- Windows PowerShell 使用 `.venv\Scripts\...`，不要照抄 `.venv/bin/...`。
- macOS/Linux 使用 `.venv/bin/...`。
- 如果系统里同时存在多个 Python，请先确认 `py -0p`（Windows）或 `python3.12 --version`（macOS/Linux）的结果。
- 代理、Cookie、模型缓存和工作目录都保存在本机；路径中含空格时，建议使用引号或写入 `.env`。

常见系统依赖安装示例：

```powershell
# Windows PowerShell（任选你本机已有的包管理器）
winget install Gyan.FFmpeg.Shared
winget install OpenJS.NodeJS.LTS
```

Windows 必须安装 FFmpeg 的 shared/full-shared 版本。进入该版本的 `bin` 目录后执行以下检查；`av*.dll` 至少应列出 `avcodec-*.dll`、`avformat-*.dll` 和 `avutil-*.dll`。只有 `ffmpeg.exe`、`ffplay.exe`、`ffprobe.exe` 且没有 `av*.dll` 的目录属于静态构建，TorchCodec 无法使用它提供运行库。

```powershell
$ffmpegBin = "C:\path\to\ffmpeg\bin"
Get-ChildItem "$ffmpegBin\av*.dll"
& "$ffmpegBin\ffmpeg.exe" -version
& "$ffmpegBin\ffprobe.exe" -version
```

记下通过检查的 `bin` 目录；在第 4 步创建 `.env` 后填入该实际路径。Python 3.8+ 的 DLL 加载规则需要应用显式注册搜索目录；单独修改 `PATH` 无法保证 TorchCodec 找到这些 DLL。Dubloom 启动时会读取 `FFMPEG_PATH`，检查同目录的 `av*.dll`，并通过 `os.add_dll_directory()` 注册该目录。配置错误会在启动阶段直接给出原因。

```bash
# Ubuntu / Debian / WSL2
sudo apt update
sudo apt install -y ffmpeg nodejs npm
```

```bash
# macOS（Homebrew）
brew install ffmpeg node
```

如果你的系统包管理器无法提供 Python 3.12，建议从 Python 官网、pyenv、conda/mamba 或发行版推荐方式安装；关键是后续创建虚拟环境时确认使用的是 3.12。

### 2. 获取项目

在 Windows PowerShell、macOS 或 Linux 中执行以下命令。当前仓库为私有仓库，克隆前需登录有访问权限的 GitHub 账号：

```powershell
git clone https://github.com/wind-far/dubloom.git
cd dubloom
git submodule update --init --recursive
```

Demucs 以源码子模块引入，请不要跳过 `git submodule update`。

### 3. 安装依赖

#### Windows PowerShell

Python 依赖：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\pip.exe install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

前端依赖：

```powershell
Push-Location apps/web
npm ci --registry=https://registry.npmmirror.com
Pop-Location
```

#### macOS / Linux / WSL2

Python 依赖：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

前端依赖：

```bash
(cd apps/web && npm ci --registry=https://registry.npmmirror.com)
```

如果 Aliyun 镜像中某个 Python 包暂时不可用，再单独对失败的包使用 Tsinghua 源重试；不要把多个镜像混在同一条 resolver 命令里。

#### 可选：NVIDIA CUDA GPU

如果要用 NVIDIA GPU 跑 Whisper、Demucs 或 VoxCPM，请在安装 `requirements.txt` 之前先安装 CUDA 版 PyTorch：

Windows PowerShell：

```powershell
.\.venv\Scripts\pip.exe install -r requirements-pytorch-cu128.txt
```

Linux / WSL2：

```bash
.venv/bin/pip install -r requirements-pytorch-cu128.txt
```

`requirements-pytorch-cu128.txt` 默认使用 PyTorch 的 `cu128` wheel 源。不同 NVIDIA 驱动或 CUDA 环境可能需要不同的 PyTorch CUDA 版本，请按 [PyTorch 官方安装页](https://pytorch.org/get-started/locally/) 选择匹配命令。CPU 用户和 macOS 用户不需要执行这一步；如果没有安装 CUDA 版 PyTorch，请在 `.env` 中设置 `DEVICE=cpu`。

安装后可以验证 CUDA 是否真的可用：

```bash
.venv/bin/python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

### 4. 配置环境

Windows PowerShell：

```powershell
Copy-Item env.txt.example .env
```

macOS / Linux / WSL2：

```bash
cp env.txt.example .env
```

应用运行时读取 `.env`。不要提交 API key、Cookie、下载视频或生成产物。

Windows 用户把第 1 步确认过的 shared/full-shared FFmpeg 实际路径写入刚创建的 `.env`：

```dotenv
FFMPEG_PATH=C:/path/to/ffmpeg/bin/ffmpeg.exe
FFPROBE_PATH=C:/path/to/ffmpeg/bin/ffprobe.exe
```

后端默认强制认证；`YOUDUB_AUTH_PASSWORD_HASH` 未配置时会拒绝启动。请在本机交互式输入访问密码并生成 Argon2id 哈希，命令不会把明文密码写入 shell 历史：

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -c "from getpass import getpass; from pwdlib import PasswordHash; print(PasswordHash.recommended().hash(getpass('Dubloom password: ')))"
```

macOS / Linux / WSL2：

```bash
.venv/bin/python -c "from getpass import getpass; from pwdlib import PasswordHash; print(PasswordHash.recommended().hash(getpass('Dubloom password: ')))"
```

把输出的整行哈希填入 `.env` 的 `YOUDUB_AUTH_PASSWORD_HASH`。不要填写明文密码，也不要把真实哈希提交到 Git。

常用环境变量：

| 变量 | 说明 |
| --- | --- |
| `WORKFOLDER` | 每个任务的媒体、分段音频和中间产物目录。 |
| `MODEL_CACHE_DIR` | ModelScope 模型缓存目录，默认用于 VoxCPM2。 |
| `YOUDUB_AUTH_PASSWORD_HASH` | 必填的登录密码 Argon2id 哈希；不接受明文密码。 |
| `YOUDUB_AUTH_SESSION_TTL_SECONDS` | 登录会话绝对有效期，默认 `604800` 秒（7 天）。 |
| `YOUDUB_AUTH_COOKIE_SECURE` | HTTPS 部署必须设为 `true`；仅可信的本机 HTTP 开发可设为 `false`。 |
| `YOUDUB_AUTH_COOKIE_SAMESITE` | 会话 Cookie 的 SameSite 策略，可选 `lax` 或 `strict`；同源代理部署建议 `strict`。 |
| `DEVICE` | 模型运行设备，例如 `auto`、`cuda`、`cuda:0`、`mps`、`mps:0` 或 `cpu`；`auto` 按 CUDA、MPS、CPU 顺序选择。 |
| `DEMUCS_DEVICE` / `WHISPER_DEVICE` | 可选组件级设备覆盖；留空时使用 `DEVICE`。Whisper 选择 MPS 时会退回 CPU，因为词级时间戳对齐依赖 MPS 不支持的 float64 DTW。 |
| `DEMUCS_CHUNK_SECONDS` | 人声分离的分块长度，必须为正整数，默认 `600`（10 分钟）。内存峰值由单个“分块 + 10 秒上下文”的推理和两份 10 秒 overlap tail 决定；每块写出后，完整输入与输出张量会在下一块推理前释放，跨块只保留两份 tail，内存不会随视频总长或分块数累积。默认窗口约 2.8 GiB 仅作参考，实际峰值还取决于模型、`shifts`、设备和底层库。首音轨以 float32 解码：mono 复制为双声道，双声道及以上只取前两个声道。临时输入使用 FFmpeg WAV `-rf64 auto`，超过 RIFF 上限时自动切换 RF64；两份 float32 stem 和两份最终 PCM16 输出固定使用 RF64，消除普通 WAV 的 4 GiB 边界。临时字节数约为“时长秒 × 采样率 × 声道数 × (4 + 4 × 2)”；按 44.1 kHz 双声道估算为 3.55 GiB/小时，写入最终输出时还需 1.18 GiB/小时，建议至少预留 4.73 GiB/小时。临时文件在成功或失败后都会清理。 |
| `RELEASE_GPU_MEMORY_AFTER_STAGE` | 默认 `true`。Demucs、Whisper、VoxCPM 阶段结束后释放模型引用和可用的 CUDA/MPS 缓存，并在任务结束时再次清理。单线程流水线在同一任务中不会再次使用这些模型；设为 `false` 可保留跨任务模型缓存、减少重新加载耗时，同时会增加显存持续占用和 OOM 风险。接受 `1/0`、`true/false`、`yes/no`、`on/off`。 |
| `FFMPEG_PATH` / `FFPROBE_PATH` | 可选的媒体程序完整路径；Windows 上使用 TorchCodec 时，`FFMPEG_PATH` 必须指向 shared/full-shared 构建。 |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址，例如 `https://api.openai.com/v1`。 |
| `OPENAI_API_KEY` | 翻译阶段使用的 API key。 |
| `OPENAI_MODEL` | 翻译阶段使用的 Chat Completions 模型。 |
| `OPENAI_TRANSLATE_CONCURRENCY` | 翻译阶段的并发请求数，默认 `50`。 |
| `LOCAL_UPLOAD_MAX_BYTES` | 本地视频上传大小上限，默认 4 GiB。 |
| `LOCAL_SUBTITLE_MAX_BYTES` | 可选本地 SRT 字幕上传大小上限，默认 20 MiB。 |
| `YTDLP_PROXY_PORT` | yt-dlp 使用的本机代理端口，例如 `7890`。 |
| `HTTP_PROXY` / `ALL_PROXY` | 未在 UI 中设置代理端口时，yt-dlp 可读取 `HTTP_PROXY`；HTTPX/OpenAI SDK 也会读取这些环境代理。 |
| `NO_PROXY` | 逗号分隔的代理绕过列表；使用本地 OpenAI 兼容服务时建议包含 `localhost,127.0.0.1,::1`，避免本地请求绕行系统代理。 |
| `VOXCPM_MODEL` / `VOXCPM_MODEL_DIR` | VoxCPM2 的 ModelScope 模型名或本地模型目录；VoxCPM 依赖库内部选择 CUDA/MPS/CPU，任务日志会显示为 `voxcpm=library-auto`。 |
| `VOXCPM_LOAD_DENOISER` / `VOXCPM_CFG_VALUE` / `VOXCPM_INFERENCE_TIMESTEPS` / `VOXCPM_MIN_REFERENCE_MS` | VoxCPM2 推理参数。 |
| `CORS_ALLOW_ORIGINS` / `CORS_ALLOW_ORIGIN_REGEX` | 显式允许的跨源前端来源；不能使用 `*`。同源 Next 代理不需要配置。 |

Demucs 分离结果采用同目录 pending 发布：handler 每次实际执行时先删除旧 final 和遗留 pending，再完整生成 `.audio_vocals.pending.wav` 与 `.audio_bgm.pending.wav`；两份文件都关闭写完后，才分别原子替换 `audio_vocals.wav` 与 `audio_bgm.wav`。普通异常会删除 pending 和已经发布的单份 final。SIGKILL 或掉电可能留下 pending 或单份 final，failed/running stage 再次恢复时会先清理并完整重算。真正 succeeded 的 stage 由 PipelineRunner 根据 stage 元数据恢复，不会再次调用 handler。

默认 CORS 只允许 `localhost`、`127.0.0.1` 和 `::1` 的 `:3000`。推荐始终使用 Next.js 同源 `/api` 代理；如果浏览器确实直连不同 origin 的后端，必须把完整、可信的 origin 追加到 `CORS_ALLOW_ORIGINS`，例如 `https://dubloom.example.com`。CORS 不是认证或 CSRF 防护，后端仍会校验 HttpOnly 会话 Cookie 和每会话 CSRF token。

### 5. 启动服务

#### Windows PowerShell

后端：

```powershell
.\.venv\Scripts\uvicorn.exe backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```powershell
npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 3000
```

#### macOS / Linux / WSL2

后端：

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```bash
npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 3000
```

前端默认通过同源 `/api/...` 请求访问后端，并由 Next.js 代理到 `http://127.0.0.1:8000`。如果后端不在本机 `8000` 端口，启动前端时设置 `NEXT_SERVER_API_BASE_URL`，例如：

```bash
NEXT_SERVER_API_BASE_URL=http://192.168.1.10:8000 npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 3000
```

打开：

```text
http://localhost:3000
```

如果从局域网、WSL2 或远程机器访问，浏览器里使用运行前端机器的实际 IP 或主机名，例如 `http://192.168.1.20:3000`。后端默认监听 `0.0.0.0:8000`，前端默认监听 `0.0.0.0:3000`。

浏览器应始终访问前端地址，由 Next.js 转发 `/api`；不要把认证信息放进 `NEXT_PUBLIC_*`、URL query 或前端存储。通过局域网或公网访问时，请在前端前面配置 HTTPS 反向代理并设置 `YOUDUB_AUTH_COOKIE_SECURE=true`。明文 HTTP 只适用于可信的本机开发环境。

### 运行时文件权限

在 POSIX 系统上，后端会在读取 `.env`、连接 SQLite 或启动 worker 前永久设置进程 `umask 0077`。启动迁移只检查文件系统元数据，不读取或改写文件内容，并执行以下策略：

- `data/`、Cookie、日志和 `WORKFOLDER` 下的目录收紧为 `0700`，普通文件收紧为 `0600`。
- SQLite 主库和 `-journal`、`-wal`、`-shm` sidecar、`.env`、`env.txt`、Cookie、上传与新生成产物保持 owner-only。
- 符号链接、特殊文件、异主文件和不安全的可写祖先会让启动失败；服务不会在权限迁移失败后继续启动 worker。
- `MODEL_CACHE_DIR` 根目录必须由 root 或服务账号拥有且不可被其他用户写入；服务账号拥有的缓存根会收紧为 `0700`。缓存内部不做递归 chmod 或内容校验，因此部署前必须确认已有模型缓存可信。

建议用专用 OS 用户运行服务，并确保仓库及自定义 `WORKFOLDER` 的父目录不允许其他组或用户重命名目录项。该边界防护其他 UID 或不可信组用户，不防同 UID 进程、调试器或 root；更强隔离请使用独立账号、容器或系统服务沙箱。

首次启用或执行权限迁移时，应先停止仍会创建或删除运行时文件的旧实例；如果并行启动因 fail-closed 校验失败，请停止旧实例后重试启动。

Windows 的 `chmod`/`umask` 不等价于 NTFS ACL。Windows 部署需由管理员把仓库、`.env`、`env.txt`、`data` 和 `WORKFOLDER` 的 DACL 限制到服务账号；应用会做兼容性检查，但不能替代正确的 NTFS ACL。真实 `.env`、`env.txt`、Cookie、SQLite、`data/` 和 `workfolder/` 已被 `.gitignore` 排除，不要强制加入 Git。

## 页面里怎么用

1. 使用生成哈希时设置的访问密码登录。
2. 打开右上角 Settings。
3. 粘贴 Netscape 格式 YouTube Cookie。
4. 设置 yt-dlp 代理端口，例如 `7890` 或 `20171`。
5. 填写 OpenAI base URL 和 API key。
6. 点击 `Get models` 拉取模型列表，或手动输入模型名。
7. 按 API 提供商额度调整 `Translate concurrency`。
8. 回到首页，提交 YouTube URL、Bilibili URL，或上传本地视频。
   - 在“输出内容”中选择“硬字幕（保留原音）”“配音（无硬字幕）”或“硬字幕和配音”。
   - “人工校审”默认开启：翻译完成后任务会停在“等待校审”，不会直接生成配音和成片；若希望保持旧版全自动行为，可关闭人工校审。
   - 已创建的翻译 / TTS Provider Profile 可以在提交任务时选择；未选择时继续使用现有 OpenAI-compatible 与 VoxCPM2 默认配置。
   - 本地视频可额外上传一份已翻译好的 `.srt` 字幕；上传后 Dubloom 会跳过 Whisper 识别和 OpenAI 翻译，再按所选输出内容使用这份字幕。
   - 本地视频支持“英文 -> 中文”“日文 -> 中文”和“中文 -> 英文”。翻译方向也决定可选字幕的目标语言，例如选择“日文 -> 中文”时，上传的 SRT 会被视为中文字幕。
9. 进入任务详情页查看阶段进度；等待校审时打开校审工作台，逐句修改译文、时间码、说话人、发音方式和 TTS Profile，并试听原声或生成 TTS 预览。
10. 批准校审后任务从切分音频阶段继续运行。成片后再次编辑会把结果标记为“需要重新生成”；应用更改时仅重做脏片段及后续混音、封装。

API key 和 Cookie 会在页面中脱敏显示，后端不会把 Cookie 明文返回给前端。

### 导出 YouTube Cookie

YouTube 下载可使用 Netscape 格式的 Cookie 文件：

1. 在浏览器中登录自己的 YouTube 账号。
2. 使用可信的本地工具导出该站点的 Cookie，保存为 Netscape 格式的 `cookies.txt`。
3. 将文件内容粘贴到 Settings 的 YouTube cookie 输入框。Cookie 属于登录凭据，不要提交到仓库或分享给他人。

请只处理你有权下载、转换和发布的视频内容。

## 工作流程

```text
YouTube / Bilibili URL
  -> yt-dlp 下载单个视频
  -> Demucs 分离人声与背景音
  -> Whisper 识别语音并输出词级时间戳
  -> 句子与时间范围整理
  -> OpenAI 兼容 API 预处理全文并逐句并发翻译
  -> 可选人工校审：逐句编辑、试听、TTS 预览与批准
  -> 按输出内容分支：
     - subtitles：保留原音并压制硬字幕
     - dubbing：生成并混合目标语言配音，不压制硬字幕
     - both：生成并混合配音，同时压制硬字幕
  -> FFmpeg 输出最终 mp4
```

本地视频上传使用同一条后半段流水线，支持英文或日文识别后翻译为中文，以及中文识别后翻译为英文。日译中方向会把 `ja` 传给 Whisper，并使用专用日译中提示词。若同时上传已翻译 `.srt` 字幕，系统会从 SRT 生成内部字幕时间轴，跳过 Whisper 与 OpenAI 翻译阶段，再按所选输出内容继续处理。v1 仅支持本地视频搭配 `.srt`，不支持 URL 任务附加字幕。

## 主要功能

- **端到端处理**：从 URL 到最终视频，不需要手动拆分音频、整理字幕或压制视频。
- **视频输入**：支持 YouTube、Bilibili 链接和本地视频上传。
- **三种输出模式**：可选择保留原音的硬字幕视频、无硬字幕的配音视频，或同时包含两者的视频。
- **本地优先**：SQLite、Cookie、日志、中间产物和最终视频都保存在本机目录中。
- **可观察任务进度**：任务历史、阶段状态、阶段耗时、运行日志和错误信息都可以在页面里查看。
- **失败可恢复**：失败任务可以从失败阶段继续执行，已成功阶段会复用缓存产物。
- **逐句质量控制**：翻译后可暂停校审，支持乐观锁保存、硬错误校验、语速提示、原声试听和 TTS 预览。
- **局部重生成**：成片后修改只失效相关 TTS 片段以及混音、视频产物，不重新下载、分离、识别或翻译。
- **模型适配层**：翻译与 TTS 通过 Provider 接口调用；默认实现保持 OpenAI-compatible 与 VoxCPM2，并支持保存任务配置快照。
- **持久化作业队列**：Pipeline、逐句预览和脏段渲染作业写入 SQLite，进程重启后可恢复排队中的工作。
- **可重跑可清理**：支持按任务 rerun，也支持删除任务记录、日志和 `workfolder/` 下的会话目录。
- **结果可检查**：任务成功后可在页面内播放最终视频，也可以下载 mp4 文件。
- **设置在 UI 内完成**：YouTube Cookie、yt-dlp 代理端口、OpenAI base URL、API key、模型名和翻译并发数都可在 Settings 中维护。
- **适合二次开发**：管线串行、模块边界清晰，方便替换 ASR、翻译、TTS 或字幕样式。

## 技术栈

- Frontend: Next.js App Router, shadcn/ui, Tailwind CSS, Lucide icons
- Backend: FastAPI, SQLite, persistent single-GPU FIFO worker
- Download: yt-dlp
- Source separation: Demucs source submodule
- ASR: openai-whisper（默认 `large-v3-turbo`）
- Translation: OpenAI-compatible Chat Completions API
- TTS: VoxCPM2
- Media processing: FFmpeg, pydub, librosa, audiostretchy

## 开发与测试

后端测试：

Windows PowerShell：

```powershell
.\.venv\Scripts\pytest.exe backend/tests
```

macOS / Linux / WSL2：

```bash
.venv/bin/pytest backend/tests
```

前端检查：

```powershell
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

项目的主要目录：

```text
backend/app/       FastAPI API、任务队列、流水线和模型适配器
backend/tests/     后端单元测试
apps/web/          Next.js WebUI
scripts/           辅助脚本
submodule/demucs/  Demucs 源码子模块
```

## 项目状态与贡献

Dubloom Studio 当前定位为本地创作者校审工作台，使用串行视频处理流水线，支持翻译后人工校审、逐句试听与局部重生成。项目仍处于 MVP 阶段，优先保持最短链路稳定和架构可读。

欢迎贡献：

- 改进安装和模型下载体验。
- 适配更多 ASR、TTS 或翻译后端。
- 优化字幕样式、横竖屏布局和语音时长对齐。
- 提升 YouTube / Bilibili 下载稳定性。
- 增强任务管理、产物管理和失败恢复体验。
- 补充不同平台的运行说明。

问题反馈和功能建议请提交到[本仓库 Issues](https://github.com/wind-far/dubloom/issues)，代码贡献通过 Pull Request 提交。

## 开源许可

本项目使用 Apache License 2.0，详见 [LICENSE](LICENSE)。第三方依赖与模型遵循各自的许可证。
