// skill-spotter mod (M7): show suggestions as a band above the prompt, with buttons.
//
//   You've done this 5 times — [Create /weekly-changelog]  [Not now]
//
// Needs Claude Code with mods (v2.1.287+). On older versions this module doesn't load,
// the session never registers a band, and the Stop hook keeps using systemMessage.
// All data stays local: the band talks to the bundled skill-spotter CLI, nothing else.

type Pending = { text: string; what?: string; id?: string; name?: string; draft?: string }

let pending: Pending | null = null
let sessionId = ''

async function cli($: any, args: string[]): Promise<string> {
  const data = $.env.get('CLAUDE_PLUGIN_DATA')
  const base = [$.plugin.root() + '/scripts/skill-spotter', ...(data ? ['--data-dir', data] : [])]
  const result = await $.process.run(base[0], [...base.slice(1), ...args])
  return String(result?.stdout ?? '').trim()
}

export function register(on: any) {
  on('session.start', async ($: any, e: any, next: any) => {
    sessionId = String($.session.id())
    await cli($, ['band', 'register', '--session', sessionId])
    return next(e)
  })

  // After each turn, fetch a suggestion the Stop hook queued for this session.
  on('turn.complete', async ($: any, e: any, next: any) => {
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
    const label = pending.what ? `You've done this ${pending.what}` : pending.text
    return Box({
      flexDirection: 'row',
      columnGap: 2,
      children: [
        Text({ children: ['skill-spotter: ' + label] }),
        pending.draft
          ? Button({
              key: 'create',
              label: `Create /${pending.name}`,
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
                if (pending!.id!.startsWith('p')) await cli($, ['snooze', pending!.id!])
                close()
              },
            })
          : null,
      ].filter(Boolean),
    })
  })
}
