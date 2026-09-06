export const AUTH_UNAUTHORIZED_EVENT = "youdub:auth-unauthorized"

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"])
const MAX_VALIDATION_ITEMS_INSPECTED = 20
const MAX_VALIDATION_MESSAGES = 3
const MAX_VALIDATION_MESSAGE_LENGTH = 240
let csrfToken = ""

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

export function isAbortError(error: unknown) {
  return error instanceof Error && error.name === "AbortError"
}

export type AuthSession = {
  authenticated: true
  csrf_token: string
  expires_at: string
}

type ResponseOptions = {
  emitUnauthorized?: boolean
}

function errorMessage(body: unknown, status: number) {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === "string" && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const messages: string[] = []
      for (const item of detail.slice(0, MAX_VALIDATION_ITEMS_INSPECTED)) {
        if (item && typeof item === "object" && "msg" in item) {
          const message = (item as { msg?: unknown }).msg
          if (typeof message === "string" && message.trim()) {
            const characters = Array.from(message.trim())
            const normalized = characters.length > MAX_VALIDATION_MESSAGE_LENGTH
              ? `${characters.slice(0, MAX_VALIDATION_MESSAGE_LENGTH - 1).join("")}…`
              : message.trim()
            if (!messages.includes(normalized)) messages.push(normalized)
          }
        }
        if (messages.length >= MAX_VALIDATION_MESSAGES) break
      }
      if (messages.length > 0) return messages.join("; ")
    }
  }
  return `Request failed: ${status}`
}

function emitUnauthorized() {
  csrfToken = ""
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT))
  }
}

async function parseResponse<T>(response: Response, options: ResponseOptions = {}): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    if (response.status === 401 && options.emitUnauthorized !== false) emitUnauthorized()
    throw new ApiError(errorMessage(body, response.status), response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function requestHeaders(options?: RequestInit) {
  const headers = new Headers(options?.headers)
  const method = (options?.method || "GET").toUpperCase()
  if (options?.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  if (UNSAFE_METHODS.has(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken)
  }
  return headers
}

export type StageStatus = "pending" | "running" | "succeeded" | "failed" | "skipped"
export type TaskStatus = "queued" | "running" | "paused" | "awaiting_review" | "succeeded" | "failed"
export type ExecutionMode = "auto" | "manual"
export type OutputMode = "subtitles" | "dubbing" | "both"
export type ReviewMode = "none" | "required"
export type ProviderKind = "translation" | "tts"
export type AudioMode = "tts" | "original"

export type TaskStage = {
  task_id: string
  name: string
  label: string
  status: StageStatus
  progress: number | null
  started_at: string | null
  completed_at: string | null
  last_message: string | null
  error_message: string | null
}

export type Task = {
  id: string
  url: string
  title: string | null
  status: TaskStatus
  current_stage: string | null
  session_path: string | null
  final_video_path: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  execution_mode: ExecutionMode
  output_mode: OutputMode
  review_mode?: ReviewMode
  result_stale?: boolean
  review_approved_at?: string | null
  translation_profile_id?: string | null
  tts_profile_id?: string | null
  stages: TaskStage[]
}

export type ProviderProfile = {
  id: string
  kind: ProviderKind
  name: string
  provider: string
  model: string | null
  config: Record<string, unknown>
  has_secrets: boolean
}

export type TaskSegment = {
  id: string
  task_id: string
  position: number
  source_text: string
  translated_text: string
  start_ms: number
  end_ms: number
  speaker: string | null
  audio_mode: AudioMode
  tts_profile_id: string | null
  revision: number
  dirty: boolean
  preview_status: "none" | "queued" | "running" | "generating" | "ready" | "failed"
  preview_path: string | null
  preview_error?: string | null
  warnings: Array<string | { code: string; message: string }>
}

export type Job = {
  id: string
  task_id: string
  job_type: "pipeline" | "segment_preview" | "dirty_render"
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled"
  progress: number | null
  error_message: string | null
}

export type TaskSegmentsResponse = {
  segments: TaskSegment[]
  task: Pick<Task, "id" | "status" | "review_mode" | "review_approved_at" | "result_stale">
}

export type CookieInfo = {
  exists: boolean
  size: number
  updated_at: number | null
  content: string
}

export type OpenAISettings = {
  base_url: string
  api_key: string
  has_api_key: boolean
  model: string
  translate_concurrency: string
}

export type OpenAIModels = {
  models: string[]
}

export type YtdlpSettings = {
  proxy_port: string
}

export type LocalDirection = "en-zh" | "ja-zh" | "zh-en"

async function request<T>(
  path: string,
  options?: RequestInit,
  responseOptions?: ResponseOptions,
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: requestHeaders(options),
    credentials: "include",
    cache: "no-store",
  })
  return parseResponse<T>(response, responseOptions)
}

export async function getAuthSession() {
  const session = await request<AuthSession>(
    "/api/auth/session",
    undefined,
    { emitUnauthorized: false },
  )
  csrfToken = session.csrf_token
  return session
}

export async function login(password: string) {
  csrfToken = ""
  const session = await request<AuthSession>(
    "/api/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ password }),
    },
    { emitUnauthorized: false },
  )
  csrfToken = session.csrf_token
  return session
}

export async function logout() {
  try {
    await request<void>("/api/auth/logout", { method: "POST" })
  } finally {
    csrfToken = ""
  }
}

export type TaskSummary = {
  id: string
  url: string
  title: string | null
  status: TaskStatus
  current_stage: string | null
  final_video_path: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  execution_mode?: ExecutionMode
  output_mode?: OutputMode
  review_mode?: ReviewMode
  result_stale?: boolean
  review_approved_at?: string | null
}

export type TaskListStatus = "all" | TaskStatus
export type TaskListExecutionMode = "all" | ExecutionMode
export type TaskListSort =
  | "created_desc"
  | "created_asc"
  | "started_desc"
  | "started_asc"
  | "completed_desc"
  | "completed_asc"
  | "status_asc"
  | "status_desc"
  | "title_asc"
  | "title_desc"

export type TaskListParams = {
  page?: number
  page_size?: number
  q?: string
  status?: TaskListStatus
  execution_mode?: TaskListExecutionMode
  sort?: TaskListSort
}

export type TaskListResponse = {
  tasks: TaskSummary[]
  total: number
  active_count: number
  page: number
  page_size: number
}

export function getCurrentTask() {
  return request<Task | null>("/api/tasks/current")
}

export async function getTaskLog(taskId: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(`/api/tasks/${taskId}/log`, {
    cache: "no-store",
    credentials: "include",
    signal,
  })
  if (!response.ok) return parseResponse<string>(response)
  return response.text()
}

export function listTasks(params: TaskListParams | number = {}, signal?: AbortSignal) {
  const normalized = typeof params === "number" ? { page_size: params } : params
  const search = new URLSearchParams()

  Object.entries(normalized).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return
    search.set(key, String(value))
  })

  const query = search.toString()
  return request<TaskListResponse>(
    `/api/tasks${query ? `?${query}` : ""}`,
    signal ? { signal } : undefined,
  )
}

export function getTask(taskId: string, signal?: AbortSignal) {
  return request<Task>(`/api/tasks/${taskId}`, signal ? { signal } : undefined)
}

export function deleteTask(taskId: string) {
  return request<void>(`/api/tasks/${taskId}`, { method: "DELETE" })
}

export function rerunTask(taskId: string) {
  return request<Task>(`/api/tasks/${taskId}/rerun`, { method: "POST" })
}

export function resumeTask(taskId: string) {
  return request<Task>(`/api/tasks/${taskId}/resume`, { method: "POST" })
}

export function continueTask(taskId: string, executionMode?: ExecutionMode) {
  return request<Task>(`/api/tasks/${taskId}/continue`, {
    method: "POST",
    body: JSON.stringify(executionMode ? { execution_mode: executionMode } : {}),
  })
}

export function redoStage(taskId: string, stageName: string) {
  return request<Task>(`/api/tasks/${taskId}/stages/${stageName}/redo`, { method: "POST" })
}

export function createTask(
  url: string,
  executionMode: ExecutionMode = "auto",
  outputMode: OutputMode = "both",
  reviewMode: ReviewMode = "none",
  translationProfileId?: string,
  ttsProfileId?: string,
) {
  return request<Task>("/api/tasks", {
    method: "POST",
    body: JSON.stringify({
      url,
      execution_mode: executionMode,
      output_mode: outputMode,
      review_mode: reviewMode,
      translation_profile_id: translationProfileId || null,
      tts_profile_id: ttsProfileId || null,
    }),
  })
}

export async function uploadLocalTask(
  file: File,
  direction: LocalDirection,
  subtitleFile: File | null = null,
  executionMode: ExecutionMode = "auto",
  outputMode: OutputMode = "both",
  reviewMode: ReviewMode = "none",
  translationProfileId?: string,
  ttsProfileId?: string,
) {
  const form = new FormData()
  form.append("direction", direction)
  form.append("file", file)
  if (subtitleFile) {
    form.append("subtitle_file", subtitleFile)
  }
  form.append("execution_mode", executionMode)
  form.append("output_mode", outputMode)
  form.append("review_mode", reviewMode)
  if (translationProfileId) form.append("translation_profile_id", translationProfileId)
  if (ttsProfileId) form.append("tts_profile_id", ttsProfileId)

  const options: RequestInit = {
    method: "POST",
    body: form,
  }
  const response = await fetch("/api/tasks/upload", {
    ...options,
    headers: requestHeaders(options),
    credentials: "include",
    cache: "no-store",
  })
  return parseResponse<Task>(response)
}

export function getCookieInfo() {
  return request<CookieInfo>("/api/cookies/youtube")
}

export function saveCookie(content: string) {
  return request<CookieInfo>("/api/cookies/youtube", {
    method: "POST",
    body: JSON.stringify({ content }),
  })
}

export function getOpenAISettings() {
  return request<OpenAISettings>("/api/settings/openai")
}

export function saveOpenAISettings(settings: {
  base_url: string
  api_key: string
  clear_api_key?: boolean
  model: string
  translate_concurrency: string
}) {
  return request<OpenAISettings>("/api/settings/openai", {
    method: "POST",
    body: JSON.stringify(settings),
  })
}

export function getOpenAIModels(settings: {
  base_url: string
  api_key: string
}) {
  return request<OpenAIModels>("/api/settings/openai/models", {
    method: "POST",
    body: JSON.stringify(settings),
  })
}

export function getYtdlpSettings() {
  return request<YtdlpSettings>("/api/settings/ytdlp")
}

export function saveYtdlpSettings(settings: YtdlpSettings) {
  return request<YtdlpSettings>("/api/settings/ytdlp", {
    method: "POST",
    body: JSON.stringify(settings),
  })
}

export function finalVideoUrl(taskId: string) {
  return `/api/tasks/${taskId}/artifact/final-video`
}

export function finalVideoDownloadUrl(taskId: string) {
  return `/api/tasks/${taskId}/artifact/final-video?download=1`
}

export function sourceVideoUrl(taskId: string) {
  return `/api/tasks/${taskId}/artifact/source-video`
}

export function listProviderProfiles(kind?: ProviderKind, signal?: AbortSignal) {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : ""
  return request<ProviderProfile[]>(
    `/api/provider-profiles${query}`,
    signal ? { signal } : undefined,
  )
}

export function createProviderProfile(profile: Omit<ProviderProfile, "id" | "has_secrets"> & { secrets?: Record<string, string> }) {
  return request<ProviderProfile>("/api/provider-profiles", {
    method: "POST",
    body: JSON.stringify(profile),
  })
}

export function updateProviderProfile(
  profileId: string,
  profile: Partial<Omit<ProviderProfile, "id" | "has_secrets">> & { secrets?: Record<string, string> },
) {
  return request<ProviderProfile>(`/api/provider-profiles/${profileId}`, {
    method: "PATCH",
    body: JSON.stringify(profile),
  })
}

export function deleteProviderProfile(profileId: string) {
  return request<void>(`/api/provider-profiles/${profileId}`, { method: "DELETE" })
}

export function listTaskSegments(taskId: string, signal?: AbortSignal) {
  return request<TaskSegmentsResponse>(
    `/api/tasks/${taskId}/segments`,
    signal ? { signal } : undefined,
  )
}

export type SegmentUpdate = Pick<
  TaskSegment,
  "translated_text" | "start_ms" | "end_ms" | "speaker" | "audio_mode" | "tts_profile_id"
> & { expected_revision: number }

export function updateTaskSegment(taskId: string, segmentId: string, update: SegmentUpdate) {
  return request<TaskSegment>(`/api/tasks/${taskId}/segments/${segmentId}`, {
    method: "PATCH",
    body: JSON.stringify(update),
  })
}

export function createSegmentPreview(taskId: string, segmentId: string) {
  return request<Job>(`/api/tasks/${taskId}/segments/${segmentId}/preview`, { method: "POST" })
}

export function segmentAudioUrl(taskId: string, segmentId: string, kind: "source" | "preview") {
  return `/api/tasks/${taskId}/segments/${segmentId}/audio?kind=${kind}`
}

export function approveTaskReview(taskId: string) {
  return request<Task & { job_id?: string }>(`/api/tasks/${taskId}/review/approve`, { method: "POST" })
}

export function renderDirtySegments(taskId: string) {
  return request<Job | (Task & { job_id: string })>(`/api/tasks/${taskId}/render-dirty`, { method: "POST" })
}

export function getJob(jobId: string, signal?: AbortSignal) {
  return request<Job>(`/api/jobs/${jobId}`, signal ? { signal } : undefined)
}
