# Auto-Benchmark: LLM 驱动的自动化基准测试调优系统

## 1. 项目概述

Auto-Benchmark 是一个 LLM 驱动的自动化迭代优化系统。它能够：
1. 分析目标项目的代码（任意带有 benchmark 脚本的项目）
2. 利用 LLM Agent 提出并应用代码修改方案
3. 自动运行 benchmark 并解析结果
4. 效果提升 → 提交保存修改
5. 效果变差 → 回滚并尝试其他修改方案
6. 循环迭代直至达到目标指标或达到最大迭代次数

使用 `git worktree` 进行实验分支的隔离管理。

---

## 2. 技术栈

| 组件 | 技术选型 |
|------|----------|
| 语言 | Python 3.11+ |
| 包管理 | uv + hatchling |
| Agent 框架 | openai-agents >= 0.8.0 |
| 配置 | YAML (PyYAML) |
| 数据模型 | Pydantic v2 |
| CLI | click |
| 结果存储 | JSON + SQLite (轻量) |
| 可视化 | rich (终端表格/进度条) |
| Git 操作 | gitpython + subprocess |

---

## 3. 项目目录结构

```
auto-benchmark/
├── pyproject.toml                    # 项目元数据 & 依赖
├── .env.example                      # 环境变量模板
├── README.md
│
├── configs/                          # 示例配置文件
│   └── example.yaml                  # 示例项目配置
│
├── src/
│   └── auto_bench/
│       ├── __init__.py
│       ├── __main__.py               # CLI 入口: `python -m auto_bench`
│       ├── cli.py                    # Click CLI 定义
│       │
│       ├── config/                   # 配置管理
│       │   ├── __init__.py
│       │   ├── schema.py             # Pydantic 配置模型
│       │   └── loader.py             # YAML 加载 & 校验
│       │
│       ├── core/                     # 核心引擎
│       │   ├── __init__.py
│       │   ├── engine.py             # 主循环引擎 (OptimizationEngine)
│       │   ├── state.py              # 迭代状态机 (IterationState)
│       │   └── decision.py           # 决策逻辑 (keep/revert/stop)
│       │
│       ├── git/                      # Git Worktree 管理
│       │   ├── __init__.py
│       │   ├── worktree.py           # WorktreeManager
│       │   └── diff.py               # Diff 工具
│       │
│       ├── bench/                    # Benchmark 执行 & 解析
│       │   ├── __init__.py
│       │   ├── runner.py             # BenchmarkRunner
│       │   └── parser.py             # ResultParser (JSON/regex/stdout)
│       │
│       ├── agent/                    # LLM Agent 层
│       │   ├── __init__.py
│       │   ├── optimizer_agent.py    # 主优化 Agent (OptimizerAgent)
│       │   ├── analyzer_agent.py     # 结果分析 Agent (AnalyzerAgent)
│       │   ├── tools/                # Agent 可用工具
│       │   │   ├── __init__.py
│       │   │   ├── code_read.py      # 读取代码文件
│       │   │   ├── code_edit.py      # 编辑代码文件
│       │   │   ├── code_search.py    # 搜索代码 (grep/glob)
│       │   │   ├── bash_exec.py      # 执行 shell 命令
│       │   │   ├── bench_run.py      # 触发 benchmark 运行
│       │   │   └── git_ops.py        # git 操作 (diff, log, status)
│       │   └── prompts/              # Agent 系统提示词
│       │       ├── optimizer.md       # 优化器 Agent 提示词
│       │       └── analyzer.md        # 分析器 Agent 提示词
│       │
│       ├── history/                  # 迭代历史 & 持久化
│       │   ├── __init__.py
│       │   ├── store.py              # IterationStore (SQLite)
│       │   └── models.py             # 历史数据模型
│       │
│       └── report/                   # 报告生成
│           ├── __init__.py
│           └── reporter.py           # 结果汇总 & 终端报告
```

---

## 4. 配置文件 Schema (YAML)

```yaml
# configs/example.yaml
project:
  name: "my-search-algo"
  path: "/path/to/target/project"       # 目标项目路径 (必须是 git 仓库)
  base_branch: "main"                    # 基准分支

benchmark:
  command: "python run_benchmark.py"     # benchmark 执行命令
  working_dir: "."                       # 相对于项目根目录
  timeout: 300                           # 超时秒数
  setup_command: "pip install -e ."      # benchmark 前的准备命令（可选）

metrics:
  # 从 benchmark 输出中提取指标的规则
  source: "json"                         # "json" | "regex" | "stdout_kv"
  # JSON 模式: benchmark 输出 JSON 到 stdout 或指定文件
  json_path: null                        # null = stdout, 或文件路径
  # 需要跟踪的指标定义
  definitions:
    - name: "recall_at_10"
      json_key: "$.recall@10"            # JSON Path 表达式
      direction: "maximize"              # "maximize" | "minimize"
      threshold: 0.01                    # 最小改善阈值 (相对值)
      weight: 1.0                        # 多指标加权
    - name: "latency_p99"
      json_key: "$.latency.p99"
      direction: "minimize"
      threshold: 0.05
      weight: 0.5

optimization:
  max_iterations: 20                     # 最大迭代次数
  max_no_improve: 5                      # 连续无改善次数后停止
  strategy: "single_change"              # "single_change" | "batch_change"
  focus_files: []                        # 限定修改范围（可选, glob 模式）
  exclude_files:                         # 排除文件（glob 模式）
    - "tests/**"
    - "*.md"
    - "benchmark/**"

llm:
  model: "gpt-4o"                        # OpenAI 模型名
  api_base: null                         # 自定义 API base URL（可选）
  temperature: 0.7
  max_tokens: 16000

worktree:
  base_dir: ".auto-bench-worktrees"      # worktree 存放目录（相对于项目路径）
  cleanup_on_finish: true                # 优化结束后清理 worktree
```

---

## 5. 核心数据模型 (Pydantic)

```python
# src/auto_bench/config/schema.py

class ProjectConfig(BaseModel):
    name: str
    path: Path
    base_branch: str = "main"

class BenchmarkConfig(BaseModel):
    command: str
    working_dir: str = "."
    timeout: int = 300
    setup_command: str | None = None

class MetricDefinition(BaseModel):
    name: str
    json_key: str | None = None          # for JSON source
    regex: str | None = None             # for regex source
    direction: Literal["maximize", "minimize"]
    threshold: float = 0.01
    weight: float = 1.0

class MetricsConfig(BaseModel):
    source: Literal["json", "regex", "stdout_kv"]
    json_path: str | None = None
    definitions: list[MetricDefinition]

class OptimizationConfig(BaseModel):
    max_iterations: int = 20
    max_no_improve: int = 5
    strategy: Literal["single_change", "batch_change"] = "single_change"
    focus_files: list[str] = []
    exclude_files: list[str] = []

class LLMConfig(BaseModel):
    model: str = "gpt-4o"
    api_base: str | None = None
    temperature: float = 0.7
    max_tokens: int = 16000

class WorktreeConfig(BaseModel):
    base_dir: str = ".auto-bench-worktrees"
    cleanup_on_finish: bool = True

class AutoBenchConfig(BaseModel):
    """顶层配置"""
    project: ProjectConfig
    benchmark: BenchmarkConfig
    metrics: MetricsConfig
    optimization: OptimizationConfig
    llm: LLMConfig = LLMConfig()
    worktree: WorktreeConfig = WorktreeConfig()
```

```python
# src/auto_bench/history/models.py

class MetricResult(BaseModel):
    name: str
    value: float
    direction: Literal["maximize", "minimize"]

class BenchmarkResult(BaseModel):
    metrics: list[MetricResult]
    raw_output: str
    exit_code: int
    duration_seconds: float

class IterationRecord(BaseModel):
    iteration_id: int
    branch_name: str
    worktree_path: str
    status: Literal["pending", "running", "success", "failed", "reverted"]
    hypothesis: str                      # LLM 的修改假设
    changes_summary: str                 # 修改摘要
    diff: str                            # git diff 内容
    baseline_metrics: dict[str, float]   # 基线指标
    result_metrics: dict[str, float] | None  # 本次结果指标
    improvement: dict[str, float] | None # 改善幅度
    decision: Literal["keep", "revert", "stop"] | None
    llm_reasoning: str                   # LLM 的分析推理
    timestamp: datetime
    error_message: str | None = None
```

---

## 6. Git Worktree 管理策略

### 6.1 Worktree 生命周期

```
目标项目 (main branch)
│
├── .auto-bench-worktrees/
│   ├── iter-001/                # 第 1 次迭代的 worktree
│   ├── iter-002/                # 第 2 次迭代的 worktree
│   └── ...
│
└── .auto-bench-data/            # 迭代数据存储
    ├── history.db               # SQLite 历史记录
    └── reports/                 # 生成的报告
```

### 6.2 WorktreeManager 接口

```python
# src/auto_bench/git/worktree.py

class WorktreeManager:
    def __init__(self, project_path: Path, config: WorktreeConfig):
        ...

    async def setup(self) -> None:
        """确保目标项目是 git 仓库，获取 baseline commit"""

    async def create_iteration_worktree(self, iteration_id: int) -> WorktreeInfo:
        """
        创建新的 worktree 用于本次迭代：
        1. 从当前最佳 commit 创建新分支: auto-bench/iter-{id}
        2. git worktree add .auto-bench-worktrees/iter-{id} auto-bench/iter-{id}
        3. 返回 WorktreeInfo(path, branch_name, base_commit)
        """

    async def commit_changes(self, worktree_path: Path, message: str) -> str:
        """在 worktree 中提交修改，返回 commit hash"""

    async def accept_iteration(self, iteration_id: int) -> None:
        """
        接受本次迭代的修改：
        1. 将 iter 分支 merge 到 best 分支
        2. 更新 best commit 指针
        """

    async def revert_iteration(self, iteration_id: int) -> None:
        """
        回滚本次迭代：
        1. 移除 worktree
        2. 删除对应分支
        """

    async def get_diff(self, worktree_path: Path) -> str:
        """获取 worktree 相对于 base 的 diff"""

    async def cleanup(self) -> None:
        """清理所有 worktree 和临时分支"""

class WorktreeInfo(BaseModel):
    path: Path
    branch_name: str
    base_commit: str
```

### 6.3 分支策略

```
main (用户的主分支，不动)
│
├── auto-bench/best          ← 当前最佳结果分支（随迭代前进）
│   ├── auto-bench/iter-001  ← 第 1 次迭代（成功 → merge 到 best）
│   ├── auto-bench/iter-002  ← 第 2 次迭代（失败 → 删除）
│   ├── auto-bench/iter-003  ← 第 3 次迭代（成功 → merge 到 best）
│   └── ...
```

- 每次迭代从 `auto-bench/best` 创建新分支
- 成功的迭代 merge 回 `auto-bench/best`
- 失败的迭代直接删除分支和 worktree
- 最终用户可以选择将 `auto-bench/best` merge 回 `main`

---

## 7. Agent 架构设计

### 7.1 双 Agent 协作模型

```
┌─────────────────────────────────────────────────────────────┐
│                    OptimizationEngine                       │
│                     (主循环控制)                              │
│                                                             │
│  ┌──────────────────┐       ┌──────────────────┐           │
│  │  OptimizerAgent   │       │  AnalyzerAgent   │           │
│  │  (代码优化专家)    │       │  (结果分析专家)    │           │
│  │                    │       │                    │          │
│  │  Tools:            │       │  Tools:            │          │
│  │  - code_read       │       │  - bench_run       │          │
│  │  - code_edit       │       │  - code_read       │          │
│  │  - code_search     │       │  - git_ops (diff)  │          │
│  │  - bash_exec       │       │                    │          │
│  │  - git_ops         │       │  职责:             │           │
│  │                    │       │  - 分析 benchmark   │          │
│  │  职责:             │       │    结果             │           │
│  │  - 阅读理解代码     │       │  - 与基线对比       │          │
│  │  - 提出修改假设     │       │  - 判断是否改善     │          │
│  │  - 实施代码修改     │       │  - 给出 keep/revert │          │
│  │                    │       │    决策建议          │          │
│  └──────────────────┘       └──────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 OptimizerAgent 定义

```python
# src/auto_bench/agent/optimizer_agent.py
from agents import Agent, Runner, ModelSettings
from agents.tool_context import ToolContext

class OptimizerAgent:
    def __init__(self, config: LLMConfig):
        self.agent = Agent(
            name="OptimizerAgent",
            instructions=self._load_system_prompt(),
            tools=[
                code_read_tool,
                code_edit_tool,
                code_search_tool,
                bash_exec_tool,
                git_ops_tool,
            ],
            model=config.model,
            model_settings=ModelSettings(
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            ),
        )

    async def propose_and_apply(
        self,
        worktree_path: Path,
        context: OptimizationContext,
    ) -> ProposalResult:
        """
        向 Agent 提供:
        - 项目代码结构
        - 历史迭代记录 (哪些修改有效/无效)
        - 当前基线指标
        - 优化目标
        让 Agent 分析代码并直接通过工具进行修改
        """
        prompt = self._build_prompt(worktree_path, context)
        result = await Runner.run(self.agent, input=prompt)
        return self._parse_result(result)
```

### 7.3 AnalyzerAgent 定义

```python
# src/auto_bench/agent/analyzer_agent.py

class AnalyzerAgent:
    def __init__(self, config: LLMConfig):
        self.agent = Agent(
            name="AnalyzerAgent",
            instructions=self._load_system_prompt(),
            tools=[bench_run_tool, code_read_tool, git_ops_tool],
            model=config.model,
            model_settings=ModelSettings(
                temperature=0.3,  # 分析需要更确定性
            ),
        )

    async def analyze_results(
        self,
        baseline: BenchmarkResult,
        current: BenchmarkResult,
        diff: str,
        context: OptimizationContext,
    ) -> AnalysisResult:
        """
        分析 benchmark 结果，返回:
        - decision: "keep" | "revert"
        - reasoning: 分析推理过程
        - suggestions: 后续优化建议
        """
```

### 7.4 Agent 工具定义

```python
# src/auto_bench/agent/tools/code_read.py
from agents import function_tool

@function_tool
async def code_read(ctx, file_path: str) -> str:
    """读取指定路径的代码文件内容。

    Args:
        file_path: 相对于 worktree 根目录的文件路径
    """
    # 安全检查：确保路径在 worktree 范围内
    full_path = ctx.context.worktree_path / file_path
    return full_path.read_text()

# src/auto_bench/agent/tools/code_edit.py
@function_tool
async def code_edit(
    ctx,
    file_path: str,
    old_content: str,
    new_content: str,
) -> str:
    """精确替换文件中的指定内容。

    Args:
        file_path: 相对于 worktree 根目录的文件路径
        old_content: 要被替换的原始内容（必须精确匹配）
        new_content: 替换后的新内容
    """

# src/auto_bench/agent/tools/code_search.py
@function_tool
async def code_search(ctx, pattern: str, glob: str = "**/*") -> str:
    """在项目中搜索匹配的代码内容。

    Args:
        pattern: 搜索的正则表达式
        glob: 文件过滤模式
    """

# src/auto_bench/agent/tools/bash_exec.py
@function_tool
async def bash_exec(ctx, command: str, timeout: int = 60) -> str:
    """在 worktree 目录下执行 shell 命令。

    Args:
        command: 要执行的命令
        timeout: 超时秒数
    """

# src/auto_bench/agent/tools/bench_run.py
@function_tool
async def bench_run(ctx) -> str:
    """运行 benchmark 命令并返回原始输出。"""

# src/auto_bench/agent/tools/git_ops.py
@function_tool
async def git_diff(ctx) -> str:
    """查看当前 worktree 中的所有修改 (git diff)。"""

@function_tool
async def git_log(ctx, n: int = 10) -> str:
    """查看最近的 git 提交记录。"""

@function_tool
async def git_status(ctx) -> str:
    """查看当前 worktree 的 git 状态。"""
```

---

## 8. 主循环状态机

```
                    ┌──────────┐
                    │  INIT    │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
              ┌─────│ BASELINE │  运行基线 benchmark
              │     └────┬─────┘
              │          │
              │     ┌────▼──────────┐
              │     │ CREATE_WORKTREE│  git worktree add
              │     └────┬──────────┘
              │          │
              │     ┌────▼─────┐
              │     │ OPTIMIZE │  LLM Agent 分析代码并修改
              │     └────┬─────┘
              │          │
              │     ┌────▼─────┐
              │     │ BENCHMARK│  在 worktree 中运行 benchmark
              │     └────┬─────┘
              │          │
              │     ┌────▼─────┐
              │     │ ANALYZE  │  比较结果，做出决策
              │     └────┬─────┘
              │          │
              │     ┌────▼─────┐
              │  ┌──│ DECIDE   │
              │  │  └──┬───┬───┘
              │  │     │   │
              │  │  keep  revert
              │  │     │   │
              │  │  ┌──▼┐ ┌▼───┐
              │  │  │SAVE│ │UNDO│
              │  │  └──┬┘ └┬───┘
              │  │     │   │
              │  │     └───┘
              │  │        │
              │  │   ┌────▼──────┐
              │  │   │CHECK_STOP │  检查停止条件
              │  │   └──┬────┬───┘
              │  │      │    │
              │  │   continue stop
              │  │      │    │
              │  │      │  ┌─▼────┐
              │  └──────┘  │REPORT│  生成最终报告
              │            └──┬───┘
              │               │
              │          ┌────▼─┐
              └──────────│ DONE │
                         └──────┘
```

### 8.1 Engine 实现

```python
# src/auto_bench/core/engine.py

class OptimizationEngine:
    def __init__(self, config: AutoBenchConfig):
        self.config = config
        self.worktree_mgr = WorktreeManager(config.project.path, config.worktree)
        self.bench_runner = BenchmarkRunner(config.benchmark)
        self.result_parser = ResultParser(config.metrics)
        self.optimizer = OptimizerAgent(config.llm)
        self.analyzer = AnalyzerAgent(config.llm)
        self.store = IterationStore(config.project.path / ".auto-bench-data")
        self.state = IterationState()

    async def run(self) -> OptimizationReport:
        """主执行入口"""
        # 1. 初始化
        await self.worktree_mgr.setup()

        # 2. 运行基线 benchmark
        baseline = await self._run_baseline()

        # 3. 迭代循环
        iteration = 0
        no_improve_count = 0

        while iteration < self.config.optimization.max_iterations:
            iteration += 1
            self.state.set(IterationPhase.CREATE_WORKTREE)

            # 3a. 创建本次迭代的 worktree
            wt = await self.worktree_mgr.create_iteration_worktree(iteration)

            # 3b. 让 Optimizer Agent 修改代码
            self.state.set(IterationPhase.OPTIMIZE)
            context = self._build_context(baseline, iteration)
            proposal = await self.optimizer.propose_and_apply(wt.path, context)

            # 3c. 在 worktree 中运行 benchmark
            self.state.set(IterationPhase.BENCHMARK)
            result = await self.bench_runner.run(wt.path)
            metrics = self.result_parser.parse(result)

            # 3d. 分析结果
            self.state.set(IterationPhase.ANALYZE)
            diff = await self.worktree_mgr.get_diff(wt.path)
            analysis = await self.analyzer.analyze_results(
                baseline, metrics, diff, context
            )

            # 3e. 做出决策
            self.state.set(IterationPhase.DECIDE)
            decision = self._make_decision(baseline, metrics, analysis)

            # 3f. 执行决策
            if decision == "keep":
                await self.worktree_mgr.commit_changes(wt.path, proposal.summary)
                await self.worktree_mgr.accept_iteration(iteration)
                baseline = metrics  # 更新基线
                no_improve_count = 0
            else:
                await self.worktree_mgr.revert_iteration(iteration)
                no_improve_count += 1

            # 3g. 记录历史
            await self.store.save_iteration(...)

            # 3h. 检查停止条件
            if no_improve_count >= self.config.optimization.max_no_improve:
                break

        # 4. 生成报告
        report = await self._generate_report()

        # 5. 清理
        if self.config.worktree.cleanup_on_finish:
            await self.worktree_mgr.cleanup()

        return report
```

---

## 9. Benchmark 执行 & 结果解析

```python
# src/auto_bench/bench/runner.py

class BenchmarkRunner:
    def __init__(self, config: BenchmarkConfig):
        self.config = config

    async def run(self, worktree_path: Path) -> RawBenchmarkOutput:
        """
        在 worktree 目录下执行 benchmark 命令：
        1. 如有 setup_command，先执行
        2. 执行 benchmark command
        3. 捕获 stdout/stderr/exit_code
        4. 返回原始输出
        """
        cwd = worktree_path / self.config.working_dir

        if self.config.setup_command:
            await self._exec(self.config.setup_command, cwd)

        result = await self._exec(
            self.config.command, cwd, timeout=self.config.timeout
        )
        return RawBenchmarkOutput(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            duration=result.duration,
        )

# src/auto_bench/bench/parser.py

class ResultParser:
    def __init__(self, config: MetricsConfig):
        self.config = config

    def parse(self, output: RawBenchmarkOutput) -> BenchmarkResult:
        """根据配置解析 benchmark 输出为结构化指标"""
        if self.config.source == "json":
            return self._parse_json(output)
        elif self.config.source == "regex":
            return self._parse_regex(output)
        elif self.config.source == "stdout_kv":
            return self._parse_kv(output)

    def _parse_json(self, output: RawBenchmarkOutput) -> BenchmarkResult:
        """
        解析 JSON 输出:
        - 从 stdout 或指定文件读取 JSON
        - 使用 jsonpath 提取各指标
        """

    def _parse_regex(self, output: RawBenchmarkOutput) -> BenchmarkResult:
        """
        用正则表达式从 stdout 提取指标:
        e.g. "Recall@10: 0.85" → {"recall_at_10": 0.85}
        """

    def _parse_kv(self, output: RawBenchmarkOutput) -> BenchmarkResult:
        """
        解析 key=value 或 key: value 格式的输出
        """
```

---

## 10. CLI 设计

```python
# src/auto_bench/cli.py
import click

@click.group()
def cli():
    """Auto-Benchmark: LLM 驱动的自动化基准测试调优工具"""
    pass

@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--max-iter", type=int, help="覆盖最大迭代次数")
@click.option("--dry-run", is_flag=True, help="只分析不修改")
@click.option("--verbose", "-v", is_flag=True, help="详细输出")
def run(config_path: str, max_iter: int | None, dry_run: bool, verbose: bool):
    """运行自动化优化循环"""
    config = load_config(config_path)
    if max_iter:
        config.optimization.max_iterations = max_iter
    engine = OptimizationEngine(config)
    asyncio.run(engine.run())

@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def baseline(config_path: str):
    """仅运行基线 benchmark 并显示结果"""

@cli.command()
@click.argument("project_path", type=click.Path(exists=True))
def init(project_path: str):
    """交互式生成配置文件"""

@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def report(config_path: str):
    """查看历史优化报告"""

@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def cleanup(config_path: str):
    """清理所有 worktree 和临时分支"""
```

使用示例：
```bash
# 初始化配置
auto-bench init /path/to/my/project

# 运行基线测试
auto-bench baseline configs/my-project.yaml

# 开始自动优化
auto-bench run configs/my-project.yaml --max-iter 10

# 查看报告
auto-bench report configs/my-project.yaml

# 清理
auto-bench cleanup configs/my-project.yaml
```

---

## 11. 错误处理 & 恢复策略

| 场景 | 处理方式 |
|------|----------|
| Benchmark 执行超时 | 记录为失败迭代，revert，继续下一轮 |
| Benchmark 执行出错 (non-zero exit) | 让 AnalyzerAgent 分析错误信息，决定是修复还是 revert |
| LLM API 调用失败 | 重试 3 次，指数退避，仍失败则暂停等待用户干预 |
| LLM 生成的代码修改导致语法错误 | 在 benchmark 前做快速语法检查，失败则 revert |
| Git worktree 操作失败 | 清理残留 worktree，重试一次 |
| 用户中断 (Ctrl+C) | 捕获 SIGINT，清理当前 worktree，保存已有历史，优雅退出 |
| 进程崩溃恢复 | 启动时检查 `.auto-bench-data/state.json`，从中断点恢复 |

---

## 12. 实现顺序

### Phase 1: 项目骨架 & 配置
1. 初始化项目 (`pyproject.toml`, 目录结构)
2. 实现配置 schema (`config/schema.py`)
3. 实现配置加载 (`config/loader.py`)
4. 编写示例配置文件

### Phase 2: Git Worktree 管理
5. 实现 `WorktreeManager` 核心功能
6. 实现分支策略 (create/accept/revert)
7. 编写 worktree 单元测试

### Phase 3: Benchmark 执行
8. 实现 `BenchmarkRunner`
9. 实现 `ResultParser` (JSON/regex/kv)
10. 编写 benchmark 解析测试

### Phase 4: Agent 工具
11. 实现 Agent 工具集 (code_read, code_edit, code_search, bash_exec, git_ops)
12. 编写工具安全检查 (路径限制等)
13. 编写 Agent 系统提示词

### Phase 5: Agent 集成
14. 实现 `OptimizerAgent`
15. 实现 `AnalyzerAgent`
16. 集成测试：Agent + 工具 + Worktree

### Phase 6: 主循环 & 决策
17. 实现 `OptimizationEngine` 主循环
18. 实现决策逻辑 (`decision.py`)
19. 实现状态机 (`state.py`)

### Phase 7: 历史 & 报告
20. 实现 `IterationStore` (SQLite)
21. 实现报告生成 (`reporter.py`)

### Phase 8: CLI & 打磨
22. 实现 CLI 命令 (`cli.py`)
23. 实现错误恢复机制
24. 端到端测试
25. 编写文档

---

## 13. 关键设计决策说明

### 为什么用双 Agent 而不是单 Agent？
- **关注点分离**：Optimizer 专注代码理解和修改，Analyzer 专注结果评估
- **减少偏见**：同一个 Agent 做修改又评价自己容易产生确认偏误
- **灵活性**：可以用不同模型、不同参数分别优化两个 Agent

### 为什么用 git worktree 而不是简单的 git branch？
- **并行安全**：worktree 有独立的工作目录，不影响用户的主工作区
- **隔离性**：benchmark 执行在独立目录中，不污染原项目
- **可审计**：每个 worktree 对应一个实验，清晰可追溯

### 为什么把 benchmark 结果解析做成可配置的？
- **通用性**：不同项目的 benchmark 输出格式千差万别
- **JSON/regex/kv 三种模式**：覆盖最常见的输出格式
- **可扩展**：用户可以自定义 parser

### 为什么选择 SQLite 存储历史？
- **零依赖**：无需额外数据库服务
- **结构化查询**：方便生成报告和分析趋势
- **持久化**：支持进程崩溃恢复
