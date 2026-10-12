// Names for the generated OpenAPI types. Regenerate with `npm run gen:api`.
import type { components } from './schema.gen'

type S = components['schemas']

export type ActionKind = S['ActionKind']
export type ActionOut = S['ActionOut']
export type ApproveIn = S['ApproveIn']
export type Category = S['Category']
export type DemoOut = S['DemoOut']
export type EventOut = S['EventOut']
export type MessageDetail = S['MessageDetail']
export type MessagePage = S['MessagePage']
export type MessageState = S['MessageState']
export type MessageSummary = S['MessageSummary']
export type Preset = S['PresetOut']
export type Priority = S['Priority']
export type QuotaOut = S['QuotaOut']
export type Risk = S['Risk']
export type StatsOut = S['StatsOut']
export type StatusOut = S['StatusOut']
export type TestEmailIn = S['TestEmailIn']
export type TestEmailOut = S['TestEmailOut']
export type UsageOut = S['UsageOut']

/** What /api/events sends with every message event. */
export interface LiveEvent {
  event: EventOut
  message: MessageSummary | null
}

/** The inbox tabs and the states each one shows. */
export type Filter = 'all' | 'review' | 'dead'
export const FILTER_STATES: Record<Filter, MessageState[]> = {
  all: [],
  review: ['awaiting_approval'],
  dead: ['dead'],
}
