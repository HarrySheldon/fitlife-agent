import ts from 'typescript'
import { expect, it } from 'vitest'


const sources = import.meta.glob(
  [
    '../pages/**/*.{ts,tsx}',
    '../components/**/*.{ts,tsx}',
    '../hooks/**/*.{ts,tsx}',
    '../services/**/*.ts',
  ],
  { eager: true, query: '?raw', import: 'default' },
) as Record<string, string>

const approvedDataValues = new Set([
  'FL',
  'FitLife Agent',
  'OpenAI',
  'English',
  '中文',
  'kg · cm · km',
  'lb · ft/in · mi',
  'kcal',
  'g',
  'Calories',
  'Protein',
  'over',
  '96g',
  'kcal ·',
  'kcal -',
  'https://models.example.com/v1',
])

function hasProductText(value: string): boolean {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return /[A-Za-z]/.test(normalized)
    && !approvedDataValues.has(normalized)
}

function isTrackedProperty(node: ts.StringLiteralLike): boolean {
  const parent = node.parent
  if (!ts.isPropertyAssignment(parent)) return false
  const name = parent.name.getText().replace(/["']/g, '')
  if (['label', 'message', 'title', 'description', 'placeholder'].includes(name)) return true
  const declaration = parent.parent.parent
  return ts.isVariableDeclaration(declaration)
    && /(?:labels|messages|summaries|descriptions|copy)$/i.test(declaration.name.getText())
}

function ancestor<T extends ts.Node>(
  node: ts.Node,
  predicate: (candidate: ts.Node) => candidate is T,
): T | null {
  let candidate = node.parent
  while (candidate) {
    if (predicate(candidate)) return candidate
    candidate = candidate.parent
  }
  return null
}

function isTranslationCallArgument(node: ts.StringLiteralLike): boolean {
  const call = node.parent
  if (!ts.isCallExpression(call) || call.arguments[0] !== node) return false
  return call.expression.getText() === 't' || call.expression.getText() === 'i18n.t'
}

function isTranslationKeyInPageHelper(node: ts.StringLiteralLike, path: string): boolean {
  return /^[a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+$/.test(node.text)
    && isPageHelperReturn(node, path)
}

function isVisibleJsxExpression(node: ts.Node): boolean {
  const expression = node.parent
  if (!ts.isJsxExpression(expression)) return false
  const parent = expression.parent
  if (!ts.isJsxAttribute(parent)) return true
  return ['aria-label', 'placeholder', 'title'].includes(parent.name.getText())
}

function isTranslationTemplateArgument(node: ts.TemplateExpression): boolean {
  const call = node.parent
  if (!ts.isCallExpression(call) || call.arguments[0] !== node) return false
  return call.expression.getText() === 't' || call.expression.getText() === 'i18n.t'
}

function isServiceMessage(node: ts.Node, path: string): boolean {
  if (!path.includes('/services/')) return false
  const declaration = ancestor(node, ts.isVariableDeclaration)
  return declaration !== null && /^(?:message|error|feedback)$/i.test(declaration.name.getText())
}

function isPageHelperReturn(node: ts.Node, path: string): boolean {
  return path.includes('/pages/')
    && path.endsWith('.ts')
    && !path.includes('.contract.')
    && ancestor(node, ts.isReturnStatement) !== null
}

function templateText(node: ts.TemplateExpression): string {
  return [node.head.text, ...node.templateSpans.map((span) => span.literal.text)].join(' ')
}

function trackedLiterals(path: string, source: string): string[] {
  const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const failures: string[] = []

  function visit(node: ts.Node) {
    if (ts.isJsxText(node) && hasProductText(node.text)) {
      failures.push(node.text.trim())
    }
    if (ts.isStringLiteralLike(node) && hasProductText(node.text)) {
      const parent = node.parent
      const trackedAttribute = ts.isJsxAttribute(parent)
        && ['aria-label', 'placeholder', 'title'].includes(parent.name.getText())
      const visibleExpression = isVisibleJsxExpression(node)
      if (
        !isTranslationCallArgument(node)
        && !isTranslationKeyInPageHelper(node, path)
        && (trackedAttribute
          || visibleExpression
          || isTrackedProperty(node)
          || isServiceMessage(node, path)
          || isPageHelperReturn(node, path))
      ) {
        failures.push(node.text.trim())
      }
    }
    if (ts.isTemplateExpression(node)) {
      const text = templateText(node)
      const visibleExpression = isVisibleJsxExpression(node)
      if (
        !isTranslationTemplateArgument(node)
        &&
        hasProductText(text)
        && (visibleExpression || isServiceMessage(node, path) || isPageHelperReturn(node, path))
      ) {
        failures.push(text.trim())
      }
    }
    ts.forEachChild(node, visit)
  }

  visit(file)
  return failures.map((literal) => `${path}: ${literal}`)
}

it('contains no untranslated tracked product literals', () => {
  const failures = Object.entries(sources)
    .filter(([path]) => !path.includes('.test.') && !path.includes('.contract.'))
    .flatMap(([path, source]) => trackedLiterals(path, source))

  expect(failures, failures.join('\n')).toEqual([])
})

it.each([
  [
    '../pages/evaluationViewModel.ts',
    "const GROUP_LABELS = { by_expected_tool: 'Expected tool' };",
    'Expected tool',
  ],
  [
    '../pages/evaluationViewModel.ts',
    'function summary(failed: number) { return `${failed} cases failed` }',
    'cases failed',
  ],
  [
    '../services/api.ts',
    'const message = payload.message || `Request failed: ${response.status}`',
    'Request failed:',
  ],
  [
    'Example.tsx',
    "const view = <div>{'Visible fallback'}</div>",
    'Visible fallback',
  ],
])('detects user-visible literals in %s', (path, source, expected) => {
  expect(trackedLiterals(path, source).join('\n')).toContain(expected)
})
