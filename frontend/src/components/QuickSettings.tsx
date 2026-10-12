import { useNavigate } from '@tanstack/react-router'
import { MoonIcon, RotateCcwIcon, SlidersHorizontalIcon, SunIcon } from 'lucide-react'
import { Switch as SwitchPrimitive } from 'radix-ui'

import { useResetDemo, useSetMode } from '@/api/queries'
import type { StatusOut } from '@/api/types'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { connectionLines } from '@/lib/present'
import { useSession } from '@/lib/session'
import { useTheme } from '@/lib/theme'

import { Dot } from './Status'

/** Settings people change rarely: review mode, theme, and what the agent is connected to. */
export function QuickSettings({ status }: { status: StatusOut }) {
  const setMode = useSetMode()
  const [theme, setTheme] = useTheme()
  const { restart } = useSession()
  const navigate = useNavigate()
  const reset = useResetDemo(() => {
    restart()
    void navigate({ to: '/', search: {} }) // the open email belonged to the old sandbox
  })
  const review = (setMode.variables ?? status.mode) === 'review'

  return (
    <Popover>
      <PopoverTrigger
        aria-label="Quick settings"
        title="Quick settings"
        className="flex size-8 items-center justify-center rounded-sm text-fg hover:bg-field data-[state=open]:bg-field"
      >
        <SlidersHorizontalIcon className="size-4" />
      </PopoverTrigger>
      <PopoverContent aria-label="Quick settings" className="flex flex-col">
        <label className="flex items-center gap-3 rounded-md p-2.5 hover:bg-well">
          <span className="flex flex-1 flex-col gap-0.5">
            <span className="font-medium">Review before acting</span>
            <span className="text-xs text-muted-fg">
              Notion tasks and reply drafts wait for your approval.
            </span>
          </span>
          <Switch
            checked={review}
            disabled={setMode.isPending}
            onCheckedChange={(on) => setMode.mutate(on ? 'review' : 'auto')}
          />
        </label>

        <label className="flex items-center gap-3 rounded-md p-2.5 hover:bg-well">
          <span className="flex-1 font-medium">Theme</span>
          <ThemeSwitch dark={theme === 'dark'} onChange={(dark) => setTheme(dark ? 'dark' : 'light')} />
        </label>

        <div className="mx-2.5 mt-1.5 flex flex-col gap-1.5 border-t pt-3 pb-1.5 text-[13px]">
          {connectionLines(status).map((line) => (
            <span key={line.name} className="flex items-center gap-2">
              <Dot tone={line.on ? 'ok' : 'muted'} className="size-[7px]" />
              {line.name}
              <span className="ml-auto text-muted-fg">{line.text}</span>
            </span>
          ))}
          <span className="text-xs text-muted-fg">Model: {status.model}</span>
        </div>

        {status.source === 'demo' && (
          <button
            type="button"
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
            className="mt-1 flex items-center gap-3 rounded-md p-2.5 text-left hover:bg-well disabled:opacity-50"
          >
            <RotateCcwIcon className="size-4 shrink-0 text-muted-fg" />
            <span className="flex flex-col gap-0.5">
              <span className="font-medium">Start the demo over</span>
              <span className="text-xs text-muted-fg">
                {reset.error ? reset.error.message : 'A fresh copy of the sample inbox.'}
              </span>
            </span>
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}

/** The sun and the moon sit inside the track, so the switch explains itself. */
function ThemeSwitch({ dark, onChange }: { dark: boolean; onChange: (dark: boolean) => void }) {
  const Icon = dark ? MoonIcon : SunIcon
  return (
    <SwitchPrimitive.Root
      checked={dark}
      onCheckedChange={onChange}
      aria-label="Dark theme"
      className="relative h-7 w-13 shrink-0 rounded-full bg-field text-muted-fg"
    >
      <SunIcon className="absolute top-1.5 left-1.5 size-3.5" />
      <MoonIcon className="absolute top-1.5 right-1.5 size-3.5" />
      <SwitchPrimitive.Thumb className="absolute top-0.5 left-0.5 flex size-6 items-center justify-center rounded-full bg-panel text-fg shadow-[0_1px_3px_rgb(0_0_0/0.25)] transition-transform duration-150 data-[state=checked]:translate-x-6">
        <Icon className="size-3.5" />
      </SwitchPrimitive.Thumb>
    </SwitchPrimitive.Root>
  )
}
