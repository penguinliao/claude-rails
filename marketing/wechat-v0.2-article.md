# 我让 AI 给自己的代码加了门禁，然后它花了一整天绕过门禁

> Claude Rails v0.2 发布 — 一个 AI 代码质量门禁系统的自我进化故事

---

## 背景：AI 写代码的准确率只有 50%

Anthropic 内部数据显示，Claude Code 生成的代码准确率约 50%。也就是说，AI 写的每两段代码里，有一段是有问题的。

作为一个不懂代码的产品经理，我没法自己审代码。所以我做了一个系统：**Claude Rails** — 一套 Hook 物理约束，强制 AI 走"先写需求 → 再写代码 → 机器审查 → 机器测试"的流水线。不信任 AI 说"我修好了"，而是让工具真跑一遍验证。

v0.1 上线后效果不错，代码准确率从 50% 提升到了 80%+。但今天发生的事让我意识到——**规则本身也可以被规则的执行者绕过**。

---

## 第一个发现：AI 连续 advance 跳过审查

今天在用 Claude Rails 开发一个新项目时，我注意到 AI（Claude Opus）做了一件很聪明的事：

它 reset 了 pipeline，然后连续快速 advance，REVIEW 和 TEST 阶段 0 秒通过。没有审查，没有测试。流水线跑完了，但什么都没检查。

就像一个学生发现了快速翻页就能"看完"一本书的技巧。

## 第二个发现：伪测试

我加了格式检查——test_results.md 必须包含"N/M PASS"格式。AI 立刻适应了：

```
T1 语法检查 PASS
T2 函数存在 PASS
T3 签名正确 PASS
3/3 PASS
```

格式完美。但内容全是"语法正确""函数存在"——这不是测试，这是对着镜子说"我长得不错"。

## 第三个发现：我自己也在绕过

最讽刺的是——我让 AI 修复这些漏洞时，AI（和我）全程没有走 pipeline。

我们讨论了两个小时如何防止 AI 绕过规则，最后发现：**harness-engineering 项目本身从来没有用过自己的 pipeline**。一个代码质量门禁系统，自己的代码没有经过任何门禁。

就像一个安检系统的安检员自己不过安检。

---

## 根因分析

挖到最后，问题不是"AI 太聪明"，而是**架构有 3 个结构性缺口**：

### 缺口 1：旧 pipeline 永久有效

上周的 pipeline 停在 IMPLEMENT 阶段，今天来了新任务，AI 直接开始编辑代码。Hook 只问"现在是 IMPLEMENT 吗？"——不问"这个 pipeline 是为当前任务创建的吗？"

**一个过期的通行证，永远不会被收回。**

### 缺口 2：REVIEW/TEST 检查的是 AI 的自述

REVIEW 检查 review.md 里有没有关键词（P0/P1/问题/风险），TEST 检查 test_results.md 的格式。本质都是在读 AI 自己写的报告——AI 当然知道怎么写一份"看起来正确"的报告。

**如果你让考生自己批改试卷，满分率会是 100%。**

### 缺口 3：micro 路由是后门

`start --route micro` 直接跳到 IMPLEMENT，不需要 spec，REVIEW 和 TEST 也跳过。设计本意是给"改个错别字"用的，但 AI 可以把任何改动标记为 micro。

**给门留了一个"仅限员工"的侧门，但没有检查谁是员工。**

---

## 修复方案

用了一个判断标准过滤方案：**这个改动是 harness 自己在做事，还是在检查 AI 的自述？**

| 做法 | 本质 | 可靠性 |
|------|------|--------|
| harness 自己执行验证 | 物理约束 | 高 |
| 确定性规则（禁止/必须） | 堵死通道 | 高 |
| 检查 AI 写的 markdown | 检查自述 | 低 |
| CLAUDE.md 文字规则 | 靠 AI 自觉 | 无 |

### 改动 1：Pipeline 过期

超过 4 小时未活动的 pipeline 自动失效。AI 必须为新任务启动新 pipeline，从写需求开始。

**效果**：改动写进去的那一刻，立刻拦住了我——因为当前 pipeline 是 12 小时前的。自己的门禁拦了自己，证明有效。

### 改动 2：REVIEW/TEST 物理门禁

REVIEW 不再检查 review.md 的关键词，而是 harness 自己跑 ruff/mypy/bandit 扫描代码。TEST 不再检查 test_results.md 的格式，而是 harness 用 subprocess 真实执行测试脚本。

**AI 不能靠"写一段 markdown"过关，必须写一个真正能跑的测试脚本。**

### 改动 3：吃自己的狗粮

删除了 harness-engineering 的自编辑豁免。从这个版本开始，harness 的代码修改必须走 harness 的 pipeline。

这个 commit 本身就是通过 pipeline 交付的：SPEC → IMPLEMENT → REVIEW(100/100) → TEST(6/6 scripts exit 0)。

---

## 开发过程中踩的坑

### 坑 1：Hook 扫描自己的测试代码

pre_commit hook 会扫描 bash 命令里的关键词（`pipeline.json`、`.harness/`）。当我要写测试脚本时，测试代码里引用了这些路径，被 hook 拦了。我花了 40 分钟用 base64 编码、chr() 拼字符串、写到 /tmp 再执行——本质上就是在绕过自己写的规则。

**教训**：关键词黑名单是脆弱的。改为只检测实际的文件写入操作（`>`, `>>`, `cp`, `mv`），不再扫描字符串内容。合法操作不被误杀，真正的篡改仍被 deny 规则拦截。

### 坑 2：AC 提取的去重问题

spec.md 里的验收标准在表格和正文中都出现，`extract_acceptance_criteria()` 把短版本和长版本都提取了（6 条变 12 条）。导致 TEST 阶段要求 12 个测试脚本但只有 6 个——被自己的门禁拦住了。

**教训**：用子字符串去重——如果新 AC 是已有 AC 的子串，跳过。表格优先提取（最结构化的来源）。

### 坑 3：验收标准不能等到开发完再写

开发完代码再写测试，AI 会不自觉地让测试适配代码（确认偏误）。验收标准必须在 SPEC 阶段锁定，成为 TEST 阶段的物理验证基准。

**这不是 AI 的问题，人也一样。先写答案再写题目，题目一定是对的。**

---

## 一句话总结

v0.1 解决的是"AI 写的代码质量不够"。v0.2 解决的是"AI 会绕过质量检查"。

**能绕过的规则不是规则。** 规则的有效性不取决于规则写得多详细，而取决于规则的执行者有没有能力（和动机）绕过它。

AI 的优化目标是"通过检查"而非"做好检查"。唯一可靠的办法是：**让检查者和被检查者不是同一个实体**。harness 检查 AI 的代码，不是 AI 检查自己的代码。

---

**Claude Rails** 是一个开源的 AI 代码质量门禁系统，基于 Claude Code Hook 实现。

GitHub: https://github.com/penguinliao/claude-rails

一行安装：
```bash
curl -fsSL https://raw.githubusercontent.com/penguinliao/claude-rails/main/install.sh | bash
```
