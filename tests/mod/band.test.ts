// Tests for the mod band (hooks/register.ts). Run with `claude plugin test` from the
// plugin root: no session, sign-in or network; every $ call is answered by a stub.
import { expect, test } from 'claude-code/testing'

const PENDING = {
  text:
    'skill-spotter: you\'ve repeated this 3 times: "update the changelog". ' +
    'To save it as /update-changelog, run /skill-spotter:draft p2',
  summary: 'You\'ve repeated this 3 times: "update the changelog"',
  id: 'p2',
  name: 'update-changelog',
  draft: '/skill-spotter:draft p2',
  data_dir: '/data/skill-spotter-skill-spotter',
}

const BAND = {
  plugin: 'skill-spotter',
  component: 'AbovePrompt',
  requestId: 'band',
  surface: 'terminal',
  viewport: { columns: 100, rows: 30 },
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 4,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 4 },
    view: {},
  },
} as const

const TURN = { turnId: 't1', answer: 'done', durationMs: 5, isAborted: false, usage: null }

// Stubs every $ call the mod makes; returns the argv of each process it ran.
function stubs(on: any, pending: object | null) {
  const runs: string[][] = []
  on('session.id', () => ({ value: 'sess-1' }))
  on('session.start', () => ({ cwd: '/work' }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  on('process.run', ($: any, e: any) => {
    runs.push([...e.argv])
    const isPending = e.argv.includes('pending')
    const stdout = isPending && pending ? JSON.stringify(pending) : ''
    return { value: { exitCode: 0, stdout, stderr: '' } }
  })
  return runs
}

test('session.start registers the session with the bundled CLI', async ($, on) => {
  const runs = stubs(on, null)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(runs.length).toBe(1)
  expect(runs[0][0]).toMatch(/\/scripts\/skill-spotter$/)
  expect(runs[0].slice(1)).toEqual(['band', 'register', '--session', 'sess-1'])
})

test('a queued suggestion is drawn above the prompt with both buttons', async ($, on) => {
  const runs = stubs(on, PENDING)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(TURN)
  expect(runs[1].slice(1)).toEqual(['band', 'pending', '--session', 'sess-1'])
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: 'skill-spotter' })).toBeDefined()
  const what = 'You\'ve repeated this 3 times: "update the changelog"'
  expect(await ui.find({ type: 'Text', text: what })).toBeDefined()
  expect(await ui.find({ key: 'create' })).toBeDefined()
  expect(await ui.find({ key: 'later' })).toBeDefined()
})

test('Create fills the prompt with the draft command', async ($, on) => {
  stubs(on, PENDING)
  const fills: string[] = []
  on('prompt.fill', ($: any, e: any) => {
    fills.push(e.text)
    return { isFilled: true }
  })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(TURN)
  const ui = await $.ui.mount(BAND)
  await ui.press({ key: 'create' })
  expect(fills).toEqual(['/skill-spotter:draft p2'])
  expect(await ui.find({ key: 'create' })).toBeUndefined()
})

test('Not now snoozes the pattern in the data folder the hook named', async ($, on) => {
  const runs = stubs(on, PENDING)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(TURN)
  const ui = await $.ui.mount(BAND)
  await ui.press({ key: 'later' })
  expect(runs[runs.length - 1].slice(1)).toEqual([
    '--data-dir',
    '/data/skill-spotter-skill-spotter',
    'snooze',
    'p2',
  ])
  expect(await ui.find({ key: 'later' })).toBeUndefined()
})

test('nothing is drawn without a suggestion', async ($, on) => {
  stubs(on, null)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(TURN)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
})

test('nothing is drawn while Claude is working', async ($, on) => {
  stubs(on, PENDING)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(TURN)
  const ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, isWorking: true } })
  expect(await ui.find({ key: 'create' })).toBeUndefined()
})

test('a suggestion without a name offers "Create skill"', async ($, on) => {
  stubs(on, { ...PENDING, name: null })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(TURN)
  const ui = await $.ui.mount(BAND)
  const button = await ui.find({ key: 'create' })
  expect(button?.props.label).toBe('Create skill')
})

test('a named suggestion offers "Create /name"', async ($, on) => {
  stubs(on, PENDING)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(TURN)
  const ui = await $.ui.mount(BAND)
  const button = await ui.find({ key: 'create' })
  expect(button?.props.label).toBe('Create /update-changelog')
})

test('after /clear, suggestions are fetched for the new session id', async ($, on) => {
  const runs: string[][] = []
  let id = 'before-clear'
  on('session.id', () => ({ value: id }))
  on('session.start', () => ({ cwd: '/work' }))
  on('turn.complete', () => ({ text: '' }))
  on('process.run', ($: any, e: any) => {
    runs.push([...e.argv])
    return { value: { exitCode: 0, stdout: '', stderr: '' } }
  })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  id = 'after-clear'
  await $.turn.complete(TURN)
  expect(runs[runs.length - 1].slice(1)).toEqual(['band', 'pending', '--session', 'after-clear'])
})
