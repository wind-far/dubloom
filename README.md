# Dubloom · 织声

面向个人创作者与小团队的本地视频译制校审工作台。导入视频、翻译字幕、逐句试听与修改，再生成配音和成片。

**简体中文** · [English](README.en.md)

[快速开始](#quick-start) · [使用流程](#usage) · [配置说明](#configuration) · [反馈问题](https://github.com/wind-far/dubloom/issues)

> [!NOTE]
> 项目处于 MVP 阶段。支持 YouTube、Bilibili 和本地视频，默认在翻译完成后暂停，等待人工校审。日译中已有自动化参数链路与回归测试，真实日语媒体的模型效果仍待验收。
>
> 视频、数据库和生成产物保存在本机；翻译文本会发送到你配置的 OpenAI 兼容 API。下载视频、模型和依赖也需要网络访问。

<a id="overview"></a>

## Dubloom 是什么？

Dubloom 把视频译制组织成可检查、可修改的任务流程：先获得译文，再逐句确认用词、时间码与发音方式，批准后继续生成视频。成片后的修改会标记结果过期，可重新生成受影响的片段并更新最终视频。

界面采用浅色工作台布局，提供任务列表、阶段进度、原视频预览、字幕编辑区和片段设置。后台使用 SQLite 与单线程 FIFO 作业队列，适合本地串行处理。

<a id="capabilities"></a>

## 五项核心能力

| 能力 | 日常用途 | 实现位置 |
| --- | --- | --- |
| 视频导入 | 提交 YouTube / Bilibili 链接，或上传本地视频与可选的已翻译 SRT。 | [输入适配器](backend/app/adapters/) |
| 自动处理 | 分离人声、识别语音、整理句子，并通过翻译 API 生成译文。 | [处理流水线](backend/app/pipeline.py) |
| 逐句校审 | 修改译文、时间码、说话人和发音方式，试听原声与配音预览。 | [校审工作台](apps/web/src/app/tasks/%5Bid%5D/review/page.tsx) |
| 局部重生成 | 成片后复用未修改的 TTS 缓存，重新生成修改段，再混音与封装。 | [校审与渲染](backend/app/review.py) |
| 任务与模型配置 | 查看任务日志、恢复失败阶段；选择翻译 / TTS 配置并保存任务参数快照。 | [作业队列](backend/app/worker.py) · [Provider](backend/app/providers/) |

默认 Provider 为 OpenAI-compatible 翻译和本地 VoxCPM2。配置档案可通过 `/api/provider-profiles` 接口管理，并在创建任务时选择；当前没有完整的配置档案管理页面。

<a id="formats"></a>

## 支持的输入与输出

| 输入 | 翻译方向 | 可附加字幕 |
| --- | --- | --- |
| YouTube 链接 | 英文 → 中文 | 不支持 |
| Bilibili 链接 | 中文 → 英文 | 不支持 |
| 本地视频 | 英文 → 中文、日文 → 中文、中文 → 英文 | 已翻译的 `.srt` |

本地 SRT 应使用所选方向的目标语言。提供 SRT 后，任务跳过语音识别与 API 翻译，继续校审和输出流程。默认上传上限为视频 4 GiB、字幕 20 MiB，可通过环境变量调整。

| 输出模式 | 音轨 | 画面字幕 |
| --- | --- | --- |
| `subtitles` | 保留原始音轨 | 压制目标语言硬字幕 |
| `dubbing` | 目标语言配音与背景音 | 不额外压制字幕 |
| `both` | 目标语言配音与背景音 | 压制目标语言硬字幕 |

当前面向单个视频任务，不包含完整多轨时间线、口型同步或多人协作功能。

<a id="requirements"></a>

## 运行要求

| 组件 | 要求 |
| --- | --- |
| Python | 3.12，使用独立虚拟环境。 |
| Node.js | 建议 22.13+ 的 22.x 或 24.x，配合 npm；前端测试依赖也受 Node 版本约束。 |
| FFmpeg / ffprobe | 可从 `PATH` 找到，或通过完整路径配置。硬字幕输出需要 `subtitles` / libass 支持。 |
| 推理设备 | 完整处理建议使用 NVIDIA CUDA GPU；CPU 模式较慢。Whisper 在选择 MPS 时回退到 CPU。 |
| 翻译服务 | 可用的 OpenAI 兼容 Chat Completions API 地址、密钥和模型名；已翻译 SRT 可跳过该步骤。 |
| 存储与网络 | 为模型缓存、源视频和中间音频预留空间；按视频来源配置网络、代理与 Cookie。 |

首次模型下载和完整视频处理可能耗时较长。VoxCPM 的实际运行设备由依赖库选择，任务日志中显示为 `voxcpm=library-auto`。

<a id="quick-start"></a>

## 快速开始

### 1. 获取项目

当前仓库为私有仓库，克隆前需使用有访问权限的 GitHub 账号。

```bash
git clone --recurse-submodules https://github.com/wind-far/dubloom.git
cd dubloom
```

已有工作副本可执行 `git submodule update --init --recursive` 补齐 Demucs 子模块。

### 2. 安装依赖

先安装符合上表要求的 Python、Node.js 和 FFmpeg。若使用 NVIDIA CUDA，先在虚拟环境中安装适配本机驱动的 PyTorch，再安装项目依赖；仓库提供 [CUDA 12.8 安装文件](requirements-pytorch-cu128.txt)。

<details open>
<summary>macOS / Linux / WSL2</summary>

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
# 可选，仅 NVIDIA CUDA 环境：
# .venv/bin/python -m pip install -r requirements-pytorch-cu128.txt
.venv/bin/python -m pip install -r requirements.txt
npm --prefix apps/web ci
cp env.txt.example .env
```

</details>

<details>
<summary>Windows PowerShell</summary>

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
# 可选，仅 NVIDIA CUDA 环境：
# .\.venv\Scripts\python.exe -m pip install -r requirements-pytorch-cu128.txt
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix apps/web ci
Copy-Item env.txt.example .env
```

Windows 使用 TorchCodec 时需要 FFmpeg 的 shared/full-shared 构建。将 `FFMPEG_PATH` 指向其中的 `ffmpeg.exe`，同目录必须包含 `avcodec-*.dll`、`avformat-*.dll`、`avutil-*.dll` 等动态库。只有可执行文件的静态构建不满足此要求。

</details>

前端安装默认使用仓库配置的 npm 镜像；需要切换时可执行 `npm --prefix apps/web ci --registry=https://registry.npmjs.org`。

### 3. 设置登录密码与运行参数

后端要求配置 Argon2id 密码哈希。执行以下命令，交互式输入访问密码：

```bash
.venv/bin/python -c "from getpass import getpass; from pwdlib import PasswordHash; print(PasswordHash.recommended().hash(getpass('Dubloom password: ')))"
```

Windows 将命令中的 `.venv/bin/python` 替换为 `.\.venv\Scripts\python.exe`。

在 `.env` 中填写完整哈希，并调整设备与翻译设置：

```dotenv
YOUDUB_AUTH_PASSWORD_HASH='<粘贴完整的 Argon2id 哈希>'
DEVICE=cpu
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=
OPENAI_MODEL=
```

有可用 CUDA 环境时将 `DEVICE` 改为 `cuda`。翻译 API 地址、密钥与模型也可在登录后的“设置”中填写。`YOUDUB_*` 是当前代码读取的配置键，请保留名称。

### 4. 启动工作台

在两个终端中分别启动后端和前端，均从仓库根目录执行：

```bash
# 终端 1：后端
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```bash
# 终端 2：前端
npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3000
```

Windows 后端命令同样替换 Python 路径即可。打开 [http://127.0.0.1:3000](http://127.0.0.1:3000)，使用刚才设置的密码登录。

前端通过同源 `/api` 代理访问后端。如 8000 端口已被占用，可将后端端口改为 8001，并在启动前端的终端中设置：

```bash
# macOS / Linux / WSL2
export NEXT_SERVER_API_BASE_URL=http://127.0.0.1:8001
```

```powershell
# Windows PowerShell
$env:NEXT_SERVER_API_BASE_URL = "http://127.0.0.1:8001"
```

<a id="usage"></a>

## 使用流程

### 创建任务

1. 在“设置”中配置翻译 API、模型和并发数。按需要补充 YouTube 的 Netscape 格式 Cookie 与下载代理。
2. 提交视频链接或上传本地文件，选择翻译方向与输出模式。
3. 保持默认的“人工校审”开启；如需自动处理完成，可将其关闭。
4. 在任务详情中查看阶段进度和日志。

### 校审与试听

1. 任务进入 `awaiting_review` 后打开校审工作台。
2. 选择字幕段，修改译文、开始 / 结束时间、说话人和发音方式。
3. 保存后试听原始人声，或生成并试听 TTS 预览。预览与正式渲染共用串行队列，需要等待当前作业结束。
4. 处理空译文、非法时间范围等阻断错误；字符速率和参考音频偏短属于提示，由你判断是否调整。
5. 批准后继续生成成片，在任务详情中播放或下载 MP4。

### 修改已完成的视频

保存新的片段修改后，任务会显示结果需要重新生成。点击“应用全部更改”后，系统更新修改段的 TTS、混音和视频；仅字幕模式直接更新字幕封装，已有下载、分离、识别和翻译结果会继续复用。

```text
导入 → 识别 / 翻译 → 人工校审 → 批准 → 生成视频
                       ↑                   │
                       └── 修改字幕段 ──────┘
                            ↓
                       局部重生成 → 更新视频
```

API 创建任务的 `review_mode` 默认仍为 `none`；WebUI 默认提交 `required`。旧任务进入校审时，可从已有翻译文件加载字幕段。

<a id="configuration"></a>

## 配置说明

完整配置示例见 [env.txt.example](env.txt.example) 与 [.env.example](.env.example)。应用启动时读取仓库根目录的 `.env`。

| 配置 | 用途 / 默认值 |
| --- | --- |
| `YOUDUB_AUTH_PASSWORD_HASH` | 必填登录哈希；会话默认有效期为 7 天。 |
| `DEVICE` | Whisper / Demucs 的设备选择；示例文件默认 `cuda`，无 CUDA 时需修改。 |
| `DEMUCS_DEVICE` / `WHISPER_DEVICE` | 单独覆盖对应组件的设备。 |
| `FFMPEG_PATH` / `FFPROBE_PATH` | FFmpeg / ffprobe 的完整路径。 |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` | 默认翻译服务；可在 UI 中维护。 |
| `OPENAI_TRANSLATE_CONCURRENCY` | 翻译并发数，默认 50；按服务额度调整。 |
| `VOXCPM_MODEL` / `VOXCPM_MODEL_DIR` | VoxCPM2 模型名 / 本地模型目录。 |
| `VOXCPM_MIN_REFERENCE_MS` | TTS 参考音频最短长度，默认 1200 ms。 |
| `DEMUCS_CHUNK_SECONDS` | 人声分离分块长度，默认 600 秒。 |
| `RELEASE_GPU_MEMORY_AFTER_STAGE` | 默认 `true`，阶段结束后释放模型引用和可用设备缓存。 |
| `LOCAL_UPLOAD_MAX_BYTES` / `LOCAL_SUBTITLE_MAX_BYTES` | 本地视频 / SRT 的上传上限。 |
| `YTDLP_PROXY_PORT` / `HTTP_PROXY` / `ALL_PROXY` | 下载或 API 的代理配置。 |
| `NO_PROXY` | 使用本地 API 时包含 `localhost,127.0.0.1,::1`。 |
| `NEXT_SERVER_API_BASE_URL` | 前端服务启动环境中的后端地址，默认 `http://127.0.0.1:8000`。 |

Provider 配置的非敏感参数会写入任务快照。现有任务重跑时可沿用快照；修改全局设置主要影响新任务。

<a id="data"></a>

## 本地数据与输出

| 默认路径 | 内容 |
| --- | --- |
| `data/youdub.sqlite` | 任务、字幕段、配置档案、作业和登录会话。 |
| `data/cookies/` | 下载使用的 Cookie。 |
| `data/logs/` | 任务运行日志。 |
| `data/modelscope/` | 模型缓存，可通过 `MODEL_CACHE_DIR` 修改。 |
| `workfolder/_uploads/` | 本地上传文件。 |
| `workfolder/<session>/metadata/` | 识别、翻译与时间信息。 |
| `workfolder/<session>/segments/` | 原声切片、TTS、预览与时间拉伸音频。 |
| `workfolder/<session>/media/video_final.mp4` | 最终成片。 |

`WORKFOLDER` 可修改任务产物根目录。环境文件、运行数据库、Cookie、日志与媒体目录已被 Git 忽略；其中仍可能包含敏感内容，分享前请检查。

POSIX 系统启动时会收紧运行目录和文件权限，并拒绝不安全的路径。Windows 需要自行配置对应的 NTFS 访问权限。跨机器访问时需另行配置监听地址、HTTPS 反向代理与 `YOUDUB_AUTH_COOKIE_SECURE=true`；浏览器继续通过前端的同源 API 访问。

<a id="development"></a>

## 开发与检查

前端使用 Next.js App Router、React、Tailwind CSS 与 shadcn/ui；后端使用 FastAPI、SQLite，视频处理由 yt-dlp、Demucs、Whisper、VoxCPM2 和 FFmpeg 完成。

```text
apps/web/              Next.js 界面与前端测试
backend/app/           API、数据库、任务队列与流水线
backend/app/providers/ 翻译 / TTS 接口与默认实现
backend/app/adapters/  视频下载、识别、音频和模型适配器
backend/tests/         后端测试
scripts/               辅助脚本
submodule/demucs/      Demucs 源码子模块
```

在已安装依赖的环境中执行：

```bash
.venv/bin/python -m pytest backend/tests -q
npm --prefix apps/web test
npm --prefix apps/web run lint
(cd apps/web && npx tsc --noEmit)
npm --prefix apps/web run build
```

Windows 使用虚拟环境中的 `python.exe`；类型检查可先 `cd apps/web`，执行 `npx tsc --noEmit` 后回到根目录。

纯后端单元测试可在独立环境中仅安装 [backend/requirements-test.txt](backend/requirements-test.txt)，无需下载模型。[CI 工作流](.github/workflows/ci.yml) 包含后端测试、前端测试、Lint、类型检查、生产构建和依赖审计；自动化检查不等于真实媒体的翻译、配音效果验收。

<a id="contributing"></a>

## 参与贡献

通过 [Issues](https://github.com/wind-far/dubloom/issues) 提交问题或功能建议，通过 [Pull Request](https://github.com/wind-far/dubloom/pulls) 提交代码。问题报告请附操作系统、运行版本、复现步骤与脱敏日志；功能修改请补充对应测试，并同步更新中英文说明。

<a id="license"></a>

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。第三方依赖与模型遵循各自的许可证。
