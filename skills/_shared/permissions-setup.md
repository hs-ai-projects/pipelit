# Pipelit 权限配置

## 缺少 Bash 权限时

用 AskUserQuestion 询问：

```
⚙️ Pipelit 首次使用

~/.claude/settings.json 缺少必要的 Bash 命令权限。
没有这些权限，skill 运行时会频繁弹出确认提示。

是否自动添加到全局配置？（一次配置，所有项目生效）
```

选项：
- 是，添加权限 + 通知 hook（推荐）
- 是，仅添加权限
- 否，我手动处理

**用户选"添加权限"时，执行：**

```bash
node -e "
const fs = require('fs');
const path = require('path');
const os = require('os');
const dir = path.join(os.homedir(), '.claude');
const file = path.join(dir, 'settings.json');
const newRules = ['Bash(*)', 'Edit', 'Write', 'Read'];
if (!fs.existsSync(dir)) fs.mkdirSync(dir);
const existing = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
existing.permissions = existing.permissions || {};
const current = existing.permissions.allow || [];
existing.permissions.allow = [...new Set([...current, ...newRules])];
fs.writeFileSync(file, JSON.stringify(existing, null, 2));
console.log('done');
"
```

提示：`✅ 权限已添加到 ~/.claude/settings.json`

---

## 缺少通知 hook 时（或用户选了"+ hook"）

用 AskUserQuestion 询问：

```
🔔 系统通知 hook（可选）

AI 等待你输入时，可以弹出系统通知，避免不知道 AI 在等你而卡住。
是否添加？
```

选项：
- 是，添加通知 hook
- 否，不需要

**用户选"是"时，执行：**

```bash
node -e "
const fs = require('fs');
const os = require('os');
const file = '.claude/settings.json';
const isWin = os.platform() === 'win32';
const cmd = isWin
  ? 'powershell.exe -NonInteractive -ExecutionPolicy Bypass -File \"scripts/notify.ps1\" 2>/dev/null; exit 0'
  : 'bash scripts/notify.sh 2>/dev/null; exit 0';
const existing = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
existing.hooks = existing.hooks || {};
existing.hooks.PreToolUse = existing.hooks.PreToolUse || [];
const alreadyHasHook = existing.hooks.PreToolUse.some(h => h.matcher === 'AskUserQuestion');
if (!alreadyHasHook) {
  existing.hooks.PreToolUse.push({
    matcher: 'AskUserQuestion',
    hooks: [{ type: 'command', command: cmd }]
  });
}
fs.writeFileSync(file, JSON.stringify(existing, null, 2));
console.log('done');
"
```

提示：`✅ 通知 hook 已添加`
