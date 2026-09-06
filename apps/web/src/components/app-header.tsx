"use client"

import Link from "next/link"
import { useState } from "react"
import { ArrowLeft, Loader2, LogOut } from "lucide-react"

import { Button } from "@/components/ui/button"
import { SettingsDialog } from "@/components/settings-dialog"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"

export function AppHeader({ backHref }: { backHref?: string }) {
  const { t } = useI18n()
  const { logout } = useAuth()
  const [loggingOut, setLoggingOut] = useState(false)

  async function handleLogout() {
    if (loggingOut) return
    setLoggingOut(true)
    try {
      await logout()
    } finally {
      setLoggingOut(false)
    }
  }

  return (
    <header className="flex flex-col gap-4 border-b border-border/80 pb-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-2.5">
        {backHref ? (
          <Button
            variant="ghost"
            size="icon-sm"
            className="-ml-1 border border-transparent hover:border-border"
            nativeButton={false}
            render={<Link href={backHref} aria-label={t.common.back} />}
          >
            <ArrowLeft className="size-4" />
          </Button>
        ) : null}
        <Link
          href="/"
          className="flex min-w-0 items-center gap-3 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/35"
        >
          <span aria-hidden="true" className="h-5 w-px bg-border" />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/youdub-logo.svg"
            alt="Dubloom · 织声"
            className="h-6 w-auto sm:h-7"
          />
        </Link>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <SettingsDialog />
        <Button
          type="button"
          variant="ghost"
          className="border border-transparent hover:border-border"
          onClick={handleLogout}
          disabled={loggingOut}
        >
          {loggingOut ? <Loader2 className="size-4 animate-spin" /> : <LogOut className="size-4" />}
          <span className="hidden sm:inline">{loggingOut ? t.auth.loggingOut : t.auth.logout}</span>
        </Button>
      </div>
    </header>
  )
}
