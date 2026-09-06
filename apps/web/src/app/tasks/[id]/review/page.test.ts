import { describe, expect, it } from "vitest"

import { validateSegment } from "@/app/tasks/[id]/review/validation"

describe("字幕段硬校验", () => {
  it("拒绝空译文、负开始时间和倒置时间轴", () => {
    expect(validateSegment({
      translated_text: "   ",
      start_ms: -1,
      end_ms: -2,
      speaker: null,
      audio_mode: "tts",
      tts_profile_id: null,
    })).toEqual(["empty_translation", "invalid_start", "invalid_end"])
  })

  it("允许有效译文和相邻毫秒时间轴", () => {
    expect(validateSegment({
      translated_text: "有效译文",
      start_ms: 1000,
      end_ms: 1001,
      speaker: "speaker-1",
      audio_mode: "original",
      tts_profile_id: null,
    })).toEqual([])
  })
})
