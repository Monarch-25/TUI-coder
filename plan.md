# Dokument Agent — System Design & Implementation Plan
### Version 2.0 — Merged & Improved

> **Stack:** Python 3.12 · AWS Bedrock (Claude) · Temporal.io · Textual TUI · DuckDB · SQLite · Git VCS  
> **Deployment:** Local-first terminal application  
> **Primary model:** `anthropic.claude-3-5-sonnet-20241022-v2:0` (Sonnet default · Opus for deep reasoning)

---

## Table of Contents

1. [Vision & Mental Model](#1-vision--mental-model)
2. [System Architecture](#2-system-architecture)
3. [Core Subsystems](#3-core-subsystems)
   - 3.1 [Agent Orchestrator](#31-agent-orchestrator)
   - 3.2 [Planner](#32-planner)
   - 3.3 [Executor](#33-executor)
   - 3.4 [Reflection Loop](#34-reflection-loop)
   - 3.5 [Tool Runtime](#35-tool-runtime)
   - 3.6 [Workflow Engine](#36-workflow-engine)
   - 3.7 [Memory System (DuckDB)](#37-memory-system-duckdb)
   - 3.8 [VCS Layer](#38-vcs-layer)
4. [Full Tool Registry](#4-full-tool-registry)
5. [TUI Design (Textual)](#5-tui-design-textual)
6. [Bedrock LLM Integration](#6-bedrock-llm-integration)
7. [Phased Implementation Plan](#7-phased-implementation-plan)
   - [Phase 0 — Scaffolding](#phase-0--scaffolding--dev-environment)
   - [Phase 1 — TUI Shell (Textual)](#phase-1--tui-shell-textual)
   - [Phase 2 — Bedrock + Planner/Executor Loop](#phase-2--bedrock--plannerexecutor-loop)
   - [Phase 3 — Document & Audio Ingestion](#phase-3--document--audio-ingestion)
   - [Phase 4 — Standard Tool Library](#phase-4--standard-tool-library)
   - [Phase 5 — Reflection Loop](#phase-5--reflection-loop)
   - [Phase 6 — Dynamic Tool Builder](#phase-6--dynamic-tool-builder)
   - [Phase 7 — Temporal Workflow Engine](#phase-7--temporal-workflow-engine)
   - [Phase 8 — Git-like VCS Layer](#phase-8--git-like-vcs-layer)
   - [Phase 9 — Reproducible Flow System](#phase-9--reproducible-flow-system)
   - [Phase 10 — Context Optimization & Memory](#phase-10--context-optimization--memory)
   - [Phase 11 — Polish & Hardening](#phase-11--polish-observability--hardening)
8. [Data Models](#8-data-models)
9. [Directory Structure](#9-directory-structure)
10. [Tech Stack Summary](#10-tech-stack-summary)
11. [Suggested Additions](#11-suggested-additions)
12. [Risk Register](#12-risk-register)

---

## 1. Vision & Mental Model

The system is best understood as **three concentric rings** surrounding a live execution kernel:

```
┌──────────────────────────────────────────────────────────────────┐
│  OUTER RING: Reproducible Flow Library                           │
│  Frozen · shareable · CLI-addressable · `agent run <id>`         │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  MIDDLE RING: Live Agent Session                           │  │
│  │  Planner → Executor → Reflection → VCS snapshots           │  │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │  INNER RING: Tool Execution Kernel                   │  │  │
│  │  │  Standard library + Dynamic tools + Sandbox          │  │  │
│  │  │  All wrapped in Temporal activities                  │  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Core Loop (per turn)

```
User Input + optional file upload
        │
        ▼
Ingest / parse (doc, audio, CSV…)
        │
        ▼
┌── PLANNER (Claude Sonnet/Opus) ──────────────────────────┐
│  Input: user query + available tools + session memory     │
│  Output: Structured Plan IR (ordered steps + tool hints)  │
└───────────────────────────┬──────────────────────────────┘
                            │
                   [/approve if configured]
                            │
                            ▼
┌── EXECUTOR ───────────────────────────────────────────────┐
│  For each step in Plan IR:                                 │
│    → Select tool from registry (or trigger Dynamic Build) │
│    → Wrap in Temporal activity (retry, timeout, trace)    │
│    → Emit live event to TUI (step panel + log panel)      │
│    → VCS snapshot on success                              │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌── REFLECTION LOOP ────────────────────────────────────────┐
│  Compare expected vs actual output                        │
│  If failure: identify cause → adjust plan/tool/prompt     │
│  Retry with corrected approach (Temporal handles backoff) │
│  Record failure + fix in DuckDB `failures` table          │
└───────────────────────────┬──────────────────────────────┘
                            │
                  Converged? → User confirms
                            │
                            ▼
        Flow crystallized → assigned an ID
                            │
                            ▼
          `agent run <flow-id> --doc new.pdf`
```

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     CLI Entry Point                                  │
│              python -m agent  /  agent run <id>                      │
└─────────────────────────┬────────────────────────────────────────────┘
                          │
             ┌────────────▼────────────┐
             │   TUI Layer (Textual)   │
             │  Header · Stream panel  │
             │  Plan panel · Exec panel│
             │  Logs panel (collapse)  │
             │  Input bar              │
             └────────────┬────────────┘
                          │
             ┌────────────▼────────────┐
             │    Agent Orchestrator   │
             │  ┌─────────┐ ┌───────┐  │
             │  │ Planner │ │Reflect│  │
             │  └────┬────┘ └───┬───┘  │
             │       └────┬─────┘      │
             │       ┌────▼────┐       │
             │       │Executor │       │
             │       └────┬────┘       │
             └────────────┼────────────┘
                          │
          ┌───────────────┼─────────────────┐
          │               │                 │
 ┌────────▼──────┐ ┌──────▼──────┐ ┌───────▼────────┐
 │ Bedrock Claude│ │Tool Registry│ │  Temporal.io   │
 │ Sonnet/Opus   │ │ std+dynamic │ │  retry, audit  │
 └───────────────┘ └──────┬──────┘ └───────┬────────┘
                          │                │
         ┌────────────────┼────────────────┘
         │                │
┌────────▼────────┐ ┌─────▼──────────────┐ ┌────────────────────┐
│ Ingestion Layer │ │   VCS Layer        │ │   Flow Store       │
│PDF·CSV·DOCX·    │ │ git-inspired       │ │ pipeline.py        │
│Audio·Transcript │ │ snapshot·diff·     │ │ system_prompt.txt  │
└─────────────────┘ │ restore·branch     │ │ tools/ config.json │
                    └────────────────────┘ └────────────────────┘
                                │
                    ┌───────────▼────────────┐
                    │   Memory (DuckDB)      │
                    │ sessions · messages    │
                    │ tool_calls · failures  │
                    │ workflows · chunks     │
                    └────────────────────────┘
```

---

## 3. Core Subsystems

### 3.1 Agent Orchestrator

The orchestrator owns the session lifecycle and coordinates all subsystems. It does **not** reason — that is the Planner's job.

**Responsibilities:**
- Initialize a session, load memory/history
- Route user input to Planner or directly to a slash command handler
- Drive the Planner → Executor → Reflection loop
- Enforce the Temporal workflow boundary around every turn
- Emit events to the TUI event bus after every state change
- Trigger VCS snapshots at defined checkpoints

```python
class AgentOrchestrator:
    planner:    Planner
    executor:   Executor
    reflector:  ReflectionLoop
    session:    Session
    tui_bus:    EventBus

    async def handle_turn(self, user_input: str):
        await self.tui_bus.emit(THINKING, "Understanding request…")
        plan = await self.planner.plan(user_input, self.session)

        if self.session.config.require_approval:
            await self.tui_bus.emit(AWAITING_APPROVAL, plan)
            await self.wait_for_approval()   # /approve or /reject in TUI

        result = await self.executor.execute(plan, self.session)

        if result.has_failures:
            await self.reflector.reflect(plan, result, self.session)

        await self.session.vcs.snapshot("turn_complete")
```

---

### 3.2 Planner

The Planner uses **Claude Sonnet** by default and **Claude Opus** for complex multi-step plans (auto-detected by step count or user flag). It outputs a structured **Plan IR** — not free text.

**Inputs:** user query · loaded documents schema · available tools · session memory  
**Output:** `Plan` — an ordered list of `PlanStep` objects

```python
@dataclass
class PlanStep:
    index:       int
    description: str           # human-readable ("Extract revenue table")
    tool_hint:   str | None    # suggested tool name, can be overridden
    inputs:      dict          # expected tool inputs
    depends_on:  list[int]     # step indices this depends on (for parallelism)
    confidence:  float         # 0–1, low triggers Opus escalation

@dataclass
class Plan:
    query:    str
    steps:    list[PlanStep]
    strategy: str              # "sequential" | "parallel" | "mixed"
    model:    str              # which model produced this plan
```

The Planner prompt instructs Claude to return JSON-structured output only, which is validated with Pydantic. This makes the Plan deterministic and inspectable in the TUI plan panel.

```python
class Planner:
    async def plan(self, query: str, session: Session) -> Plan:
        model = self._select_model(query, session)  # Sonnet or Opus
        await emit(THINKING, f"Planning with {model}…")
        response = await bedrock.complete(
            model=model,
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_prompt(query, session)}],
            response_format="json",
        )
        plan = Plan.model_validate_json(response.text)
        await emit(PLAN_READY, plan)
        return plan

    def _select_model(self, query: str, session: Session) -> str:
        # Escalate to Opus if:
        # - User passed --deep flag
        # - Similar past queries had >2 reflection retries
        # - Query contains "complex" / "architecture" / "design" heuristics
        if session.config.force_opus or self._is_complex(query, session):
            return OPUS_MODEL_ID
        return SONNET_MODEL_ID
```

---

### 3.3 Executor

The Executor iterates over `Plan.steps`, selects tools, runs them through Temporal, and streams every state change to the TUI.

```python
class Executor:
    async def execute(self, plan: Plan, session: Session) -> ExecutionResult:
        results: dict[int, ToolResult] = {}
        failures: list[StepFailure]   = []

        for step in plan.steps:
            await emit(STEP_START, step)

            tool = registry.get(step.tool_hint) or await self._infer_tool(step)
            if tool is None:
                tool = await dynamic_builder.build(step)  # Phase 6

            try:
                result = await temporal.run_activity(
                    tool_name=tool.name,
                    args=self._resolve_inputs(step, results),
                    session_id=session.id,
                )
                results[step.index] = result
                await emit(STEP_SUCCESS, step, result)
                await session.memory.record_tool_call(step, result)

            except ToolExecutionError as e:
                failures.append(StepFailure(step=step, error=e))
                await emit(STEP_FAILURE, step, e)

        return ExecutionResult(results=results, failures=failures)
```

---

### 3.4 Reflection Loop

After every execution, the Reflection loop inspects failures and decides:
- **Retry same tool** with corrected inputs (e.g. fixed column name in SQL)
- **Switch tool** (e.g. fallback from `aws_transcribe` to `whisper`)
- **Replan** (invoke Planner again with failure context)
- **Escalate to Opus** (if Sonnet produced the failing plan)
- **Ask user** (if all strategies exhausted)

```python
class ReflectionLoop:
    MAX_RETRIES = 3

    async def reflect(self, plan: Plan, result: ExecutionResult, session: Session):
        for failure in result.failures:
            await emit(THINKING, f"Analyzing failure in step {failure.step.index}…")

            cause = await self._diagnose(failure, session)
            strategy = self._select_strategy(cause, failure, session)

            for attempt in range(self.MAX_RETRIES):
                await emit(RETRY, f"Attempt {attempt+1}/{self.MAX_RETRIES} — {strategy.label}")
                retry_result = await strategy.execute(failure, session)

                if retry_result.success:
                    await emit(STEP_SUCCESS, failure.step, retry_result)
                    await session.memory.record_fix(failure, cause, strategy)
                    break
            else:
                await emit(ASKING_USER, f"Exhausted retries for step {failure.step.index}")

    def _diagnose(self, failure: StepFailure, session: Session) -> FailureCause:
        # Categories: WRONG_COLUMN, WRONG_SCHEMA, MODEL_HALLUCINATION,
        #             TIMEOUT, MISSING_TOOL, PERMISSION_DENIED
        ...
```

The `failures` DuckDB table (Section 3.7) stores every failure + its fix. Future sessions on similar queries will look up this table before retrying, skipping known-bad paths immediately.

---

### 3.5 Tool Runtime

See Section 4 for the full registry. Key runtime concerns:

- Every tool implements `Tool` ABC with `name`, `description`, `schema()`, `execute()`
- Tool context provides: `session_id`, `workspace`, `db` (DuckDB conn), `event_bus`, `permissions`
- All execution goes through Temporal (retry + audit)
- Tools emit TUI events at `start`, `progress` (optional), `end`/`error`
- Permission levels: `read` · `write` · `exec` · `network` · `ask` (prompts user)

---

### 3.6 Workflow Engine

After a successful conversation, the agent crystallizes the session into a **portable workflow artifact** with a deterministic structure:

```
~/.agent/flows/<flow-id>/
├── pipeline.py          ← fully executable Python replay script
├── system_prompt.txt    ← optimized system prompt for this task type
├── config.json          ← parameter schema, model, permissions
├── tools/
│   ├── __init__.py
│   └── dynamic_<slug>.py  ← any generated tools, self-contained
└── vcs_snapshot/        ← exact state at crystallization
```

`pipeline.py` is a standalone Python script — it can be run directly (`python pipeline.py --doc new.pdf`) or through the agent CLI (`agent run <id>`). This means flows are inspectable, editable, and version-controllable with plain git.

---

### 3.7 Memory System (DuckDB)

DuckDB serves as both the in-process SQL engine for document queries **and** the agent's persistent memory store. All tables live in `~/.agent/agent.db`.

```sql
-- Session tracking
CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,
    created_at   TIMESTAMP,
    title        TEXT,
    directory    TEXT,
    flow_id      TEXT,           -- set if this is a flow replay
    config       JSON
);

-- Full message history (role + content blocks)
CREATE TABLE messages (
    id           TEXT PRIMARY KEY,
    session_id   TEXT REFERENCES sessions(id),
    role         TEXT,           -- 'user' | 'assistant'
    content      JSON,           -- list of content blocks
    timestamp    TIMESTAMP,
    tokens       INTEGER,
    cached       BOOLEAN         -- Bedrock cache hit?
);

-- Every tool invocation, keyed to session + message
CREATE TABLE tool_calls (
    id           TEXT PRIMARY KEY,
    session_id   TEXT,
    message_id   TEXT,
    tool_name    TEXT,
    inputs       JSON,
    output       TEXT,
    status       TEXT,           -- 'success' | 'error' | 'timeout'
    duration_ms  INTEGER,
    attempt      INTEGER,        -- retry attempt number (1 = first)
    timestamp    TIMESTAMP
);

-- All failures + their resolutions (feeds the Reflection Loop)
CREATE TABLE failures (
    id           TEXT PRIMARY KEY,
    session_id   TEXT,
    tool_name    TEXT,
    error_type   TEXT,           -- FailureCause enum
    error_msg    TEXT,
    fix_strategy TEXT,
    fixed        BOOLEAN,
    resolution   TEXT,
    timestamp    TIMESTAMP
);

-- Crystallized workflow index
CREATE TABLE workflows (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    description  TEXT,
    version      INTEGER,
    vcs_sha      TEXT,
    created_at   TIMESTAMP,
    run_count    INTEGER DEFAULT 0,
    last_run_at  TIMESTAMP
);

-- Ingested document chunks + embeddings
CREATE TABLE chunks (
    id           TEXT PRIMARY KEY,
    session_id   TEXT,
    document_id  TEXT,
    chunk_index  INTEGER,
    content      TEXT,
    page         INTEGER,
    speaker      TEXT,
    timestamp_s  FLOAT,
    embedding    FLOAT[1536]
);

-- DuckDB-registered tables from ingested documents
CREATE TABLE doc_tables (
    id           TEXT PRIMARY KEY,
    document_id  TEXT,
    table_name   TEXT,           -- DuckDB table name for SQL queries
    column_names JSON,
    row_count    INTEGER
);
```

---

### 3.8 VCS Layer

A git-inspired object store that versions the complete agent state at each checkpoint.

**What gets snapshotted:**
- Full conversation history (`conversation.jsonl`)
- DuckDB table exports (`.parquet`)
- Dynamic tool source code (`tools/*.py`)
- Todo list state (`todo.json`)
- Plan IR of the current turn (`plan.json`)
- Failure log (`failures.json`)

**CLI commands (from TUI or terminal):**
```
/vcs log                 — chronological snapshot history
/vcs diff <sha>          — what changed at a checkpoint
/vcs restore <sha>       — roll back to that state
/vcs branch <name>       — branch for an experimental approach
```

**Auto-snapshot triggers:**
1. After every successful tool call
2. After every agent reply
3. After every document upload
4. Before and after dynamic tool creation
5. Before and after the Reflection loop
6. At workflow crystallization

---

## 4. Full Tool Registry

Every tool: `name` · `description` (fed to Claude) · Pydantic input schema · `execute()` method · permission level · Temporal activity wrapper.

### 4.1 Document & Data Tools

| Tool | Purpose | Implementation |
|---|---|---|
| `document_read` | Read ingested chunks by index/range | In-memory chunk store |
| `document_search` | Semantic search across chunks | Bedrock Titan embeddings + cosine similarity |
| `table_extract` | Extract tables from PDF/DOCX as DataFrames | `pdfplumber`, `python-docx` |
| `sql_query` | Run SQL against extracted tables | DuckDB in-process |
| `sql_schema_inspect` | Show columns, types, sample rows | DuckDB `DESCRIBE` |
| `csv_parse` | Parse CSV/Excel → queryable table | `pandas` + DuckDB `register()` |
| `dataframe_transform` | Filter, group, reshape a DataFrame | `pandas` |
| `json_query` | JMESPath queries against JSON | `jmespath` |
| `diff_documents` | Diff two document chunk versions | `difflib` |
| `ocr_extract` | Extract text from scanned images/PDFs | `pytesseract` (Phase 11) |

### 4.2 NLP & AI Tools

| Tool | Purpose | Implementation |
|---|---|---|
| `sentiment_analyze` | Sentiment of text/transcript segment | Single Bedrock Claude call, structured JSON output |
| `summarize` | Summarize a document section | Bedrock Claude |
| `entity_extract` | Named entities: people, orgs, dates, amounts | Bedrock Claude |
| `intent_classify` | Classify speaker intent in transcript | Bedrock Claude |
| `topic_model` | Identify topics across long document | Bedrock Claude, chunked |
| `translate` | Translate between languages | Bedrock Claude |
| `keyword_extract` | Key terms / TF-IDF extraction | `sklearn` or Claude |
| `transcript_segment` | Split transcript by speaker/time | Custom parser + regex |
| `transcript_clean` | Remove filler words, fix formatting | Bedrock Claude |

### 4.3 Search & File Tools

| Tool | Purpose | Implementation |
|---|---|---|
| `grep` | Regex search across ingested content | `ripgrep` subprocess or Python `re` |
| `glob` | Find files matching pattern in workspace | `pathlib.glob` |
| `file_read` | Read any file in workspace | Sandboxed `open()` |
| `file_write` | Write/overwrite a file (VCS-snapshotted) | Sandboxed, triggers snapshot |
| `file_diff` | Diff two file versions | `difflib.unified_diff` |
| `web_fetch` | Fetch a URL and return text | `httpx` |
| `web_search` | Search the web | Brave Search API |

### 4.4 Computation & Utility Tools

| Tool | Purpose | Implementation |
|---|---|---|
| `calculator` | Safe math expression evaluation | `ast`-based safe eval |
| `date_time` | Current time, timezone, date arithmetic | `pendulum` |
| `unit_convert` | Length, weight, currency conversions | `pint` |
| `regex_test` | Test a regex against an input string | `re` |
| `hash` | MD5/SHA256 content hash | `hashlib` |
| `format_json` | Pretty-print and validate JSON | `json` stdlib |
| `template_render` | Fill a Jinja2 template | `jinja2` |
| `count_tokens` | Count tokens for text + model | Bedrock token API |

### 4.5 Code Tools

| Tool | Purpose | Implementation |
|---|---|---|
| `code_exec` | Execute Python in sandboxed subprocess | `subprocess` + `resource` limits + 10s timeout |
| `code_lint` | Lint Python code | `ruff` subprocess |
| `code_format` | Format Python code | `black` subprocess |
| `shell_run` | Run shell command (permission-gated) | `subprocess` + allowlist, prompts user |
| `ast_parse` | Parse Python into AST summary | `ast` stdlib |

### 4.6 Audio Tools

| Tool | Purpose | Implementation |
|---|---|---|
| `audio_transcribe` | Transcribe audio → text | AWS Transcribe (async) or local `whisper` |
| `audio_segment` | Split by silence/speaker | `pydub` + `pyannote` |
| `transcript_parse` | Parse timestamped transcript format | Custom regex parser |
| `transcript_clean` | Remove fillers, fix punctuation | Bedrock Claude |

### 4.7 Session & Flow Tools

| Tool | Purpose | Implementation |
|---|---|---|
| `todo_write` | Write/update session todo list | In-session state |
| `todo_read` | Read current todo list | In-session state |
| `snapshot_create` | VCS: create named snapshot | VCS layer |
| `snapshot_restore` | VCS: restore a prior snapshot | VCS layer |
| `snapshot_diff` | VCS: diff two snapshots | VCS layer |
| `flow_crystallize` | Freeze session into reproducible flow | Flow store |
| `flow_inspect` | Describe steps of a crystallized flow | Flow store |
| `context_compress` | Summarize old turns to free context window | Bedrock Claude |

### 4.8 Dynamic / Generated Tools (built at runtime)

| Tool | Purpose |
|---|---|
| `build_tool` | Meta-tool: generates + registers a new Python tool for this session |
| `dynamic_<slug>` | Custom tool generated by agent mid-session |
| `composed_<slug>` | Composition of 2+ tools chained together |

---

## 5. TUI Design (Textual)

**Why Textual over plain Rich:** Textual supports full widget interactivity — keyboard-navigable panels, collapsible sections, scrollable logs, and modal dialogs — making it suitable for a full-featured CLI application rather than a scrolling output display.

### 5.1 Layout

```
┌──────────────────────────────────────────────────────────────┐
│ HEADER: [Session: abc123] [Model: Sonnet] [Tokens: 12,441]  │
│          [Cache hits: 91%] [Cost: $0.042]                    │
├────────────────────────────┬─────────────────────────────────┤
│ CONVERSATION STREAM        │ SIDEBAR                         │
│ operator> summarize this   │ ┌─ TODO LIST ─────────────────┐ │
│ agent_reasoning> staging   │ │ ✔ Ingest transcript          │ │
│ plan; hidden until /plan   │ │ → Review staged plan         │ │
│ agent> ready for approval  │ │ ○ Execute approved steps     │ │
│                            │ └─────────────────────────────┘ │
│ [plan hidden by default]   │ ┌─ VCS ────────────────────────┐│
│ [logs hidden by default]   │ │ HEAD: a3f2bc "turn 4"        ││
│ [execution hidden until    │ │ branch: main                 ││
│  /approve]                 │ └─────────────────────────────┘ │
├────────────────────────────┴─────────────────────────────────┤
│ INPUT: >  /upload earnings_call.mp3                          │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 Panels

**Conversation Stream** — primary default view. It shows only:
- `operator>` user prompt or slash-command-facing request
- `agent_reasoning>` short, grey planning/execution intent
- `tool>` the exact read-only tool or command being run
- `tool_output>` the visible output snippet from that tool
- `agent>` user-visible agent reply
- inline approval prompts when a tool wants to leave the workspace or run a non-allowlisted command

Plain prompts stay in this mode by default. Planning is entered explicitly with `/plan <request>`.
The transcript must be vertically scrollable so long conversations remain inspectable without opening another panel.

**Plan Panel** — hidden by default. Revealed with `/plan`. Displays the structured `Plan IR` only when the operator explicitly asks for it.

**Execution Panel** — hidden until the plan is approved with `/approve`, then shown with step-by-step progress:
```
[✔] Step 1: transcript_segment   (0.8s)
[→] Step 2: sentiment_analyze    (running…)
[✖] Step 3: summarize            (failed — retrying)
[○] Step 4: (pending)
```

**Logs Panel** — hidden by default. Revealed with `/logs`. Each step has a sub-entry. Expand with `/expand <step>` or keyboard. Shows:
- Full tool input/output JSON
- Execution timing
- Retry history
- Temporal activity ID (click to open Web UI)

**Todo Panel** — sidebar showing the agent's `todo_write` state. Updates live.

**VCS Panel** — sidebar showing current HEAD sha + recent snapshots. `/vcs log` expands it.

### 5.3 Status Indicators

| Symbol | Meaning | Color |
|---|---|---|
| `[✔]` | Completed successfully | Green |
| `[→]` | Currently running | Yellow (animated) |
| `[✖]` | Failed | Red |
| `[○]` | Pending | Dim white |
| `[↻]` | Retrying | Orange |
| `[?]` | Awaiting user approval | Cyan blink |

### 5.4 Color Palette

| Element | Color |
|---|---|
| Default text | White |
| Agent reasoning | Grey `#7f8b99` |
| Operator text | Amber `#f2c572` |
| Agent reply | Cool white `#edf3ff` |
| Tool call | Cyan `#62d6e8` |
| Tool output | Muted blue-grey `#b5c0cd` |
| In-progress | Yellow |
| Failure / error | Red |
| Retry | Orange |
| VCS / snapshot | Blue |
| Background step detail | Dim grey |

### 5.5 Slash Commands

| Command | Action |
|---|---|
| `/upload <file>` | Ingest a document or audio file |
| `/run` | Re-run the most recent explicit plan-mode request |
| `/plan <request>` | Enter plan mode explicitly for a request and reveal the plan panel |
| `/plan` | Toggle the hidden plan panel after a plan has been staged |
| `/logs` | Toggle the hidden logs panel |
| `/thinking on\|off\|budget <n>` | Toggle Claude thinking mode and its reasoning-token budget |
| `/approve` | Approve a pending tool request or a staged plan |
| `/reject` | Reject the pending tool request or staged plan |
| `/retry` | Retry the last failed step |
| `/expand <n>` | Expand logs for step N |
| `/model sonnet\|opus` | Switch LLM model for this session |
| `/vcs log` | Show snapshot history |
| `/vcs diff <sha>` | Show diff at a snapshot |
| `/vcs restore <sha>` | Roll back to a snapshot |
| `/vcs branch <name>` | Create a branch |
| `/cost` | Show cumulative Bedrock spend |
| `/flows` | List all crystallized flows |
| `/export` | Export session as Markdown/JSON |
| `/clear` | Clear conversation, keep documents |
| `/help` | Show all commands |

### 5.6 Textual Implementation Notes

```python
# agent/tui/app.py
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Log, Static
from textual.containers import Horizontal, Vertical

class AgentApp(App):
    CSS_PATH = "agent.tcss"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                StreamPanel(id="stream"),
                PlanPanel(id="plan"),
                ExecutionPanel(id="execution"),
                CollapsibleLogs(id="logs"),
            ),
            Vertical(
                TodoPanel(id="todo"),
                VCSPanel(id="vcs"),
                id="sidebar",
            ),
        )
        yield CommandInput(id="input")
        yield Footer()

    async def on_agent_event(self, event: AgentEvent):
        """All agent events route here to update the appropriate panel."""
        match event.kind:
            case EventKind.THINKING:
                self.query_one("#stream", StreamPanel).push(event)
            case EventKind.TOOL_START:
                self.query_one("#stream", StreamPanel).push(event)
            case EventKind.TOOL_OUTPUT:
                self.query_one("#stream", StreamPanel).push(event)
            case EventKind.STEP_START:
                self.query_one("#execution", ExecutionPanel).set_running(event.step)
            case EventKind.STEP_SUCCESS:
                self.query_one("#execution", ExecutionPanel).set_done(event.step)
            case EventKind.PLAN_READY:
                self.query_one("#plan", PlanPanel).load(event.plan)
            case EventKind.TODO_UPDATE:
                self.query_one("#todo", TodoPanel).update(event.todos)
```

`PlanPanel` and `CollapsibleLogs` stay hidden until `/plan` or `/logs` toggles them on. `ExecutionPanel` stays hidden until the staged plan is approved.

### 5.7 Rich Coder Conversation Experience

The strongest terminal coding agents feel "alive" because the UI is not just a chat log. Claude Code, Codex CLI, and OpenCode all make the operator feel in control by exposing the **decision trail** around the answer:
- a persistent status line with model/session/sandbox context
- a typed transcript, not a single undifferentiated text stream
- explicit tool lifecycle visibility: why a tool ran, what ran, and what came back
- progressive disclosure: high-signal conversation by default, deeper plan/log detail on demand
- safe mode separation between read-only exploration and state-changing execution

This app should mirror that contract:

**Principle 1 — Typed transcript**
- `operator>` captures the user turn
- `agent_reasoning>` shows short decision text and model thinking deltas when available
- `tool>` shows the exact tool/command selected
- `tool_output>` shows the relevant output snippet
- `agent>` shows the user-facing answer or approval request

**Principle 2 — Reason before tool**
- Before each tool call, the agent should explain *why* it is using that tool in one short grey line.
- This is the key UX move that makes tool use feel intentional instead of noisy.

**Principle 3 — Read-only conversation, approval-gated mutation**
- Conversational turns may use read-only tools immediately for grounding: repo listing, search, file reads, git status.
- If a conversation turn wants to leave the workspace or run a non-allowlisted command, it pauses in-stream and waits for `/approve` or `/reject`.
- Multi-step execution, file mutation, and broader workflow changes still belong behind `/plan <request>` and the staged approval flow.

**Principle 4 — Detail in the stream, bulk detail behind panels**
- The stream should contain enough tool output to justify the answer.
- Raw step logs, full payloads, and execution internals remain behind `/logs`.
- Structured plan IR remains behind `/plan`.

**Principle 5 — Status line is part of the product**
- Surface: session id, active model, backend (`local` vs `bedrock`), thinking mode, tokens, cache, cost, approval mode, and branch.
- This is not decoration; it is how operators stay oriented during long-running work.

### 5.8 Conversation Event Model

The conversation UI should be driven by typed events rather than ad hoc strings. This is the core architectural move behind a rich coder TUI.

```python
@dataclass
class TranscriptEvent:
    kind: Literal[
        "user",
        "reasoning",
        "tool_call",
        "tool_output",
        "assistant",
        "warning",
        "system",
    ]
    text: str
    meta: dict[str, Any] = field(default_factory=dict)
```

**Turn flow for a direct coder conversation**
1. append `operator>` query
2. append short `agent_reasoning>` explaining the next grounding step
3. append `tool>` with the exact command/tool name
4. append `tool_output>` with the relevant snippet
5. repeat 2–4 as needed
6. if a tool crosses a boundary, append an approval request and pause until `/approve` or `/reject`
7. append streamed `agent_reasoning>` thinking deltas if Claude thinking mode is enabled
8. append streamed `agent>` final answer

This is the architecture to preserve even as the backend evolves from local heuristics to Bedrock tool use and later multi-agent execution.

### 5.9 Live Conversation Tool Subset

The current coder-facing conversation tool set should mirror the most useful read/explore tools from Cline and similar agents, without pretending the full act-mode surface already exists:

| Tool | Purpose | Conversation contract |
|---|---|---|
| `list_files` | Repo and folder discovery | Auto-runs inside workspace |
| `search_files` | `rg`-style code and text search | Auto-runs inside workspace |
| `read_file` | Direct file inspection | Auto-runs inside workspace |
| `list_code_definition_names` | High-level code map | Auto-runs inside workspace |
| `git_status` | Repo state grounding | Auto-runs inside workspace |
| `execute_command` | Shell access for inspection | Auto-approve only for read-only allowlisted commands; otherwise ask |
| `use_skill` | Load local domain skill packs | Auto-runs and exposes bundled docs/scripts |

Deferred from the broader Cline-style set for later phases:
- file write/edit/apply-patch tools
- browser and web tools
- MCP server tools
- subagents
- condensed memory / summarization tools as separate runtime tools

---

## 6. Bedrock LLM Integration

### 6.1 Model routing

```python
SONNET  = "anthropic.claude-sonnet-4-20250514-v1:0"      # default, thinking-capable
HAIKU   = "anthropic.claude-haiku-4-5-20251001-v1:0"     # cheap tasks
OPUS    = "anthropic.claude-opus-4-20250514-v1:0"        # deep reasoning, thinking-capable

def select_model(purpose: str, session: Session) -> str:
    if session.config.force_opus:
        return OPUS
    match purpose:
        case "planning" if session.config.deep_mode:
            return OPUS
        case "planning":
            return SONNET
        case "reflection" if session.reflection_retries > 2:
            return OPUS       # escalate after repeated failures
        case "reflection":
            return SONNET
        case "calculator" | "datetime" | "format_json":
            return HAIKU      # cheap tools don't need Sonnet
        case _:
            return SONNET
```

### 6.1.1 Thinking Mode

For Bedrock-backed Claude conversation turns, thinking mode is operator-controlled from the TUI:

```python
thinking = {
    "type": "enabled",
    "budget_tokens": session.thinking_budget_tokens,
} if session.thinking_enabled else None
```

Behavior contract:
- `/thinking on` enables Bedrock Claude extended thinking
- `/thinking off` disables it
- `/thinking budget <n>` changes the reasoning-token budget
- thinking deltas stream into `agent_reasoning>` in grey
- final user-facing text continues streaming into `agent>`
- if Bedrock is unavailable locally, the TUI keeps the toggle state and falls back honestly to local conversation mode

### 6.2 Streaming client

```python
# agent/core/llm.py
import boto3, json
from typing import AsyncIterator

class BedrockClient:
    def __init__(self, profile: str, region: str):
        session = boto3.Session(profile_name=profile, region_name=region)
        self._client = session.client("bedrock-runtime")

    async def stream(
        self,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8096,
            "system": system,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools

        resp = self._client.invoke_model_with_response_stream(
            modelId=model,
            body=json.dumps(body),
            contentType="application/json",
        )
        for event in resp["body"]:
            chunk = json.loads(event["chunk"]["bytes"])
            yield self._parse(chunk)
```

### 6.3 Prompt caching

Add `cache_control: {type: "ephemeral"}` to the last content block of every completed turn. The system prompt + tool definitions are marked on the first request and cached for 5 minutes. This targets 85%+ cache hit rate within a session, cutting input token costs by ~90%.

```python
def inject_cache_breakpoints(messages: list[dict]) -> list[dict]:
    """
    Mark the last content block of every completed turn as a cache breakpoint.
    Only the newest (incomplete) turn gets no breakpoint.
    """
    for msg in messages[:-1]:       # all but the latest
        content = msg["content"]
        if isinstance(content, list) and content:
            content[-1]["cache_control"] = {"type": "ephemeral"}
    return messages
```

---

## 7. Phased Implementation Plan

---

### Phase 0 — Scaffolding & Dev Environment

**Goal:** Working skeleton with all deps, local Temporal running, AWS Bedrock access confirmed.

**Duration:** 1–2 days

#### Steps

**0.1 — Project init**
```bash
python -m venv .venv && source .venv/bin/activate
pip install hatch
hatch new dokument-agent
```

**0.2 — `pyproject.toml` dependencies**
```toml
[project]
dependencies = [
  "textual>=0.47",
  "boto3>=1.34",
  "temporalio>=1.5",
  "duckdb>=0.10",
  "pdfplumber>=0.10",
  "python-docx>=1.1",
  "pandas>=2.2",
  "openpyxl>=3.1",
  "pydub>=0.25",
  "openai-whisper>=20231117",
  "httpx>=0.26",
  "pint>=0.23",
  "jinja2>=3.1",
  "pendulum>=3.0",
  "pydantic>=2.6",
  "typer>=0.12",
  "jmespath>=1.0",
  "ruff>=0.3",
  "black>=24",
  "pytest>=8",
  "pytest-asyncio>=0.23",
]
```

**0.3 — Local Temporal server**
```bash
brew install temporal   # or: curl -sSf https://temporal.download/cli.sh | sh
temporal server start-dev --db-filename ~/.agent/temporal.db
# Dashboard at http://localhost:8233
```

Add `Makefile`:
```makefile
dev:
	temporal server start-dev --db-filename ~/.agent/temporal.db &
	python -m agent chat

test:
	pytest tests/ -v --asyncio-mode=auto

lint:
	ruff check . && black --check .
```

**0.4 — AWS Bedrock access**
```bash
aws configure --profile agent-dev
# Region: us-east-1 (Claude availability)
# Test: aws bedrock list-foundation-models --profile agent-dev
```

`~/.agent/config.toml`:
```toml
[bedrock]
profile = "agent-dev"
region  = "us-east-1"
sonnet  = "anthropic.claude-sonnet-4-20250514-v1:0"
haiku   = "anthropic.claude-haiku-4-5-20251001-v1:0"
opus    = "anthropic.claude-opus-4-20250514-v1:0"

[agent]
require_approval = false   # set true to gate execution behind /approve
deep_mode        = false   # set true to default Planner to Opus

[paths]
workspace = "~/.agent/workspace"
flows     = "~/.agent/flows"
db        = "~/.agent/agent.db"
```

**Milestone:** `python -m agent --help` works, Temporal dashboard at `localhost:8233`, `aws bedrock` test call succeeds.

---

### Phase 1 — TUI Shell (Textual)

**Goal:** Full interactive terminal UI with a stream-first default view, optional plan/log inspection, and approval-gated execution — before any real LLM logic.

**Duration:** 3–5 days

**Why TUI first:** Building the UI first forces you to define the event contract between the agent and the display layer. Every subsequent phase just emits events — the rendering is already done.

#### Steps

**1.1 — Textual app skeleton**
Create `agent/tui/app.py` with all panels composed but stubbed with placeholder content. Run `textual run agent/tui/app.py` and see the layout.

**1.2 — Event bus**
```python
# agent/tui/events.py
from dataclasses import dataclass, field
from enum import Enum, auto
from asyncio import Queue

class EventKind(Enum):
    THINKING       = auto()
    PLAN_READY     = auto()
    TOOL_START     = auto()
    TOOL_OUTPUT    = auto()
    STEP_START     = auto()
    STEP_SUCCESS   = auto()
    STEP_FAILURE   = auto()
    RETRY          = auto()
    SNAPSHOT       = auto()
    REPLY          = auto()
    TODO_UPDATE    = auto()
    AWAITING_APPROVAL = auto()
    TOKEN_STREAM   = auto()

@dataclass
class AgentEvent:
    kind:    EventKind
    message: str
    detail:  dict = field(default_factory=dict)
```

**1.3 — Stream panel with token streaming**
The stream panel renders token-by-token using `textual`'s `reactive` system. Bedrock SSE chunks are fed via the event bus and appended character by character.

**1.4 — Plan panel**
Render the `Plan IR` as an ASCII-styled numbered list, but keep it hidden until `/plan` is invoked. Steps update their status in-place (pending → running → done/failed).

**1.5 — Execution panel**
Uses `textual` `DataTable` or custom widget. Each row = one step. Status cell updates via event. The panel only becomes visible after `/approve`.

**1.6 — Collapsible logs panel**
`textual.widgets.Collapsible` wrapping a `Log` widget per step. Keep it hidden until `/logs` is invoked. `/expand 2` in the input bar expands step 2.

**1.7 — Sidebar: todo + VCS panels**
`TodoPanel` renders the todo list as a styled table. `VCSPanel` shows HEAD sha + recent snapshot labels.

**1.8 — Command input**
`textual.widgets.Input` with autocomplete for slash commands. History via `~/.agent/history`.

**1.9 — Mock agent loop**
Wire a fake async function that emits `THINKING → PLAN_READY → STEP_START → STEP_SUCCESS` events on a timer. Goal: see the approval gate, optional `/plan` and `/logs` inspection, and execution timeline without any LLM calls.

**Milestone:** `agent chat` opens on a conversation-first screen. `/plan` and `/logs` reveal their hidden panels on demand, and `/approve` reveals execution progress — zero real LLM calls.

---

### Phase 2 — Bedrock + Planner/Executor Loop

**Goal:** Deliver a real coder conversation experience first: direct conversation turns, inline read-only tools, Bedrock-backed Claude replies with optional thinking mode, then approval-gated planning/execution. No Reflection or Temporal yet.

**Duration:** 4–5 days

#### Steps

**2.1 — `BedrockClient`** — streaming wrapper (Section 6.2) with thinking-mode support. Leave the invocation path in place even if local auth is unavailable.

**2.2 — Conversation runtime**
- read-only workspace tools for conversational grounding:
  - `list_files`
  - `search_files`
  - `read_file`
  - `list_code_definition_names`
  - `git_status`
- approval-aware conversation tools:
  - `execute_command`
  - `use_skill`
- these run inline in the transcript without requiring `/approve`
- each tool call must be preceded by one short reasoning line that explains why the tool was chosen
- if a tool wants to leave the workspace or run a non-allowlisted command, the turn pauses in the stream and waits for `/approve` or `/reject`

**2.3 — Multi-prompt system prompt stack**
- `conversation_system` — default terminal conversation behavior
- `planner_system` — structured plan synthesis
- `executor_system` — approved execution reporting
- `conversation_summary` — turn compression for memory
- `next_prompt_suggestion` — next useful operator prompt

```python
def build_system_prompt_stack(session: Session, tools: list[Tool]) -> dict[str, str]:
    tool_list   = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    doc_summary = summarize_loaded_docs(session)
    return {
        "conversation": render_prompt("conversation_system", session),
        "planner": render_prompt("planner_system", session),
        "executor": render_prompt("executor_system", session),
        "summary": render_prompt("conversation_summary", session),
        "suggestions": render_prompt("next_prompt_suggestion", session),
    }
```

**2.4 — Thinking-mode command**
- `/thinking on`
- `/thinking off`
- `/thinking budget <n>`
- when enabled and Bedrock is live, stream Claude thinking into `agent_reasoning>`

**2.5 — Planner** — see Section 3.2. Outputs validated `Plan` Pydantic model.

**2.6 — Executor** — see Section 3.3. Runs steps in sequence, emits TUI events.

**2.7 — `/approve` gate** — if `require_approval = true` in config, pause after Plan is displayed and wait for `/approve` or `/reject` command.

**2.8 — Prompt caching** — inject `cache_control` breakpoints per Section 6.3.

**Milestone:** Full round-trip — user can talk to the agent in a coder-style transcript, see why tools were used and what they returned, optionally enable Claude thinking mode, and still stage coherent approval-gated plans for executable work.

---

### Phase 3 — Document & Audio Ingestion

**Goal:** Accept PDF, CSV, DOCX, plain text, and audio. Parse into normalized chunks + DuckDB tables.

**Duration:** 3–4 days

#### DuckDB schema (ingestion tables)

```sql
-- See Section 3.7 for full schema
-- Key tables: sessions, chunks, doc_tables
```

#### Ingestion pipeline

```python
# agent/ingestion/pipeline.py
class IngestionPipeline:
    def ingest(self, filepath: Path, session_id: str) -> Document:
        filetype = detect_filetype(filepath)   # python-magic
        parser   = self._get_parser(filetype)
        chunks   = parser.parse(filepath)
        tables   = parser.extract_tables(filepath)
        doc      = self._store(filepath, chunks, tables, session_id)
        self._embed(doc)    # async Bedrock Titan embeddings
        return doc
```

**Parsers to implement:**
- `PDFParser` — `pdfplumber` for text + table extraction, one chunk per page
- `CSVParser` — `pandas.read_csv`, register as DuckDB table, emit schema chunk
- `DOCXParser` — `python-docx` paragraphs + tables
- `AudioParser` — AWS Transcribe (async job, poll) with local `whisper` fallback → `TranscriptParser` for speaker segmentation + `transcript_clean` tool

**TUI events during ingestion:**
```
📄 Ingesting: earnings_call.mp3
   ↳ Detected: audio/mpeg (47.2 MB)
🎙  Transcribing via AWS Transcribe…
✅ Transcription complete — 8,432 words · 14 speaker turns
🔪 Chunking into 87 segments
🧮 Embedding 87 chunks via Bedrock Titan…
✅ Document ready: earnings_call [doc_a3f2]
```

**Milestone:** Upload a PDF with tables and an MP3 — both indexed in DuckDB, SQL-queryable.

---

### Phase 4 — Standard Tool Library

**Goal:** Implement all tools from Section 4, tested, permission-gated.

**Duration:** 1–2 weeks

**Priority order:**

**Week 1 — Core data + NLP (unblocks the primary use cases):**
1. `sql_query` + `sql_schema_inspect`
2. `grep`
3. `document_search` (embeddings)
4. `table_extract`
5. `sentiment_analyze`
6. `summarize`
7. `calculator` + `date_time`
8. `todo_write` + `todo_read`

**Week 2 — Remaining library:**
9. `transcript_segment` + `transcript_clean`
10. `entity_extract` + `keyword_extract`
11. `dataframe_transform`
12. `file_read` + `file_write`
13. `code_exec` (sandboxed)
14. `web_fetch`
15. `template_render` + `format_json`

**Each tool requires:**
- Implementation in `agent/tools/<category>/<name>.py`
- Pydantic input schema
- `pytest` unit test with fixture inputs
- Permission level declaration
- Bedrock model routing hint (Haiku/Sonnet/none)

**Milestone:** All 25+ stdlib tools working and tested. Agent can do a full document analysis with only standard tools.

---

### Phase 5 — Reflection Loop

**Goal:** The agent can automatically recover from tool failures without user intervention.

**Duration:** 3–4 days

#### Steps

**5.1 — `FailureCause` taxonomy**
```python
class FailureCause(Enum):
    WRONG_COLUMN       = "wrong_column"      # SQL column doesn't exist
    WRONG_SCHEMA       = "wrong_schema"      # table structure unexpected
    MODEL_HALLUCINATION = "hallucination"    # Claude generated invalid code/query
    TIMEOUT            = "timeout"           # tool exceeded time limit
    MISSING_TOOL       = "missing_tool"      # no tool for the task
    PERMISSION_DENIED  = "permission_denied"
    EMPTY_RESULT       = "empty_result"      # tool ran but returned nothing
```

**5.2 — Diagnosis prompt** — a short Bedrock Claude call (Haiku is fine) that reads the error and classifies it into a `FailureCause`.

**5.3 — Recovery strategies**
```python
RECOVERY_STRATEGIES: dict[FailureCause, list[Strategy]] = {
    FailureCause.WRONG_COLUMN:     [InspectSchemaFirst, CorrectColumnName],
    FailureCause.WRONG_SCHEMA:     [InspectSchemaFirst, ReplanWithSchema],
    FailureCause.MODEL_HALLUCINATION: [RetryWithStricter Prompt, EscalateToOpus],
    FailureCause.TIMEOUT:          [RetryWithTimeout2x, SwitchTool],
    FailureCause.MISSING_TOOL:     [BuildDynamicTool],  # triggers Phase 6
    FailureCause.EMPTY_RESULT:     [BroaderQuery, AskUser],
}
```

**5.4 — Record to DuckDB** — every failure + fix → `failures` table. On future sessions, a lookup before retrying skips known-bad approaches.

**Milestone:** Run a query on a CSV with a deliberately wrong column name. Agent detects the error, inspects schema, corrects the column, and succeeds — all shown in the TUI with `[↻] Retry 1/3` annotations.

---

### Phase 6 — Dynamic Tool Builder

**Goal:** The agent can generate and register new Python tools mid-session when the standard library is insufficient.

**Duration:** 3–4 days

#### Steps

**6.1 — `build_tool` meta-tool** — added to every agent session. Claude is instructed to use it when `FailureCause.MISSING_TOOL` is detected.

**6.2 — Sandboxed execution**
```python
# agent/tools/dynamic/sandbox.py
import subprocess, asyncio, resource, tempfile

async def run_in_sandbox(code: str, test_args: dict, timeout: int = 10) -> SandboxResult:
    wrapper = f"""
import resource, socket, sys, json

# Memory limit: 256 MB
resource.setrlimit(resource.RLIMIT_AS, (256*1024**2, 256*1024**2))

# Disable network
import socket as _sock
_orig = _sock.socket
_sock.socket = lambda *a, **k: (_ for _ in ()).throw(
    PermissionError("No network in sandbox"))

{code}

result = execute({json.dumps(test_args)})
print(json.dumps({{"output": str(result)}}))
"""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(wrapper)
        tmppath = f.name

    proc = await asyncio.create_subprocess_exec(
        "python", tmppath,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return SandboxResult(error=f"Timeout after {timeout}s")

    if proc.returncode != 0:
        return SandboxResult(error=stderr.decode())
    return SandboxResult(output=json.loads(stdout)["output"])
```

**6.3 — Tool persistence** — dynamic tools saved to `~/.agent/workspace/<session>/tools/dynamic_<slug>.py`. Included in workflow crystallization.

**6.4 — TUI annotation** — dynamic tool creation shown in trace:
```
🛠  Building tool: extract_action_items
   ↳ Generating Python implementation…
   ↳ Linting with ruff… ✔
   ↳ Sandbox test with sample args… ✔
✅ Tool registered: extract_action_items
```

**Milestone:** Agent builds a custom "extract_action_items_by_speaker" tool during a call analysis session, uses it successfully, and it appears in the tool registry.

---

### Phase 7 — Temporal Workflow Engine

**Goal:** Every tool execution is a durable Temporal activity. Process restarts, retries, and failure history are automatic.

**Duration:** 3–4 days

#### Steps

**7.1 — Temporal worker**
```python
# agent/temporal/worker.py
from temporalio.client import Client
from temporalio.worker import Worker

async def start_worker():
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue="agent-tasks",
        workflows=[AgentTurnWorkflow],
        activities=[execute_tool_activity, call_llm_activity],
    )
    await worker.run()
```

**7.2 — `AgentTurnWorkflow`**
```python
@workflow.defn
class AgentTurnWorkflow:
    @workflow.run
    async def run(self, turn_input: TurnInput) -> TurnOutput:
        plan = await workflow.execute_activity(
            call_planner_activity, turn_input,
            start_to_close_timeout=timedelta(seconds=60),
        )
        for step in plan.steps:
            result = await workflow.execute_activity(
                execute_tool_activity,
                args=[step.tool_name, step.inputs, turn_input.session_id],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=2),
                    backoff_coefficient=2.0,
                    non_retryable_error_types=["PermissionError"],
                ),
            )
            if result.failed:
                await workflow.execute_activity(reflect_activity, result)
        return TurnOutput(...)
```

**7.3 — TUI ↔ Temporal** — Temporal activities post events to the same `event_bus` the TUI consumes. The Temporal Web UI (localhost:8233) shows the full execution graph in parallel.

**7.4 — Resume after crash** — if the agent process is killed mid-turn, restarting runs `agent chat --resume <session-id>` which reconnects to the in-flight Temporal workflow.

**Milestone:** Kill the agent process mid-tool-execution. Restart it. The turn resumes from exactly where it was.

---

### Phase 8 — Git-like VCS Layer

**Goal:** Every meaningful state is snapshotted. Users can diff, rollback, and branch.

**Duration:** 3 days

#### Object store structure
```
~/.agent/workspace/<session-id>/.agent-vcs/
├── HEAD                    → ref: refs/heads/main
├── refs/heads/main         → <sha>
└── objects/<sha>/
    ├── metadata.json       (label, timestamp, parent_sha)
    ├── conversation.jsonl  (message history)
    ├── plan.json           (last Plan IR)
    ├── todo.json
    ├── failures.json
    ├── tables/             (DuckDB table parquet exports)
    └── tools/              (dynamic tool source)
```

#### Key operations
```python
class VCSStore:
    async def snapshot(self, label: str) -> str: ...     # returns sha
    async def diff(self, sha_a: str, sha_b: str): ...
    async def restore(self, sha: str): ...
    async def branch(self, name: str): ...
    async def log(self) -> list[SnapshotMeta]: ...
```

**Milestone:** After a bad tool call, `/vcs restore <sha>` returns the session to exactly the pre-failure state.

---

### Phase 9 — Reproducible Flow System

**Goal:** Crystallize successful sessions into CLI-runnable flows with `agent run <id>`.

**Duration:** 4–5 days

#### Crystallization output
```
~/.agent/flows/<flow-id>/
├── pipeline.py           ← standalone executable Python script
├── system_prompt.txt     ← optimized prompt for this task type
├── config.json           ← parameter schema + model + permissions
├── tools/
│   ├── __init__.py
│   └── dynamic_*.py      ← any generated tools, self-contained
└── vcs_snapshot/         ← exact VCS state at crystallization
```

#### `agent run <id>` CLI
```python
@app.command()
def run(
    flow_id: str,
    doc: Optional[Path] = typer.Option(None, "--doc", "-d"),
    query: Optional[str] = typer.Option(None, "--query", "-q"),
):
    """Run a crystallized flow on a new document."""
    flow    = flow_store.load(flow_id)
    session = Session.from_flow(flow, doc=doc, query=query)
    # Restore dynamic tools from flow definition
    for tool in flow.dynamic_tools:
        session.registry.register(DynamicTool.from_source(tool))
    # Execute deterministically — same steps, new inputs
    asyncio.run(FlowRunner(session, flow).run_with_tui())
```

**Milestone:** Full round-trip — have a transcript analysis conversation → crystallize → `agent run <id> --doc new_call.mp3` → identical steps execute on the new file.

---

### Phase 10 — Context Optimization & Memory

**Goal:** Keep Bedrock costs low, context window healthy, and session intelligence improving over time.

**Duration:** 3 days

**10.1 — Context compaction** — when history exceeds 80% of context window, summarize old turns into a single compressed chunk. Last 10 turns always kept verbatim.

**10.2 — Failure memory lookups** — before retrying any tool, check the `failures` table for the same `(tool_name, error_type)` pair. If a fix is known, apply it immediately without an LLM call.

**10.3 — Token budget display** — live in TUI header: `[Tokens: 24,891 / 200,000 (12%)] [Cache: 91%]`

**10.4 — Embedding-based retrieval** — for documents >50 pages, never pass full content to Claude. Embed the query, retrieve top-k chunks, pass only those.

---

### Phase 11 — Polish, Observability & Hardening

**Duration:** Ongoing

- **OCR support** — `pytesseract` for scanned PDFs
- **Multi-document sessions** — JOIN across DuckDB tables from different uploads
- **`/export`** — session as Markdown report or JSON
- **Structured JSON logging** — `~/.agent/logs/<date>.jsonl` for every event
- **Permission confirmation dialogs** — Textual modal for `exec` + `shell_run` tools
- **Flow versioning** — `agent run <id>@v2`, diffs between flow versions
- **`agent vcs gc`** — prune VCS objects older than 30 days
- **Test suite** — unit tests for all tools, integration tests for ingestion, E2E flow roundtrip

---

## 8. Data Models

```python
# agent/core/models.py

@dataclass
class Session:
    id:          str          # ULID
    created_at:  datetime
    workspace:   Path
    history:     list[Message]
    documents:   list[Document]
    todo_list:   list[TodoItem]
    vcs:         VCSStore
    registry:    ToolRegistry
    memory:      MemoryStore  # DuckDB connection
    flow_id:     str | None
    temporal_wf: str | None   # Temporal workflow run ID
    config:      SessionConfig

@dataclass
class SessionConfig:
    require_approval: bool = False
    deep_mode:        bool = False   # force Opus for planning
    force_opus:       bool = False
    allowed_perms:    set[str] = field(default_factory=lambda: {"read", "exec"})

@dataclass
class PlanStep:
    index:       int
    description: str
    tool_hint:   str | None
    inputs:      dict
    depends_on:  list[int]
    confidence:  float        # < 0.6 → escalate to Opus

@dataclass
class Plan:
    query:    str
    steps:    list[PlanStep]
    strategy: str             # "sequential" | "parallel" | "mixed"
    model:    str

@dataclass
class ToolResult:
    output:   str
    title:    str
    metadata: dict = field(default_factory=dict)
    error:    str | None = None
    duration_ms: int = 0

@dataclass
class Flow:
    id:               str
    name:             str
    version:          int
    system_prompt:    str
    tool_sequence:    list[FlowStep]
    dynamic_tools:    list[DynamicTool]
    parameter_schema: dict
    vcs_sha:          str
```

---

## 9. Directory Structure

```
dokument-agent/
├── agent/
│   ├── __init__.py
│   ├── cli.py                      # typer: chat · run · export · flows
│   ├── core/
│   │   ├── agent.py                # AgentOrchestrator
│   │   ├── planner.py              # Planner + Plan IR
│   │   ├── executor.py             # Executor
│   │   ├── reflection.py           # ReflectionLoop
│   │   ├── llm.py                  # BedrockClient (streaming)
│   │   ├── prompt.py               # System prompt assembly + cache injection
│   │   └── session.py              # Session state + lifecycle
│   ├── tui/
│   │   ├── app.py                  # Textual App root
│   │   ├── panels.py               # StreamPanel · PlanPanel · ExecutionPanel etc
│   │   ├── events.py               # EventKind enum + AgentEvent dataclass
│   │   ├── commands.py             # Slash command handlers
│   │   └── agent.tcss              # Textual CSS styles
│   ├── tools/
│   │   ├── base.py                 # Tool ABC · ToolContext · ToolResult
│   │   ├── registry.py             # ToolRegistry
│   │   ├── document/               # sql_query · grep · document_search · table_extract
│   │   ├── nlp/                    # sentiment · summarize · entity_extract · transcript_*
│   │   ├── compute/                # calculator · date_time · unit_convert
│   │   ├── code/                   # code_exec · code_lint · shell_run
│   │   ├── session/                # todo_* · snapshot_* · flow_crystallize
│   │   └── dynamic/
│   │       ├── builder.py          # build_tool meta-tool
│   │       └── sandbox.py          # sandboxed code execution
│   ├── ingestion/
│   │   ├── pipeline.py             # IngestionPipeline
│   │   ├── parsers/
│   │   │   ├── pdf.py
│   │   │   ├── csv.py
│   │   │   ├── docx.py
│   │   │   └── audio.py            # AWS Transcribe + Whisper fallback
│   │   └── embeddings.py           # Bedrock Titan
│   ├── temporal/
│   │   ├── worker.py
│   │   ├── workflows.py            # AgentTurnWorkflow
│   │   └── activities.py
│   ├── vcs/
│   │   └── store.py                # VCSStore
│   ├── flows/
│   │   ├── crystallize.py
│   │   ├── runner.py               # FlowRunner (deterministic replay)
│   │   └── store.py
│   └── storage/
│       ├── db.py                   # DuckDB connection + schema init
│       └── config.py               # Config loader (TOML → pydantic)
├── tests/
│   ├── tools/                      # One test per tool with fixture data
│   ├── ingestion/                  # Fixture PDFs, CSVs, audio samples
│   ├── reflection/                 # Failure → recovery scenarios
│   └── flows/                      # Crystallize → replay roundtrip
├── fixtures/
│   ├── sample.pdf
│   ├── sample.csv
│   └── sample_transcript.mp3
├── Makefile
└── pyproject.toml
```

---

## 10. Tech Stack Summary

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.12+ | Best fit for NLP, AWS SDK, rapid prototyping |
| LLM — default | Bedrock Claude Sonnet 3.5 v2 | Speed + cost balance |
| LLM — deep reasoning | Bedrock Claude Opus 3 | Complex plans, escalated reflection |
| LLM — cheap tasks | Bedrock Claude Haiku 3 | Calculator, format_json, diagnosis |
| TUI | Textual | Full widget interactivity, keyboard nav, modals |
| TUI rendering | Rich (via Textual) | Markdown, tables, syntax highlighting |
| CLI | Typer | Auto `--help`, subcommands, type-safe |
| Workflow engine | Temporal.io (Python SDK) | Retry, durability, audit trail — local SQLite backend |
| In-process SQL | DuckDB | Embeddable, fast, no server needed |
| Agent memory | DuckDB (same db) | Unified storage for docs + agent state |
| Session metadata | SQLite (stdlib) | Lightweight fallback for simple queries |
| PDF parsing | pdfplumber | Best table extraction |
| DOCX | python-docx | |
| Audio transcription | AWS Transcribe (primary) + Whisper (fallback) | |
| Embeddings | Bedrock Titan Embeddings V2 | |
| HTTP | httpx (async) | web_fetch tool |
| Date/time | pendulum | Better timezone + arithmetic than stdlib |
| Config | tomllib (stdlib 3.11+) + Pydantic | |
| Sandboxing | subprocess + resource limits | No Docker required for local-first |

---

## 11. Suggested Additions

**1. `.dokument/rules.md` — project-level agent rules**  
Like `CLAUDE.md` / `AGENTS.md`, a project file the agent reads and includes in the system prompt. Teams can define conventions: "Our transcripts use speaker format `[EXEC]:`, `[ANALYST]:`".

**2. Skill system**  
`~/.agent/skills/*.md` — user-defined reusable workflows invoked with `@skill_name` in chat. Each skill is a mini-prompt that gets injected, telling the agent how to approach a class of problem.

**3. Multi-document JOIN queries**  
DuckDB can JOIN across tables from different documents already — just expose it in the system prompt. "Compare Q3 and Q4 earnings calls" becomes a single SQL query.

**4. Flow versioning**  
`agent run <id>@v2`. Diffs between flow versions are inspectable with `agent flows diff <id> v1 v2`.

**5. Output formatters**  
After a flow produces results, pipe through: Markdown report, CSV, JSON, or a Rich-rendered HTML summary for sharing outside the terminal.

**6. `agent vcs gc`**  
Prune VCS objects older than N days to keep disk usage bounded.

**7. Model cost dashboard**  
`/cost` command shows a breakdown: total tokens by model tier, cache hit rate, estimated USD spend. Feeds a feedback loop for tuning which models handle which tasks.

---

## 12. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Temporal operational complexity | Medium | SQLite backend for local-first; `temporal server start-dev` is one command |
| Sandboxed code execution exploited | Low (local only) | `resource` limits + no network + 10s timeout + restricted filesystem |
| Bedrock latency degrades UX | Medium | Stream all LLM responses; spinner shows immediately; Haiku for cheap tasks |
| Dynamic tool code quality poor | Medium | Lint + sandbox test before registration; VCS rollback always available |
| Context window overflow on large docs | High | Chunk + embed; retrieve top-k only; compaction at 80% window usage |
| Audio transcription cost/latency | Medium | Local Whisper fallback; show progress in TUI with time estimate |
| VCS object store grows unbounded | Low | `agent vcs gc` command in Phase 11; prune objects >30 days |
| Flow replay breaks on new doc schema | Medium | Pydantic parameter schema validation before replay; clear error message with diff |
| Reflection loop infinite retries | Low | `MAX_RETRIES = 3` hard limit; escalate to user if exhausted |
| Planner IR validation fails | Medium | Strict Pydantic schema; retry Planner with schema error as context |

---

*Version 2.0 — March 2026 | Merged from v1 plan + Coding Agent Platform design doc*
