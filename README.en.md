<h1 align="center">🎙️ Dubloom · 织声</h1>

<p align="center"><code>dubloom-studio</code></p>

<h3 align="center">Turn a video into subtitles and voiceover you can refine line by line</h3>

<p align="center">Video import · Subtitle translation · Line-by-line review · Audio previews · Partial regeneration · Video export</p>

<p align="center">A local AI video localization workspace for individual creators and small teams</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-007EC6?style=flat-square" alt="License: Apache 2.0" /></a>
  <a href="#formats"><img src="https://img.shields.io/badge/Output-MP4-FF7F50?style=flat-square" alt="Output: MP4" /></a>
  <a href="#usage"><img src="https://img.shields.io/badge/Review-line--by--line-8A2BE2?style=flat-square" alt="Review: line-by-line" /></a>
  <a href="#capabilities"><img src="https://img.shields.io/badge/TTS-VoxCPM2-00A9D6?style=flat-square" alt="TTS: VoxCPM2" /></a>
  <a href="#data"><img src="https://img.shields.io/badge/Storage-local_SQLite-20C55A?style=flat-square" alt="Storage: local SQLite" /></a>
  <a href="#overview"><img src="https://img.shields.io/badge/Stage-MVP-E3A008?style=flat-square" alt="Stage: MVP" /></a>
</p>

<p align="center">
  <a href="#capabilities">✨ Features</a> ·
  <a href="#requirements">💻 Requirements</a> ·
  <a href="#quick-start">🚀 Installation</a> ·
  <a href="#usage">🎬 Usage</a> ·
  <a href="#configuration">⚙️ Configuration</a> ·
  <a href="https://github.com/wind-far/dubloom/issues">💬 Feedback</a>
</p>

<p align="center"><a href="README.md">简体中文</a> · <strong>English</strong></p>

> [!NOTE]
> This project is an MVP. It accepts YouTube, Bilibili, and local videos, and pauses for human review after translation by default. Japanese-to-Chinese has automated parameter-flow and regression coverage; model-quality acceptance with real Japanese media is still pending.
>
> Videos, databases, and generated files stay on your computer. Translation text is sent to your configured OpenAI-compatible API. Downloading videos, models, and dependencies also requires network access.

<a id="overview"></a>

## What is Dubloom?

Dubloom organizes video localization into tasks you can inspect and revise. Review the translated wording, timing, and audio mode for each segment, then approve the task to continue rendering. Editing a completed task marks its output as stale; you can regenerate the affected segments and update the final video.

The light workspace includes a task list, stage progress, source video preview, subtitle editor, and segment inspector. A SQLite database and a single-threaded FIFO worker support serial processing on a local machine.

<a id="capabilities"></a>

## Five core capabilities

| Capability | Everyday use | Implementation |
| --- | --- | --- |
| Video import | Submit YouTube / Bilibili URLs, or upload a local video with an optional translated SRT. | [Input adapters](backend/app/adapters/) |
| Automated processing | Separate vocals, transcribe speech, organize sentences, and translate through an API. | [Pipeline](backend/app/pipeline.py) |
| Line-by-line review | Edit translation, timing, speaker, and audio mode; audition source vocals and TTS previews. | [Review workspace](apps/web/src/app/tasks/%5Bid%5D/review/page.tsx) |
| Partial regeneration | Reuse unchanged TTS files, regenerate edited segments, then remix and render the video. | [Review and rendering](backend/app/review.py) |
| Tasks and model configuration | Inspect logs, resume failed stages, select translation / TTS profiles, and retain task parameter snapshots. | [Worker](backend/app/worker.py) · [Providers](backend/app/providers/) |

The default providers are OpenAI-compatible translation and local VoxCPM2. Profiles can be managed through `/api/provider-profiles` and selected when creating a task; a full profile-management UI is not yet available.

<a id="formats"></a>

## Supported inputs and outputs

| Input | Translation direction | Optional subtitles |
| --- | --- | --- |
| YouTube URL | English → Chinese | Not supported |
| Bilibili URL | Chinese → English | Not supported |
| Local video | English → Chinese, Japanese → Chinese, Chinese → English | Translated `.srt` |

A local SRT must use the target language of the selected direction. Providing one skips speech recognition and API translation, then continues through review and output. Default upload limits are 4 GiB for video and 20 MiB for subtitles; both are configurable.

| Output mode | Audio | On-screen subtitles |
| --- | --- | --- |
| `subtitles` | Original audio track | Burned-in target-language subtitles |
| `dubbing` | Target-language voiceover with background audio | No additional subtitles burned in |
| `both` | Target-language voiceover with background audio | Burned-in target-language subtitles |

The current scope is individual video tasks. It does not include a full multitrack timeline, lip synchronization, or multi-user collaboration.

<a id="requirements"></a>

## Requirements

| Component | Requirement |
| --- | --- |
| Python | 3.12 in a dedicated virtual environment. |
| Node.js | Recommended: 22.x starting at 22.13, or 24.x, with npm. Frontend test dependencies also impose Node version requirements. |
| FFmpeg / ffprobe | Available on `PATH` or configured with absolute paths. Hard subtitles require the `subtitles` filter / libass. |
| Inference device | An NVIDIA CUDA GPU is recommended for full processing; CPU mode is slow. Whisper falls back to CPU when MPS is selected. |
| Translation service | An OpenAI-compatible Chat Completions API URL, key, and model name. A translated SRT can bypass this step. |
| Storage and network | Allow space for model caches, source videos, and intermediate audio. Configure connectivity, proxies, and cookies for the video source as needed. |

Initial model downloads and full video processing can take substantial time. The VoxCPM library selects its own device, shown in task logs as `voxcpm=library-auto`.

<a id="quick-start"></a>

## Quick start

### 1. Get the source

This repository is currently private. Use a GitHub account with access before cloning.

```bash
git clone --recurse-submodules https://github.com/wind-far/dubloom.git
cd dubloom
```

For an existing checkout, run `git submodule update --init --recursive` to initialize Demucs.

### 2. Install dependencies

Install Python, Node.js, and FFmpeg according to the requirements above. For NVIDIA CUDA, install a PyTorch build compatible with your driver inside the virtual environment before the project dependencies. The repository includes a [CUDA 12.8 requirements file](requirements-pytorch-cu128.txt).

<details open>
<summary>macOS / Linux / WSL2</summary>

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
# Optional, NVIDIA CUDA environments only:
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
# Optional, NVIDIA CUDA environments only:
# .\.venv\Scripts\python.exe -m pip install -r requirements-pytorch-cu128.txt
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix apps/web ci
Copy-Item env.txt.example .env
```

TorchCodec on Windows requires a shared/full-shared FFmpeg build. Set `FFMPEG_PATH` to its `ffmpeg.exe`; the same directory must contain DLLs such as `avcodec-*.dll`, `avformat-*.dll`, and `avutil-*.dll`. A static build containing only executables does not meet this requirement.

</details>

Frontend installation uses the npm mirror configured in the repository. To use the official registry, run `npm --prefix apps/web ci --registry=https://registry.npmjs.org`.

### 3. Configure login and runtime settings

The backend requires an Argon2id password hash. Run this command and enter your access password interactively:

```bash
.venv/bin/python -c "from getpass import getpass; from pwdlib import PasswordHash; print(PasswordHash.recommended().hash(getpass('Dubloom password: ')))"
```

On Windows, replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`.

Paste the complete hash into `.env`, then configure the device and translation settings:

```dotenv
YOUDUB_AUTH_PASSWORD_HASH='<paste the complete Argon2id hash>'
DEVICE=cpu
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=
OPENAI_MODEL=
```

Set `DEVICE=cuda` if CUDA is available. You can also configure the translation API URL, key, and model in Settings after login. Keep the `YOUDUB_*` names: these are the configuration keys the application currently reads.

### 4. Start the workspace

Run the backend and frontend in separate terminals, both from the repository root:

```bash
# Terminal 1: backend
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```bash
# Terminal 2: frontend
npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3000
```

On Windows, substitute the virtual environment's Python path in the backend command. Open [http://127.0.0.1:3000](http://127.0.0.1:3000) and sign in with the password you just set.

The frontend proxies same-origin `/api` requests to the backend. If port 8000 is occupied, start the backend on 8001 and set the following in the frontend terminal before launching it:

```bash
# macOS / Linux / WSL2
export NEXT_SERVER_API_BASE_URL=http://127.0.0.1:8001
```

```powershell
# Windows PowerShell
$env:NEXT_SERVER_API_BASE_URL = "http://127.0.0.1:8001"
```

<a id="usage"></a>

## Usage

### Create a task

1. Configure the translation API, model, and concurrency in Settings. Add Netscape-format YouTube cookies and a download proxy if needed.
2. Submit a video URL or upload a local file, then select the translation direction and output mode.
3. Leave human review enabled by default, or disable it to let the task finish automatically.
4. Open the task details to inspect stage progress and logs.

### Review and audition

1. Open the review workspace when the task reaches `awaiting_review`.
2. Select a segment and edit its translation, start / end time, speaker, and audio mode.
3. Save, then audition the source vocals or generate a TTS preview. Previews and final rendering share the serial queue and wait for the current job.
4. Resolve blocking errors such as empty translations or invalid time ranges. High character rates and short reference clips are advisory warnings for you to assess.
5. Approve the review to continue rendering, then play or download the MP4 from the task details.

### Revise a completed video

Saving segment changes marks the result as needing regeneration. Use “Apply all changes” to update affected TTS clips, the audio mix, and the video. Subtitle-only tasks update subtitle rendering directly; existing downloads, source separation, transcripts, and translations are reused.

```text
Import → Transcribe / translate → Review → Approve → Render video
                                   ↑                     │
                                   └── Edit segments ────┘
                                            ↓
                                   Partial render → Updated video
```

API task creation still defaults to `review_mode=none`; the WebUI submits `required` by default. Opening review for an older task can load its segments from an existing translation artifact.

<a id="configuration"></a>

## Configuration

See [env.txt.example](env.txt.example) and [.env.example](.env.example) for configuration examples. The application reads `.env` at the repository root on startup.

| Setting | Purpose / default |
| --- | --- |
| `YOUDUB_AUTH_PASSWORD_HASH` | Required login hash. Sessions expire after 7 days by default. |
| `DEVICE` | Device selection for Whisper / Demucs. Example files default to `cuda`; change this if CUDA is unavailable. |
| `DEMUCS_DEVICE` / `WHISPER_DEVICE` | Per-component device overrides. |
| `FFMPEG_PATH` / `FFPROBE_PATH` | Absolute paths to FFmpeg / ffprobe. |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` | Default translation service; also configurable in the UI. |
| `OPENAI_TRANSLATE_CONCURRENCY` | Translation request concurrency, default 50. Adjust for your service quota. |
| `VOXCPM_MODEL` / `VOXCPM_MODEL_DIR` | VoxCPM2 model name / local model directory. |
| `VOXCPM_MIN_REFERENCE_MS` | Minimum TTS reference length, default 1200 ms. |
| `DEMUCS_CHUNK_SECONDS` | Source-separation chunk length, default 600 seconds. |
| `RELEASE_GPU_MEMORY_AFTER_STAGE` | Default `true`: release model references and available device caches after each stage. |
| `LOCAL_UPLOAD_MAX_BYTES` / `LOCAL_SUBTITLE_MAX_BYTES` | Upload limits for local videos / SRT files. |
| `YTDLP_PROXY_PORT` / `HTTP_PROXY` / `ALL_PROXY` | Proxy configuration for downloads or API requests. |
| `NO_PROXY` | Include `localhost,127.0.0.1,::1` when using a local API. |
| `NEXT_SERVER_API_BASE_URL` | Backend URL in the frontend process environment; defaults to `http://127.0.0.1:8000`. |

Non-sensitive provider parameters are saved in task snapshots. Existing tasks can reuse those snapshots when rerun; global setting changes primarily affect new tasks.

<a id="data"></a>

## Local data and outputs

| Default path | Contents |
| --- | --- |
| `data/youdub.sqlite` | Tasks, subtitle segments, provider profiles, jobs, and login sessions. |
| `data/cookies/` | Cookies used for downloading. |
| `data/logs/` | Task execution logs. |
| `data/modelscope/` | Model cache; configurable with `MODEL_CACHE_DIR`. |
| `workfolder/_uploads/` | Uploaded local files. |
| `workfolder/<session>/metadata/` | Transcripts, translations, and timing information. |
| `workfolder/<session>/segments/` | Source clips, TTS files, previews, and time-stretched audio. |
| `workfolder/<session>/media/video_final.mp4` | Final rendered video. |

Set `WORKFOLDER` to change the task-artifact root. Environment files, runtime databases, cookies, logs, and media directories are excluded from Git. They may still contain sensitive content; review them before sharing.

On POSIX systems, startup restricts runtime directory and file permissions and rejects unsafe paths. Windows deployments need appropriate NTFS permissions configured separately. Access from other machines requires explicit listening addresses, an HTTPS reverse proxy, and `YOUDUB_AUTH_COOKIE_SECURE=true`; browsers should continue using the frontend's same-origin API.

<a id="development"></a>

## Development and checks

The frontend uses Next.js App Router, React, Tailwind CSS, and shadcn/ui. The backend uses FastAPI and SQLite, with yt-dlp, Demucs, Whisper, VoxCPM2, and FFmpeg for media processing.

```text
apps/web/              Next.js UI and frontend tests
backend/app/           API, database, worker, and pipeline
backend/app/providers/ Translation / TTS interfaces and defaults
backend/app/adapters/  Download, ASR, audio, and model adapters
backend/tests/         Backend tests
scripts/               Helper scripts
submodule/demucs/      Demucs source submodule
```

With dependencies installed, run:

```bash
.venv/bin/python -m pytest backend/tests -q
npm --prefix apps/web test
npm --prefix apps/web run lint
(cd apps/web && npx tsc --noEmit)
npm --prefix apps/web run build
```

On Windows, use the virtual environment's `python.exe`. For the type check, `cd apps/web`, run `npx tsc --noEmit`, and return to the repository root.

Backend unit tests can use a separate environment with only [backend/requirements-test.txt](backend/requirements-test.txt), without downloading models. The [CI workflow](.github/workflows/ci.yml) covers backend tests, frontend tests, linting, type checking, production builds, and dependency auditing. Automated checks do not establish translation or voice quality on real media.

<a id="contributing"></a>

## Contributing

Use [Issues](https://github.com/wind-far/dubloom/issues) for bugs and feature requests, and [Pull Requests](https://github.com/wind-far/dubloom/pulls) for code contributions. Include your OS, runtime versions, reproduction steps, and redacted logs in bug reports. Add relevant tests for functional changes and keep both README versions in sync.

<a id="license"></a>

## License

This project uses the [Apache License 2.0](LICENSE). Third-party dependencies and models remain subject to their respective licenses.
