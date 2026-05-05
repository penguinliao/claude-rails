# Antagonist 跨项目 P0 类别库（v2 自举沉淀）

**用途**：审查新项目时，先针对性扫这 7 类历史 P0，再做角度审查。
**来源**：harness-engineering antagonist v2 自举 19 轮发现的 21 个真 P0（2026-05-03，含 Opus + Sonnet + DeepSeek 三家共识）。

每条都包含**检测特征**（怎么 grep）和**修法**（治本而非治标）。

---

## 1. 状态机假 PASS（5 子类）

凡涉及 "consecutive_pass / cp / 通过计数器 / 同 issue N 轮" 的状态机，必须警惕假 PASS 入口：

- **1.1 cp 累加只看本轮**：必须同时 `not has_unfixed_blocking` 才 +1，否则 LLM 漏报 N 轮即假 PASS
- **1.2 decide_exit fallthrough**：本轮无 blocking 但 cp<3 不能返 0，应返"CONTINUE"
- **1.3 stuck 跨 severity**：B 方案下 P1 不应触发 ESCALATE，stuck 列表必须 `_is_blocking` 过滤
- **1.4 全 skip 后返 []**：raw_issues 非空但所有元素被 skip → 必须 raise 不能当本轮无 issue
- **1.5 issues=null/string 静默当空**：JSON 字段类型错应 raise

**检测**：`grep "consecutive_pass +="` 看是否同时检查全表 unfixed + per-family 共识
**修法**：状态机决策前先验证"是否真的本轮没问题"，多重断言

---

## 2. Prompt Injection（3 子类）

凡把 untrusted 内容（git diff / spec / 历史 issue / 用户输入）拼进 LLM prompt：

- **2.1 任一段无 marker 保护**：diff 防了 spec 没防 → 攻击者改 spec.md 注入
- **2.2 固定 marker 可被伪造**：用 ``` 或 `=== END DIFF ===` 攻击者一行复制即闭合
- **2.3 markdown fence 不靠谱**：LLM 不严格按 spec 解析，6 个反引号也能闭合

**检测**：`grep "parts.append(diff_text|spec_text|historical_issues)"` 看是否 nonce 包裹
**修法**：所有 untrusted 段用**同一随机 nonce** + BEGIN/END marker（不依赖 markdown 语义）

---

## 3. .env / 环境变量 RCE 注入（4 子类，治本=升级白名单）

凡 `os.environ[key] = value` 或 `subprocess(env=...)`：

- **3.1 OS 层**：PATH / PYTHONPATH / PYTHONHOME → 解析路径污染
- **3.2 动态链接器**：LD_PRELOAD / LD_LIBRARY_PATH / DYLD_*（macOS）→ 共享库劫持
- **3.3 git 系列**：GIT_EXEC_PATH / GIT_SSH_COMMAND / GIT_DIR / GIT_WORK_TREE / GIT_CONFIG_PARAMETERS / SSH_ASKPASS → git/ssh 行为劫持
- **3.4 网络/TLS**：HTTPS_PROXY / SSL_CERT_FILE / REQUESTS_CA_BUNDLE / SSLKEYLOGFILE → MITM 抓包/密钥泄漏

**检测**：`grep "os.environ\[" or "subprocess.run(.*env="`
**修法**：**白名单**（仅允许 `BUSINESS_*` 业务前缀）— 黑名单 ≥3 轮还能挑新成员就升级白名单（详见 feedback_blacklist_to_whitelist_treatment）

---

## 4. JSON 解析鲁棒性（4 子类）

凡 `json.loads(llm_output)`：

- **4.1 invalid escape**：LLM 输出 `\s\d` 未 escape 成 `\\s\\d` → JSON 非法
- **4.2 字段缺失**：`{"rotation_used":[]}` 没 issues → 不能当空当 ok
- **4.3 字段类型错**：null/string/int 当 list 处理
- **4.4 单 issue dict 不套 list**：`{"issues":{"sev":"P0",...}}` LLM 偶发输出

**检测**：`grep "json.loads"` 看后续是否检查 schema 字段存在 + 类型
**修法**：每种异常都 `raise LLMOutputUnparseable`（不静默返 []）+ parse 预处理修 invalid escape：
```python
fixed = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', text)
```

---

## 5. 异常路径漏接（3 子类）

凡 `try/except`：

- **5.1 try 内 raise 被自己 except 吞**：try 块抛 RuntimeError 但 `except RuntimeError` 在同一函数 → 永久错误当瞬时重试
- **5.2 http.client 异常不是 URLError 子类**：IncompleteRead / RemoteDisconnected 必须显式列
- **5.3 UnicodeDecodeError 不是 OSError 子类**：是 ValueError 子类 → except OSError 漏接

**检测**：`grep "except (" or "except.*as"` 看异常树覆盖
**修法**：契约错误用专用异常类（不复用 RuntimeError）；except 链显式列所有可能异常子类

---

## 6. 跨家族/跨源数据规范化（1 类）

凡多来源数据合并：

- **6.1 file 路径不规范化**：DeepSeek 报 `"harness/x.py"` vs Qwen 报 `"./harness/x.py"` 精确比较失败 → issue 重复

**检测**：`grep "file ==" or "path =="` 看是否 normpath
**修法**：`os.path.normpath` 规范化后比较

---

## 7. severity / 优先级处理（2 子类）

凡基于 LLM 输出的 severity 做决策：

- **7.1 白名单旁路**：LLM 输出 'CRITICAL' / 'BLOCKER' / 'P0BUG' 不在 P0/P1/P2/P3 → 既不阻断也不识别
- **7.2 跨轮静默降级**：第 1 轮报 P0，第 2 轮同 issue 报 P1 → severity 被覆盖 → 绕过 has_unfixed_blocking 闸

**检测**：`grep "severity" or "priority"`
**修法**：严格 P0/P1/P2/P3 白名单（其他 skip）+ 跨轮取较高 severity（不无条件覆盖）

---

## 元规则（来自 v2 19 轮自举的方法论）

- **黑名单防御 ≥3 轮还能挑新成员 → 升级白名单**（治本）
- **绕不过的攻击面写 spec "不在本次范围"**（治本，让下轮 antagonist 不再挑）
- **LLM 输出 JSON ~20% 概率有 invalid escape → parse 端必须容错**
- **找茬角度强制轮换**（边界 / 并发 / 异常 / 安全 / 性能 / 跨系统）防找茬疲劳
- **多家族 PASS 标准用 ≥(N-1) 共识**，不要全数共识（防完美主义死循环）
