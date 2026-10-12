import { expect, test } from '@playwright/test'

test('on a phone the list and the email take turns', async ({ page }) => {
  await page.goto('/')
  const list = page.getByRole('region', { name: 'Messages' })
  await expect(page.getByRole('region', { name: 'Selected email' })).toHaveCount(0)

  await list.getByRole('link', { name: /Chatbot for our dental clinic/ }).click()
  const email = page.getByRole('region', { name: 'Selected email' })
  await expect(email.getByRole('heading')).toHaveText('Chatbot for our dental clinic?')
  await expect(list).toHaveCount(0)

  await email.getByRole('button', { name: 'Inbox' }).click()
  await expect(list).toBeVisible()
})
