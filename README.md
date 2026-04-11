# Claude Rails 🚂

> **Rails for Claude Code — put your AI pair-programmer on a track**
> Turn Claude Code's code accuracy from ~50% to 80%+
> Built for non-technical PMs and developers who care about quality

**Language**: **English** · [简体中文](README.zh-CN.md)

<sub>📦 Project brand: **Claude Rails** · Core engine & CLI: **harness** (same pattern as Ruby on Rails' `rails` gem — brand name and CLI name don't have to match)</sub>

[![CI](https://github.com/penguinliao/claude-rails/actions/workflows/test.yml/badge.svg)](https://github.com/penguinliao/claude-rails/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-required-orange.svg)](https://claude.ai/download)

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/penguinliao/claude-rails/main/install.sh | bash
```

Ready in 2 minutes. **Read the "benefits vs costs" table below before you install.**

---

## Who this is for

✅ **You'll love it if you**:
- Use Claude Code on **production projects** (not 5-minute prototypes)
- Are tired of Claude's "looks fixed but actually isn't" loop
- Want AI to write a spec before touching code
- Are a PM / product manager / non-technical developer but care about code quality

❌ **Don't install this if you**:
- Only write 5-minute toy projects (the pipeline overhead will drive you crazy)
- Use Cursor / Aider / Continue (Claude Code only, for now)
- Write Ruby / Go / Rust (Python / TypeScript / Vue only, for now)
- Are token-cost sensitive (we will 2–3x your token usage)

---

## Benefits vs Costs (the core tradeoff)

| Dimension | Without Claude Rails | With Claude Rails |
|---|---|---|
| **Code accuracy** | ~50% (Anthropic internal data) | **~80%+** (based on 367 real bugs) |
| **Security vulnerabilities** | AI may write SQL injection, hardcoded secrets | **Physical blocks on 10 golden rules** |
| **Spec documentation** | Usually missing, AI forgets after writing | **Every feature leaves a spec.md** |
| **AI promises vs reality** | "I fixed it" without actually fixing | **Hooks run real tools — we don't trust AI's word** |
| **Token consumption** | 1x baseline | **2–3x** (5-stage pipeline + multiple tool calls) |
| **Time per feature** | 3–5 minutes | **5–15 minutes** (quality vs speed tradeoff) |
| **Cognitive load on PM** | Review every change | **PM only at start and end** |

---

## Three steps to start

```bash
# 1. Install (once, 2 minutes)
curl -fsSL https://raw.githubusercontent.com/penguinliao/claude-rails/main/install.sh | bash

# 2. Enable in any project
cd your-project/
harness init

# 3. Use Claude Code normally
claude
```

Then tell Claude: **"build feature X"** — Claude Rails will make it walk through 5 stages:
`SPEC → DESIGN → IMPLEMENT → REVIEW → TEST`

Every stage has a physical gate. Can't advance without passing. You don't need to understand the stages — you only need to:
- **At the start**: tell Claude what to build
- **At the end**: look at the "all passed" report and verify

---

## How it works (you don't need to understand — but you can expand)

<details>
<summary><b>The 5-stage pipeline</b> — force AI to work in steps</summary>

| Stage | What AI does | Gate condition |
|---|---|---|
| 1. SPEC | Write down what to build (no code) | spec.md matches expected format |
| 2. DESIGN | Decide how (architecture / interfaces / affected files) | Review passes |
| 3. IMPLEMENT | Actually write code | ruff + mypy + bandit + 8-dim scoring all green |
| 4. REVIEW | Independent AI review (cognitive isolation) | Review passes |
| 5. TEST | Run tests + user acceptance | Tests pass |

This is a **hard constraint**: AI cannot skip stages or bypass them. Try to write code directly and the hook will block you.

</details>

<details>
<summary><b>7 quality tools</b> — all auto-installed</summary>

| Tool | Purpose |
|---|---|
| [ruff](https://github.com/astral-sh/ruff) | Python lint + autofix |
| [mypy](https://mypy-lang.org/) | Python type checking |
| [bandit](https://bandit.readthedocs.io/) | Python security vulnerability scanning |
| [detect-secrets](https://github.com/Yelp/detect-secrets) | Hardcoded secret detection |
| [radon](https://radon.readthedocs.io/) | Code complexity analysis |
| [pre-commit](https://pre-commit.com/) | Pre-commit hooks runner |
| [esbuild](https://esbuild.github.io/) | TypeScript / JavaScript syntax check |

The install script handles everything. **You don't configure anything.**

</details>

<details>
<summary><b>8-dimension scoring</b> — gradient feedback, not binary PASS/FAIL</summary>

Weights derived from analyzing 367 real bugs across production projects:

| Dimension | Weight | Why this weight |
|---|---|---|
| Functional correctness | 33% | 117/367 bugs were logic errors — the most common |
| Spec compliance | 18% | 37 bugs were "built the wrong thing" |
| Type safety | 14% | Type errors cause subtle runtime bugs |
| Security | 12% | Low frequency but catastrophic impact |
| Complexity | 8% | Predicts future maintenance cost |
| Architecture | 5% | Prevents codebase decay |
| Secret safety | 5% | **Zero tolerance**: any leak = BLOCKED |
| Code quality | 5% | Readability |

**Hard gates** (any trigger = BLOCKED, regardless of total score):
- Secret leak detected
- Functional < 60 (code doesn't even run)
- Security < 50 (dangerous vulnerabilities)

</details>

---

## Why we can claim "50% → 80%"

This isn't marketing fluff. Claude Rails follows three principles:

1. **Environment > Model**
   From Mitchell Hashimoto's 2026 "Harness Engineering" concept — don't chase a stronger AI, chase a better verification environment.

2. **Physical constraints > promises**
   We don't believe AI when it says "I fixed it". Hooks run real tools to verify. AI cannot bypass — try to write code? No active pipeline → blocked. Pipeline not in IMPLEMENT stage → blocked.

3. **Spec-first** (Self-Spec, ICLR 2026)
   Making AI write a spec before coding improves pass rate by 2–5%. Claude Rails turns this into a mandatory flow.

### This project uses itself to develop itself
From v0.1, every code change in this repo walks through its own 5-stage pipeline. **If it can't reliably constrain itself, what makes you think it can constrain your project?**

---

## FAQ

**Q: Will it modify my existing Claude Code settings?**
A: Yes, but with **auto-backup** to `~/.claude/settings.json.backup.<timestamp>`. The merge is smart — all your existing hooks and permission rules are preserved.

**Q: Can I uninstall cleanly?**
A: One command: `harness uninstall`. Deletes `~/.harness/`, restores the settings.json backup. No residue.

**Q: 2–3x token cost? I can't afford that.**
A: True, that's the cost. Claude Rails fits **quality-matters-more-than-cost** scenarios (production code, paid client projects, open-source releases). If you're writing weekend toys, **don't install it** — use vanilla Claude Code.

**Q: Does it support Cursor / Aider / Continue?**
A: No. Claude Rails depends on Claude Code's hook system.

**Q: Does it support Java / Go / Rust?**
A: Not yet. Only Python / TypeScript / Vue have full physical constraints.

**Q: What's the code quality of Claude Rails itself?**
A: From v0.1, every change is constrained by its own pipeline. We don't do "the cobbler's children have no shoes".

---

## Troubleshooting

```bash
harness doctor          # Check environment
harness status          # Show current project's pipeline stage
cat ~/.harness/.harness/hook.log   # View hook logs
```

More docs: [docs/](docs/)

---

## Uninstall

```bash
harness uninstall
```

Or manually:
```bash
rm -rf ~/.harness/
# Restore the most recent settings.json backup
cp ~/.claude/settings.json.backup.<latest-timestamp> ~/.claude/settings.json
```

---

## For developers

Want to contribute to Claude Rails itself?

```bash
git clone https://github.com/penguinliao/claude-rails
cd claude-rails
pip install -e .
```

Deep-dive documentation:
- [Architecture](docs/architecture.md)
- [Reward functions](docs/reward-functions.md)
- [Spec-first workflow](docs/spec-first-workflow.md)
- [Single-focus principle](docs/single-focus-principle.md)
- [RL environment design](docs/rl-environment.md)

---

## Research basis

Claude Rails isn't based on gut feeling. Every core decision has evidence:

- **Harness Engineering** (Mitchell Hashimoto, 2026) — environment > model
- **Self-Spec** (ICLR 2026) — spec-first improves pass rate by 2–5%
- **Ralph Loop** (2026) — execution feedback loop reduces hotfixes by 40%
- **FunPRM** (2026) — process reward > outcome reward
- **Static Analysis as Feedback** (arXiv:2508.14419) — security issues dropped from 40% to 13%

---

## License

[MIT](LICENSE) — free to use, modify, and sell. Only requirement: keep the copyright notice.

---

## Acknowledgments

Inspired by Anthropic's Claude Code hook design, Mitchell Hashimoto's harness engineering concept, and every developer who has been bitten by AI writing code that "looks right but isn't".
