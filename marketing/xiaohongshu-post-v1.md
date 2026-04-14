# 小红书发布文案 v1

## 封面建议
- 背景：纯色（白或浅蓝），放一个大大的 🚂 emoji 和 "Claude Rails" 字样
- 副标题：「让 AI 写代码准确率从 50% 提升到 80%+」
- 右下角小字：「3 小时从想法到开源」
- 或者：直接用 GitHub 首页截图 + CI 绿色徽章

---

## 标题（3 选 1）

**版本 A（反差感最强，推荐）**：
```
我是产品经理，不懂代码🥹 却做了个开源工具让 Claude Code 准确率 50%→80%
```

**版本 B（痛点共鸣）**：
```
受够了 Claude 说"我修好了"但其实没修🤡 我做了个工具治这个病
```

**版本 C（数字导向）**：
```
3 小时开源上线🚂 让 Claude Code 写代码准确率翻倍的工具
```

---

## 正文

```
🥹 我是产品经理，不懂代码

我的 Claude Code 配置文件第一行就写着：
「我是 PM，不懂代码，请用中文回答」

但最近几个月我每天都在用 Claude Code 写代码。

最崩溃的不是 bug，是 Claude 信誓旦旦地说：
「✅ 我已修复此问题」
然后一跑 —— 还是错的。
同一个对话、同一个 bug、连续三次。

😤 于是我问了自己一个很朴素的问题：

「如果不再『问』AI，而是『验证』AI 呢？」

---

🚂 Claude Rails 就是答案

它做一件很简单的事：
不相信 AI 说"我修好了"，
用 hook 跑真实工具去验证。

强制 AI 走 5 个阶段：
📝 先写规格（不写代码）
🎨 再设计架构
💻 才能写代码
🔍 独立 AI 审查（认知隔离）
✅ 跑测试验收

每一步都有物理门禁。
AI 想跳？hook 直接拦截。
它想绕过？对不起，代码写不进去。

---

✨ 你会得到什么

✅ 代码准确率 50% → 80%+
   （基于 367 项真实 bug 数据）

✅ 10 条安全铁律自动拦截
   SQL 注入 / 硬编码密钥 / CORS 通配符...

✅ 每个功能自动留下规格文档
   不用自己记

✅ AI 无法绕过质量检查
   hook 是物理拦截，不是 prompt 承诺

---

⚠️ 代价是什么（我必须说清楚）

❌ Token 消耗 2-3 倍
   每个功能走 5 阶段，Claude 要说更多话

❌ 单功能从 3 分钟变 10 分钟
   慢是必然，换来的是不用返工

❌ 只支持 Claude Code
   不支持 Cursor / Aider / Continue

❌ 只支持 Python / TypeScript / Vue
   Java / Go / Rust 后续版本支持

---

🎯 适合谁

✅ 要上生产的项目
✅ 付费客户的项目
✅ 开源发布前的代码
✅ 受够 Claude"幻觉修复"的人
✅ PM / 产品经理 / 非专业开发者

❌ 不适合 5 分钟玩具原型
❌ 不适合对 token 成本敏感的场景

---

🚀 一行命令安装（2 分钟）

打开终端，粘贴这一行：

curl -fsSL https://raw.githubusercontent.com/penguinliao/claude-rails/main/install.sh | bash

脚本会自动：
① 检测 Claude Code 和 Python 环境
② 下载 harness 核心
③ 安装 7 个质量工具（ruff、mypy、bandit 等）
④ 合并你的 Claude Code 配置（自动备份）
⑤ 创建 harness 命令

---

📖 使用方法（3 步）

Step 1️⃣：安装完成后，进入你的项目
cd 你的项目目录

Step 2️⃣：初始化 harness
harness init

Step 3️⃣：正常启动 Claude Code
claude

然后告诉 Claude：「开发 XX 功能」

就这样。

Claude 会自动走 5 个阶段：
SPEC → DESIGN → IMPLEMENT → REVIEW → TEST

你不需要懂这些阶段。
你只需要：
• 起点：告诉它要做什么
• 终点：看它汇报"全部通过"时验收

---

🧪 不信？去看 git 历史

这个项目本身是用 Claude Code 开发的。
而开发过程中，它被 Claude Rails 反过来约束着。
整个项目花了 3 小时，从想法到开源上线。

每一次 commit 的 message 都写了「为什么」。
包括 harness 在开发自己时抓到的几个 bug。

不必相信我，去看 git 历史：
github.com/penguinliao/claude-rails/commits/main

---

🗑️ 怎么卸载

harness uninstall

一条命令，干净卸载。
删掉 ~/.harness/，恢复 settings.json 备份。
不留任何残留。

---

🔗 链接

GitHub（英文首页 + 中文 README）：
https://github.com/penguinliao/claude-rails

中文完整说明：
https://github.com/penguinliao/claude-rails/blob/main/README.zh-CN.md

遇到问题提 issue：
https://github.com/penguinliao/claude-rails/issues

---

💡 最后一句话

我分享它不是因为我是一个了不起的工程师（我不是）。

我分享它是因为 **这个方法有效**：
· Environment > Model（环境比模型重要）
· 物理约束 > AI 的承诺
· 规格优先 > 代码优先

如果一个不懂代码的 PM 都能做出这个，
工程师能做出什么？

欢迎帮我测试，欢迎 star，欢迎提 issue 🙏

---

#AI编程 #ClaudeCode #开源项目 #产品经理 #代码质量
#Anthropic #AIProductManager #vibecoding #独立开发者 #SpecFirst
```

---

## 排版技巧提示（发小红书时）

1. **第一句话要抓住人**：标题直接摆冲突（"我不懂代码" + "做开源工具"）
2. **每 3-5 行空一行**：小红书用户滑屏阅读，长段落会被划过去
3. **emoji 做视觉锚点**：每一个小标题前加 1 个相关 emoji
4. **关键数据加粗**：50% → 80%、2-3 倍、3 小时
5. **代码用「」或直接贴**：小红书不支持 markdown，用等宽符号包裹
6. **图片建议**：
   - 图 1：封面（Claude Rails 🚂 + 核心价值）
   - 图 2：GitHub 首页截图（展示 CI 绿色 + star 数）
   - 图 3：install.sh 运行截图（双语横幅）
   - 图 4：收益 vs 代价表格图（我可以帮你做）
   - 图 5：git log 截图（11 个 commit 的真实开发史）

## 最佳发布时间

- **中午 12:00-13:00**（午休刷小红书高峰）
- **晚上 21:00-23:00**（睡前刷）
- 避开周一早上（通勤时间信息过载）
- 周五晚或周末效果最好

## 话题标签选择逻辑

- `#AI编程` `#ClaudeCode` — 精准受众
- `#开源项目` — 技术圈关注者
- `#产品经理` — 反差感受众（PM 看到会觉得"他都能做我也能"）
- `#代码质量` — 专业开发者
- `#独立开发者` — 独立开发者社区
- `#vibecoding` — 新兴 AI 编程文化标签
- 避免加 `#人工智能` 这种太泛的标签（竞争太激烈）
