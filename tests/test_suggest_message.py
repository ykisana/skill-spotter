"""The suggestion text a user sees (ADR 0009)."""

from __future__ import annotations

from skill_spotter import suggest


def test_message_names_skill_spotter_the_task_and_the_command():
    assert suggest.message(2, 3, "update-changelog", "update the changelog") == (
        'skill-spotter: you\'ve repeated this 3 times: "update the changelog". '
        "To save it as /update-changelog, run /skill-spotter:draft p2"
    )


def test_message_without_a_prompt_has_no_empty_quote():
    assert suggest.message(2, 1, "x", None) == (
        "skill-spotter: you've repeated this 1 time. To save it as /x, run /skill-spotter:draft p2"
    )
    assert '""' not in suggest.message(2, 3, "x", "   ")


def test_long_prompts_are_cut_at_a_word():
    prompt = "write release notes into the changelog for commits after the latest tag, commit"
    q = suggest.quote(prompt)
    assert q == '"write release notes into the changelog for commits after…"'
    assert len(q) <= suggest.QUOTE_CHARS + 3


def test_quote_is_one_line_without_pasted_blocks_or_double_quotes():
    prompt = (
        'fix the "login"\n\n  bug\n<pasted_content id="1">\nTraceback...\n'
        '</pasted_content id="1">\n'
    )
    assert suggest.quote(prompt) == "\"fix the 'login' bug\""


def test_context_text_drops_the_prefix():
    text = suggest.context_text(suggest.message(2, 3, "x", "do it"))
    assert text.startswith("skill-spotter (a local Claude Code plugin) noticed")
    assert "skill-spotter: " not in text
