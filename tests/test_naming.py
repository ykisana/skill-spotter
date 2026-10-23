from __future__ import annotations

from skill_spotter import naming


def rep(words, first=None, tokens=None, lead=None):
    return {"words": words, "first": first or {}, "tokens": tokens or {}, "lead": lead or {}}


def test_object_from_edited_file_and_update_fallback():
    r = rep(
        {"changelog": 1.0, "commit": 1.0, "tag": 1.0, "add": 0.34, "write": 0.34},
        first={"add": 0.34, "update": 0.33, "write": 0.33},
        tokens={"edit:CHANGELOG.md": 1.0, "bash:git tag": 0.5},
    )
    # 'add' starts a third of the prompts; either verb is a fine default for Claude to refine.
    assert naming.suggest_name(r, None) in ("update-changelog", "add-changelog")


def test_consistent_first_verb_wins():
    r = rep({"deploy": 1.0, "api": 1.0, "staging": 0.67}, first={"deploy": 1.0})
    assert (
        naming.suggest_name(r, None, order_hint=["deploy", "api", "staging"])
        == "deploy-api-staging"
    )


def test_qualifier_before_object():
    r = rep(
        {"weekly": 1.0, "changelog": 1.0, "write": 1.0},
        first={"write": 1.0},
        tokens={"edit:docs/CHANGELOG.md": 1.0},
    )
    name = naming.suggest_name(r, None, order_hint=["write", "weekly", "changelog", "eng"])
    assert name == "write-weekly-changelog"


def test_falls_back_to_action_tokens():
    r = rep({}, tokens={"bash:npm run test": 1.0, "bash:npm": 0.1})
    assert naming.suggest_name(r, None) == "npm-run-test"


def test_collisions(tmp_path, monkeypatch):
    skills = tmp_path / ".claude" / "skills"
    (skills / "deploy-api").mkdir(parents=True)
    r = rep({"deploy": 1.0, "api": 1.0}, first={"deploy": 1.0})
    assert naming.suggest_name(r, str(tmp_path)) == "deploy-api-2"
    assert naming.suggest_name(rep({"review": 1.0}, first={"review": 1.0}), None) != "review"
    assert naming.suggest_name(r, None, taken=["deploy-api"]) == "deploy-api-2"


def test_names_are_short_kebab():
    r = rep({"x" * 60: 1.0})
    name = naming.suggest_name(r, None)
    assert len(name) <= 40 and name == name.lower()


def test_object_from_command_words():
    r = rep(
        {"create": 1.0, "annotated": 1.0, "git": 1.0, "tag": 1.0, "next": 1.0, "patch": 1.0},
        first={"create": 1.0},
        tokens={"bash:git tag -a": 1.0, "bash:git tag": 0.5, "bash:git": 0.1},
    )
    hint = ["create", "annotated", "git", "tag", "next", "patch", "version"]
    assert naming.suggest_name(r, None, order_hint=hint) in ("create-tag", "create-annotated-tag")


def test_words_beat_the_command_when_no_prompt_starts_with_a_verb():
    # ADR 0009: a None == None comparison rejected every word, so names fell back to the
    # command (/sqlite3, /psql) whenever no prompt started with a verb.
    r = rep(
        {"weekly": 1.0, "metrics": 0.75, "report": 0.75},
        first={"weekly": 0.5, "metrics": 0.5},
        tokens={"bash:psql": 1.0},
    )
    assert naming.guess(r, None, order_hint=["weekly", "metrics", "report"]) == (
        "weekly-metrics",
        False,
    )


def test_a_verb_among_the_first_words_counts():
    # "can you push this branch and open the pr" -> content words: push, branch, open, pr
    r = rep(
        {"pr": 1.0, "push": 0.75, "branch": 0.75},
        first={"push": 0.25, "pr": 0.25, "wrap": 0.25, "get": 0.25},
        lead={"push": 0.75, "pr": 1.0, "branch": 0.5},
    )
    assert naming.suggest_name(r, None, order_hint=["push", "branch", "pr"]).startswith("push-")


def test_run_is_a_name_verb_but_not_a_task_word():
    from skill_spotter import suggest
    from skill_spotter.capture import normalize_text

    assert normalize_text.content_words("run the pending migrations") == [
        "run",
        "pending",
        "migrations",
    ]
    assert "run" not in normalize_text.normalize("run the pending migrations")
    r = rep({"run": 1.0, "migrations": 1.0}, first={"run": 1.0}, lead={"run": 1.0})
    assert naming.suggest_name(r, None, order_hint=["run", "migrations"]) == "run-migrations"
    # "run" alone doesn't make a text-only pattern specific enough to suggest
    assert suggest.is_generic(None, "?", rep({"run": 1.0, "it": 1.0}))


def test_weak_guesses():
    worded = rep({"deploy": 1.0, "api": 1.0}, first={"deploy": 1.0})
    assert naming.guess(worded, None) == ("deploy-api", False)
    # from a command, not the prompts' words
    assert naming.guess(rep({}, tokens={"bash:sqlite3": 1.0}), None) == ("sqlite3", True)
    # a lone noun
    assert naming.guess(rep({"prod": 1.0}), None)[1]
    # a clash with a built-in command or an existing skill needs a number
    assert naming.guess(rep({"memory": 1.0, "leak": 0.5}), None)[1]
    assert naming.guess(worded, None, taken=["deploy-api"]) == ("deploy-api-2", True)


def test_prepositions_never_name_a_skill():
    # Live (ADR 0009): "update the changelog with the commits since the last tag and commit
    # it" was named /update-changelog-since.
    words = ["update", "changelog", "commits", "since", "last", "tag", "commit"]
    r = rep(
        {w: 1.0 for w in words},
        first={"update": 1.0},
        lead={"update": 1.0, "changelog": 1.0, "commits": 1.0},
        tokens={"edit:CHANGELOG.md": 1.0, "bash:git commit -a": 1.0},
    )
    assert naming.guess(r, None, order_hint=words) == ("update-changelog", False)
