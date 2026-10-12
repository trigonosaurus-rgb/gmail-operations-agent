import { expect, test } from '@playwright/test'

// Each test gets a fresh browser context, so a fresh demo sandbox with the seed inbox.

test('the seed inbox triages live, and a reviewed email is approved', async ({ page }) => {
  await page.goto('/')
  const list = page.getByRole('region', { name: 'Messages' })
  const tom = list.getByRole('link', { name: /URGENT: the chatbot is not answering/ })

  // Triage happens after the page loaded: only the event stream can bring it in.
  await expect(tom).toContainText('Needs review')
  await tom.click()

  const email = page.getByRole('region', { name: 'Selected email' })
  await expect(email.getByRole('heading')).toHaveText('URGENT: the chatbot is not answering')
  await email.getByRole('checkbox', { name: 'Include' }).last().click() // leave out the reply draft
  await email.getByRole('button', { name: 'Approve · run 2 actions' }).click()

  await expect(email.getByText(/^Actions · finished/)).toBeVisible()
  await expect(email.getByText('Skipped', { exact: true })).toBeVisible()
  await expect(tom).toContainText('Done')
})

test('a dead letter is retried without repeating finished actions', async ({ page }) => {
  await page.goto('/?filter=dead')
  const list = page.getByRole('region', { name: 'Messages' })
  // The opening scenario approves this email and Notion "fails" once.
  const jonas = list.getByRole('link', { name: /KI-Assistent/ })
  await expect(jonas).toBeVisible({ timeout: 15_000 })
  await jonas.click()

  const email = page.getByRole('region', { name: 'Selected email' })
  await expect(email.getByRole('alert')).toContainText("won't be created twice")
  await email.getByRole('button', { name: 'Retry' }).click()
  await expect(email.getByText(/^Actions · finished/)).toBeVisible()

  await email.getByRole('tab', { name: 'Activity & cost' }).click()
  await expect(email.getByText('Retry requested')).toBeVisible()
  await expect(email.getByText('Sheets row appended')).toHaveCount(1) // not appended twice
})

test('a test email from the composer goes through the guardrails', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Test email' }).click()
  const form = page.getByRole('dialog', { name: 'Send a test email' })
  await form.getByRole('button', { name: 'Prompt injection' }).click()
  await form.getByRole('button', { name: 'Send to agent' }).click()
  await expect(form).toBeHidden()

  const email = page.getByRole('region', { name: 'Selected email' })
  await expect(email.getByRole('heading')).toHaveText('Partnership')
  await expect(email.getByRole('note')).toContainText('Prompt injection detected')
  await expect(email.getByText('Notion task', { exact: true })).toHaveCount(0) // no task for a risky email
})

test('search and the stats page', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('searchbox', { name: 'Search emails' }).fill('счёт')
  const list = page.getByRole('region', { name: 'Messages' })
  await expect(list.getByRole('link')).toHaveCount(1)
  await expect(page).toHaveURL(/q=/)

  await page.getByRole('navigation').getByRole('link', { name: 'Stats' }).click()
  await expect(page.getByRole('heading', { name: 'Stats' })).toBeVisible()
  await expect(page.getByRole('row', { name: /Invoice/ })).toBeVisible()
})
