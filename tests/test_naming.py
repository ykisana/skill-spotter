from __future__ import annotations

from skill_spotter import naming


def rep(words, first=None, tokens=None):
    return {"words": words, "first": first or {}, "tokens": tokens or {}}


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
