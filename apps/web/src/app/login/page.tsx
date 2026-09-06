"use client"

import Link from "next/link"
import { FormEvent, useState } from "react"
import { Loader2, LockKeyhole, LogIn } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"

export default function LoginPage() {
  const { login } = useAuth()
  const { language, t } = useI18n()
  const [password, setPassword] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!password || submitting) return
    setSubmitting(true)
    setError("")
    try {
      await login(password)
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? t.auth.invalidCredentials
          : t.auth.loginError,
      )
    } finally {
      setPassword("")
      setSubmitting(false)
    }
  }

  return (
    <main className="relative isolate flex min-h-screen items-center justify-center overflow-hidden px-4 py-10">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_50%_14%,rgba(0,122,255,0.12),transparent_28rem)]"
      />
      <div className="w-full max-w-[22rem]">
        <Link
          href="/login"
          className="mx-auto mb-8 flex w-fit rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/20"
          aria-label="Dubloom · 织声"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/youdub-logo.svg" alt="Dubloom · 织声" className="h-9 w-auto" />
        </Link>
        <Card className="workspace-panel relative overflow-visible rounded-3xl py-0">
          <CardHeader className="border-b border-border/70 px-5 py-5">
            <div className="mb-3 flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <LockKeyhole className="size-4" />
            </div>
            <p className="workspace-overline">Dubloom workspace</p>
            <CardTitle className="text-base">
              {language === "zh" ? "登录织声" : "Sign in to Dubloom"}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-5 py-5">
            <form onSubmit={submit} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="password">{t.auth.password}</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  autoFocus
                  maxLength={512}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={submitting}
                  required
                />
              </div>
              {error ? (
                <p className="rounded-md border border-destructive/25 bg-destructive/8 px-3 py-2 text-sm text-destructive" role="alert">
                  {error}
                </p>
              ) : null}
              <Button type="submit" size="lg" className="w-full" disabled={submitting || !password}>
                {submitting ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />}
                {submitting ? t.auth.signingIn : t.auth.signIn}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
