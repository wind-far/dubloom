import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-16 w-full resize-y rounded-lg border border-input bg-white/82 px-3 py-2 text-base text-foreground shadow-[inset_0_1px_2px_rgba(0,0,0,0.035)] transition-[background-color,border-color,box-shadow] outline-none placeholder:text-muted-foreground/75 hover:border-black/25 focus-visible:border-ring focus-visible:bg-white focus-visible:ring-3 focus-visible:ring-ring/16 disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 md:text-sm",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
