import { TaskSegment } from "@/lib/api"

export type EditableSegment = Pick<
  TaskSegment,
  "translated_text" | "start_ms" | "end_ms" | "speaker" | "audio_mode" | "tts_profile_id"
>

export type SegmentValidationCode = "empty_translation" | "invalid_start" | "invalid_end"

export function validateSegment(segment: EditableSegment): SegmentValidationCode[] {
  const errors: SegmentValidationCode[] = []
  if (!segment.translated_text.trim()) errors.push("empty_translation")
  if (!Number.isFinite(segment.start_ms) || segment.start_ms < 0) errors.push("invalid_start")
  if (!Number.isFinite(segment.end_ms) || segment.end_ms <= segment.start_ms) errors.push("invalid_end")
  return errors
}
