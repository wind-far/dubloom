export function statusBadgeClass(status?: string): string {
  if (status === "succeeded") return "border-emerald-600/15 bg-emerald-500/10 text-emerald-700"
  if (status === "failed") return "border-rose-600/15 bg-rose-500/10 text-rose-700"
  if (status === "running") return "border-primary/25 bg-primary/10 text-primary"
  if (status === "paused" || status === "awaiting_review") return "border-amber-600/15 bg-amber-500/10 text-amber-700"
  if (status === "queued") return "border-border bg-muted text-muted-foreground"
  return "border-border bg-background text-foreground"
}
