import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { useDemo, useSendTestEmail, useStatus } from '@/api/queries'
import type { DemoOut, TestEmailIn } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

const EMPTY: TestEmailIn = { sender_name: '', sender_address: '', subject: '', body: '' }

/** The demo's "send a test email" form: presets from the eval set, or your own text. */
export function Composer({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const demo = useDemo(useStatus().data?.source === 'demo')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby="composer-about">
        {demo.data ? (
          <Form demo={demo.data} onSent={() => onOpenChange(false)} />
        ) : (
          <p className="p-6 text-muted-fg">{demo.error ? demo.error.message : 'Loading…'}</p>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Form({ demo, onSent }: { demo: DemoOut; onSent: () => void }) {
  const [preset, setPreset] = useState(0)
  const [mail, setMail] = useState<TestEmailIn>(() => fromPreset(demo, 0))
  const send = useSendTestEmail()
  const navigate = useNavigate()
  const { quota } = demo
  const custom = preset < 0

  const set = (key: keyof TestEmailIn) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setPreset(-1)
    setMail({ ...mail, [key]: e.target.value })
  }
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    send.mutate(mail, {
      onSuccess: (result) => {
        onSent()
        void navigate({ to: '/', search: { m: result.message.id } })
      },
    })
  }

  return (
    <form onSubmit={submit} className="flex flex-col">
      <header className="flex flex-col gap-1 px-6 pt-5 pr-14 max-sm:px-4 max-sm:pr-14">
        <DialogTitle className="text-lg font-semibold">Send a test email</DialogTitle>
        <DialogDescription id="composer-about" className="max-w-[52ch] text-[13px] text-muted-fg">
          It goes through the same pipeline as real mail: triage by the model, code guardrails,
          then actions in sandboxes. Nothing leaves the demo.
        </DialogDescription>
      </header>

      <div className="flex flex-col gap-4 px-6 pt-4.5 pb-5 max-sm:px-4">
        <fieldset className="flex flex-col gap-2">
          <legend className="pb-2 text-[13px] font-medium">Start from an example</legend>
          <div className="flex flex-wrap gap-1.5">
            {demo.presets.map((p, i) => (
              <button
                key={p.id}
                type="button"
                aria-pressed={preset === i}
                onClick={() => {
                  setPreset(i)
                  setMail(fromPreset(demo, i))
                }}
                className={cn(
                  'min-h-8 rounded-full px-3 text-[13px]',
                  preset === i ? 'bg-primary text-primary-fg' : 'bg-well hover:bg-field',
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </fieldset>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
          <Field label="Sender name">
            <input value={mail.sender_name} onChange={set('sender_name')} maxLength={100} className={INPUT} />
          </Field>
          <Field label="Sender address">
            <input
              type="email"
              required
              value={mail.sender_address}
              onChange={set('sender_address')}
              maxLength={254}
              className={INPUT}
            />
          </Field>
        </div>
        <Field label="Subject">
          <input
            required
            value={mail.subject}
            onChange={set('subject')}
            maxLength={demo.max_subject_chars}
            className={INPUT}
          />
        </Field>
        <Field label="Message">
          <textarea
            required
            rows={8}
            value={mail.body}
            onChange={set('body')}
            maxLength={demo.max_body_chars}
            className={cn(INPUT, 'resize-y py-3 leading-[1.55]')}
          />
        </Field>
      </div>

      <footer className="flex flex-wrap items-center gap-2.5 px-6 py-3.5 shadow-[0_-1px_0_var(--hair)] max-sm:px-4">
        <span role="status" className={cn('flex-[1_1_220px] text-xs', send.error ? 'text-danger' : 'text-muted-fg')}>
          {send.error ? send.error.message : quotaText(demo, custom)}
        </span>
        <DialogClose asChild>
          <Button variant="well">Cancel</Button>
        </DialogClose>
        <Button type="submit" variant="primary" disabled={quota.left <= 0 || send.isPending}>
          {send.isPending ? 'Sending…' : 'Send to agent'}
        </Button>
      </footer>
    </form>
  )
}

const INPUT =
  'min-h-10 rounded-sm bg-well px-3 text-sm font-normal outline-none focus-visible:outline-2 focus-visible:outline-review'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-[13px] font-medium">
      {label}
      {children}
    </label>
  )
}

function fromPreset(demo: DemoOut, index: number): TestEmailIn {
  const p = demo.presets[index]
  return p
    ? { sender_name: p.sender_name, sender_address: p.sender_address, subject: p.subject, body: p.body }
    : EMPTY
}

function quotaText(demo: DemoOut, custom: boolean): string {
  const { quota, live } = demo
  if (quota.left <= 0) return 'Daily limit reached. Come back tomorrow or browse the sample inbox.'
  const left = `${quota.left} of ${quota.limit} test emails left today`
  if (!live) return `${left} · the live model is off, so only the examples work: they replay recorded runs`
  return custom ? `${left} · your text goes to the live model, about $0.0001` : `${left} · examples replay recorded runs`
}
