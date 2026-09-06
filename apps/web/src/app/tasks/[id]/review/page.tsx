"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { use, useCallback, useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  Check,
  Clapperboard,
  Clock3,
  ListVideo,
  Loader2,
  Play,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Volume2,
  WandSparkles,
} from "lucide-react"

import { AppHeader } from "@/components/app-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  ApiError,
  AudioMode,
  Job,
  ProviderProfile,
  Task,
  TaskSegment,
  approveTaskReview,
  createSegmentPreview,
  getJob,
  getTask,
  listProviderProfiles,
  listTaskSegments,
  renderDirtySegments,
  segmentAudioUrl,
  sourceVideoUrl,
  updateTaskSegment,
} from "@/lib/api"
import { useI18n } from "@/lib/i18n"
import { EditableSegment, validateSegment } from "./validation"

function hasChanged(segment: TaskSegment, draft: EditableSegment) {
  return segment.translated_text !== draft.translated_text
    || segment.start_ms !== draft.start_ms
    || segment.end_ms !== draft.end_ms
    || (segment.speaker || null) !== (draft.speaker || null)
    || segment.audio_mode !== draft.audio_mode
    || (segment.tts_profile_id || null) !== (draft.tts_profile_id || null)
}

function localWarnings(segment: EditableSegment) {
  const durationSeconds = Math.max(0, (segment.end_ms - segment.start_ms) / 1000)
  const charactersPerSecond = durationSeconds > 0
    ? Array.from(segment.translated_text.replace(/\s/g, "")).length / durationSeconds
    : 0
  return {
    highReadingSpeed: charactersPerSecond > 12,
    shortReference: segment.audio_mode === "tts" && durationSeconds > 0 && durationSeconds < 1.2,
  }
}

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

async function waitForJob(job: Job) {
  let current = job
  for (let attempt = 0; attempt < 120 && (current.status === "queued" || current.status === "running"); attempt += 1) {
    await wait(1000)
    current = await getJob(job.id)
  }
  return current
}

export default function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const { t } = useI18n()
  const [task, setTask] = useState<Task | null>(null)
  const [segments, setSegments] = useState<TaskSegment[]>([])
  const [drafts, setDrafts] = useState<Record<string, EditableSegment>>({})
  const [profiles, setProfiles] = useState<ProviderProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const [savingId, setSavingId] = useState<string | null>(null)
  const [savedId, setSavedId] = useState<string | null>(null)
  const [previewingId, setPreviewingId] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)
  const [rendering, setRendering] = useState(false)
  const [actionError, setActionError] = useState("")
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null)

  const ttsProfiles = profiles.filter((profile) => profile.kind === "tts")

  const applySegments = useCallback((next: TaskSegment[]) => {
    setSegments(next)
    setSelectedSegmentId((current) => (
      current && next.some((segment) => segment.id === current)
        ? current
        : next[0]?.id || null
    ))
    setDrafts(Object.fromEntries(next.map((segment) => [segment.id, {
      translated_text: segment.translated_text,
      start_ms: segment.start_ms,
      end_ms: segment.end_ms,
      speaker: segment.speaker,
      audio_mode: segment.audio_mode,
      tts_profile_id: segment.tts_profile_id,
    }])))
  }, [])

  const load = useCallback(async () => {
    setError("")
    try {
      const [nextTask, segmentResponse, nextProfiles] = await Promise.all([
        getTask(id),
        listTaskSegments(id),
        listProviderProfiles(),
      ])
      setTask(nextTask)
      applySegments(segmentResponse.segments)
      setProfiles(nextProfiles)
    } catch (err) {
      setError(err instanceof Error ? err.message : t.review.loadError)
    } finally {
      setLoading(false)
    }
  }, [applySegments, id, t.review.loadError])

  useEffect(() => {
    void load()
  }, [load])

  function updateDraft(segmentId: string, patch: Partial<EditableSegment>) {
    setSavedId(null)
    setDrafts((current) => ({
      ...current,
      [segmentId]: { ...current[segmentId], ...patch },
    }))
  }

  function validationMessages(draft: EditableSegment) {
    return validateSegment(draft).map((code) => {
      if (code === "empty_translation") return t.review.emptyTranslation
      if (code === "invalid_start") return t.review.invalidStart
      return t.review.invalidEnd
    })
  }

  async function saveSegment(segment: TaskSegment) {
    const draft = drafts[segment.id]
    if (!draft) return null
    const errors = validationMessages(draft)
    if (errors.length > 0) {
      setRowErrors((current) => ({ ...current, [segment.id]: errors.join(" ") }))
      return null
    }
    if (!hasChanged(segment, draft)) return segment

    setSavingId(segment.id)
    setRowErrors((current) => ({ ...current, [segment.id]: "" }))
    try {
      const updated = await updateTaskSegment(id, segment.id, {
        ...draft,
        speaker: draft.speaker?.trim() || null,
        expected_revision: segment.revision,
      })
      setSegments((current) => current.map((item) => item.id === updated.id ? updated : item))
      setDrafts((current) => ({ ...current, [updated.id]: {
        translated_text: updated.translated_text,
        start_ms: updated.start_ms,
        end_ms: updated.end_ms,
        speaker: updated.speaker,
        audio_mode: updated.audio_mode,
        tts_profile_id: updated.tts_profile_id,
      } }))
      setTask((current) => current
        ? { ...current, result_stale: Boolean(current.final_video_path) }
        : current)
      setSavedId(segment.id)
      return updated
    } catch (err) {
      const message = err instanceof ApiError && err.status === 409
        ? t.review.conflict
        : err instanceof Error ? err.message : t.review.saveError
      setRowErrors((current) => ({ ...current, [segment.id]: message }))
      return null
    } finally {
      setSavingId(null)
    }
  }

  async function saveAllChanged() {
    let currentSegments = segments
    for (const segment of currentSegments) {
      const draft = drafts[segment.id]
      if (!draft || !hasChanged(segment, draft)) continue
      const updated = await saveSegment(segment)
      if (!updated) return false
      currentSegments = currentSegments.map((item) => item.id === updated.id ? updated : item)
    }
    return true
  }

  async function handlePreview(segment: TaskSegment) {
    setActionError("")
    setPreviewingId(segment.id)
    try {
      const saved = await saveSegment(segment)
      if (!saved) return
      const job = await createSegmentPreview(id, segment.id)
      setSegments((current) => current.map((item) => item.id === segment.id
        ? { ...item, preview_status: "queued" }
        : item))
      const completed = await waitForJob(job)
      if (completed.status !== "succeeded") throw new Error(completed.error_message || t.review.previewError)
      const response = await listTaskSegments(id)
      applySegments(response.segments)
    } catch (err) {
      setRowErrors((current) => ({
        ...current,
        [segment.id]: err instanceof Error ? err.message : t.review.previewError,
      }))
    } finally {
      setPreviewingId(null)
    }
  }

  const hardErrorCount = useMemo(() => Object.values(drafts)
    .reduce((count, draft) => count + validateSegment(draft).length, 0), [drafts])
  const changedCount = useMemo(() => segments.filter((segment) => {
    const draft = drafts[segment.id]
    return segment.dirty || Boolean(draft && hasChanged(segment, draft))
  }).length, [drafts, segments])
  const selectedSegment = useMemo(
    () => segments.find((segment) => segment.id === selectedSegmentId) || null,
    [segments, selectedSegmentId],
  )
  const selectedDraft = selectedSegment ? drafts[selectedSegment.id] : null
  const selectedErrors = selectedDraft ? validationMessages(selectedDraft) : []
  const selectedLocalWarnings = selectedDraft ? localWarnings(selectedDraft) : null
  const selectedWarnings = selectedSegment && selectedDraft ? [
    ...(selectedSegment.warnings || []).map((warning) => typeof warning === "string" ? warning : warning.message),
    ...(selectedLocalWarnings?.highReadingSpeed ? [t.review.highReadingSpeed] : []),
    ...(selectedLocalWarnings?.shortReference ? [t.review.shortReference] : []),
  ] : []

  async function handleApprove() {
    setActionError("")
    if (hardErrorCount > 0) {
      setActionError(t.review.fixErrors)
      return
    }
    setApproving(true)
    try {
      if (!await saveAllChanged()) return
      await approveTaskReview(id)
      router.push(`/tasks/${id}`)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t.review.approveError)
    } finally {
      setApproving(false)
    }
  }

  async function handleRenderDirty() {
    setActionError("")
    if (hardErrorCount > 0) {
      setActionError(t.review.fixErrors)
      return
    }
    setRendering(true)
    try {
      if (!await saveAllChanged()) return
      await renderDirtySegments(id)
      router.push(`/tasks/${id}`)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t.review.renderDirtyError)
    } finally {
      setRendering(false)
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center text-muted-foreground">
        <div className="flex items-center gap-3 text-sm"><Loader2 className="size-5 animate-spin text-primary" /> {t.review.loading}</div>
      </main>
    )
  }

  return (
    <main className="min-h-screen text-foreground">
      <div className="mx-auto flex w-full max-w-[1720px] flex-col gap-4 px-4 py-4 sm:px-6">
        <div className="[&_header]:border-border">
          <AppHeader backHref={`/tasks/${id}`} />
        </div>

        <header className="flex flex-col gap-4 border-b border-border pb-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-primary"><Clapperboard className="size-3.5" /> Review console</div>
            <h1 className="mt-1 truncate text-xl font-semibold text-foreground">{task?.title || t.review.title}</h1>
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">{id}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-lg border border-border bg-white/65 px-2.5 py-1.5 text-muted-foreground">{segments.length} {t.review.segments}</span>
            <span className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-2.5 py-1.5 text-amber-700">{changedCount} {t.review.dirty}</span>
            {hardErrorCount > 0 ? <span className="rounded-lg border border-rose-500/20 bg-rose-500/10 px-2.5 py-1.5 text-rose-700">{hardErrorCount} errors</span> : null}
            <Button type="button" variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="size-3.5" /> {t.review.refresh}</Button>
            <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/tasks/${id}`} />}>{t.review.backToTask}</Button>
          </div>
        </header>

        {error ? <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-4 py-3 text-sm text-rose-700">{error}</div> : null}
        {task?.result_stale ? <div className="flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-50 px-4 py-2.5 text-xs text-amber-800"><AlertTriangle className="size-4 shrink-0" /> {t.review.resultStale}</div> : null}

        <section className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0 space-y-4">
            <Card>
              <CardHeader className="flex-row items-center justify-between border-b border-border pb-4">
                <CardTitle className="flex items-center gap-2"><Clapperboard className="size-4 text-primary" /> {t.review.sourceVideo}</CardTitle>
                <span className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-muted-foreground"><span className="size-1.5 rounded-full bg-rose-500" /> Source monitor</span>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="overflow-hidden rounded-xl border border-border bg-black">
                  <video src={sourceVideoUrl(id)} crossOrigin="use-credentials" controls preload="metadata" className="aspect-video max-h-[48dvh] w-full bg-black object-contain" />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex-row items-center justify-between border-b border-border pb-4">
                <CardTitle className="flex items-center gap-2"><ListVideo className="size-4 text-primary" /> {t.review.segments}</CardTitle>
                <span className="text-xs text-muted-foreground">{selectedSegment ? `${String(selectedSegment.position + 1).padStart(2, "0")} / ${segments.length}` : `0 / ${segments.length}`}</span>
              </CardHeader>
              <CardContent className="px-0 pt-0">
                {segments.length === 0 ? <p className="px-6 py-12 text-center text-sm text-muted-foreground">{t.review.noSegments}</p> : (
                  <div className="max-h-[680px] overflow-y-auto">
                    <div className="sticky top-0 z-10 grid grid-cols-[72px_minmax(0,1fr)_minmax(0,1fr)_80px] gap-3 border-b border-border bg-white/90 px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground backdrop-blur-xl">
                      <span>Time</span><span>{t.review.sourceText}</span><span>{t.review.translatedText}</span><span>Status</span>
                    </div>
                    {segments.map((segment) => {
                      const draft = drafts[segment.id]
                      if (!draft) return null
                      const errors = validationMessages(draft)
                      const changed = hasChanged(segment, draft)
                      const active = segment.id === selectedSegmentId
                      return (
                        <button
                          key={segment.id}
                          type="button"
                          onClick={() => setSelectedSegmentId(segment.id)}
                          className={`grid w-full grid-cols-[72px_minmax(0,1fr)_minmax(0,1fr)_80px] gap-3 border-b border-border px-4 py-3 text-left transition-colors ${active ? "bg-primary/[0.07] shadow-[inset_3px_0_0_#007aff]" : "hover:bg-black/[0.025]"}`}
                        >
                          <span className="font-mono text-[10px] leading-5 text-muted-foreground">{(segment.start_ms / 1000).toFixed(2)}<br />{(segment.end_ms / 1000).toFixed(2)}</span>
                          <span className="line-clamp-3 text-xs leading-5 text-muted-foreground">{segment.source_text}</span>
                          <span className="line-clamp-3 text-xs leading-5 text-foreground/85">{draft.translated_text || "—"}</span>
                          <span className="flex flex-col items-start gap-1">
                            <span className="font-mono text-[10px] text-muted-foreground">#{String(segment.position + 1).padStart(2, "0")}</span>
                            {(changed || segment.dirty) ? <Badge className="bg-amber-500/12 text-amber-700">{t.review.dirty}</Badge> : null}
                            {errors.length > 0 ? <Badge className="bg-rose-500/12 text-rose-700">Error</Badge> : null}
                            {segment.preview_status === "ready" ? <Badge className="bg-emerald-500/12 text-emerald-700">Audio</Badge> : null}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <aside className="min-w-0 space-y-4 xl:sticky xl:top-4 xl:self-start">
            <Card>
              <CardHeader className="flex-row items-center justify-between border-b border-border pb-4">
                <CardTitle className="flex items-center gap-2"><SlidersHorizontal className="size-4 text-primary" /> Inspector</CardTitle>
                {selectedSegment ? <span className="font-mono text-[10px] text-muted-foreground">SEG {String(selectedSegment.position + 1).padStart(2, "0")}</span> : null}
              </CardHeader>
              <CardContent className="space-y-4 pt-0">
                {selectedSegment && selectedDraft ? (
                  <>
                    <div className="apple-inset rounded-xl p-3">
                      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{t.review.sourceText}</p>
                      <p className="text-xs leading-5 text-foreground/70">{selectedSegment.source_text}</p>
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor={`translation-${selectedSegment.id}`} className="text-xs">{t.review.translatedText}</Label>
                      <Textarea id={`translation-${selectedSegment.id}`} value={selectedDraft.translated_text} aria-invalid={selectedErrors.includes(t.review.emptyTranslation)} onChange={(event) => updateDraft(selectedSegment.id, { translated_text: event.target.value })} className="min-h-28" />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5"><Label className="flex items-center gap-1 text-xs"><Clock3 className="size-3" /> {t.review.start}</Label><Input aria-label={`${t.review.start} ${selectedSegment.position + 1}`} type="number" min="0" step="0.001" value={selectedDraft.start_ms / 1000} onChange={(event) => updateDraft(selectedSegment.id, { start_ms: Math.round(Number(event.target.value) * 1000) })} /></div>
                      <div className="space-y-1.5"><Label className="flex items-center gap-1 text-xs"><Clock3 className="size-3" /> {t.review.end}</Label><Input aria-label={`${t.review.end} ${selectedSegment.position + 1}`} type="number" min="0" step="0.001" value={selectedDraft.end_ms / 1000} onChange={(event) => updateDraft(selectedSegment.id, { end_ms: Math.round(Number(event.target.value) * 1000) })} /></div>
                    </div>

                    <div className="space-y-1.5"><Label className="text-xs">{t.review.speaker}</Label><Input aria-label={`${t.review.speaker} ${selectedSegment.position + 1}`} value={selectedDraft.speaker || ""} onChange={(event) => updateDraft(selectedSegment.id, { speaker: event.target.value })} /></div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5"><Label className="text-xs">{t.review.audioMode}</Label><Select value={selectedDraft.audio_mode} onValueChange={(value) => value && updateDraft(selectedSegment.id, { audio_mode: value as AudioMode })}><SelectTrigger aria-label={`${t.review.audioMode} ${selectedSegment.position + 1}`}><span>{selectedDraft.audio_mode === "original" ? t.review.audioOriginal : t.review.audioTts}</span></SelectTrigger><SelectContent><SelectItem value="tts">{t.review.audioTts}</SelectItem><SelectItem value="original">{t.review.audioOriginal}</SelectItem></SelectContent></Select></div>
                      <div className="space-y-1.5"><Label className="text-xs">{t.review.ttsProfile}</Label><Select value={selectedDraft.tts_profile_id || "default"} onValueChange={(value) => updateDraft(selectedSegment.id, { tts_profile_id: value === "default" ? null : value })} disabled={selectedDraft.audio_mode === "original"}><SelectTrigger aria-label={`${t.review.ttsProfile} ${selectedSegment.position + 1}`}><span className="truncate">{selectedDraft.tts_profile_id ? ttsProfiles.find((profile) => profile.id === selectedDraft.tts_profile_id)?.name || selectedDraft.tts_profile_id : t.review.defaultProfile}</span></SelectTrigger><SelectContent><SelectItem value="default">{t.review.defaultProfile}</SelectItem>{ttsProfiles.map((profile) => <SelectItem key={profile.id} value={profile.id}>{profile.name}</SelectItem>)}</SelectContent></Select></div>
                    </div>

                    {(selectedErrors.length > 0 || selectedWarnings.length > 0 || rowErrors[selectedSegment.id]) ? (
                      <div className="space-y-2 rounded-xl border border-amber-500/20 bg-amber-50 p-3">
                        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-amber-700"><AlertTriangle className="size-3.5" /> QC signals</p>
                        {selectedErrors.map((message) => <p key={message} className="text-xs leading-5 text-rose-700">{message}</p>)}
                        {selectedWarnings.map((message, index) => <p key={`${message}-${index}`} className="text-xs leading-5 text-amber-800/80">{message}</p>)}
                        {rowErrors[selectedSegment.id] ? <p className="text-xs leading-5 text-rose-700">{rowErrors[selectedSegment.id]}</p> : null}
                      </div>
                    ) : null}

                    <div className="space-y-3 border-t border-border pt-4">
                      <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"><Volume2 className="size-3.5" /> Audio audition</p>
                      <div><span className="mb-1 block text-xs text-muted-foreground">{t.review.sourceAudio}</span><audio controls preload="none" src={segmentAudioUrl(id, selectedSegment.id, "source")} className="h-9 w-full" /></div>
                      {selectedSegment.preview_status === "ready" ? <div><span className="mb-1 block text-xs text-muted-foreground">{t.review.previewAudio}</span><audio key={`${selectedSegment.id}-${selectedSegment.revision}-${selectedSegment.preview_status}`} controls preload="none" src={segmentAudioUrl(id, selectedSegment.id, "preview")} className="h-9 w-full" /></div> : null}
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <Button type="button" variant="outline" onClick={() => void saveSegment(selectedSegment)} disabled={savingId !== null || selectedErrors.length > 0}>{savingId === selectedSegment.id ? <Loader2 className="size-3 animate-spin" /> : savedId === selectedSegment.id ? <Check className="size-3" /> : <Save className="size-3" />}{savingId === selectedSegment.id ? t.review.saving : savedId === selectedSegment.id ? t.review.saved : t.review.save}</Button>
                      <Button type="button" onClick={() => void handlePreview(selectedSegment)} disabled={previewingId !== null || selectedDraft.audio_mode === "original" || selectedErrors.length > 0}>{previewingId === selectedSegment.id ? <Loader2 className="size-3 animate-spin" /> : <Play className="size-3" />}{previewingId === selectedSegment.id ? t.review.generatingPreview : t.review.generatePreview}</Button>
                    </div>
                  </>
                ) : <p className="py-12 text-center text-sm text-muted-foreground">{t.review.noSegments}</p>}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="space-y-3 px-4 py-4">
                <div className="flex items-center justify-between text-xs"><span className="text-muted-foreground">Quality gate</span><span className={hardErrorCount > 0 ? "text-rose-700" : "text-emerald-700"}>{hardErrorCount > 0 ? `${hardErrorCount} errors` : "Ready"}</span></div>
                {actionError ? <p className="text-xs leading-5 text-rose-700">{actionError}</p> : null}
                {hardErrorCount > 0 ? <p className="text-xs leading-5 text-rose-700">{t.review.fixErrors}</p> : null}
                {task?.status !== "awaiting_review" ? (
                  <Button className="w-full" type="button" onClick={() => void handleRenderDirty()} disabled={rendering || approving || hardErrorCount > 0}>{rendering ? <Loader2 className="size-4 animate-spin" /> : <WandSparkles className="size-4" />}{rendering ? t.review.renderingDirty : t.review.renderDirty}</Button>
                ) : (
                  <Button className="w-full bg-emerald-600 text-white hover:bg-emerald-700" type="button" onClick={() => void handleApprove()} disabled={approving || rendering || hardErrorCount > 0 || segments.length === 0}>{approving ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}{approving ? t.review.approving : t.review.approve}</Button>
                )}
              </CardContent>
            </Card>
          </aside>
        </section>
      </div>
    </main>
  )
}
