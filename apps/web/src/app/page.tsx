"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { ChangeEvent, FormEvent, useCallback, useRef, useState } from "react"
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Clock3,
  Film,
  Languages,
  LayoutDashboard,
  ListVideo,
  Mic2,
  Play,
  Plus,
  Search,
  Upload,
  Workflow,
} from "lucide-react"

import {
  ExecutionMode,
  LocalDirection,
  OutputMode,
  ProviderProfile,
  ReviewMode,
  TaskListExecutionMode,
  TaskListResponse,
  TaskListSort,
  TaskListStatus,
  TaskSummary,
  createTask,
  isAbortError,
  listProviderProfiles,
  listTasks,
  uploadLocalTask,
} from "@/lib/api"
import { useI18n } from "@/lib/i18n"
import { statusBadgeClass } from "@/lib/status"
import { SerialPollingContext, useSerialPolling } from "@/lib/use-serial-polling"
import uploadContract from "@/lib/upload-contract.json"
import { AppHeader } from "@/components/app-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select"

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]
const TASK_SEARCH_MAX_LENGTH = 200
const LOCAL_VIDEO_ACCEPT = uploadContract.video_extensions.join(",")

function truncateSearchQuery(value: string) {
  return Array.from(value).slice(0, TASK_SEARCH_MAX_LENGTH).join("")
}

function isActive(status: string) {
  return status === "queued" || status === "running"
}

function isAwaitingAction(status: string) {
  return status === "paused" || status === "awaiting_review"
}

function formatTime(value: string | null) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function shortUrl(url: string) {
  return url.replace(/^https?:\/\/(www\.)?/, "")
}

function selectedLabel<T extends string>(options: { value: T; label: string }[], value: T) {
  return options.find((option) => option.value === value)?.label || value
}

function pageRangeText(language: string, start: number, end: number, total: number) {
  if (language === "zh") return `显示 ${start}-${end} / 共 ${total} 个任务`
  return `Showing ${start}-${end} of ${total} tasks`
}

function pageIndexText(language: string, page: number, totalPages: number) {
  if (language === "zh") return `第 ${page} / ${totalPages} 页`
  return `Page ${page} / ${totalPages}`
}

export default function Home() {
  const router = useRouter()
  const { activeTasksText, language, stageLabel, statusLabel, t } = useI18n()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const subtitleInputRef = useRef<HTMLInputElement>(null)
  const [youtubeUrl, setYoutubeUrl] = useState("")
  const [bilibiliUrl, setBilibiliUrl] = useState("")
  const [localFile, setLocalFile] = useState<File | null>(null)
  const [localSubtitleFile, setLocalSubtitleFile] = useState<File | null>(null)
  const [localDirection, setLocalDirection] = useState<LocalDirection>("en-zh")
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("auto")
  const [outputMode, setOutputMode] = useState<OutputMode>("both")
  const [reviewMode, setReviewMode] = useState<ReviewMode>("required")
  const [providerProfiles, setProviderProfiles] = useState<ProviderProfile[]>([])
  const [providerProfilesLoaded, setProviderProfilesLoaded] = useState(false)
  const [translationProfileId, setTranslationProfileId] = useState("default")
  const [ttsProfileId, setTtsProfileId] = useState("default")
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [taskTotal, setTaskTotal] = useState(0)
  const [activeTaskCount, setActiveTaskCount] = useState<number | null>(null)
  const [taskPage, setTaskPage] = useState(1)
  const [taskPageSize, setTaskPageSize] = useState(20)
  const [taskQuery, setTaskQuery] = useState("")
  const [taskStatus, setTaskStatus] = useState<TaskListStatus>("all")
  const [taskExecutionMode, setTaskExecutionMode] = useState<TaskListExecutionMode>("all")
  const [taskSort, setTaskSort] = useState<TaskListSort>("created_desc")
  const [error, setError] = useState("")
  const [taskListError, setTaskListError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const localDirectionOptions: { value: LocalDirection; label: string }[] = [
    { value: "en-zh", label: t.home.localEnZh },
    { value: "ja-zh", label: t.home.localJaZh },
    { value: "zh-en", label: t.home.localZhEn },
  ]

  const executionModeOptions: { value: ExecutionMode; label: string }[] = [
    { value: "auto", label: t.home.executionAuto },
    { value: "manual", label: t.home.executionManual },
  ]

  const outputModeOptions: { value: OutputMode; label: string }[] = [
    { value: "subtitles", label: t.home.outputSubtitles },
    { value: "dubbing", label: t.home.outputDubbing },
    { value: "both", label: t.home.outputBoth },
  ]

  const reviewModeOptions: { value: ReviewMode; label: string }[] = [
    { value: "required", label: t.home.reviewRequired },
    { value: "none", label: t.home.reviewNone },
  ]

  const translationProfiles = providerProfiles.filter((profile) => profile.kind === "translation")
  const ttsProfiles = providerProfiles.filter((profile) => profile.kind === "tts")

  const statusOptions: { value: TaskListStatus; label: string }[] = [
    { value: "all", label: t.home.allStatuses },
    { value: "queued", label: statusLabel("queued") },
    { value: "running", label: statusLabel("running") },
    { value: "paused", label: statusLabel("paused") },
    { value: "awaiting_review", label: statusLabel("awaiting_review") },
    { value: "succeeded", label: statusLabel("succeeded") },
    { value: "failed", label: statusLabel("failed") },
  ]

  const modeOptions: { value: TaskListExecutionMode; label: string }[] = [
    { value: "all", label: t.home.allModes },
    { value: "auto", label: t.home.modeAuto },
    { value: "manual", label: t.home.modeManual },
  ]

  const sortOptions: { value: TaskListSort; label: string }[] = [
    { value: "created_desc", label: t.home.sortCreatedDesc },
    { value: "created_asc", label: t.home.sortCreatedAsc },
    { value: "started_desc", label: t.home.sortStartedDesc },
    { value: "started_asc", label: t.home.sortStartedAsc },
    { value: "completed_desc", label: t.home.sortCompletedDesc },
    { value: "completed_asc", label: t.home.sortCompletedAsc },
    { value: "status_asc", label: t.home.sortStatusAsc },
    { value: "status_desc", label: t.home.sortStatusDesc },
    { value: "title_asc", label: t.home.sortTitleAsc },
    { value: "title_desc", label: t.home.sortTitleDesc },
  ]

  const applyTaskList = useCallback((result: TaskListResponse) => {
    const lastPage = Math.max(1, Math.ceil(result.total / result.page_size))
    setTaskTotal(result.total)
    setActiveTaskCount(
      Number.isInteger(result.active_count) && result.active_count >= 0
        ? result.active_count
        : null,
    )
    if (result.total > 0 && result.tasks.length === 0 && result.page > lastPage) {
      setTasks([])
      setTaskPage(lastPage)
      return
    }
    setTasks(result.tasks)
  }, [])

  const pollTasks = useCallback(async ({ signal, isCurrent }: SerialPollingContext) => {
    try {
      const result = await listTasks({
        page: taskPage,
        page_size: taskPageSize,
        q: taskQuery,
        status: taskStatus,
        execution_mode: taskExecutionMode,
        sort: taskSort,
      }, signal)
      if (isCurrent()) {
        setTaskListError("")
        applyTaskList(result)
      }
    } catch (err) {
      if (isCurrent() && !isAbortError(err)) {
        setTaskListError(err instanceof Error ? err.message : t.home.loadError)
      }
    }
  }, [
    applyTaskList,
    taskExecutionMode,
    taskPage,
    taskPageSize,
    taskQuery,
    taskSort,
    taskStatus,
    t.home.loadError,
  ])

  useSerialPolling(pollTasks)

  const loadProviderProfiles = useCallback(() => {
    if (providerProfilesLoaded) return
    setProviderProfilesLoaded(true)
    listProviderProfiles()
      .then(setProviderProfiles)
      .catch(() => setProviderProfiles([]))
  }, [providerProfilesLoaded])

  function resetTaskPage() {
    setTaskPage(1)
  }

  function selectLocalFile(event: ChangeEvent<HTMLInputElement>) {
    setError("")
    setLocalFile(event.target.files?.[0] || null)
    setLocalSubtitleFile(null)
    if (subtitleInputRef.current) {
      subtitleInputRef.current.value = ""
    }
  }

  function selectLocalSubtitleFile(event: ChangeEvent<HTMLInputElement>) {
    setError("")
    setLocalSubtitleFile(event.target.files?.[0] || null)
  }

  async function submitTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError("")
    const submittedUrl = youtubeUrl.trim() || bilibiliUrl.trim()
    if (!submittedUrl && !localFile) return
    setSubmitting(true)
    try {
      const created = localFile
        ? await uploadLocalTask(
          localFile,
          localDirection,
          localSubtitleFile,
          executionMode,
          outputMode,
          reviewMode,
          translationProfileId === "default" ? undefined : translationProfileId,
          ttsProfileId === "default" ? undefined : ttsProfileId,
        )
        : await createTask(
          submittedUrl,
          executionMode,
          outputMode,
          reviewMode,
          translationProfileId === "default" ? undefined : translationProfileId,
          ttsProfileId === "default" ? undefined : ttsProfileId,
        )
      setYoutubeUrl("")
      setBilibiliUrl("")
      setLocalFile(null)
      setLocalSubtitleFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
      if (subtitleInputRef.current) {
        subtitleInputRef.current.value = ""
      }
      router.push(`/tasks/${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : t.home.createError)
    } finally {
      setSubmitting(false)
    }
  }

  const hasUrl = Boolean(youtubeUrl.trim() || bilibiliUrl.trim())
  const hasLocalFile = Boolean(localFile)
  const canSubmit = Boolean((hasUrl || hasLocalFile) && !submitting)
  const totalPages = Math.max(1, Math.ceil(taskTotal / taskPageSize))
  const displayPage = Math.min(taskPage, totalPages)
  const pageStart = taskTotal === 0 ? 0 : (displayPage - 1) * taskPageSize + 1
  const pageEnd = Math.min(taskTotal, displayPage * taskPageSize)
  const hasTaskFilters = Boolean(taskQuery.trim()) || taskStatus !== "all" || taskExecutionMode !== "all"
  const selectContentClass = "border-border bg-white/96 text-foreground shadow-xl backdrop-blur-2xl"
  const fieldClass = "border-input bg-white/84 text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-primary/15"
  const selectTriggerClass = "h-9 border-input bg-white/84 text-foreground focus-visible:border-primary focus-visible:ring-primary/15"

  return (
    <main
      aria-label={language === "zh" ? "织声视频生产工作台" : "Dubloom video production workspace"}
      className="min-h-screen text-foreground selection:bg-primary/20"
    >
      <div className="pointer-events-none fixed inset-x-0 top-0 h-80 bg-[radial-gradient(circle_at_70%_-10%,rgba(0,122,255,0.12),transparent_55%)]" />
      <div className="relative mx-auto grid min-h-screen w-full max-w-[1720px] grid-cols-1 gap-3 p-3 sm:p-4 lg:grid-cols-[224px_minmax(0,1fr)_380px] lg:gap-4 lg:p-5">
        <aside className="apple-material order-1 rounded-2xl p-4 lg:sticky lg:top-5 lg:flex lg:h-[calc(100vh-2.5rem)] lg:flex-col">
          <div className="[&_header]:!flex-col [&_header]:!items-stretch [&_header]:gap-5 [&_header]:border-0 [&_header]:pb-0 [&_header>div:first-child]:justify-center [&_header>div:last-child]:grid [&_header>div:last-child]:grid-cols-2 [&_header_button]:border-border [&_header_button]:bg-white/55 [&_header_button]:text-foreground/75 [&_header_button:hover]:bg-white [&_header_button:hover]:text-foreground">
            <AppHeader />
          </div>

          <nav className="mt-7 hidden space-y-1 lg:block" aria-label={language === "zh" ? "织声工作台导航" : "Dubloom workspace navigation"}>
            <a href="#task-queue" className="flex items-center gap-3 rounded-xl bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-sm">
              <LayoutDashboard className="size-4" />
              {language === "zh" ? "任务工作台" : "Task workspace"}
            </a>
            <a href="#create-task" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-black/[0.045] hover:text-foreground">
              <Plus className="size-4" />
              {t.home.createTitle}
            </a>
            <a href="#task-queue" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-black/[0.045] hover:text-foreground">
              <ListVideo className="size-4" />
              {t.home.taskHistory}
            </a>
          </nav>

          <div className="mt-7 hidden lg:block">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <Workflow className="size-3.5" />
              {language === "zh" ? "生产流程" : "Production flow"}
            </div>
            <ol className="mt-4 space-y-0">
              {[
                { icon: Film, zh: "输入素材", en: "Input", noteZh: "链接或本地视频", noteEn: "URL or local video" },
                { icon: Languages, zh: "翻译处理", en: "Process", noteZh: "识别、翻译与分离", noteEn: "ASR, translation, stems" },
                { icon: CheckCircle2, zh: "人工校审", en: "Review", noteZh: "逐句核对与试听", noteEn: "Edit and preview" },
                { icon: Mic2, zh: "成片输出", en: "Output", noteZh: "配音、混音与字幕", noteEn: "Voice, mix, subtitles" },
              ].map((step, index) => (
                <li key={step.en} className="relative flex gap-3 pb-5 last:pb-0">
                  {index < 3 ? <span className="absolute left-[13px] top-7 h-[calc(100%-1.25rem)] w-px bg-black/8" /> : null}
                  <span className="relative flex size-7 shrink-0 items-center justify-center rounded-full border border-border bg-white/70 text-muted-foreground shadow-sm">
                    <step.icon className="size-3.5" />
                  </span>
                  <div className="pt-0.5">
                    <p className="text-xs font-medium text-foreground/85">{language === "zh" ? step.zh : step.en}</p>
                    <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{language === "zh" ? step.noteZh : step.noteEn}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <div className="apple-inset mt-auto hidden rounded-xl p-3 lg:block">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <CircleDot className="size-3.5 text-emerald-600" />
              {activeTaskCount !== null && activeTaskCount > 0
                ? activeTasksText(activeTaskCount)
                : language === "zh" ? "工作节点就绪" : "Worker ready"}
            </div>
          </div>
        </aside>

        <section id="task-queue" className="order-3 min-w-0 lg:order-2">
          <Card className="h-full gap-0 rounded-2xl py-0">
            <CardHeader className="border-b border-border px-4 py-4 sm:px-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary/80">
                    {language === "zh" ? "Production queue" : "Production queue"}
                  </p>
                  <CardTitle className="mt-1 text-lg font-semibold text-foreground">
                    {t.home.taskHistory} <span className="font-normal text-muted-foreground">{taskTotal}</span>
                  </CardTitle>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Clock3 className="size-3.5" />
                  {language === "zh" ? "自动刷新任务状态" : "Live task status"}
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-0">
              <div className="border-b border-border px-4 py-3 sm:px-5">
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-[minmax(180px,1fr)_132px_132px_168px_88px]">
                  <div className="relative sm:col-span-2 xl:col-span-1">
                    <Label htmlFor="task-search" className="sr-only">{t.home.taskSearchPlaceholder}</Label>
                    <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                    <Input
                      id="task-search"
                      className={`h-9 pl-8 ${fieldClass}`}
                      value={taskQuery}
                      onChange={(event) => {
                        setTaskQuery(truncateSearchQuery(event.target.value))
                        resetTaskPage()
                      }}
                      placeholder={t.home.taskSearchPlaceholder}
                    />
                  </div>
                  <div>
                    <Label htmlFor="task-status-filter" className="sr-only">{t.home.taskStatusFilter}</Label>
                    <Select value={taskStatus} onValueChange={(value) => { setTaskStatus(value as TaskListStatus); resetTaskPage() }}>
                      <SelectTrigger id="task-status-filter" className={selectTriggerClass}>
                        <span className="min-w-0 truncate text-left">{selectedLabel(statusOptions, taskStatus)}</span>
                      </SelectTrigger>
                      <SelectContent className={selectContentClass}>
                        {statusOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label htmlFor="task-mode-filter" className="sr-only">{t.home.taskModeFilter}</Label>
                    <Select value={taskExecutionMode} onValueChange={(value) => { setTaskExecutionMode(value as TaskListExecutionMode); resetTaskPage() }}>
                      <SelectTrigger id="task-mode-filter" className={selectTriggerClass}>
                        <span className="min-w-0 truncate text-left">{selectedLabel(modeOptions, taskExecutionMode)}</span>
                      </SelectTrigger>
                      <SelectContent className={selectContentClass}>
                        {modeOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label htmlFor="task-sort" className="sr-only">{t.home.taskSort}</Label>
                    <Select value={taskSort} onValueChange={(value) => { setTaskSort(value as TaskListSort); resetTaskPage() }}>
                      <SelectTrigger id="task-sort" className={selectTriggerClass}>
                        <span className="min-w-0 truncate text-left">{selectedLabel(sortOptions, taskSort)}</span>
                      </SelectTrigger>
                      <SelectContent className={selectContentClass}>
                        {sortOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label htmlFor="task-page-size" className="sr-only">{t.home.taskPageSize}</Label>
                    <Select value={String(taskPageSize)} onValueChange={(value) => { setTaskPageSize(Number(value)); resetTaskPage() }}>
                      <SelectTrigger id="task-page-size" className={selectTriggerClass}>
                        <span className="min-w-0 truncate text-left">{taskPageSize}</span>
                      </SelectTrigger>
                      <SelectContent className={selectContentClass}>
                        {PAGE_SIZE_OPTIONS.map((option) => <SelectItem key={option} value={String(option)}>{option}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>

              {taskListError ? (
                <div className="mx-4 mt-4 rounded-lg border border-red-400/20 bg-red-400/8 px-3 py-2 text-sm text-red-300">{taskListError}</div>
              ) : null}

              {tasks.length === 0 ? (
                <div className="flex min-h-72 flex-col items-center justify-center px-6 py-12 text-center">
                  <span className="flex size-12 items-center justify-center rounded-2xl bg-black/[0.045] text-muted-foreground"><ListVideo className="size-5" /></span>
                  <p className="mt-4 max-w-sm text-sm text-muted-foreground">{hasTaskFilters ? t.home.noMatchingTasks : t.home.empty}</p>
                </div>
              ) : (
                <ScrollArea className="max-h-[calc(100dvh-15.5rem)] min-h-[24rem] overflow-hidden">
                  <ul className="flex flex-col">
                    {tasks.map((item) => (
                      <li key={item.id} className="border-b border-border last:border-b-0">
                        <Link href={`/tasks/${item.id}`} className="group grid w-full gap-3 px-4 py-3.5 text-sm transition-colors hover:bg-primary/[0.045] sm:px-5 xl:grid-cols-[minmax(0,1fr)_150px_140px_24px] xl:items-center">
                          <div className="min-w-0">
                            <p className="truncate text-left font-medium text-foreground transition-colors group-hover:text-black">{item.title || shortUrl(item.url)}</p>
                            <p className="mt-1 truncate text-xs text-muted-foreground">{shortUrl(item.url)}</p>
                          </div>
                          <div className="flex min-w-0 items-center gap-2 xl:block">
                            <Badge className={statusBadgeClass(item.status)}>{statusLabel(item.status)}</Badge>
                            <p className="truncate text-xs text-muted-foreground xl:mt-1.5">
                              {(isActive(item.status) || isAwaitingAction(item.status)) && item.current_stage
                                ? stageLabel(item.current_stage)
                                : item.execution_mode === "manual"
                                  ? t.home.modeManual
                                  : t.home.modeAuto}
                            </p>
                          </div>
                          <div className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground xl:block">
                            <span data-testid={`task-output-mode-${item.id}`}>{selectedLabel(outputModeOptions, item.output_mode || "both")}</span>
                            <span className="xl:mt-1.5 xl:block">{formatTime(item.created_at)}</span>
                          </div>
                          <ChevronRight className="hidden size-4 text-black/25 transition-all group-hover:translate-x-0.5 group-hover:text-primary xl:block" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </ScrollArea>
              )}

              {taskTotal > 0 ? (
                <div className="flex flex-col gap-3 border-t border-border px-4 py-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-5">
                  <span>{pageRangeText(language, pageStart, pageEnd, taskTotal)}</span>
                  <div className="flex items-center justify-between gap-3 sm:justify-end">
                    <span>{pageIndexText(language, displayPage, totalPages)}</span>
                    <div className="flex items-center gap-1.5">
                      <Button type="button" variant="outline" size="sm" onClick={() => setTaskPage((page) => Math.max(1, page - 1))} disabled={displayPage <= 1}>
                        <ChevronLeft className="size-4" />{t.home.previousPage}
                      </Button>
                      <Button type="button" variant="outline" size="sm" onClick={() => setTaskPage((page) => Math.min(totalPages, page + 1))} disabled={displayPage >= totalPages}>
                        {t.home.nextPage}<ChevronRight className="size-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </section>

        <aside id="create-task" className="order-2 lg:order-3 lg:sticky lg:top-5 lg:h-[calc(100vh-2.5rem)] lg:overflow-y-auto">
          <Card className="gap-0 rounded-2xl py-0">
            <CardHeader className="border-b border-border px-4 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary/70">New production</p>
                  <CardTitle className="mt-1 text-lg font-semibold text-foreground">{t.home.createTitle}</CardTitle>
                </div>
                <span className="flex size-9 items-center justify-center rounded-lg bg-primary/12 text-primary ring-1 ring-primary/20"><Plus className="size-4" /></span>
              </div>
              <div className="mt-3 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                <span className="text-primary">Input</span><ChevronRight className="size-3" /><span>Process</span><ChevronRight className="size-3" /><span>Review</span><ChevronRight className="size-3" /><span>Output</span>
              </div>
            </CardHeader>
            <CardContent className="p-4">
              <form onSubmit={submitTask} className="space-y-4">
                <div className="apple-inset rounded-xl p-3">
                  <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{language === "zh" ? "输入来源" : "Input source"}</p>
              <div className="space-y-2">
                <Label htmlFor="youtube-url">{t.home.youtubeLabel}</Label>
                <Input
                  id="youtube-url"
                  value={youtubeUrl}
                  onChange={(event) => setYoutubeUrl(event.target.value)}
                  placeholder="https://www.youtube.com/watch?v=..."
                  disabled={Boolean(bilibiliUrl.trim()) || hasLocalFile}
                  className={fieldClass}
                />
              </div>
              <div className="mt-3 space-y-2">
                <Label htmlFor="bilibili-url">{t.home.bilibiliLabel}</Label>
                <Input
                  id="bilibili-url"
                  value={bilibiliUrl}
                  onChange={(event) => setBilibiliUrl(event.target.value)}
                  placeholder="https://www.bilibili.com/video/BV..."
                  disabled={Boolean(youtubeUrl.trim()) || hasLocalFile}
                  className={fieldClass}
                />
              </div>
              <div className="my-3 flex items-center gap-3 text-[10px] uppercase tracking-[0.12em] text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">or</div>
              <div className="grid gap-3 sm:grid-cols-[1fr_132px] lg:grid-cols-1 xl:grid-cols-[1fr_132px]">
                <div className="space-y-2">
                  <Label htmlFor="local-video">{t.home.localVideoLabel}</Label>
                  <Input
                    ref={fileInputRef}
                    id="local-video"
                    type="file"
                    accept={LOCAL_VIDEO_ACCEPT}
                    onChange={selectLocalFile}
                    disabled={hasUrl}
                    className={`${fieldClass} file:text-muted-foreground`}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="local-direction">{t.home.localDirectionLabel}</Label>
                  <Select
                    value={localDirection}
                    onValueChange={(value) => setLocalDirection(value as LocalDirection)}
                    disabled={hasUrl}
                  >
                    <SelectTrigger id="local-direction" className={selectTriggerClass}>
                      <span className="min-w-0 truncate text-left">
                        {selectedLabel(localDirectionOptions, localDirection)}
                      </span>
                    </SelectTrigger>
                    <SelectContent className={selectContentClass}>
                      {localDirectionOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="mt-3 space-y-2">
                <Label htmlFor="local-subtitle">{t.home.localSubtitleLabel}</Label>
                <Input
                  ref={subtitleInputRef}
                  id="local-subtitle"
                  type="file"
                  accept=".srt"
                  onChange={selectLocalSubtitleFile}
                  disabled={hasUrl || !hasLocalFile}
                  className={`${fieldClass} file:text-muted-foreground`}
                />
                <p className="text-xs text-muted-foreground">
                  {t.home.localSubtitleHelp}
                </p>
                {localFile ? (
                  <div data-testid="local-upload-selection" className="rounded-xl border border-primary/15 bg-primary/5 px-3 py-2 text-xs text-muted-foreground"
                    aria-live="polite"
                  >
                    <p>
                      {t.home.currentLocalVideo}: <span className="font-medium text-foreground">{localFile.name}</span>
                    </p>
                    <p>
                      {t.home.subtitleForCurrentVideo}:{" "}
                      <span className="font-medium text-foreground">
                        {localSubtitleFile?.name || t.home.noSubtitleSelected}
                      </span>
                    </p>
                  </div>
                ) : null}
              </div>
                </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="output-mode">{t.home.outputModeLabel}</Label>
                  <Select
                    value={outputMode}
                    onValueChange={(value) => setOutputMode(value as OutputMode)}
                  >
                    <SelectTrigger id="output-mode" className={selectTriggerClass}>
                      <span className="min-w-0 truncate text-left">
                        {selectedLabel(outputModeOptions, outputMode)}
                      </span>
                    </SelectTrigger>
                    <SelectContent className={selectContentClass}>
                      {outputModeOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="execution-mode">{t.home.executionModeLabel}</Label>
                  <Select
                    value={executionMode}
                    onValueChange={(value) => setExecutionMode(value as ExecutionMode)}
                  >
                    <SelectTrigger id="execution-mode" className={selectTriggerClass}>
                      <span className="min-w-0 truncate text-left">
                        {selectedLabel(executionModeOptions, executionMode)}
                      </span>
                    </SelectTrigger>
                    <SelectContent className={selectContentClass}>
                      {executionModeOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
                <div className="space-y-2">
                  <Label htmlFor="review-mode">{t.home.reviewModeLabel}</Label>
                  <Select value={reviewMode} onValueChange={(value) => setReviewMode(value as ReviewMode)}>
                    <SelectTrigger id="review-mode" className={selectTriggerClass}>
                      <span className="min-w-0 truncate text-left">
                        {selectedLabel(reviewModeOptions, reviewMode)}
                      </span>
                    </SelectTrigger>
                    <SelectContent className={selectContentClass}>
                      {reviewModeOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="translation-profile">{t.home.translationProfile}</Label>
                  <Select value={translationProfileId} onValueChange={(value) => value && setTranslationProfileId(value)}>
                    <SelectTrigger id="translation-profile" className={selectTriggerClass} onPointerDown={loadProviderProfiles} onFocus={loadProviderProfiles}>
                      <span className="min-w-0 truncate text-left">
                        {translationProfileId === "default"
                          ? t.home.defaultProfile
                          : translationProfiles.find((profile) => profile.id === translationProfileId)?.name || translationProfileId}
                      </span>
                    </SelectTrigger>
                    <SelectContent className={selectContentClass}>
                      <SelectItem value="default">{t.home.defaultProfile}</SelectItem>
                      {translationProfiles.map((profile) => (
                        <SelectItem key={profile.id} value={profile.id}>{profile.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="tts-profile">{t.home.ttsProfile}</Label>
                  <Select value={ttsProfileId} onValueChange={(value) => value && setTtsProfileId(value)}>
                    <SelectTrigger id="tts-profile" className={selectTriggerClass} onPointerDown={loadProviderProfiles} onFocus={loadProviderProfiles}>
                      <span className="min-w-0 truncate text-left">
                        {ttsProfileId === "default"
                          ? t.home.defaultProfile
                          : ttsProfiles.find((profile) => profile.id === ttsProfileId)?.name || ttsProfileId}
                      </span>
                    </SelectTrigger>
                    <SelectContent className={selectContentClass}>
                      <SelectItem value="default">{t.home.defaultProfile}</SelectItem>
                      {ttsProfiles.map((profile) => (
                        <SelectItem key={profile.id} value={profile.id}>{profile.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
                <p className="text-xs text-muted-foreground">
                  {reviewMode === "required" ? selectedLabel(reviewModeOptions, reviewMode) : selectedLabel(executionModeOptions, executionMode)}
                </p>
                <Button type="submit" className="h-9 px-4" disabled={!canSubmit}>
                  {hasLocalFile ? <Upload className="size-4" /> : <Play className="size-4" />}
                  {submitting ? t.home.submitting : t.home.createTask}
                </Button>
              </div>
            </form>

            {error ? (
              <div className="mt-4 rounded-lg border border-red-400/20 bg-red-400/8 px-3 py-2 text-sm text-red-300">
                {error}
              </div>
            ) : null}
            </CardContent>
          </Card>
        </aside>
      </div>
    </main>
  )
}
