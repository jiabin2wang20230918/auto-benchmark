# Auto-Benchmark

LLM 驱动的自动化基准测试调优系统。通过 AI Agent 迭代分析代码、提出优化方案、运行 benchmark 并自动决策保留或回滚，实现全自动的代码性能优化。

## 工作原理

```
┌─────────────────────────────────────────────────────┐
│              OptimizationEngine 主循环                │
│                                                     │
│  1. 运行基线 Benchmark                                │
│           │                                         │
│           ▼                                         │
│  2. 创建 Git Worktree (隔离实验环境)                    │
│           │                                         │
│           ▼                                         │
│  3. OptimizerAgent 分析代码 → 提出假设 → 修改代码       │
│           │                                         │
│           ▼                                         │
│  4. 在 Worktree 中运行 Benchmark                      │
│           │                                         │
│           ▼                                         │
│  5. AnalyzerAgent 对比结果 → 决策 keep / revert        │
│           │                                         │
│       ┌───┴───┐                                     │
│     keep    revert                                  │
│       │       │                                     │
│    合并到     删除分支                                  │
│    best分支   和worktree                              │
│       └───┬───┘                                     │
│           │                                         │
│  6. 检查停止条件 → 继续 / 生成报告                       │
└─────────────────────────────────────────────────────┘
```

核心特性：
- **双 Agent 协作**：OptimizerAgent 负责代码修改，AnalyzerAgent 负责结果评估，避免"自己评价自己"的确认偏误
- **Git Worktree 隔离**：每次迭代在独立 worktree 中进行，不影响用户主工作区
- **混合决策机制**：算法指标检测 + LLM 分析判断相结合
- **灵活的指标解析**：支持 JSON / 正则 / Key-Value 三种 benchmark 输出格式
- **完整审计追踪**：每次迭代的假设、代码变更、指标变化、决策理由均有记录

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| 语言 | Python 3.11+ |
| 包管理 | uv + hatchling |
| Agent 框架 | openai-agents >= 0.8.0 |
| LLM 后端 | 任意 OpenAI 兼容 API (OpenAI / vLLM / Ollama / Azure 等) |
| 配置 | YAML (PyYAML) |
| 数据模型 | Pydantic v2 |
| CLI | Click |
| 终端 UI | Rich (表格 / 进度条) |
| 结果存储 | JSON 文件 |
| Git 操作 | asyncio subprocess |

## 快速开始

### 1. 安装

```bash
# 克隆项目
git clone <repo-url>
cd auto-benchmark

# 安装依赖 (推荐使用 uv)
uv sync
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，设置你的 API 密钥：

```bash
# OpenAI API 配置
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1    # 可选，支持自定义兼容 API

# 可选：覆盖默认模型
# AUTO_BENCH_MODEL=gpt-4o
```

支持任意 OpenAI 兼容的 API 服务（vLLM、Ollama、Azure OpenAI、各类代理等），只需修改 `OPENAI_BASE_URL` 即可。

### 3. 为目标项目创建配置

```bash
# 交互式生成配置文件
auto-bench init /path/to/your/project
```

或手动创建，参考 `configs/example.yaml`：

```yaml
project:
  name: "my-search-algo"
  path: "/path/to/your/project"       # 目标项目路径（必须是 git 仓库）
  base_branch: "main"

benchmark:
  command: "python run_benchmark.py"  # benchmark 执行命令
  working_dir: "."                    # 相对于项目根目录
  timeout: 300                        # 超时秒数
  setup_command: "pip install -e ."   # benchmark 前的准备命令（可选）

metrics:
  source: "json"                      # "json" | "regex" | "stdout_kv"
  json_file: null                     # null = 从 stdout 解析 JSON
  definitions:
    - name: "recall_at_10"
      json_key: "$.recall_at_10"      # JSONPath 表达式
      direction: "maximize"           # "maximize" | "minimize"
      threshold: 0.01                 # 最小改善阈值（相对值）
      weight: 1.0                     # 多指标加权权重
    - name: "latency_p99_ms"
      json_key: "$.latency_p99_ms"
      direction: "minimize"
      threshold: 0.05
      weight: 0.5

optimization:
  max_iterations: 20                  # 最大迭代次数
  max_no_improve: 5                   # 连续无改善次数后停止
  strategy: "single_change"           # "single_change" | "batch_change"
  focus_files: []                     # 限定修改范围（glob 模式，空 = 全部）
  exclude_files:                      # 排除文件（glob 模式）
    - "tests/**"
    - "benchmark/**"

llm:
  model: "gpt-4o"
  api_base: null                      # 自定义 API base URL（可选）
  temperature: 0.7
  max_tokens: 16000
  # 可选：为不同 Agent 配置不同的 LLM（未设置的字段自动继承上面的全局值）
  # optimizer:
  #   model: "claude-sonnet-4-20250514"
  #   api_base: "https://api.anthropic.com/v1"
  #   api_key: "sk-ant-..."
  #   temperature: 0.8
  # analyzer:
  #   model: "gpt-4o-mini"

worktree:
  base_dir: ".auto-bench-worktrees"   # worktree 存放目录
  cleanup_on_finish: true             # 优化结束后清理 worktree
```

### 4. 运行

```bash
# 运行基线 benchmark，查看当前指标
auto-bench baseline configs/your-project.yaml

# 开始自动优化循环
auto-bench run configs/your-project.yaml

# 限制最大迭代次数
auto-bench run configs/your-project.yaml --max-iter 10

# 试运行模式（只分析不修改）
auto-bench run configs/your-project.yaml --dry-run

# 详细输出模式
auto-bench run configs/your-project.yaml -v

# 查看优化报告
auto-bench report configs/your-project.yaml

# 清理所有 worktree 和临时分支
auto-bench cleanup configs/your-project.yaml
```

## 项目结构

```
auto-benchmark/
├── pyproject.toml                     # 项目元数据 & 依赖
├── .env.example                       # 环境变量模板
├── configs/
│   └── example.yaml                   # 示例配置
│
└── src/auto_bench/
    ├── __init__.py
    ├── __main__.py                    # python -m auto_bench 入口
    ├── cli.py                         # Click CLI 命令定义
    │
    ├── config/                        # 配置管理
    │   ├── schema.py                  # Pydantic 配置模型
    │   └── loader.py                  # YAML 加载 & 校验
    │
    ├── core/                          # 核心引擎
    │   ├── engine.py                  # OptimizationEngine 主循环
    │   ├── state.py                   # IterationState 迭代状态机
    │   └── decision.py                # 评分与决策逻辑
    │
    ├── agent/                         # LLM Agent 层
    │   ├── optimizer_agent.py         # OptimizerAgent — 代码优化
    │   ├── analyzer_agent.py          # AnalyzerAgent — 结果分析
    │   ├── context.py                 # AgentContext 共享上下文
    │   ├── model_provider.py          # OpenAI 兼容 API 适配
    │   ├── prompts/
    │   │   ├── optimizer.md           # 优化器系统提示词
    │   │   └── analyzer.md            # 分析器系统提示词
    │   └── tools/                     # Agent 可用工具
    │       ├── code_read.py           # 读取文件 / 列出文件
    │       ├── code_edit.py           # 编辑文件 / 写入文件
    │       ├── code_search.py         # 正则搜索代码
    │       ├── bash_exec.py           # 执行 shell 命令（含安全过滤）
    │       ├── bench_run.py           # 触发 benchmark 运行
    │       └── git_ops.py             # git diff / log / status
    │
    ├── bench/                         # Benchmark 执行 & 解析
    │   ├── runner.py                  # BenchmarkRunner 异步执行
    │   └── parser.py                  # ResultParser (JSON/regex/KV)
    │
    ├── git/                           # Git Worktree 管理
    │   ├── worktree.py                # WorktreeManager
    │   └── diff.py                    # Diff 工具函数
    │
    ├── history/                       # 迭代历史持久化
    │   ├── models.py                  # 数据模型 (IterationRecord, OptimizationReport)
    │   └── store.py                   # IterationStore (JSON 文件存储)
    │
    └── report/                        # 报告生成
        └── reporter.py               # Rich 终端报告展示
```

## 架构详解

### 双 Agent 协作

系统采用两个专职 Agent 协作完成优化闭环：

**OptimizerAgent（代码优化专家）**
- 读取并理解项目代码
- 基于历史迭代记录和当前指标，提出优化假设
- 通过工具直接修改代码（最多 30 轮工具调用）
- 可用工具：`code_read`、`list_files`、`code_edit`、`code_write`、`code_search`、`bash_exec`、`git_diff`、`git_log`

**AnalyzerAgent（结果分析专家）**
- 对比基线与当前 benchmark 结果
- 评估每个指标的变化是否超过噪声阈值
- 输出结构化的 keep/revert 决策和推理过程
- 低温度设置 (0.3)，确保判断稳定性

两个 Agent 支持配置不同的 LLM（模型、API 端点、密钥、温度等），通过 `llm.optimizer` 和 `llm.analyzer` 设置覆盖值，未设置的字段自动继承全局 `llm` 配置。

### 混合决策机制

引擎结合算法判断与 LLM 分析做出最终决策：

| 算法判断 | LLM 建议 | 最终决策 | 理由 |
|---------|---------|---------|------|
| 改善 | keep | **keep** | 双方一致 |
| 未改善 | revert | **revert** | 双方一致 |
| 改善 | revert | **keep** | 信任客观指标 |
| 未改善 | keep | **revert** | 信任客观指标 |

### Git 分支策略

```
main (用户主分支，不修改)
│
├── auto-bench/best             ← 当前最佳结果分支（随迭代推进）
│   ├── auto-bench/iter-001     ← 迭代 1（成功 → 合并到 best）
│   ├── auto-bench/iter-002     ← 迭代 2（失败 → 删除）
│   ├── auto-bench/iter-003     ← 迭代 3（成功 → 合并到 best）
│   └── ...
```

- 每次迭代从 `auto-bench/best` 创建新分支和独立 worktree
- 成功的迭代合并回 `auto-bench/best`
- 失败的迭代删除分支和 worktree
- 最终用户可将 `auto-bench/best` 合并回 `main`

### Benchmark 结果解析

支持三种格式从 benchmark 输出中提取指标：

**JSON 模式** — benchmark 输出 JSON 到 stdout 或文件
```yaml
metrics:
  source: "json"
  json_file: null                    # null = 从 stdout 解析
  definitions:
    - name: "recall"
      json_key: "$.results.recall"   # JSONPath 表达式
```

**正则模式** — 用正则从 stdout 提取数值
```yaml
metrics:
  source: "regex"
  definitions:
    - name: "throughput"
      regex: "Throughput:\\s+(?P<value>[\\d.]+)"
```

**Key-Value 模式** — 解析 `key: value` 或 `key=value` 格式
```yaml
metrics:
  source: "stdout_kv"
  definitions:
    - name: "accuracy"
```

### 安全措施

- **路径限制**：Agent 工具只能操作 worktree 目录内的文件
- **危险命令过滤**：`bash_exec` 工具会拦截 `rm -rf /`、`mkfs`、`dd if=` 等危险命令
- **输出截断**：文件读取限制 100KB，命令输出限制 50KB，防止上下文溢出
- **优雅中断**：支持 Ctrl+C 信号处理，清理当前 worktree 后安全退出
- **文件排除**：通过 `exclude_files` 配置保护测试文件、文档等不被修改

## 数据存储

优化过程的数据存储在目标项目的 `.auto-bench-data/` 目录下：

```
.auto-bench-data/
├── iterations/
│   ├── iter-001.json    # 每次迭代的完整记录
│   ├── iter-002.json
│   └── ...
└── report.json          # 最终优化报告
```

每条迭代记录包含：迭代编号、状态、优化假设、代码变更摘要、diff、修改的文件列表、基线指标、结果指标、改善幅度、决策、LLM 推理过程和时间戳。

## License

MIT
