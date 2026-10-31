# michael-customizations

Port of `PS-Graham/hermes-agent@michael/local-hermes-customizations` (May 2026) to Hermes v0.22.5.

It is a plugin rather than a branch because `hermes update` on the stable channel lands detached at
the release commit, which would silently drop commits on any branch of the checkout.

| Fork change | Now |
| --- | --- |
| `hermes sessions live ...` | `hermes live ...` (plugin CLI commands are top-level). Needs tmux, so on native Windows it only reports that. |
| `compression.pre_compaction_review` | Same config key, off by default. Writes `HERMES_HOME/session-reviews/precompaction/<lineage>.md`. Restart after changing it. |
| `HERMES_DISABLE_MANAGED_NOUS_TOOLS` | Same env var, read at plugin load. |
| `update.auto_restore_local_changes` | Dropped: upstream `updates.non_interactive_local_changes` covers it, and the plugin leaves no local source changes to restore. |
| ASCII separators in `sessions list` | Dropped: the Unicode output works on Windows, piped and unpiped, in v0.22.5. |

`tests/` is plain pytest. The Hermes runtime ships without pytest, so install it to a separate folder
and put that and the checkout on `sys.path` before `import hermes_bootstrap`.
