# Stage 3: IMPLEMENT

## 架构：Opus 调度，Sonnet 执行

**Opus（主Agent）不直接写代码。** 所有代码编写通过 Agent tool 派 Sonnet 子agent 完成。

### Opus 的工作

1. **拆分任务**：根据 spec.md，把实现拆成独立的模块级任务
2. **逐个派发**：每次派一个 Sonnet agent 实现一个模块，完成后再派下一个
3. **Sonnet 自测**：每个 Sonnet agent 在返回前必须验证代码语法正确
4. **冲突检查**：多个 Sonnet 改同一文件时，合并后检查语法和关键函数存在

### 派发 Sonnet 的 Prompt 模板

    你是代码实现工程师。直接写代码，不要分析确认。

    ## 流水线规则（必须遵守，违反=交付作废）

    1. **开工前先检查流水线状态**：运行 `python3 -m harness.pipeline status`
       - 必须处于 Stage 3 IMPLEMENT 阶段才能写代码
       - 如果不在 Stage 3 → 立即停止，返回"当前不在IMPLEMENT阶段，无法写代码"
       - 如果没有活跃的pipeline → 立即停止，返回"没有活跃的pipeline"
    2. **只改 spec 列出的文件**：不在 spec.md 影响文件列表里的文件，不要动
    3. **不做 Stage 4/5 的事**：不做代码审查、不做测试验收、不评价自己代码质量
    4. **不修改 pipeline.json**：不要运行 advance/retreat/reset，流水线控制是 Opus 的事
    5. **不碰测试文件**：.harness/test_*.py 和 .harness/*_brief.md 是 SPEC 阶段锁定的，不能修改（hook 会拦截）

    ## 任务

    任务：[具体要实现什么]
    文件：[要修改的文件路径]
    项目根目录：[project_root 的绝对路径]
    接口要求：[从 spec.md 接口契约部分摘取]
    验收标准：[从 spec.md 摘取的相关验收标准]

    ## 编码要求

    1. 严格按接口契约实现，不自行修改接口签名
    2. 写完整代码，不留 TODO
    3. 处理异常情况
    4. 完成后运行 python3 -c "import ast; ast.parse(open('文件路径').read())" 验证语法

    ## 接口变更流程

    如果你发现 spec 中定义的接口不合理，**不要私自修改**：
    1. 在 .harness/change_request.md 写明：要改什么、为什么要改、建议怎么改
    2. 按原 spec 继续实现其他部分
    3. Opus 会在你完成后看到变更请求并裁决

### Agent tool 参数

    Agent(
        subagent_type="general-purpose",
        model="sonnet",
        prompt="...",
    )

### 物理约束（hook 自动执行）

以下文件在 IMPLEMENT 阶段被 pre_edit hook 物理锁定，Sonnet 无法修改：

| 文件 | 原因 |
|------|------|
| .harness/test_*.py | 测试脚本在 SPEC 阶段由 Opus 编写，认知隔离 |
| .harness/*_brief.md | 审计任务书在 SPEC 阶段锁定 |
| .harness/spec.md | 非 SPEC 阶段不可编辑（已有） |

唯一可写的 .harness 文件：`.harness/change_request.md`（接口变更上报通道）

### 验证条件

- 所有 spec.md 中的影响文件都已实现
- 每个文件语法正确
- Opus 不直接 Edit/Write 代码文件

### Opus 绝对不做

- **不直接写代码**：所有代码改动通过 Sonnet 完成
- **不做测试**：测试是 Stage 5 的事
- **不做审查**：审查是 Stage 4 的事（且要用新上下文）
