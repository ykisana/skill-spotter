"""Background tier (SPEC 5.5): batch re-clustering, run detached every N turns.

``launcher`` is stdlib-only and imported by the Stop hook; ``job`` runs in its own
process and may import optional extras installed into the plugin data directory.
"""
