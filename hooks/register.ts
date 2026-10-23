// skill-spotter mod (M7): show suggestions as a band above the prompt, with buttons.
//
//   skill-spotter: You've repeated this 5 times: "…"  [Create /weekly-changelog]  [Not now]
//
// Needs Claude Code with mods (v2.1.287+). On older versions this module doesn't load,
// the session never registers a band, and the Stop hook keeps using systemMessage.
// All data stays local: the band talks to the bundled skill-spotter CLI, nothing else.

type Pending = {
  text: string
  summary?: string
  id?: string
  name?: string
  draft?: string
  data_dir?: string
}

let pending: Pending | null = null
let sessionId = ''

// A mod can't read CLAUDE_PLUGIN_DATA (only hooks get it), so the band hand-off goes
// through a fixed mailbox folder and each suggestion names the data folder to act on.
async function cli($: any, args: string[]): Promise<string> {
  const result = await $.process.run([$.plugin.root + '/scripts/skill-spotter', ...args])
  return String(result?.stdout ?? '').trim()
}

export function register(on: any) {
  on('session.start', async ($: any, e: any, next: any) => {
    sessionId = String(await $.session.id())
    await cli($, ['band', 'register', '--session', sessionId])
    return next(e)
  })

  // After each turn, fetch a suggestion the Stop hook queued for this session. The id is
  // read again: /clear starts a new session without a new session.start, and `band
  // pending` registers the new id so the next suggestion comes here, not as a message.
  on('turn.complete', async ($: any, e: any, next: any) => {
    sessionId = String(await $.session.id())
    const out = await cli($, ['band', 'pending', '--session', sessionId])
    if (out) {
      try {
        pending = JSON.parse(out)
        $.ui.invalidate('ui.render')
      } catch {
        pending = null
      }
    }
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($: any, e: any, next: any) => {
    if (!pending || e.props?.isWorking) return next(e)
    const { Box, Text, Button } = $.ui.resolve(e)
    const close = () => {
      pending = null
      $.ui.invalidate('ui.render')
    }
    const label = pending.summary ?? pending.text.replace(/^skill-spotter: /, '')
    return Box({
      flexDirection: 'row',
      columnGap: 2,
      children: [
        Text({ children: ['skill-spotter: ' + label] }),
        pending.draft
          ? Button({
              key: 'create',
              label: pending.name ? `Create /${pending.name}` : 'Create skill',
              hotkey: '1',
              onPress: async () => {
                await $.prompt.fill({ text: pending!.draft })
                close()
              },
            })
          : null,
        pending.id
          ? Button({
              key: 'later',
              label: 'Not now',
              hotkey: '2',
              onPress: async () => {
                const p = pending!
                if (p.id!.startsWith('p')) {
                  await cli($, [...(p.data_dir ? ['--data-dir', p.data_dir] : []), 'snooze', p.id!])
                }
                close()
              },
            })
          : null,
      ].filter(Boolean),
    })
  })
}
