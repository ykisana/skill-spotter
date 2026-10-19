from __future__ import annotations

import pytest

from skill_spotter.capture import filters, normalize_text, redact

# --- redaction ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123",
        "sk-proj-abcdefghijklmnopqrstuvwxyz012345",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_11ABCDEFGHIJKLMNOPQRSTUV_xyz",
        "xoxb-1234567890-abcdefghijkl",
        "AKIAABCDEFGHIJKLMNOP",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    ],
)
def test_known_token_formats_are_redacted(secret):
    out = redact.redact(f"use {secret} please")
    assert secret not in out
    assert redact.REDACTED in out


def test_private_key_block():
    text = (
        "key:\n-----BEGIN OPENSSH PRIVATE KEY-----\nabc\ndef\n-----END OPENSSH PRIVATE KEY-----\nok"
    )
    out = redact.redact(text)
    assert "abc" not in out and out.endswith("ok")


@pytest.mark.parametrize(
    "text,leak",
    [
        ("curl -H 'Authorization: Bearer abcdef123456789xyz' https://x", "abcdef123456789xyz"),
        ("psql postgres://admin:hunter2secret@db.local/app", "hunter2secret"),
        ("export GITHUB_TOKEN=abc123def456", "abc123def456"),
        ('API_KEY="s3cr3t-value"', "s3cr3t-value"),
        ("mysql --password=topsecret1 -u root", "topsecret1"),
        ("DATABASE_URL=mysql://localhost:3306/really_long_database_name", "really_long_database"),
    ],
)
def test_assignments_and_urls(text, leak):
    assert leak not in redact.redact(text)


def test_ordinary_text_is_untouched():
    text = "deploy the api to staging and run the token tests in tests/auth.py"
    assert redact.redact(text) == text


def test_env_var_references_are_kept():
    assert redact.redact("echo $GITHUB_TOKEN") == "echo $GITHUB_TOKEN"
    assert "API_KEY=$API_KEY" in redact.redact("API_KEY=$API_KEY make deploy")


# --- filters ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,reason",
    [
        ("/review 42", "slash command"),
        ("yes", "too short"),
        ("continue please now", "too short"),
        (None, "no prompt"),
        ("<task-notification>agent 3 finished</task-notification>", "automatic"),
        ("write the weekly changelog for the eng channel", None),
    ],
)
def test_skip_reasons(prompt, reason):
    assert filters.skip_reason(prompt) == reason


def test_pasted_content_is_stripped_before_counting_words():
    prompt = (
        'fix it\n<pasted_content id="p1">\nlots of pasted log lines here and more\n'
        '</pasted_content id="p1">\n'
    )
    assert filters.strip_pasted(prompt) == "fix it"
    assert filters.skip_reason(prompt) == "too short"


def test_quick_repeat_is_skipped_but_later_repeat_is_not():
    p = "check the deploy status of the api"
    assert filters.skip_reason(p, previous_prompt=p, seconds_since_previous=60) == "repeat"
    assert filters.skip_reason(p, previous_prompt=p, seconds_since_previous=3600) is None


def test_scheduled_prompts_are_automatic():
    cron = "check the build status and report failures"
    assert filters.skip_reason(cron, scheduled_prompts=[cron]) == "automatic"
    truncated = cron[:20] + "… [+30 chars]"
    assert filters.looks_automatic(cron, [truncated])


# --- text normalization -------------------------------------------------------------


def norm(text):
    return normalize_text.normalize(text)


def test_placeholders():
    tokens = norm("deploy v1.2.3 to https://x.io and fix #42 in src/app.py by 2026-10-01, 3 times")
    for placeholder in ("<ref>", "<url>", "<path>", "<date>", "<num>"):
        assert placeholder in tokens


def test_synonyms_unify_phrasings():
    a = set(norm("write release notes from merged PRs"))
    b = set(norm("write the changelog from merged pull requests"))
    assert a == b


def test_stemming():
    assert norm("running tests") == norm("run test")
    assert norm("deploys") == ["deploy"]
    assert norm("migrations") == ["migration"]
    assert norm("policies") == ["policy"]


def test_rephrasings_overlap_more_than_different_tasks():
    a = normalize_text.ngrams(norm("pull this week's merged PRs and write the changelog summary"))
    b = normalize_text.ngrams(norm("summarize merged pull requests into the release notes"))
    c = normalize_text.ngrams(norm("fix the flaky login test in the auth service"))
    assert normalize_text.jaccard(a, b) > normalize_text.jaccard(a, c)


def test_content_words_for_naming():
    assert normalize_text.content_words("Write the weekly changelog for #eng") == [
        "write",
        "weekly",
        "changelog",
        "eng",
    ]
