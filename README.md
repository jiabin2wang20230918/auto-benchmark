# Auto-Benchmark

> Automated code optimization powered by LLM agents. Point it at any project with a benchmark script, and it will iteratively improve your code — hands-free.

[**Chinese / 中文文档**](README_zh.md)

## How It Works

Auto-Benchmark runs a closed-loop optimization cycle:

```
              ┌────────────────────┐
              │  Baseline Benchmark│
              └────────┬───────────┘
                       ▼
              ┌────────────────────┐
              │  Create Worktree   │  (isolated git branch)
              └────────┬───────────┘
                       ▼
              ┌────────────────────┐
              │  OptimizerAgent    │  analyze code → hypothesize → edit
              └────────┬───────────┘
                       ▼
              ┌────────────────────┐
              │  Run Benchmark     │  in worktree
              └────────┬───────────┘
                       ▼
              ┌────────────────────┐
              │  AnalyzerAgent     │  evaluate metrics → keep / revert
              └────────┬───────────┘
                       ▼
                 ┌─────┴─────┐
               keep        revert
                 │           │
            merge to     delete branch
            best branch  & worktree
                 └─────┬─────┘
                       ▼
              check stopping condition
                 → loop or report
```

**Key design decisions:**

- **Dual-agent architecture** — The optimizer proposes changes; a separate analyzer evaluates results. This avoids confirmation bias from a single agent judging its own work.
- **Git worktree isolation** — Each iteration runs in its own worktree, so your working directory is never touched.
- **Hybrid decision engine** — Algorithmic metric checks combined with LLM-based analysis. Objective metrics always take priority.
- **Flexible metric parsing** — JSON (with JSONPath), regex, or key-value output formats.
- **Full audit trail** — Every iteration records its hypothesis, diff, metric deltas, decision, and reasoning.

## Quick Start

### Installation

```bash
git clone <repo-url>
cd auto-benchmark
uv sync
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your API key
```

```bash
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1  # optional, for compatible APIs
```

Works with any OpenAI-compatible API — OpenAI, vLLM, Ollama, Azure OpenAI, etc.

### Create a Project Config

```bash
auto-bench init /path/to/your/project
```

Or create one manually (see [`configs/example.yaml`](configs/example.yaml)):

```yaml
project:
  name: "my-search-algo"
  path: "/path/to/your/project"       # must be a git repo
  base_branch: "main"

benchmark:
  command: "python run_benchmark.py"
  working_dir: "."
  timeout: 300
  setup_command: "pip install -e ."   # optional

metrics:
  source: "json"                      # "json" | "regex" | "stdout_kv"
  definitions:
    - name: "recall_at_10"
      json_key: "$.recall_at_10"
      direction: "maximize"
      threshold: 0.01
      weight: 1.0
    - name: "latency_p99_ms"
      json_key: "$.latency_p99_ms"
      direction: "minimize"
      threshold: 0.05
      weight: 0.5

optimization:
  max_iterations: 20
  max_no_improve: 5
  strategy: "single_change"           # "single_change" | "batch_change"
  exclude_files:
    - "tests/**"
    - "benchmark/**"

llm:
  model: "gpt-4o"
  temperature: 0.7
  max_tokens: 16000
  # Optional: use different models for each agent
  # optimizer:
  #   model: "claude-sonnet-4-20250514"
  #   api_base: "https://api.anthropic.com/v1"
  #   api_key: "sk-ant-..."
  # analyzer:
  #   model: "gpt-4o-mini"
```

### Run

```bash
# Run baseline benchmark only
auto-bench baseline configs/your-project.yaml

# Start the optimization loop
auto-bench run configs/your-project.yaml

# With options
auto-bench run configs/your-project.yaml --max-iter 10
auto-bench run configs/your-project.yaml --dry-run
auto-bench run configs/your-project.yaml -v

# View report
auto-bench report configs/your-project.yaml

# Clean up worktrees and temporary branches
auto-bench cleanup configs/your-project.yaml
```

## Architecture

### Dual-Agent System

| Agent | Role | Tools | Temperature |
|-------|------|-------|-------------|
| **OptimizerAgent** | Reads code, forms hypothesis, applies changes | `code_read`, `list_files`, `code_edit`, `code_write`, `code_search`, `bash_exec`, `git_diff`, `git_log` | 0.7 (configurable) |
| **AnalyzerAgent** | Evaluates benchmark deltas, decides keep/revert | None (reasoning only) | 0.3 (deterministic) |

Each agent can be configured with a different LLM, API endpoint, and parameters via `llm.optimizer` / `llm.analyzer` overrides. Unset fields inherit from the global `llm` config.

### Decision Logic

The engine combines algorithmic checks with LLM judgment:

| Algo Check | LLM Recommendation | Final Decision | Rationale |
|------------|---------------------|----------------|-----------|
| Improved | keep | **keep** | Agreement |
| Not improved | revert | **revert** | Agreement |
| Improved | revert | **keep** | Trust objective metrics |
| Not improved | keep | **revert** | Trust objective metrics |

### Git Branch Strategy

```
main                              ← never modified
 └── auto-bench/best              ← current best (updated on each successful iteration)
      ├── auto-bench/iter-001     ← kept → merged into best
      ├── auto-bench/iter-002     ← reverted → deleted
      └── auto-bench/iter-003     ← kept → merged into best
```

### Metric Parsing

Three modes for extracting metrics from benchmark output:

**JSON** — parse stdout or a file with JSONPath
```yaml
metrics:
  source: "json"
  definitions:
    - name: "recall"
      json_key: "$.results.recall"
```

**Regex** — extract values with named capture groups
```yaml
metrics:
  source: "regex"
  definitions:
    - name: "throughput"
      regex: "Throughput:\\s+(?P<value>[\\d.]+)"
```

**Key-Value** — parse `key: value` or `key=value` lines
```yaml
metrics:
  source: "stdout_kv"
  definitions:
    - name: "accuracy"
```

## Project Structure

```
auto-benchmark/
├── pyproject.toml
├── .env.example
├── configs/
│   └── example.yaml
└── src/auto_bench/
    ├── cli.py                         # CLI commands (Click)
    ├── config/
    │   ├── schema.py                  # Pydantic config models
    │   └── loader.py                  # YAML loading & validation
    ├── core/
    │   ├── engine.py                  # Main optimization loop
    │   ├── state.py                   # Iteration state machine
    │   └── decision.py                # Scoring & decision logic
    ├── agent/
    │   ├── optimizer_agent.py         # Code optimization agent
    │   ├── analyzer_agent.py          # Result analysis agent
    │   ├── model_provider.py          # OpenAI-compatible API adapter
    │   ├── context.py                 # Shared agent context
    │   ├── prompts/                   # System prompts (Markdown)
    │   └── tools/                     # Agent tools (read/edit/search/bash/git)
    ├── bench/
    │   ├── runner.py                  # Async benchmark execution
    │   └── parser.py                  # Result parser (JSON/regex/KV)
    ├── git/
    │   ├── worktree.py                # Git worktree manager
    │   └── diff.py                    # Diff utilities
    ├── history/
    │   ├── models.py                  # IterationRecord, OptimizationReport
    │   └── store.py                   # JSON file-based persistence
    └── report/
        └── reporter.py               # Rich terminal reports
```

## Safety

- **Path sandboxing** — Agent tools can only access files within the worktree directory.
- **Dangerous command blocking** — `bash_exec` rejects commands like `rm -rf /`, `mkfs`, `dd if=`.
- **Output truncation** — File reads capped at 100KB, command output at 50KB.
- **Graceful interruption** — Ctrl+C finishes the current iteration, cleans up, and generates a report.
- **File exclusion** — Configurable `exclude_files` patterns protect tests, docs, and other critical files.

## Data Storage

Iteration data is stored in `.auto-bench-data/` under the target project:

```
.auto-bench-data/
├── iterations/
│   ├── iter-001.json
│   ├── iter-002.json
│   └── ...
└── report.json
```

Each record includes: iteration ID, status, hypothesis, changes summary, diff, files modified, baseline/result metrics, improvement percentages, decision, LLM reasoning, and timestamp.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Package Manager | uv + hatchling |
| Agent Framework | openai-agents >= 0.8.0 |
| LLM Backend | Any OpenAI-compatible API |
| Config | YAML (PyYAML) + Pydantic v2 |
| CLI | Click |
| Terminal UI | Rich |
| Persistence | JSON files |
| Git | asyncio subprocess |

## License

MIT
