[한국어](README.md) | **English**

# Cowork Pilot

An E2E AI automation system that builds entire projects from a single spec document.

Feed it a development spec and Cowork (Claude Desktop's agent mode) writes the code while cowork-pilot automatically responds to every question and permission request along the way, orchestrating execution plans chunk by chunk until the project is complete. You plan, AI does the rest.

---

## What It Does

### Phase 1 — Auto-Response (Watch Mode)

Monitors a Cowork session's JSONL log in real time. When an `AskUserQuestion` or tool permission request appears:

1. **Watcher** tails the JSONL file and detects `tool_use` events
2. **Dispatcher** reads project docs (`golden-rules.md`, `decision-criteria.md`) and recent conversation context to build a prompt for the CLI agent
3. **CLI Agent** (`claude -p`) returns an option number, "allow/deny", or "ESCALATE"
4. **Validator** checks response format (retries up to 3 times on bad format)
5. **Responder** sends keyboard input to the Claude Desktop app via AppleScript (arrow keys, Enter, Cmd+V, etc.)
6. **Post-verify** confirms the response was delivered by checking for a `tool_result` in the JSONL

Dangerous requests (payments, secrets, production deploys, etc.) are automatically **ESCALATE**d with a macOS notification + TTS alert.

### Phase 2 — Execution Plan Orchestration (Harness Mode)

Automatically executes exec-plans in `docs/exec-plans/` chunk by chunk:

1. Promotes exec-plans from `planning/` to `active/`
2. Opens a new Cowork session with each Chunk's session prompt (via AppleScript `Shift+Cmd+O`)
3. Runs Phase 1 auto-response concurrently while the Chunk is being worked on
4. When the session goes idle, checks exec-plan checkboxes (`[x]`) to determine completion
5. Sends feedback on incomplete items for retry; ESCALATEs if retries are exhausted
6. Moves to the next Chunk on completion; moves the plan to `completed/` when all Chunks are done

### Phase 3 — Meta Agent (Meta Mode)

Generates an entire project from a one-line description:

- **Step 0**: Fills out a project brief through a Cowork conversation with the user
- **Step 1**: Scaffolds project directory + doc templates from the brief
- **Step 2**: Runs Harness to auto-generate doc contents (design docs, specs, etc.)
- **Step 3**: User verification/approval (manual or auto)
- **Step 4**: Runs Harness to execute implementation plans sequentially

---

## Recommended Workflow

The overall flow is 3 steps: **Prepare spec → Generate docs structure → Auto-execute**.

### Step 1: Prepare a Development Spec

cowork-pilot needs a **development spec** (design document, feature spec, data model, etc.) to automatically implement a project. Prepare one using either method:

- **Option A — Write it in Cowork**: Have a thorough conversation about your project in Claude Desktop's Cowork mode. Save the output as a markdown file.
- **Option B — Use an existing spec**: If you already have a spec document (markdown, Notion export, etc.), use it as-is.

Format doesn't matter. What matters is that it contains the project's features, tech stack, and design direction.

### Step 2: Generate Docs Structure (`/docs-restructurer` Skill)

Once the spec is ready, open a new Cowork session, drop in the spec file, and invoke the `/docs-restructurer` skill. This skill converts the free-form spec into a standardized `docs/` structure that cowork-pilot understands:

```
docs/
├── design-docs/       # Design documents (data model, auth, architecture, etc.)
├── product-specs/     # Per-page/feature detailed specs
├── exec-plans/        # Execution plans (chunk-based)
│   ├── planning/      # Queued plans (sorted by number)
│   ├── active/        # Currently executing (max 1)
│   └── completed/     # Finished plans
├── DESIGN_GUIDE.md
├── SECURITY.md
└── QUALITY_SCORE.md
```

The key output is the `exec-plans/` directory with chunk-based execution plans. Each Chunk contains a task list, completion criteria checkboxes, and a session prompt.

> **Note**: The `/docs-restructurer` skill runs as a 5-phase pipeline. After each phase it shows results and asks for confirmation before proceeding. It may also ask additional questions if information is missing from the spec. This is a **semi-automatic process — you need to be at the Cowork screen to answer questions**.

### Step 3: Auto-Execute (`--mode harness`)

Once the docs structure is generated, navigate to the project directory in your terminal and run harness mode:

```bash
cd /path/to/your-project
cowork-pilot --mode harness
```

From this point, cowork-pilot automatically:
1. Promotes the first exec-plan from `planning/` to `active/`
2. Opens a Cowork session with Chunk 1's session prompt
3. Auto-responds to questions/permission requests while Cowork writes code
4. Chunk complete → next Chunk → all Chunks done → next exec-plan... repeat
5. Sends a macOS notification when all plans are finished

You can leave the terminal running and do other things. If a risky decision is needed, you'll get an ESCALATE notification.

### Flow Summary

```
[You] Write a spec (Cowork conversation or existing document)
  │
  ▼
[Cowork] /docs-restructurer skill generates docs/ structure
  │
  ▼
[Terminal] cowork-pilot --mode harness
  │
  ▼
[Auto] Chunk-by-chunk Cowork sessions → code → verify → repeat
  │
  ▼
[Done] Project complete notification
```

### Required Cowork Skills (Plugins)

Cowork sessions opened by cowork-pilot use the following skills. All must be installed for proper operation.

**This Repo's Plugin (Install via Marketplace)**

This repo is structured as a Cowork marketplace. In Claude Desktop settings, add a marketplace → enter this GitHub repo URL (`<owner>/cowork-pilot`) to install the `cowork-pilot` plugin, which includes these 3 skills:

| Skill | Role |
|-------|------|
| `/docs-restructurer` | Converts spec → docs/ structure (used in Step 2) |
| `/chunk-complete` | Marks exec-plan checkboxes on Chunk completion |
| `/vm-install` | Safe toolchain installation + automatic cleanup in VM |

**Separate Installation Required (Anthropic Official Plugin)**

| Skill | How to Install |
|-------|----------------|
| `/engineering:code-review` | Install the `engineering` plugin in Claude Desktop (officially provided by Anthropic) |

`/engineering:code-review` and `/chunk-complete` are part of the workflow that harness automatically injects into Chunk session prompts. The enforced order of code review → fix → completion marking maintains quality.

---

## Requirements

### Operating System

**macOS only.** Uses AppleScript (`osascript`), `pbcopy`, macOS notifications (`display notification`), and `say` TTS.

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| **Python** | 3.10+ | Runtime |
| **Claude Desktop** | Version with Cowork mode | Target app for auto-response |
| **Claude CLI** | Latest | Decision engine for questions |

Claude CLI uses the `claude -p` flag for pipe mode — receives prompts from stdin and outputs responses to stdout.

### macOS Permissions

cowork-pilot sends keyboard input (`keystroke`, `key code`) to Claude Desktop via AppleScript. This requires **Accessibility permissions**.

Go to **System Settings → Privacy & Security → Accessibility** and add/enable your terminal app (Terminal, iTerm2, Warp, etc.). Without this permission, AppleScript `keystroke`/`key code` commands are silently ignored and auto-response won't work at all.

macOS may show a permission popup on first run. If it doesn't, manually add your terminal app at the path above.

---

## Installation

```bash
# Clone the repo
git clone https://github.com/<your-username>/cowork-pilot.git
cd cowork-pilot

# Install package (editable mode)
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"
```

The only runtime dependency is `jinja2>=3.1`.

---

## Configuration

All settings are managed via `config.toml` at the project root.

```toml
[engine]
default = "claude"

[engine.claude]
command = "claude"
args = ["-p"]                # pipe mode (stdin → stdout)

[watcher]
debounce_seconds = 2.0       # Wait time after event detection before responding
poll_interval_seconds = 0.5  # JSONL file polling interval

[responder]
post_verify_timeout_seconds = 30.0  # Post-response verification timeout
max_retries = 3                     # CLI response format retry count
activate_delay_seconds = 0.3        # AppleScript app activation delay

[session]
base_path = "~/Library/Application Support/Claude/local-agent-mode-sessions"

[logging]
path = "logs/cowork-pilot.jsonl"
level = "INFO"

[harness]
idle_timeout_seconds = 30            # Chunk idle detection timeout
completion_check_max_retries = 3     # Completion verification retries
incomplete_retry_max = 3             # Incomplete feedback retries
exec_plans_dir = "docs/exec-plans"

[harness.session]
open_delay_seconds = 3.0     # Delay after opening new session
prompt_delay_seconds = 1.0   # Delay before prompt input
detect_timeout_seconds = 10.0
detect_poll_interval = 1.0
```

---

## Usage

### Phase 1: Auto-Response (Watch Mode)

With a Cowork session running:

```bash
cowork-pilot
```

Automatically finds the most recently active JSONL session and starts watching. Switches automatically when the session changes.

```bash
# Specify config file
cowork-pilot --config my-config.toml
```

### Phase 2: Execution Plan Orchestration (Harness Mode)

```bash
cowork-pilot --mode harness
```

Reads the exec-plan file in `docs/exec-plans/active/` and opens Cowork sessions chunk by chunk. Auto-promotes from `planning/` if `active/` is empty.

### Phase 3: Meta Agent (Meta Mode)

```bash
cowork-pilot --mode meta "Build a todo management web app"
```

Pass a project description as an argument. It fills out a brief through Cowork conversation, scaffolds, generates docs, and runs implementation automatically.

---

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                    cowork-pilot                       │
│                                                       │
│  ┌──────────┐   ┌────────────┐   ┌───────────────┐  │
│  │  Watcher  │──▶│ Dispatcher │──▶│  CLI Agent    │  │
│  │(JSONL Tail)│  │(Prompt Build)│ │(claude -p)    │  │
│  └──────────┘   └────────────┘   └───────┬───────┘  │
│       ▲                                   │          │
│       │              ┌────────────┐       ▼          │
│       │              │ Validator  │◀──(raw text)     │
│       │              └─────┬──────┘                  │
│       │                    │                         │
│       │              ┌─────▼──────┐                  │
│       │              │ Responder  │                  │
│       │              │(AppleScript)│                 │
│       │              └─────┬──────┘                  │
│       │                    │                         │
│       └────────────────────┘  (post-verify)          │
└─────────────────────────────────────────────────────┘
         ▲                           │
         │ JSONL read                │ AppleScript keystroke
         ▼                           ▼
┌─────────────────┐        ┌──────────────────┐
│  Cowork Session  │        │  Claude Desktop  │
│  (JSONL log)     │        │  (macOS app)     │
└─────────────────┘        └──────────────────┘
```

### Module Structure

```
src/cowork_pilot/
├── main.py                 # CLI entry point, main loop (watch/harness/meta)
├── watcher.py              # JSONL tail + state machine (IDLE→DETECTED→DEBOUNCE→PENDING→RESPONDED)
├── dispatcher.py           # Prompt building, CLI invocation, project doc loading
├── validator.py            # CLI response format validation (select/other/allow/deny/escalate)
├── responder.py            # AppleScript generation/execution, macOS notifications, clipboard, verification
├── models.py               # Dataclasses (Event, Response, EventType, WatcherState)
├── config.py               # TOML config loading (Config, HarnessConfig, MetaConfig, etc.)
├── session_finder.py       # Find most recently active JSONL session
├── session_opener.py       # Open new Cowork session via AppleScript (Shift+Cmd+O)
├── session_manager.py      # Chunk lifecycle management, exec-plan file moves
├── plan_parser.py          # Exec-plan markdown parsing (Chunk, Task, Criteria)
├── completion_detector.py  # Idle detection, Chunk completion verification, feedback sending
├── scaffolder.py           # Brief-based project directory + template scaffolding
├── brief_parser.py         # project-brief.md parsing
├── meta_runner.py          # Meta-agent orchestration (Steps 0~4)
├── logger.py               # Structured JSONL logger
└── brief_templates/        # Jinja2 project templates (.j2)
```

### Decision Documents

Rules that the CLI agent uses for decision-making live in `docs/`:

- `docs/golden-rules.md` — ESCALATE blacklist (payments, secrets, production deploys, etc. — categories where auto-response is forbidden)
- `docs/decision-criteria.md` — Per-tool allow/deny criteria (Read=always allow, Bash=conditional, etc.)

These docs are injected directly into the prompt by the Dispatcher on every request, so rule changes take effect immediately.

### Exec-Plan Format

```markdown
# Plan: Feature Implementation

## Chunk 1: Data Model

### Tasks
- Create User model
- Run DB migration

### Completion Criteria
- [ ] User model file exists
- [ ] Migration successful

### Session Prompt
Create the User model and run the migration...
```

When a Chunk is completed, `[ ]` is updated to `[x]`. When all Chunks are done, the plan is moved to `completed/`.

---

## Project Structure

```
cowork-pilot/
├── .claude-plugin/            # Cowork plugin manifest
│   └── plugin.json
├── skills/                    # Cowork skills (auto-distributed via plugin)
│   ├── docs-restructurer/     # Spec → docs/ structure conversion
│   ├── chunk-complete/        # Exec-plan checkbox marking
│   └── vm-install/            # Safe VM installation + auto-cleanup
├── src/cowork_pilot/          # Python orchestrator source code
├── tests/                     # pytest tests + JSONL fixtures
│   └── fixtures/              # Test JSONL samples
├── docs/
│   ├── golden-rules.md        # Absolute rules for auto-response
│   ├── decision-criteria.md   # Per-tool decision criteria
│   ├── specs/                 # Design spec documents
│   └── exec-plans/            # Execution plans
│       ├── active/            # Currently executing (max 1)
│       ├── planning/          # Queued (auto-promoted by number)
│       └── completed/         # Finished plans
├── config.toml                # Runtime configuration
├── pyproject.toml             # Build config (hatchling)
├── AGENTS.md                  # Project overview (for agents + humans)
└── logs/                      # Structured JSONL logs
```

---

## Testing

```bash
pytest
```

All tests use JSONL fixtures (`tests/fixtures/`) and verify each module's logic independently without actual CLI calls or AppleScript execution.

---

## Pre-Run macOS Settings

cowork-pilot works by sending keyboard input to Claude Desktop via AppleScript. If the screen turns off or locks, keystrokes won't be delivered. Check these settings before running:

**System Settings → Lock Screen:**
- "Turn display off on battery when inactive" → **Never**
- "Turn display off on power adapter when inactive" → **Never**

**System Settings → Screen Saver:**
- Screen saver start time → **Never** (or a sufficiently long interval)

**While Running:**
- It's best to **leave your Mac alone** while cowork-pilot is running. Switching focus to another app can disrupt AppleScript's keystroke timing to Claude Desktop.
- For long-running automated sessions, keeping your Mac plugged into power is recommended.

---

## Notes

- **macOS only**: Depends on macOS-specific APIs — AppleScript, `pbcopy`, `osascript`, `say`.
- **Claude Desktop required**: Reads Cowork mode's JSONL session logs and sends key inputs to the app via AppleScript, so Claude Desktop must be running.
- **Accessibility permissions**: macOS Accessibility permission is required for keyboard control via System Events.
- **Claude CLI**: The `claude` command must be in your `$PATH`.

---

## License

MIT
