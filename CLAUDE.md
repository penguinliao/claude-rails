# 初心

所有的改动和优化都应该围绕和贴合我们的初心和目标：**让非技术的 PM 在这个环境下安心地开发，并且可以交付生产级别的产品。** 同时，这个项目的目标是 GitHub 5000 star，按开源标杆项目的标准要求自己。

---

# Claude Rails — 项目全景

> Rails for Claude Code — 把 AI 编程的代码准确率从 ~50% 提升到 80%+

**品牌**：Claude Rails 🚂
**核心引擎 & CLI**：harness（类比 Ruby on Rails 的 `rails` 命令）
**仓库**：https://github.com/penguinliao/claude-rails
**版本**：v0.2.0 (MIT)
**目标用户**：使用 Claude Code 做生产项目的 PM 和开发者

---

## 核心理念

| 原则 | 含义 |
|------|------|
| **环境 > 模型** | 不追求更强的 AI，追求更好的验证环境（Hashimoto 2026） |
| **物理约束 > AI 承诺** | Hook 真跑工具验证，不信 AI 说"我修好了" |
| **规格先行** | 先写 acceptance criteria，再写代码（Self-Spec, ICLR 2026） |
| **认知隔离** | 写代码和审查代码用不同上下文，避免确认偏误 |
| **Fail-closed** | Hook 异常时拦截而非放行，安全门不会因崩溃失效 |

---

## 项目结构

```
harness-engineering/
├── harness/                # 核心引擎（质量评分 + 流水线状态机）
│   ├── pipeline.py         # 5 阶段状态机：start/advance/retreat/reset
│   ├── reward.py           # 8 维度评分引擎（基于 367 真实 bug 权重）
│   ├── runner.py           # 3 种检查模式：quick(<5s) / standard(<30s) / full(1-2min)
│   ├── verdict.py          # 评分 → PM 可读的 PASS/FAIL/BLOCKED 判决
│   ├── feedback.py         # 工具输出 → AI 可执行的修复建议
│   ├── autofix.py          # 自动修复循环（ruff --fix → 重检 → 反馈）
│   ├── exec_verifier.py    # 真实执行验证（compile → import → test → smoke）
│   ├── spec_validator.py   # 规格合规验证（LLM → AST → 关键词，三层降级）
│   ├── risk_analyzer.py    # 改动风险自动分级（→ 决定流水线厚度）
│   ├── hook_runner.py      # Hook 统一框架（输入解析 + fail-closed + 日志）
│   ├── telemetry.py        # 遥测日志（append-only SQLite）
│   ├── health.py           # 依赖健康检查（harness doctor）
│   ├── mutation_test.py    # harness 自身的突变测试
│   └── skill_extractor.py  # pipeline 完成后从客观数据提取经验 skill
│
├── hooks/                  # Claude Code Hook 脚本（物理控制层）
│   ├── pre_edit.py         # 编辑前拦截：阶段检查 + spec 范围检查
│   ├── post_edit.py        # 编辑后检查：快速质量扫描 + 自动修复
│   ├── pre_commit.py       # 提交前拦截：standard 检查 + 危险命令分类
│   ├── post_agent.py       # Agent 完成后：独立审查（认知隔离）
│   └── stop_check.py       # 停止前检查：拦截 deflection（推卸给用户）
│
├── pipeline/               # 流水线阶段定义
│   ├── stages.md           # 5 阶段概览
│   └── stage_prompts/      # 各阶段的 AI 提示词
│       ├── 01_spec.md
│       ├── 02_design.md
│       ├── 03_implement.md
│       ├── 04_review.md
│       └── 05_test.md
│
├── foundation/             # 项目模板 & 共享库
│   ├── project-template/   # 新项目骨架（含安全编码规范）
│   ├── shared-lib/         # starpalace-shared（auth/db/tasks/security）
│   └── configs/            # CORS / 日志 / 连接池配置
│
├── bin/                    # CLI 工具
│   ├── harness_cli.py      # harness init/status/doctor/advance/retreat
│   ├── new-project.sh      # 从模板创建新项目
│   └── score.sh            # 快速评分脚本
│
├── docs/                   # 深度文档
│   ├── architecture.md     # 6 层验证架构
│   ├── reward-functions.md # 8 维度权重来源
│   ├── spec-first-workflow.md
│   ├── single-focus-principle.md
│   ├── rl-environment.md
│   ├── testing-integration.md
│   └── PRD_v2.0.md
│
├── examples/               # 使用示例
├── templates/              # 文件模板
├── scripts/                # 辅助脚本
├── marketing/              # 推广材料
├── install.sh              # 一行命令安装
└── pyproject.toml          # 包配置
```

---

## 5 阶段流水线

```
SPEC(1) → DESIGN(2) → IMPLEMENT(3) → REVIEW(4) → TEST(5) → [DEPLOY(6)]
```

| 阶段 | 谁做 | 产出 | 物理约束 |
|------|------|------|---------|
| SPEC | Opus | `spec.md` + `test_ac_*.py` + `xiaoce_brief.md` + `zhuolong_brief.md` | 非此阶段不能编辑 spec.md；SPEC 阶段可写测试脚本 |
| DESIGN | Opus | 架构文档（可选） | — |
| IMPLEMENT | Sonnet 子 Agent | 修改后的代码文件 | **唯一允许写代码的阶段**；test_*.py 和 *_brief.md 物理锁定 |
| REVIEW | harness 自动 + 独立 Agent | check_standard 评分 ≥ 60 | harness 自己跑 ruff/mypy/bandit |
| TEST | harness 三层门禁 | Gate1: test_*.py exit 0 / Gate2: 小测报告 / Gate3: 浊龙报告 | harness 机械执行 + 报告文件门禁 |

**3 种路由**：
- `micro [3→4→5]` — typo/样式（1-2 行改动）
- `standard [1→3→4→5]` — 功能改动（跳设计）
- `full [1→2→3→4→5]` — 新功能/跨模块（含设计）
- 加 `-deploy` 后缀启用 Stage 6

**回退**：REVIEW/TEST 发现 bug → retreat 到 IMPLEMENT → Sonnet 修 → 重走 4-5（最多 3 次循环）

**过期**：pipeline 超过 4 小时未活动自动失效，必须 reset + start 新 pipeline。防止旧 pipeline 被复用为新任务的通行证。

**吃狗粮**：harness-engineering 自身代码也走 pipeline，无阶段豁免。spec 范围豁免仅限 harness/ 和 hooks/（避免循环依赖）。

**测试认知隔离**：测试脚本在 SPEC 阶段由 Opus 编写（代码还不存在），IMPLEMENT 阶段被 pre_edit hook 物理锁定（Sonnet 碰不到）。测试基于"应该做什么"（spec），不基于"怎么实现的"（代码）。Sonnet 发现接口不合理只能写 `.harness/change_request.md` 上报，Opus 裁决是否更新。

**三层 TEST 门禁**：
1. Gate 1: harness 机械执行 test_*.py（subprocess, exit code 判生死）
2. Gate 2: 小测白盒审计（xiaoce_brief.md 存在 → xiaoce_report.md 必须存在）
3. Gate 3: 浊龙黑盒验收（zhuolong_brief.md 存在 → zhuolong_report.md 必须存在）
- brief 不存在 = 对应 Gate 跳过（由 SPEC 阶段测试策略字段决定）
- 任何 Gate 失败 → retreat → IMPLEMENT → REVIEW → TEST（最多 3 轮）

---

## 8 维度评分引擎

基于 367 个真实生产 bug 的统计权重：

| 维度 | 权重 | 硬门禁 | 工具 |
|------|------|--------|------|
| functional | 33% | < 60 → BLOCK | compile + import + pytest |
| spec_compliance | 18% | — | LLM + AST + 关键词 |
| type_safety | 14% | — | mypy --strict |
| security | 12% | < 50 → BLOCK | bandit + ruff S 规则 |
| complexity | 8% | — | radon CC + 可维护性指数 |
| architecture | 5% | — | 自定义规则 |
| secrets | 5% | 任何泄露 → BLOCK | detect-secrets |
| code_quality | 5% | — | ruff lint |

**及格线**：加权总分 ≥ 60.0

---

## Hook 物理控制

5 个 Hook 自动执行，AI 违反会被 exit 2 硬拦截：

| Hook | 触发时机 | 做什么 | Fail 策略 |
|------|---------|--------|----------|
| pre_edit | AI 要编辑文件 | 检查 pipeline 阶段 + spec 范围 + **IMPLEMENT 阶段锁定 test_*.py 和 *_brief.md** | fail-closed |
| post_edit | AI 编辑完文件 | 快速质量扫描 + 自动修复 | fail-open |
| pre_commit | AI 要 git commit | standard 检查 + 危险命令分类 | fail-closed |
| post_agent | 子 Agent 完成 | 独立审查所有修改文件 + **检测 change_request.md** | fail-open |
| stop_check | AI 要停止 | 拦截 deflection + **pipeline 未完成时拦截停止** | fail-open |

---

## 开发规范

### 运行 harness CLI
```bash
# 必须设置 PYTHONPATH（未完整安装时）
PYTHONPATH=/Users/lkk/Desktop/harness-engineering python3 -m harness.pipeline <cmd>

# 可用命令
start --route=standard --project=/path/to/project --desc="描述"
advance --project=/path/to/project
retreat --project=/path/to/project --target=3
status --project=/path/to/project
reset --project=/path/to/project
skip --project=/path/to/project
```

### 代码风格
- Python：ruff（line-length=100, target py39）
- Lint 规则：E, F, W, I, B, S, UP（忽略 E501, S101, S603, S607）
- Type check：mypy（warn_return_any, ignore_missing_imports）
- 安全扫描：bandit + ruff S 规则

### 10 条安全编码铁律
1. 禁止硬编码密钥 — 全部从环境变量读
2. SQL 必须参数化 — 用 ? 或 %s，禁止 f-string 拼 SQL
3. 用户输入必须 Pydantic 验证
4. CORS 禁止 * 通配符
5. JWT 无默认值 — 配置缺失 raise
6. 后端错误必须有前端提示
7. DB 连接用 context manager
8. 后台任务用 safe_task（带异常处理）
9. XML 用 defusedxml（禁止 XXE）
10. 日志脱敏密钥/密码/token

### pipeline.json 不可直接修改
- settings.json deny 规则拦截 Edit/Write
- Hook 拦截 Bash 绕过
- 唯一合法途径：`python3 -m harness.pipeline advance/retreat/reset`

### 已知平台注意事项
- macOS APFS 大小写不敏感：路径比较必须 `.lower()`
- `bandit # nosec B608` 在本环境不识别：f-string SQL 直接重构为常量
- tests/ 文件也走 post_edit 严格扫描：仿真脚本要和生产代码同等规范

---

## 测试策略

### 运行项目测试
```bash
cd /Users/lkk/Desktop/harness-engineering
python3 -m pytest tests/ -v
```

### 突变测试（验证 harness 自身可靠性）
```bash
python3 -c "from harness.mutation_test import run_mutation_test, print_mutation_report; print_mutation_report(run_mutation_test(['被测文件.py']))"
```
拦截率 < 80% 时必须先修 harness 再交付。

### 交付验证（每次都要做）
1. 突变测试验证 harness 可靠性
2. 输出双重验证提醒（独立审查提示词 + 修改文件列表）

---

## 依赖

**核心依赖**（自动安装）：
- ruff >= 0.6.0（lint + 自动修复）
- mypy >= 1.10（类型检查）
- bandit >= 1.7.9（安全扫描）
- detect-secrets >= 1.5.0（密钥检测）
- radon >= 6.0.1（复杂度分析）

**可选依赖**：
- esbuild（TypeScript/Vue 语法检查）
- pytest, pytest-cov（测试）
- shellcheck-py（shell 脚本检查）

---

## 语言支持

| 语言 | 状态 | 覆盖范围 |
|------|------|---------|
| Python | ✅ 完整 | lint + type + security + functional + complexity |
| TypeScript/JavaScript | ✅ 基础 | esbuild 语法检查 + tsc 类型检查 |
| Vue SFC | ✅ 基础 | 结构验证 + esbuild |
| Go / Rust / Java | 🔜 计划中 | — |

---

## 贡献指南

这是一个目标 5000 star 的开源项目，贡献代码请遵循：

1. **规格先行**：新功能必须先写 spec.md（AC + 影响文件清单）
2. **走流水线**：所有代码改动通过 harness pipeline（自己用自己）
3. **物理约束优先**：能用 Hook 拦截的不靠文档规范
4. **不过度工程化**：解决当前问题，不为假想需求设计
5. **双语文档**：README 和用户可见文档保持中英双语
