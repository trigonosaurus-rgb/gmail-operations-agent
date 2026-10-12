import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type * as React from 'react'

import { cn } from '@/lib/utils'

// Two styles only: solid for the main action, filled gray for everything else.
// `field` sits on the page; `well` sits inside a panel. No outlines anywhere.
const buttonVariants = cva(
  'inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-sm font-medium transition-[background-color,opacity] select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-fg hover:bg-primary/85',
        field: 'bg-field hover:bg-hair-strong/70',
        well: 'bg-well hover:bg-field',
        ghost: 'text-muted-fg hover:bg-field hover:text-fg',
      },
      size: {
        sm: 'min-h-8 px-3 text-[13px]',
        md: 'min-h-10 px-4',
        icon: 'size-8',
      },
    },
    defaultVariants: { variant: 'well', size: 'md' },
  },
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  type = 'button',
  ...props
}: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'button'
  return (
    <Comp
      data-slot="button"
      type={asChild ? undefined : type}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button }
