import { expect, it } from 'vitest'

import indexHtml from '../index.html?raw'


const publicAssets = import.meta.glob('../public/**/*', {
  eager: true,
  query: '?raw',
  import: 'default',
})

it('declares a favicon that exists in the public directory', () => {
  const document = new DOMParser().parseFromString(indexHtml, 'text/html')
  const favicon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]')
  const href = favicon?.getAttribute('href')

  expect(favicon).not.toBeNull()
  expect(href).toBe('/favicon.svg')
  expect(publicAssets).toHaveProperty(`../public${href}`)
})
