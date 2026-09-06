"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { use, useCallback, useMemo, useState } from "react"
import {
  Activity,
  CheckCircle2,
  Circle,
  CircleMinus,
  Download,
  ExternalLink,
  FileText,
  Film,
  Gauge,
  Loader2,
  Play,
  RotateCw,
  Terminal,
  Trash2,
  Workflow,
  XCircle,
  AlertTriangle,
  Languages,
} from "lucide-react"

import {
  ExecutionMode,
  StageStatus,
  Task,
  continueTask,
  deleteTask,
  finalVideoDownloadUrl,
  finalVideoUrl,
  getTask,
  getTaskLog,
  isAbortError,
  redoStage,
  rerunTask,
  resumeTask,
  renderDirtySegments,
} from "@/lib/api"
import { useI18n } from "@/lib/i18n"
import { statusBadgeClass } from "@/lib/status"
import { SerialPollingContext, useSerialPolling } from "@/lib/use-serial-polling"
import { AppHeader } from "@/components/app-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"

function stageIcon(status: StageStatus) {
  if (status === "succeeded") return <CheckCircle2 className="size-4 text-emerald-600" />
  if (status === "skipped") return <CircleMinus className="size-4 text-muted-foreground" />
  if (status === "failed") return <XCircle className="size-4 text-rose-600" />
  if (status === "running") return <Loader2 className="size-4 animate-spin text-primary" />
  return <Circle className="size-4 text-black/25" />
}

function formatTime(value: string | null) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function durationOf(start: string | null, end: string | null) {
  if (!start) return ""
  const startMs = new Date(start).getTime()
  const endMs = end ? new Date(end).getTime() : Date.now()
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return ""
  const seconds = Math.max(0, Math.round((endMs - startMs) / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rem = seconds % 60
  return `${minutes}m${rem.toString().padStart(2, "0")}s`
}

function normalizeProgress(value: number | null | undefined) {
  if (typeof value !== "number") return null
  return Math.max(0, Math.min(100, Math.round(value)))
}

export default function TaskDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const { stageLabel, statusLabel, t } = useI18n()
  const [task, setTask] = useState<Task | null>(null)
  const [log, setLog] = useState("")
  const [error, setError] = useState("")
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState("")
  const [rerunOpen, setRerunOpen] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [rerunError, setRerunError] = useState("")
  const [resuming, setResuming] = useState(false)
  const [resumeError, setResumeError] = useState("")
  const [continuing, setContinuing] = useState(false)
  const [continueError, setContinueError] = useState("")
  const [redoingStage, setRedoingStage] = useState<string | null>(null)
  const [redoConfirmStage, setRedoConfirmStage] = useState<string | null>(null)
  const [redoError, setRedoError] = useState("")
  const [renderingDirty, setRenderingDirty] = useState(false)
  const [renderDirtyError, setRenderDirtyError] = useState("")

  const pollTask = useCallback(async ({ signal, isCurrent }: SerialPollingContext) => {
    try {
      const next = await getTask(id, signal)
      if (!isCurrent()) return
      setTask(next)
      const logText = await getTaskLog(id, signal)
      if (isCurrent()) setLog(logText)
    } catch (err) {
      if (isCurrent() && !isAbortError(err)) {
        setError(err instanceof Error ? err.message : t.task.loadError)
      }
    }
  }, [id, t.task.loadError])

  const invalidatePolling = useSerialPolling(pollTask)

  const handleDelete = async () => {
    invalidatePolling()
    setDeleting(true)
    setDeleteError("")
    try {
      await deleteTask(id)
      router.replace("/")
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : t.task.deleteError)
      setDeleting(false)
    }
  }

  const handleRerun = async () => {
    invalidatePolling()
    setRerunning(true)
    setRerunError("")
    try {
      const next = await rerunTask(id)
      invalidatePolling()
      setRerunOpen(false)
      setTask(next)
      setLog("")
    } catch (err) {
      setRerunError(err instanceof Error ? err.message : t.task.rerunError)
    } finally {
      setRerunning(false)
    }
  }

  const handleResume = async () => {
    invalidatePolling()
    setResuming(true)
    setResumeError("")
    try {
      const next = await resumeTask(id)
      invalidatePolling()
      setTask(next)
    } catch (err) {
      setResumeError(err instanceof Error ? err.message : t.task.resumeError)
    } finally {
      setResuming(false)
    }
  }

  const handleContinue = async (executionMode?: ExecutionMode) => {
    invalidatePolling()
    setContinuing(true)
    setContinueError("")
    try {
      const next = await continueTask(id, executionMode)
      invalidatePolling()
      setTask(next)
    } catch (err) {
      setContinueError(err instanceof Error ? err.message : t.task.continueError)
    } finally {
      setContinuing(false)
    }
  }

  const handleRedoStage = async (stageName: string) => {
    invalidatePolling()
    setRedoingStage(stageName)
    setRedoError("")
    try {
      const next = await redoStage(id, stageName)
      invalidatePolling()
      setTask(next)
      return true
    } catch (err) {
      setRedoError(err instanceof Error ? err.message : t.task.redoStageError)
      return false
    } finally {
      setRedoingStage(null)
    }
  }

  const handleConfirmRedoStage = async () => {
    if (!redoConfirmStage) return
    const succeeded = await handleRedoStage(redoConfirmStage)
    if (succeeded) setRedoConfirmStage(null)
  }

  const handleRenderDirty = async () => {
    invalidatePolling()
    setRenderingDirty(true)
    setRenderDirtyError("")
    try {
      const result = await renderDirtySegments(id)
      if ("stages" in result) setTask(result)
      else setTask(await getTask(id))
      invalidatePolling()
    } catch (err) {
      setRenderDirtyError(err instanceof Error ? err.message : t.task.renderDirtyError)
    } finally {
      setRenderingDirty(false)
    }
  }

  const isRunning = task?.status === "running"
  const isQueued = task?.status === "queued"
  const isFailed = task?.status === "failed"
  const isPaused = task?.status === "paused"
  const isManual = task?.execution_mode === "manual"
  const canRedoStage = isManual && !isRunning && !isQueued
  const redoConfirmStageInfo = task?.stages.find((stage) => stage.name === redoConfirmStage)

  const progress = useMemo(() => {
    if (!task?.stages?.length) return 0
    const completed = task.stages.filter(
      (stage) => stage.status === "succeeded" || stage.status === "skipped",
    ).length
    return Math.round((completed / task.stages.length) * 100)
  }, [task])

  if (error && !task) {
    return (
      <main className="min-h-screen text-foreground">
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
          <AppHeader backHref="/" />
          <Card className="border border-rose-500/20 bg-rose-50 text-foreground ring-0">
            <CardContent className="px-6 py-10 text-sm text-rose-700">{error}</CardContent>
          </Card>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen text-foreground">
      <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
        <div className="[&_header]:border-border">
          <AppHeader backHref="/" />
        </div>

        <header className="flex flex-col gap-4 border-b border-border pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-primary">
              <Workflow className="size-3.5" /> Production pipeline
              <Badge className={statusBadgeClass(task?.status)}>{statusLabel(task?.status)}</Badge>
            </div>
            <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground lg:text-3xl">
              {task?.title || t.task.overview}
            </h1>
            <p className="mt-2 truncate font-mono text-xs text-muted-foreground">{task?.id}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {task?.review_mode === "required" ? (
              <Button nativeButton={false} render={<Link href={`/tasks/${id}/review`} />}>
                <Languages className="size-4" /> {t.task.reviewWorkspace}
              </Button>
            ) : null}
            {task?.status === "succeeded" && task.final_video_path ? (
              <Button variant="outline" nativeButton={false} render={<a href={finalVideoDownloadUrl(task.id)} />}>
                <Download className="size-4" /> {t.task.download}
              </Button>
            ) : null}
          </div>
        </header>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-5">
            <Card>
              <CardHeader className="flex-row items-center justify-between border-b border-border pb-4">
                <CardTitle className="flex items-center gap-2"><Film className="size-4 text-primary" /> {t.task.finalVideo}</CardTitle>
                <span className="flex items-center gap-2 text-xs text-muted-foreground"><span className="size-1.5 rounded-full bg-emerald-500" /> Monitor</span>
              </CardHeader>
              <CardContent className="pt-0">
                {task?.status === "succeeded" && task.final_video_path ? (
                  <div className="overflow-hidden rounded-xl border border-border bg-black shadow-inner">
                    <video key={task.id} src={finalVideoUrl(task.id)} crossOrigin="use-credentials" controls preload="metadata" className="aspect-video w-full bg-black object-contain" />
                  </div>
                ) : (
                  <div className="flex aspect-video items-center justify-center rounded-xl border border-border bg-[radial-gradient(circle_at_center,#ffffff_0%,#ececf0_75%)]">
                    <div className="text-center">
                      {isRunning || isQueued ? <Loader2 className="mx-auto size-8 animate-spin text-primary" /> : <Film className="mx-auto size-8 text-black/20" />}
                      <p className="mt-3 text-sm text-muted-foreground">{task?.current_stage ? stageLabel(task.current_stage) : t.task.loading}</p>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">{progress}%</p>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="border-b border-border pb-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <CardTitle className="flex items-center gap-2"><Activity className="size-4 text-primary" /> {t.task.stages}</CardTitle>
                  <span className="font-mono text-xs text-muted-foreground">{progress}% complete</span>
                </div>
                <Progress value={progress} />
              </CardHeader>
              <CardContent className="pt-0">
            {isManual && canRedoStage ? (
              <p className="mb-3 text-sm text-muted-foreground">{t.task.redoStageHelp}</p>
            ) : null}
            {redoError ? (
              <div className="mb-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-sm text-rose-700">
                {redoError}
              </div>
            ) : null}
            {task ? (
              <ol className="divide-y divide-border">
                {task.stages.map((stage, index) => {
                  const stageProgress = normalizeProgress(stage.progress)
                  const showRedo =
                    canRedoStage && (stage.status === "succeeded" || stage.status === "failed")
                  return (
                    <li
                      key={stage.name}
                      className="group flex items-start gap-3 px-1 py-3.5"
                    >
                      <div className="mt-0.5 flex size-7 items-center justify-center rounded-lg border border-border bg-black/[0.025]">{stageIcon(stage.status)}</div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-[10px] text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                          <p className="font-medium text-foreground/85">{stageLabel(stage.name, stage.label)}</p>
                          <Badge className={statusBadgeClass(stage.status)}>{statusLabel(stage.status)}</Badge>
                          {stage.started_at ? (
                            <span className="ml-auto text-xs text-muted-foreground">
                              {durationOf(stage.started_at, stage.completed_at)}
                            </span>
                          ) : null}
                          {showRedo ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="ml-auto h-7 px-2 text-xs"
                              disabled={redoingStage !== null}
                              onClick={() => setRedoConfirmStage(stage.name)}
                            >
                              {redoingStage === stage.name ? (
                                <Loader2 className="size-3 animate-spin" />
                              ) : (
                                <RotateCw className="size-3" />
                              )}
                              {redoingStage === stage.name ? t.task.redoingStage : t.task.redoStage}
                            </Button>
                          ) : null}
                        </div>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          {stage.error_message || stage.last_message || t.common.waiting}
                        </p>
                        {stage.status === "running" && stageProgress !== null ? (
                          <div className="mt-2 flex items-center gap-3">
                            <Progress value={stageProgress} className="min-w-0 flex-1" />
                            <span className="w-10 text-right text-xs tabular-nums text-muted-foreground">
                              {stageProgress}%
                            </span>
                          </div>
                        ) : null}
                      </div>
                    </li>
                  )
                })}
              </ol>
            ) : null}

            {task?.error_message ? (
              <div className="mt-4 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-sm text-rose-700">
                {task.error_message}
              </div>
            ) : null}
            <Dialog
              open={redoConfirmStage !== null}
              onOpenChange={(open) => {
                if (!open && redoingStage === null) setRedoConfirmStage(null)
              }}
            >
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t.task.redoStageTitle}</DialogTitle>
                  <DialogDescription>
                    {t.task.redoStageDescription} {redoConfirmStageInfo ? stageLabel(redoConfirmStageInfo.name, redoConfirmStageInfo.label) : ""}
                    {t.common.sentenceEnd}
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose render={<Button variant="outline" disabled={redoingStage !== null} />}>
                    {t.common.cancel}
                  </DialogClose>
                  <Button onClick={handleConfirmRedoStage} disabled={redoingStage !== null}>
                    {redoingStage ? <Loader2 className="size-4 animate-spin" /> : <RotateCw className="size-4" />}
                    {redoingStage ? t.task.redoingStage : t.task.confirmRedoStage}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
            {isPaused ? (
              <div className="mt-4 space-y-3 rounded-xl border border-primary/20 bg-primary/[0.06] px-3 py-3">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm text-primary/90">{t.task.continueHelp}</p>
                  <Button onClick={() => handleContinue()} disabled={continuing}>
                    {continuing ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
                    {continuing ? t.task.continuing : t.task.continueTask}
                  </Button>
                </div>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm text-primary/90">{t.task.continueAutoHelp}</p>
                  <Button variant="outline" onClick={() => handleContinue("auto")} disabled={continuing}>
                    {continuing ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
                    {continuing ? t.task.continuing : t.task.continueAutoTask}
                  </Button>
                </div>
              </div>
            ) : null}
            {continueError ? (
              <div className="mt-2 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-sm text-rose-700">
                {continueError}
              </div>
            ) : null}
            {isFailed ? (
              <div className="mt-4 flex flex-col gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-amber-800">
                  {t.task.resumeHelp}
                </p>
                <Button onClick={handleResume} disabled={resuming}>
                  {resuming ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
                  {resuming ? t.task.resuming : t.task.resumeTask}
                </Button>
              </div>
            ) : null}
            {resumeError ? (
              <div className="mt-2 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-sm text-rose-700">
                {resumeError}
              </div>
            ) : null}
              </CardContent>
            </Card>
          </div>

          <aside className="space-y-5 xl:sticky xl:top-5 xl:self-start">
            {task?.status === "awaiting_review" ? (
              <Card className="border border-amber-500/20 bg-amber-50/90 text-foreground ring-0">
                <CardContent className="space-y-4 px-5 py-5">
                  <div className="flex gap-3"><AlertTriangle className="size-5 shrink-0 text-amber-600" /><div><p className="font-medium text-amber-900">{t.task.reviewWorkspace}</p><p className="mt-1 text-xs leading-5 text-amber-800/75">{t.task.awaitingReviewHelp}</p></div></div>
                  <Button className="w-full bg-amber-500 text-white hover:bg-amber-600" nativeButton={false} render={<Link href={`/tasks/${id}/review`} />}><Languages className="size-4" /> {t.task.reviewWorkspace}</Button>
                </CardContent>
              </Card>
            ) : null}

            {task?.result_stale ? (
              <Card className="border border-amber-500/20 bg-amber-50/90 text-foreground ring-0">
                <CardContent className="space-y-4 px-5 py-5">
                  <div className="flex gap-3"><AlertTriangle className="size-5 shrink-0 text-amber-600" /><div><p className="font-medium text-amber-900">{t.task.staleResultTitle}</p><p className="mt-1 text-xs leading-5 text-amber-800/75">{t.task.staleResultHelp}</p></div></div>
                  {renderDirtyError ? <p className="text-xs text-rose-700">{renderDirtyError}</p> : null}
                  <Button className="w-full bg-amber-500 text-white hover:bg-amber-600" type="button" onClick={handleRenderDirty} disabled={renderingDirty}>{renderingDirty ? <Loader2 className="size-4 animate-spin" /> : <RotateCw className="size-4" />}{renderingDirty ? t.task.renderingDirty : t.task.renderDirty}</Button>
                </CardContent>
              </Card>
            ) : null}

            <Card>
              <CardHeader className="border-b border-border pb-4"><CardTitle className="flex items-center gap-2"><Gauge className="size-4 text-primary" /> {t.task.overview}</CardTitle></CardHeader>
              <CardContent className="pt-0">
                {task ? <dl className="divide-y divide-border text-xs">
                  {[
                    [t.task.executionMode, task.execution_mode === "manual" ? t.task.executionManual : t.task.executionAuto],
                    [t.task.outputMode, (task.output_mode || "both") === "subtitles" ? t.task.outputSubtitles : (task.output_mode || "both") === "dubbing" ? t.task.outputDubbing : t.task.outputBoth],
                    [t.task.created, formatTime(task.created_at)],
                    [t.task.started, formatTime(task.started_at) || "—"],
                    [t.task.completed, formatTime(task.completed_at) || "—"],
                  ].map(([label, value]) => <div key={label} className="grid grid-cols-[100px_1fr] gap-3 py-2.5"><dt className="text-muted-foreground">{label}</dt><dd className="text-right text-foreground/75">{value}</dd></div>)}
                  <div className="py-2.5"><dt className="mb-1 text-muted-foreground">URL</dt><dd><a href={task.url} target="_blank" rel="noreferrer" className="flex items-start gap-1 break-all text-primary hover:text-primary/75"><span className="min-w-0 flex-1">{task.url}</span><ExternalLink className="mt-0.5 size-3 shrink-0" /></a></dd></div>
                  {task.session_path ? <div className="py-2.5"><dt className="mb-1 text-muted-foreground">{t.task.session}</dt><dd className="break-all font-mono text-[10px] leading-4 text-muted-foreground">{task.session_path}</dd></div> : null}
                </dl> : <p className="py-4 text-muted-foreground">{t.task.loading}</p>}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex-row items-center justify-between border-b border-border pb-4"><CardTitle className="flex items-center gap-2"><Terminal className="size-4 text-primary" /> {t.task.runLog}</CardTitle><FileText className="size-4 text-muted-foreground" /></CardHeader>
              <CardContent className="pt-0"><ScrollArea className="h-72 rounded-xl border border-black/10 bg-[#1d1d1f] p-3 text-[11px] text-zinc-200">{log ? <pre className="whitespace-pre-wrap break-words font-mono leading-5">{log}</pre> : <p className="text-zinc-500">{t.task.emptyLog}</p>}</ScrollArea></CardContent>
            </Card>
          </aside>
        </section>

        <Card className="border border-rose-500/15 bg-rose-50/75 text-foreground ring-0">
          <CardHeader className="border-b border-rose-500/12 pb-4"><CardTitle className="text-sm text-rose-700">{t.task.dangerZone}</CardTitle></CardHeader>
          <CardContent className="grid gap-4 pt-0 lg:grid-cols-2">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-muted-foreground">
                {t.task.rerunHelp}
              </p>
              <Dialog open={rerunOpen} onOpenChange={setRerunOpen}>
                <DialogTrigger
                  render={
                    <Button variant="outline" disabled={!task || isRunning}>
                      <RotateCw className="size-4" />
                      {t.task.rerunTask}
                    </Button>
                  }
                />
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>{t.task.rerunTitle}</DialogTitle>
                    <DialogDescription>
                      {t.task.rerunDescription}
                    </DialogDescription>
                  </DialogHeader>
                  {rerunError ? (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                      {rerunError}
                    </div>
                  ) : null}
                  <DialogFooter>
                    <DialogClose render={<Button variant="outline" disabled={rerunning} />}>
                      {t.common.cancel}
                    </DialogClose>
                    <Button onClick={handleRerun} disabled={rerunning}>
                      {rerunning ? <Loader2 className="size-4 animate-spin" /> : <RotateCw className="size-4" />}
                      {rerunning ? t.task.rerunning : t.task.confirmRerun}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-muted-foreground">
                {t.task.deleteHelp} <code className="font-mono text-xs">workfolder/</code>
                {t.common.sentenceEnd}
              </p>
              <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
                <DialogTrigger
                  render={
                    <Button variant="destructive" disabled={!task || isRunning}>
                      <Trash2 className="size-4" />
                      {t.task.deleteTask}
                    </Button>
                  }
                />
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>{t.task.deleteTitle}</DialogTitle>
                    <DialogDescription>
                      {t.task.deleteDescription}
                    </DialogDescription>
                  </DialogHeader>
                  {deleteError ? (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                      {deleteError}
                    </div>
                  ) : null}
                  <DialogFooter>
                    <DialogClose render={<Button variant="outline" disabled={deleting} />}>
                      {t.common.cancel}
                    </DialogClose>
                    <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
                      {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                      {deleting ? t.task.deleting : t.task.confirmDelete}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
            {isRunning ? (
              <p className="text-xs text-amber-400 lg:col-span-2">{t.task.runningLocked}</p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
