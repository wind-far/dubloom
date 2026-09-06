"use client"

import { FormEvent, useEffect, useState } from "react"
import { Cookie, Cpu, Eye, EyeOff, Globe2, KeyRound, Network, RefreshCw, Settings, ShieldCheck } from "lucide-react"

import {
  ApiError,
  getCookieInfo,
  getOpenAIModels,
  getOpenAISettings,
  getYtdlpSettings,
  saveCookie,
  saveOpenAISettings,
  saveYtdlpSettings,
} from "@/lib/api"
import { LANGUAGE_OPTIONS, useI18n } from "@/lib/i18n"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

type SettingsForm = {
  cookie: string
  baseUrl: string
  apiKey: string
  model: string
  translateConcurrency: string
  proxyPort: string
}

const SAVED_API_KEY_MASK = "********"
const SAVED_COOKIE_SENTINEL = "__YOUDUB_SAVED_COOKIE__"

type MessageKey = "keySaved"
type SaveSection = "cookie" | "openai" | "ytdlp"
type SaveResult = {
  section: SaveSection
  status: "saved" | "failed" | "unchanged"
  httpStatus?: number
}

const defaultSettings: SettingsForm = {
  cookie: "",
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  model: "gpt-4o-mini",
  translateConcurrency: "50",
  proxyPort: "",
}

function uniqueModels(models: string[]) {
  return Array.from(new Set(models.map((model) => model.trim()).filter(Boolean)))
}

export function SettingsDialog() {
  const { language, loadedModelsText, setLanguage, t } = useI18n()
  const [open, setOpen] = useState(false)
  const [settings, setSettings] = useState(defaultSettings)
  const [message, setMessage] = useState("")
  const [messageKey, setMessageKey] = useState<MessageKey | null>(null)
  const [modelOptions, setModelOptions] = useState<string[]>([])
  const [modelsLoaded, setModelsLoaded] = useState(false)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [cookieDirty, setCookieDirty] = useState(false)
  const [apiKeyDirty, setApiKeyDirty] = useState(false)
  const [saveResults, setSaveResults] = useState<SaveResult[]>([])
  const [saving, setSaving] = useState(false)

  const cookieValue =
    settings.cookie === SAVED_COOKIE_SENTINEL ? t.settings.savedCookie : settings.cookie
  const visibleMessage = messageKey === "keySaved" ? t.settings.keySaved : message

  useEffect(() => {
    if (!open) return
    Promise.all([getCookieInfo(), getOpenAISettings(), getYtdlpSettings()])
      .then(([cookie, openai, ytdlp]) => {
        setSettings({
          cookie: cookie.exists ? SAVED_COOKIE_SENTINEL : "",
          baseUrl: openai.base_url,
          apiKey: openai.has_api_key ? openai.api_key || SAVED_API_KEY_MASK : "",
          model: openai.model,
          translateConcurrency: openai.translate_concurrency || "50",
          proxyPort: ytdlp.proxy_port,
        })
        setModelOptions(uniqueModels([openai.model]))
        setModelsLoaded(false)
        setShowApiKey(false)
        setCookieDirty(false)
        setApiKeyDirty(false)
        setSaveResults([])
        setMessage("")
        setMessageKey(openai.has_api_key ? "keySaved" : null)
      })
      .catch((err) => {
        setMessageKey(null)
        setMessage(err.message)
      })
  }, [open])

  async function refreshSettingsFromServer() {
    const [cookieResult, openaiResult, ytdlpResult] = await Promise.allSettled([
      getCookieInfo(),
      getOpenAISettings(),
      getYtdlpSettings(),
    ])

    setSettings((current) => {
      const refreshed = { ...current }
      if (cookieResult.status === "fulfilled") {
        refreshed.cookie = cookieResult.value.exists ? SAVED_COOKIE_SENTINEL : ""
      }
      if (openaiResult.status === "fulfilled") {
        const openai = openaiResult.value
        refreshed.baseUrl = openai.base_url
        refreshed.apiKey = openai.has_api_key ? openai.api_key || SAVED_API_KEY_MASK : ""
        refreshed.model = openai.model
        refreshed.translateConcurrency = openai.translate_concurrency || "50"
      }
      if (ytdlpResult.status === "fulfilled") {
        refreshed.proxyPort = ytdlpResult.value.proxy_port
      }
      return refreshed
    })

    if (cookieResult.status === "fulfilled") setCookieDirty(false)
    if (openaiResult.status === "fulfilled") {
      setApiKeyDirty(false)
      setShowApiKey(false)
      setModelOptions(uniqueModels([openaiResult.value.model]))
      setModelsLoaded(false)
    }

    return [cookieResult, openaiResult, ytdlpResult].every(
      (result) => result.status === "fulfilled",
    )
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setMessage("")
    setMessageKey(null)
    setSaveResults([])
    setSaving(true)
    const results: SaveResult[] = []

    async function saveSection(section: SaveSection, action: () => Promise<unknown>) {
      try {
        await action()
        results.push({ section, status: "saved" })
      } catch (err) {
        results.push({
          section,
          status: "failed",
          httpStatus: err instanceof ApiError ? err.status : undefined,
        })
      }
    }

    try {
      if (cookieDirty) {
        await saveSection("cookie", () => saveCookie(settings.cookie))
      } else {
        results.push({ section: "cookie", status: "unchanged" })
      }
      const clearApiKey = apiKeyDirty && !settings.apiKey.trim()
      await saveSection("openai", () => saveOpenAISettings({
        base_url: settings.baseUrl,
        api_key: apiKeyDirty ? settings.apiKey : "",
        clear_api_key: clearApiKey,
        model: settings.model,
        translate_concurrency: settings.translateConcurrency,
      }))
      await saveSection("ytdlp", () => saveYtdlpSettings({ proxy_port: settings.proxyPort }))
      setSaveResults(results)
      setSettings((current) => ({
        ...current,
        cookie: cookieDirty ? "" : current.cookie,
        apiKey: apiKeyDirty ? "" : current.apiKey,
      }))
      if (cookieDirty) setCookieDirty(false)
      if (apiKeyDirty) setApiKeyDirty(false)
      setShowApiKey(false)

      const refreshed = await refreshSettingsFromServer()
      if (!refreshed) setMessage(t.settings.reloadError)
    } finally {
      setSaving(false)
    }
  }

  async function fetchModels() {
    setMessage("")
    setMessageKey(null)
    setModelsLoading(true)
    try {
      const response = await getOpenAIModels({
        base_url: settings.baseUrl,
        api_key: apiKeyDirty ? settings.apiKey : "",
      })
      const models = uniqueModels([settings.model, ...response.models])
      setModelOptions(models)
      setModelsLoaded(true)
      setSettings((current) => ({ ...current, model: current.model || models[0] || "" }))
      setMessage(models.length ? loadedModelsText(models.length) : t.settings.noModels)
    } catch (err) {
      setMessageKey(null)
      setMessage(err instanceof Error ? err.message : t.settings.loadModelsError)
    } finally {
      setModelsLoading(false)
    }
  }

  const saveSectionLabels: Record<SaveSection, string> = {
    cookie: t.settings.cookie,
    openai: t.settings.openaiSaveSection,
    ytdlp: t.settings.ytdlpSaveSection,
  }

  function saveResultText(result: SaveResult) {
    if (result.status === "saved") return t.settings.saveSucceeded
    if (result.status === "unchanged") return t.settings.saveUnchanged
    return `${t.settings.saveFailed}${result.httpStatus ? ` (HTTP ${result.httpStatus})` : ""}`
  }

  const fieldClass = "border-input bg-white/86 text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-primary/15"
  const selectContentClass = "border-border bg-white/96 text-foreground shadow-xl backdrop-blur-2xl"

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" />}>
        <Settings className="size-4" />
        {t.settings.button}
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-hidden border border-border bg-white/92 p-0 text-foreground ring-0 shadow-[0_28px_90px_rgba(0,0,0,0.2)] backdrop-blur-2xl sm:max-w-3xl [&_[data-slot=dialog-close]]:text-muted-foreground [&_[data-slot=dialog-close]:hover]:bg-black/5 [&_[data-slot=dialog-close]:hover]:text-foreground">
        <form onSubmit={submit} className="flex max-h-[calc(100dvh-4rem)] min-h-0 flex-col">
          <DialogHeader className="shrink-0 border-b border-border bg-white/68 px-5 py-4 pr-12">
            <div className="flex items-center gap-3">
              <span className="flex size-9 items-center justify-center rounded-lg border border-primary/15 bg-primary/8 text-primary">
                <Settings className="size-4" />
              </span>
              <div>
                <DialogTitle className="text-lg font-semibold text-foreground">{t.settings.title}</DialogTitle>
                <DialogDescription className="mt-1 text-xs text-muted-foreground">{t.settings.description}</DialogDescription>
              </div>
            </div>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto p-4 sm:p-5">
            <div className="grid gap-4 lg:grid-cols-[0.85fr_1.15fr]">
              <div className="space-y-4">
                <section className="rounded-2xl border border-border bg-black/[0.025] p-4">
                  <div className="mb-4 flex items-center gap-2">
                    <Globe2 className="size-4 text-primary" />
                    <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      {language === "zh" ? "界面与网络" : "Interface & network"}
                    </h3>
                  </div>
                  <div className="grid gap-4">
                    <div className="grid gap-2">
                      <Label htmlFor="uiLanguage">{t.settings.language}</Label>
                      <Select value={language} onValueChange={(value) => { if (value === "en" || value === "zh") setLanguage(value) }}>
                        <SelectTrigger id="uiLanguage" className={fieldClass}><SelectValue /></SelectTrigger>
                        <SelectContent className={selectContentClass}>
                          {LANGUAGE_OPTIONS.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="proxyPort">{t.settings.proxyPort}</Label>
                      <div className="relative">
                        <Network className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
                        <Input id="proxyPort" inputMode="numeric" value={settings.proxyPort} onChange={(event) => setSettings((current) => ({ ...current, proxyPort: event.target.value }))} placeholder="7890" className={`${fieldClass} pl-8`} />
                      </div>
                    </div>
                  </div>
                </section>

                <section className="rounded-2xl border border-border bg-black/[0.025] p-4">
                  <div className="mb-4 flex items-center gap-2">
                    <Cookie className="size-4 text-primary" />
                    <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">YouTube access</h3>
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="cookie">{t.settings.cookie}</Label>
                    <Textarea
                      id="cookie"
                      value={cookieValue}
                      onFocus={(event) => { if (!cookieDirty && settings.cookie === SAVED_COOKIE_SENTINEL) event.currentTarget.select() }}
                      onChange={(event) => {
                        setCookieDirty(true)
                        setSettings((current) => ({
                          ...current,
                          cookie: current.cookie === SAVED_COOKIE_SENTINEL ? event.target.value.replace(t.settings.savedCookie, "") : event.target.value,
                        }))
                      }}
                      placeholder={t.settings.cookiePlaceholder}
                      className={`min-h-40 max-h-[34dvh] overflow-auto font-mono text-xs leading-relaxed ${fieldClass}`}
                    />
                    <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <ShieldCheck className="size-3.5" />
                      {language === "zh" ? "凭据仅保存在本地后端" : "Credentials stay in the local backend"}
                    </p>
                  </div>
                </section>
              </div>

              <section className="rounded-2xl border border-border bg-black/[0.025] p-4">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Cpu className="size-4 text-primary" />
                    <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">OpenAI compatible</h3>
                  </div>
                  <span className="rounded-full border border-emerald-600/15 bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-700">
                    {settings.apiKey ? (language === "zh" ? "已配置" : "Configured") : (language === "zh" ? "待配置" : "Not configured")}
                  </span>
                </div>
                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="baseUrl">{t.settings.baseUrl}</Label>
                    <Input id="baseUrl" value={settings.baseUrl} onChange={(event) => setSettings((current) => ({ ...current, baseUrl: event.target.value }))} className={fieldClass} />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="apiKey">{t.settings.apiKey}</Label>
                    <div className="relative">
                      <KeyRound className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
                      <Input
                        id="apiKey"
                        type={showApiKey ? "text" : "password"}
                        value={settings.apiKey}
                        onFocus={(event) => { if (!apiKeyDirty && settings.apiKey === SAVED_API_KEY_MASK) event.currentTarget.select() }}
                        onChange={(event) => {
                          setApiKeyDirty(true)
                          setSettings((current) => ({ ...current, apiKey: event.target.value.replace(SAVED_API_KEY_MASK, "") }))
                        }}
                        placeholder={t.settings.apiKeyPlaceholder}
                        className={`${fieldClass} pr-9 pl-8`}
                      />
                      <Button type="button" variant="ghost" size="icon-sm" className="absolute top-1 right-1 text-muted-foreground hover:bg-black/5 hover:text-foreground" onClick={() => setShowApiKey((current) => !current)}>
                        {showApiKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                        <span className="sr-only">{showApiKey ? t.settings.hideApiKey : t.settings.showApiKey}</span>
                      </Button>
                    </div>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                    <div className="grid gap-2">
                      <Label htmlFor="model">{t.settings.model}</Label>
                      {modelsLoaded && modelOptions.length > 0 ? (
                        <Select value={settings.model} onValueChange={(value) => setSettings((current) => ({ ...current, model: value || "" }))}>
                          <SelectTrigger id="model" className={fieldClass}><SelectValue placeholder={t.settings.selectModel} /></SelectTrigger>
                          <SelectContent className={selectContentClass}>{modelOptions.map((model) => <SelectItem key={model} value={model}>{model}</SelectItem>)}</SelectContent>
                        </Select>
                      ) : (
                        <Input id="model" value={settings.model} onChange={(event) => setSettings((current) => ({ ...current, model: event.target.value }))} className={fieldClass} />
                      )}
                    </div>
                    <div className="grid gap-2 sm:self-end">
                      <Button type="button" variant="outline" onClick={fetchModels} disabled={modelsLoading || !settings.baseUrl.trim()}>
                        <RefreshCw className={`size-4 ${modelsLoading ? "animate-spin" : ""}`} />
                        {modelsLoading ? t.settings.loading : t.settings.getModels}
                      </Button>
                    </div>
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="translateConcurrency">{t.settings.translateConcurrency}</Label>
                    <Input id="translateConcurrency" inputMode="numeric" value={settings.translateConcurrency} onChange={(event) => setSettings((current) => ({ ...current, translateConcurrency: event.target.value.replace(/[^0-9]/g, "") }))} placeholder="50" className={fieldClass} />
                    <p className="text-xs leading-relaxed text-muted-foreground">{t.settings.concurrencyHelp}</p>
                  </div>
                </div>
              </section>

              {saveResults.length > 0 ? (
                <div data-testid="settings-save-results" className="rounded-2xl border border-border bg-black/[0.025] px-4 py-3 text-sm lg:col-span-2" aria-live="polite">
                  <p className="font-medium text-foreground">{t.settings.saveResultsTitle}</p>
                  <ul className="mt-1 space-y-1">
                    {saveResults.map((result) => (
                      <li key={result.section} className={result.status === "failed" ? "text-red-700" : "text-muted-foreground"}>
                        {saveSectionLabels[result.section]}: {saveResultText(result)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {visibleMessage ? <p className="text-sm text-muted-foreground lg:col-span-2">{visibleMessage}</p> : null}
            </div>
          </div>
          <DialogFooter className="mx-0 mb-0 shrink-0 rounded-none rounded-b-2xl border-border bg-white/68 px-5 py-3">
            <Button type="submit" className="px-4" disabled={saving}>
              {saving ? t.settings.saving : t.settings.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
