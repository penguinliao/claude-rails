# Harness Engineering

> **让 Claude Code 生成的代码准确率从 50% 提升到 80%+**
> 为非技术 PM 和追求代码质量的开发者设计的 Claude Code 增强工具

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-required-orange.svg)](https://claude.ai/download)

## 一行命令安装

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/harness-engineering/main/install.sh | bash
```

2 分钟后可用。**先看下面的"收益 vs 代价"再决定装不装。**

---

## 这是给谁的

✅ **适合你**，如果你：
- 用 Claude Code 开发**生产项目**（不是 5 分钟原型）
- 受够了 Claude "看起来修好了但其实没修" 的循环
- 希望 AI 先写清楚要做什么再动手
- 是 PM / 产品经理 / 非专业开发者，但要对代码质量负责

❌ **不适合你**，如果你：
- 只是写 5 分钟玩具项目（流水线的阶段开销会让你抓狂）
- 用的是 Cursor / Aider / 其他工具（目前只支持 Claude Code）
- 只写 Ruby / Go / Rust（目前只支持 Python / TypeScript / Vue）
- 对 token 消耗敏感（我们会让它翻 2-3 倍）

---

## 收益 vs 代价（核心）

| 维度 | 不用 harness | 用 harness |
|---|---|---|
| **代码准确率** | ~50%（Anthropic 内部数据）| **~80%+**（基于 367 项真实 bug 数据）|
| **安全漏洞** | AI 可能写出 SQL 注入、硬编码密钥 | **物理拦截 10 条铁律**（查到就 block） |
| **规格文档** | 通常没有，AI 写完就忘 | **每个功能自动留 spec.md** |
| **AI 承诺 vs 实际** | 经常"说修好了但没修" | **hook 真跑工具验证，不信 AI 的话** |
| **Token 消耗** | 1x 基准 | **2-3x**（5 阶段流水线 + 多轮工具调用） |
| **单功能耗时** | 3-5 分钟 | **5-15 分钟**（质量 vs 速度的权衡） |
| **认知负担** | PM 要审每一个改动 | **PM 只在起点和终点参与** |

---

## 三步上手

```bash
# 1. 安装（一次性，2 分钟）
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/harness-engineering/main/install.sh | bash

# 2. 在任何项目里启用
cd 你的项目/
harness init

# 3. 正常用 Claude Code
claude
```

然后告诉 Claude：**"开发 XX 功能"**，harness 会让它自动走 5 个阶段：
`SPEC → DESIGN → IMPLEMENT → REVIEW → TEST`

每个阶段都有物理门禁，不通过不能进下一步。你不需要懂这些阶段，只需要：
- 起点：告诉 Claude 要做什么
- 终点：看 harness 汇报"全部通过"时验收

---

## 它怎么工作（用户不需要懂，但可以展开）

<details>
<summary><b>5 阶段流水线</b> — 强制 AI 分步做事</summary>

| 阶段 | AI 干什么 | 门禁条件 |
|---|---|---|
| 1. SPEC | 写清楚要做什么（不写代码） | spec.md 符合格式 |
| 2. DESIGN | 决定怎么做（架构 / 接口 / 影响文件） | 审查通过 |
| 3. IMPLEMENT | 真正写代码 | ruff + mypy + bandit + 8 维评分全绿 |
| 4. REVIEW | 独立 AI 审查（认知隔离） | 审查通过 |
| 5. TEST | 跑测试 + 用户验收 | 测试通过 |

这个流程是**硬性约束**：AI 不能跳过，不能绕过。它想直接写代码也会被 hook 拦下来。

</details>

<details>
<summary><b>7 个质量工具</b> — 全自动装</summary>

| 工具 | 干什么 |
|---|---|
| [ruff](https://github.com/astral-sh/ruff) | Python lint + 自动修复 |
| [mypy](https://mypy-lang.org/) | Python 类型检查 |
| [bandit](https://bandit.readthedocs.io/) | Python 安全漏洞扫描 |
| [detect-secrets](https://github.com/Yelp/detect-secrets) | 硬编码密钥检测 |
| [radon](https://radon.readthedocs.io/) | 代码复杂度分析 |
| [pre-commit](https://pre-commit.com/) | Git 提交前自动运行 |
| [esbuild](https://esbuild.github.io/) | TypeScript / JavaScript 语法检查 |

安装脚本会自动装好，**用户不需要手动配置任何东西**。

</details>

<details>
<summary><b>8 维度评分</b> — 不是 PASS/FAIL，而是梯度反馈</summary>

权重基于分析 367 个真实项目 bug 得出：

| 维度 | 权重 | 为什么这个权重 |
|---|---|---|
| Functional（功能正确性） | 33% | 117/367 是逻辑错误——最常见 |
| Spec Compliance（规格符合度） | 18% | 37 个是"做错了东西" |
| Type Safety（类型安全） | 14% | 类型错误导致运行时 bug |
| Security（安全） | 12% | 频率低但后果严重 |
| Complexity（复杂度） | 8% | 预测未来维护问题 |
| Architecture（架构） | 5% | 防止代码腐烂 |
| Secret Safety（密钥） | 5% | **零容忍**：任何泄露 = BLOCKED |
| Code Quality（代码风格） | 5% | 可读性 |

**硬门禁**（任何一个触发 = BLOCKED）：
- 密钥泄露
- Functional < 60（代码根本跑不起来）
- Security < 50（危险漏洞）

</details>

---

## 为什么我敢说 "50% → 80%"

这不是随便说的数字。harness 本身设计遵循三个原则：

1. **Environment > Model**（环境比模型重要）
   来自 Mitchell Hashimoto 2026 年的 "Harness Engineering" 概念——不追求更强的 AI，追求更好的验证环境

2. **物理约束 > 承诺**
   不相信 AI 说 "我修好了"，hook 跑真实工具验证。AI 绕不过去——想写代码？没有 pipeline 我就拦。pipeline 不在 IMPLEMENT 阶段？我就拦。

3. **规格优先**（Self-Spec, ICLR 2026）
   让 AI 先写规格再动手，通过率提升 2-5%。harness 把这个原理做成了强制流程

### 这个项目是用 harness 自己开发 harness 开发的
从 v0.1 开始，这个仓库的每一次代码改动都走自己的 5 阶段流水线。**如果 harness 不能可靠地约束自己，凭什么说它能约束你的项目？**

---

## 常见问题

**Q: 会改我现有的 Claude Code 设置吗？**
A: 会，但**自动备份**到 `~/.claude/settings.json.backup.时间戳`。合并是智能的，保留你所有现有的 hook 和权限规则。

**Q: 卸载干净吗？**
A: 一条命令：`harness uninstall`。删掉 `~/.harness/`，恢复 settings.json 备份。没有残留。

**Q: token 真的翻 2-3 倍？我付不起。**
A: 是的，这是代价。harness 适合**质量重要于成本**的场景（生产代码、付费客户项目、开源发布）。如果你写的是周末玩具，**不要装**——用原生 Claude Code 就好。

**Q: 支持 Cursor / Aider / Continue 吗？**
A: 不支持。harness 强依赖 Claude Code 的 hook 系统。

**Q: 支持 Java / Go / Rust 吗？**
A: 目前不支持。只有 Python / TypeScript / Vue 有完整物理约束。

**Q: harness 自己的代码质量如何？**
A: 从 v0.1 起，harness 的每次改动都被自己的 pipeline 约束。我们不搞"医者不自医"。

---

## 故障排查

```bash
harness doctor          # 检查环境
harness status          # 当前项目 pipeline 阶段
cat ~/.harness/.harness/hook.log   # 看 hook 日志
```

详细文档：[docs/](docs/)

---

## 卸载

```bash
harness uninstall
```

或手动：
```bash
rm -rf ~/.harness/
# 恢复 settings.json 备份（找最新的）
cp ~/.claude/settings.json.backup.最新时间 ~/.claude/settings.json
```

---

## 对于开发者

想参与 harness 本身的开发？

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/harness-engineering
cd harness-engineering
pip install -e .
```

深度文档：
- [架构设计](docs/architecture.md)
- [奖励函数](docs/reward-functions.md)
- [规格优先原则](docs/spec-first-workflow.md)
- [单步聚焦原则](docs/single-focus-principle.md)
- [RL 环境设计](docs/rl-environment.md)

---

## 研究基础

harness 的设计不是拍脑袋，每个核心决策都有依据：

- **Harness Engineering** (Mitchell Hashimoto, 2026) — environment > model
- **Self-Spec** (ICLR 2026) — 规格优先提升通过率 2-5%
- **Ralph Loop** (2026) — 执行反馈循环减少 40% hotfix
- **FunPRM** (2026) — 过程奖励 > 结果奖励
- **Static Analysis as Feedback** (arXiv:2508.14419) — 安全问题从 40% 降到 13%

---

## License

[MIT](LICENSE) — 自由使用、修改、商用，只需保留版权声明。

---

## 致谢

灵感来自 Anthropic 官方的 Claude Code hook 设计、Mitchell Hashimoto 的 harness engineering 概念、以及每一个用 AI 写代码时被 "看起来对但其实不对" 坑过的开发者。
