#!/usr/bin/env bash
# Harness Engineering — 一行命令安装脚本
# 用法: curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/harness-engineering/main/install.sh | bash
# 本地测试: HARNESS_LOCAL_DEV=1 bash install.sh
set -euo pipefail

# ─────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────
GITHUB_REPO="YOUR_GITHUB_USERNAME/harness-engineering"
HARNESS_DIR="$HOME/.harness"
BIN_DIR="$HOME/.local/bin"
TOOLS="ruff mypy bandit detect-secrets radon pre-commit"

# ─────────────────────────────────────────────────────────
# 颜色（检测终端支持）
# ─────────────────────────────────────────────────────────
if [ -t 1 ] && [ "${TERM:-}" != "dumb" ] && [ "${NO_COLOR:-}" = "" ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    RED='' GREEN='' YELLOW='' CYAN='' BOLD='' RESET=''
fi

info()    { printf "${CYAN}%s${RESET}\n" "$*"; }
success() { printf "${GREEN}%s${RESET}\n" "$*"; }
warn()    { printf "${YELLOW}%s${RESET}\n" "$*"; }
error()   { printf "${RED}%s${RESET}\n" "$*" >&2; }
bold()    { printf "${BOLD}%s${RESET}\n" "$*"; }

# ─────────────────────────────────────────────────────────
# 失败时清理（trap）
# ─────────────────────────────────────────────────────────
INSTALL_STARTED=0

cleanup_on_failure() {
    if [ $INSTALL_STARTED -eq 1 ] && [ -d "$HARNESS_DIR" ]; then
        warn ""
        warn "⚠️  安装中途失败，正在清理 ~/.harness/ 避免留下半成品..."
        rm -rf "$HARNESS_DIR"
        warn "   已删除 ~/.harness/"
    fi
    error "❌ 安装失败，请查看上方错误信息。"
}

trap cleanup_on_failure ERR

# ─────────────────────────────────────────────────────────
# 第 1 步：横幅 + 优缺点对比
# ─────────────────────────────────────────────────────────
show_banner() {
    printf "\n"
    bold "╔════════════════════════════════════════════════════════╗"
    bold "║              Harness Engineering                       ║"
    bold "║  让 Claude Code 生成代码的准确率从 50% 提升到 80%+    ║"
    bold "╚════════════════════════════════════════════════════════╝"
    printf "\n"

    bold "═══ 你将得到 ═══"
    success "  ✅ 代码准确率 50% → 80%+（基于 367 项真实 bug 数据）"
    success "  ✅ 安全漏洞自动拦截（10 条铁律硬门禁）"
    success "  ✅ AI 先写规格再写代码，规格留存为文档"
    success "  ✅ AI 无法绕过质量检查（hook 物理拦截，不是 prompt 承诺）"
    printf "\n"

    bold "═══ 代价是什么 ═══"
    warn "  ⚠️  Token 消耗 2-3 倍（每个功能走 5 个阶段）"
    warn "  ⚠️  简单功能也要 5-10 分钟（适合生产代码，不适合 5 分钟原型）"
    warn "  ⚠️  目前只支持 Python / TypeScript / Vue"
    warn "  ⚠️  需要 Claude Code 环境（不支持 Cursor / Aider）"
    printf "\n"

    bold "═══ 安装内容 ═══"
    info "  📁 ~/.harness/             ← harness 核心（独立目录，好卸载）"
    info "  🔧 ~/.claude/settings.json ← 合并 hook 配置（自动备份原文件）"
    info "  📦 7 个质量工具            ← ruff / mypy / bandit / detect-secrets / radon / pre-commit / esbuild"
    info "  🔗 ~/.local/bin/harness    ← CLI 命令"
    printf "\n"
}

# ─────────────────────────────────────────────────────────
# 第 2 步：二次确认（3 秒自动继续）
# ─────────────────────────────────────────────────────────
confirm_install() {
    printf "${BOLD}按 Ctrl+C 取消，3 秒后自动继续...${RESET}\n\n"
    # read -t 不在所有 bash 3.2 版本可靠，用 sleep + trap
    # 允许用户提前按回车继续
    if read -r -t 3 -p "继续？[Y/n] " CONFIRM 2>/dev/null; then
        case "${CONFIRM:-Y}" in
            [nN]*) error "已取消安装。"; exit 0 ;;
        esac
    else
        printf "\n"
    fi
}

# ─────────────────────────────────────────────────────────
# 第 3 步：环境检测
# ─────────────────────────────────────────────────────────
PYTHON_BIN=""

check_claude_code() {
    info "[1/7] 检查 Claude Code..."
    if ! command -v claude >/dev/null 2>&1; then
        error "❌ 未检测到 Claude Code。"
        error "   请先安装：https://claude.ai/download"
        exit 1
    fi
    success "   ✅ Claude Code 已安装：$(claude --version 2>/dev/null | head -1 || echo '版本未知')"
}

check_python() {
    info "[2/7] 检查 Python 3.9+..."
    local found_bin=""
    local found_ver=""

    # 按优先级搜索，取最高版本
    for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            local ver
            ver=$("$candidate" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null || echo "0.0")
            local major minor
            major=${ver%%.*}
            minor=${ver##*.}
            if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
                found_bin="$candidate"
                found_ver="$ver"
                break
            fi
        fi
    done

    if [ -z "$found_bin" ]; then
        error "❌ 未找到 Python 3.9+。"
        error "   请安装：brew install python@3.11  （macOS）"
        error "            sudo apt install python3.11  （Ubuntu）"
        exit 1
    fi

    PYTHON_BIN="$found_bin"
    success "   ✅ Python ${found_ver}：${found_bin}"
}

check_git() {
    info "[3/7] 检查 git..."
    if ! command -v git >/dev/null 2>&1; then
        error "❌ 未找到 git。"
        error "   请安装：brew install git  或  sudo apt install git"
        exit 1
    fi
    success "   ✅ git 已安装：$(git --version)"
}

check_pip() {
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        error "❌ pip 不可用（Python: $PYTHON_BIN）。"
        error "   请安装：$PYTHON_BIN -m ensurepip --upgrade"
        exit 1
    fi
}

check_env() {
    check_claude_code
    check_python
    check_git
    check_pip
    printf "\n"
}

# ─────────────────────────────────────────────────────────
# 第 4 步：下载 harness
# ─────────────────────────────────────────────────────────
download_harness() {
    info "[4/7] 下载 / 更新 harness..."

    # 本地开发模式：用脚本所在目录作为 HARNESS_DIR
    if [ "${HARNESS_LOCAL_DEV:-}" = "1" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
        HARNESS_DIR="$SCRIPT_DIR"
        warn "   🛠️  本地开发模式，使用目录：$HARNESS_DIR"
        return 0
    fi

    INSTALL_STARTED=1

    if [ -d "$HARNESS_DIR/.git" ]; then
        info "   📁 ~/.harness/ 已存在，更新到最新..."
        cd "$HARNESS_DIR"
        if ! git pull --ff-only 2>&1; then
            warn "   ⚠️  git pull 失败，尝试 reset 到远程..."
            git fetch origin
            git reset --hard origin/main
        fi
        cd - >/dev/null
    else
        info "   📥 正在下载 harness..."
        git clone "https://github.com/$GITHUB_REPO.git" "$HARNESS_DIR"
    fi

    success "   ✅ harness 已就绪：$HARNESS_DIR"
    printf "\n"
}

# ─────────────────────────────────────────────────────────
# 第 5 步：pip install 质量工具
# ─────────────────────────────────────────────────────────
install_tools() {
    info "[5/7] 安装质量工具（ruff / mypy / bandit 等）..."

    # 检测是否需要 --break-system-packages（Ubuntu 23.04+）
    local extra_args=""
    if "$PYTHON_BIN" -m pip install --user --dry-run ruff >/dev/null 2>&1; then
        extra_args=""
    elif "$PYTHON_BIN" -m pip install --user --break-system-packages --dry-run ruff >/dev/null 2>&1; then
        extra_args="--break-system-packages"
        warn "   检测到 Ubuntu 系统 pip，自动添加 --break-system-packages"
    fi

    printf "   安装中 "
    "$PYTHON_BIN" -m pip install --user --quiet $extra_args $TOOLS \
        --progress-bar off 2>/dev/null &
    local pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        printf "."
        sleep 1
    done
    wait "$pid"
    printf " 完成\n"

    # 同样安装 esbuild（通过 npm，如果可用）
    if command -v npm >/dev/null 2>&1; then
        printf "   安装 esbuild..."
        npm install -g esbuild --quiet >/dev/null 2>&1 && printf " ✅\n" || warn " ⚠️  esbuild 安装失败（TypeScript 检查可能受影响）"
    else
        warn "   ⚠️  未找到 npm，跳过 esbuild（TypeScript 语法检查不可用）"
    fi

    success "   ✅ 质量工具安装完成"
    printf "\n"
}

# ─────────────────────────────────────────────────────────
# 第 6 步：调用 install_v2.py 合并 settings.json
# ─────────────────────────────────────────────────────────
apply_settings() {
    info "[6/7] 合并 Claude Code settings.json..."

    local installer="$HARNESS_DIR/hooks/install_v2.py"
    if [ ! -f "$installer" ]; then
        error "❌ 未找到 ${installer}，下载可能不完整。"
        exit 1
    fi

    # 记录备份位置（install_v2.py 内部会输出 backup 路径）
    local output
    if ! output=$("$PYTHON_BIN" "$installer" --apply 2>&1); then
        error "❌ settings.json 合并失败："
        error "$output"
        # 查找并恢复备份
        local backup
        backup=$(ls "$HOME/.claude/settings.json.backup."* 2>/dev/null | sort | tail -1 || echo "")
        if [ -n "$backup" ]; then
            warn "   正在从备份恢复：$backup"
            cp "$backup" "$HOME/.claude/settings.json"
            success "   ✅ settings.json 已恢复"
        fi
        exit 1
    fi

    printf "%s\n" "$output"
    success "   ✅ settings.json 合并完成"
    printf "\n"
}

# ─────────────────────────────────────────────────────────
# 第 7 步：创建 harness CLI 软链
# ─────────────────────────────────────────────────────────
create_cli() {
    info "[7/7] 创建 harness CLI..."

    mkdir -p "$BIN_DIR"

    # 写 wrapper 脚本（容错：harness_cli.py 不存在时友好提示）
    cat > "$BIN_DIR/harness" <<HARNESS_CLI
#!/bin/bash
# Harness CLI wrapper — 由 install.sh 生成
CLI="\$HOME/.harness/bin/harness_cli.py"
if [ ! -f "\$CLI" ]; then
    echo "⚠️  Harness CLI 尚未完整安装，请重新运行 install.sh"
    exit 1
fi
exec python3 "\$CLI" "\$@"
HARNESS_CLI
    chmod +x "$BIN_DIR/harness"

    # 检测 PATH
    if ! echo "$PATH" | grep -qF "$BIN_DIR"; then
        warn "   ⚠️  $BIN_DIR 不在 PATH，请将以下内容加入 ~/.zshrc 或 ~/.bashrc:"
        warn '       export PATH="$HOME/.local/bin:$PATH"'
        warn "   然后运行：source ~/.zshrc"
    fi

    success "   ✅ harness CLI 已创建：$BIN_DIR/harness"
    printf "\n"
}

# ─────────────────────────────────────────────────────────
# 完成提示
# ─────────────────────────────────────────────────────────
show_done() {
    printf "\n"
    success "✅ 安装完成！"
    printf "\n"

    bold "═══ 下一步 ═══"
    info "  1. cd 你的项目目录/"
    info "  2. harness init             # 初始化 harness（每个项目做一次）"
    info "  3. claude                   # 启动 Claude Code（必须普通模式，不带 --dangerously-skip-permissions）"
    info "  4. 告诉 Claude：'开发 XX 功能'"
    info "     → Claude 会自动走 5 个阶段：SPEC → DESIGN → IMPLEMENT → REVIEW → TEST"
    printf "\n"

    bold "═══ 卸载 ═══"
    info "  harness uninstall     # 或手动：rm -rf ~/.harness"
    printf "\n"

    bold "═══ 文档 ═══"
    info "  https://github.com/$GITHUB_REPO"
    info "  问题排查：harness doctor"
    printf "\n"
}

# ─────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────
main() {
    show_banner
    confirm_install
    check_env
    download_harness
    install_tools
    apply_settings
    create_cli
    show_done
}

main "$@"
