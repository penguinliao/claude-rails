# Stage 5: TEST

## 目标：三层门禁验证，直到可以交付

不写新代码。目标是通过三层自动门禁验证代码质量。

### 三层门禁（顺序执行）

#### Gate 1：验收测试脚本（harness 机械执行）

harness 自动用 subprocess 执行 `.harness/test_ac_*.py`。这些脚本是 SPEC 阶段写的，写代码的 Sonnet 从未看过也不能修改——认知隔离保证测试基于需求而非实现。

- 全部 exit 0 → Gate 1 通过
- 有失败 → 整个 TEST 不通过，retreat 到 IMPLEMENT 修代码

**Opus 不需要做任何事**，harness 在 advance 时自动执行。

#### Gate 2：小测白盒审计（按 brief 执行）

如果 SPEC 阶段产出了 `.harness/xiaoce_brief.md`，Opus 必须派小测 Agent 执行审计。

派小测 Agent：

    Agent(
        subagent_type="小测",
        prompt="""## 流水线规则（必须遵守）
    1. 你是测试员，不是开发者：只测试、只记录问题，绝对不修改任何代码文件
    2. 不修改 pipeline.json：不要运行 advance/retreat/reset
    3. 发现 bug 只记录，修复是 Stage 3 的事
    4. 审计完成后，把报告写入 .harness/xiaoce_report.md

    ## 审计任务书
    [读取 .harness/xiaoce_brief.md 的完整内容粘贴到这里]

    ## 项目根目录
    [project_root 的绝对路径]
    """,
    )

小测完成后写入 `.harness/xiaoce_report.md`。harness 在 advance 时检查该文件存在且非空。

如果 SPEC 阶段没有产出 `xiaoce_brief.md`，Gate 2 自动跳过。

#### Gate 3：浊龙黑盒验收（按交付单执行）

如果 SPEC 阶段产出了 `.harness/zhuolong_brief.md`，Opus 必须派浊龙 Agent 执行验收。

派浊龙 Agent：

    Agent(
        subagent_type="浊龙",
        prompt="""## 流水线规则（必须遵守）
    1. 你是验收测试员：纯用户视角操作，不修改任何代码文件
    2. 不修改 pipeline.json：不要运行 advance/retreat/reset
    3. 发现问题只记录
    4. 验收完成后，把报告写入 .harness/zhuolong_report.md

    ## 交付单
    [读取 .harness/zhuolong_brief.md 的完整内容粘贴到这里]
    """,
    )

浊龙完成后写入 `.harness/zhuolong_report.md`。harness 在 advance 时检查该文件存在且非空。

如果 SPEC 阶段没有产出 `zhuolong_brief.md`，Gate 3 自动跳过。

### 测试结果处理

- **三层都通过** → Pipeline 完成，通知 PM 验收
- **任何一层失败** → retreat 回 Stage 3，Opus 派 Sonnet 修复
- **TEST→IMPLEMENT→REVIEW→TEST 最多循环 3 次**

### Pipeline 完成后

自动发 macOS 通知叫 PM：

    osascript -e 'display notification "开发+测试全部通过，请验收" with title "Harness Pipeline" sound name "Glass"'

### 绝对不做

- **不写新代码**：发现 bug 只记录，修复回 Stage 3
- **不手动修复再重测**：必须正式回 Stage 3
- **不跳过任何已定义的测试层**：brief 存在就必须跑对应 Agent
- **不修改测试脚本让测试通过**：测试脚本在 SPEC 阶段锁定
