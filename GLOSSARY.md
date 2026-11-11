# Glossary: hermes-agent

Terms as this codebase uses them. Source: `AGENTS.md` (development guide) and the modules it names. When the code and this file disagree, the code wins; fix this file.

**AIAgent**
The class in `run_agent.py` that runs one conversation: builds messages, calls the model, executes tool calls, returns the final response. Entry points `chat()` and `run_conversation()`.

**Agent loop**
The synchronous loop inside `run_conversation()`: call the model, run any tool calls, append results, repeat until the model answers without tools or the iteration budget runs out.

**Iteration budget**
The cap on tool-calling iterations (`max_iterations`, default 90), shared between a parent agent and its subagents.

**Tool**
A callable the model can invoke. Each lives in `tools/*.py` and registers itself with `tools/registry.py` at import time; `model_tools.py` discovers them and dispatches calls through `handle_function_call()`.

**Toolset**
A named bundle of tools defined in the `TOOLSETS` dict in `toolsets.py` (for example `terminal`, `web`, `memory`, `kanban`). Platforms enable or disable toolsets. `_HERMES_CORE_TOOLS` is the default bundle.

**Terminal backend (environment)**
Where terminal commands run: local, docker, ssh, modal, daytona, singularity. Lives in `tools/environments/`. Distinct from the RL training environments in `environments/`.

**Gateway**
The messaging server in `gateway/` that connects Hermes to chat platforms. One adapter per platform in `gateway/platforms/`.

**Platform**
A surface a session runs on: `cli`, or a gateway adapter such as telegram, discord, slack, email, webhook, api_server.

**Session**
One conversation's history, stored in `SessionDB` (`hermes_state.py`), a SQLite store with FTS5 search.

**HERMES_HOME**
The state directory (config, `.env`, memory, sessions, skills, logs). Always resolve it with `get_hermes_home()` from `hermes_constants`; never hardcode `~/.hermes`.

**Profile**
A fully isolated Hermes instance with its own `HERMES_HOME`. `_apply_profile_override()` in `hermes_cli/main.py` sets it before any imports.

**Skill**
A `SKILL.md` folder of instructions the agent loads on demand. Built-in skills live in `skills/`; heavier or niche ones in `optional-skills/`, installed with `hermes skills install official/<category>/<skill>`.

**Curator**
The background skill-lifecycle system (`agent/curator.py`) that tracks usage of agent-created skills and archives stale ones to `~/.hermes/skills/.archive/`. Archived skills are restorable.

**Plugin**
An extension under `plugins/` (or `~/.hermes/plugins/`, or a pip entry point). Kinds include general plugins, memory providers, model providers, context engines, image-gen providers and dashboards.

**Model provider**
An inference backend (openrouter, anthropic, and others), shipped as a plugin under `plugins/model-providers/`.

**Memory provider**
A long-term memory backend (honcho, mem0, supermemory, and others), shipped as a plugin under `plugins/memory/`.

**Delegation**
`delegate_task` (`tools/delegate_tool.py`): spawns a subagent with an isolated context and terminal. The parent waits for the child's summary.

**Cron job**
A scheduled agent run. Store in `cron/jobs.py`, tick loop in `cron/scheduler.py`; created via the `cronjob` tool, `hermes cron`, or `/cron`.

**Kanban**
The SQLite-backed multi-agent work board (`hermes kanban`, `plugins/kanban/`). A dispatcher spawns workers that use the `kanban_*` toolset.

**Slash command**
An in-session command such as `/skin` or `/cron`, registered in `hermes_cli/commands.py`.

**Skin**
Pure-data CLI theme loaded by `hermes_cli/skin_engine.py`; user skins are YAML files in `~/.hermes/skins/`.

**TUI**
The Ink (React) terminal UI in `ui-tui/` (`hermes --tui`), backed by the Python JSON-RPC server in `tui_gateway/`.

**ACP adapter**
The Agent Client Protocol server in `acp_adapter/` for editor integration (VS Code, Zed, JetBrains).
