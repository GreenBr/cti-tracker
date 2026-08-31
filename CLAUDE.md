# CTI Tracker — 项目上下文（给无上下文的 agent）

一个个人用的威胁情报追踪器：抓公开报告/新闻 → 用 `claude -p` 提取中国相关攻击事件 → SQLite → 三语静态网站。
- GitHub（**公开仓库**，注意：勿提交文章全文/cti.db）: https://github.com/GreenBr/cti-tracker
- 线上站：Vercel，由 Bo 的账号连接本仓库，push 即自动部署（域名见 Bo 的 Vercel 控制台，形如 cti-tracker-*.vercel.app）

## 当前状态（2026-08-31）

- **v1 + i18n Web UI + 静态导出 + 每日排程，全部完成并上线。** 测试 56 passed（pytest，全离线）。
- 数据：428 篇文章 / 60 篇候选全部提取完（0 失败）/ **10 起事件**（全部 `from_cn`）/ 54 个组织。
- 每日自动更新：Windows 计划任务 **"CTI Tracker Daily"**，每天 **09:00 (UTC+8)** 唤起 WSL 跑 `scripts/daily.sh`（fetch → extract → export → 有变化才 commit+push）。已实测端到端跑通（2026-08-31）。日志：`data/daily.log`（gitignored）。
  - 注册必须用 PowerShell（README 有配方）；`schtasks /TR` 会弄坏 wsl.exe 参数（返回 0 但不执行）。
  - 已设 StartWhenAvailable（错过补跑）+ 电池允许。
- 来源：23 个里 15 个可用（中文只有 安全客、360 Netlab）；不可用的在 `sources.yaml` 里 `enabled: false` 带 `note:`。
- 已知偶发：并发跑多个 claude 进程可能撞坏 `~/.claude/.config.json`（claude 会自动备份重建）；提取失败不自动重试，用 `cti extract --retry-failed` 手动补。

## 硬约束（改动前必读）

1. **禁用 Claude API/API key**——一切 LLM 调用走 `claude -p`（Bo 的订阅）。提取失败**不自动重试**。
2. **公开站不得含文章全文**（版权）——`create_app(public=True)` 与 `cti export` 已保证；改模板时别把 `article.text` 泄进公开页。页脚 MITRE 署名必须保留。
3. **i18n 零手搓**：Babel/gettext/starlette-babel/OpenCC。新增 UI 字符串流程：`cti i18n extract` → `update` → 填 zh_CN 译文 → 清掉 fuzzy（pybabel update 的 fuzzy 匹配会塞错译文！）→ `gen-hant`（保留已审 zh_TW）→ 人工审繁体用词 → `compile`。`tests/test_i18n.py` 会挡缺译/fuzzy/过期 .mo。
4. 参数化字符串用 Jinja `{% trans %}`，不要 `_("...", kw=...)`（那是 Flask-Babel 写法，会炸）。
5. locale 命名用 `zh_CN`/`zh_TW`（gettext 经典命名，浏览器 Accept-Language 才能精确命中）。

## 命令速查

```bash
.venv/bin/cti fetch | extract [--limit N] [--retry-failed] | export | serve | datasette | init
.venv/bin/cti i18n extract | update | compile | gen-hant
.venv/bin/pytest          # 56 tests，无网络、无真实 claude
scripts/daily.sh          # 排程跑的就是它
```

## 文档地图（勿新增重复文档）

- 本文件：现状 + 约束 + 入口
- `README.md`：安装、日常操作、i18n 工作流、Vercel 发布、排程注册配方
- `docs/superpowers/specs/2026-08-30-cti-tracker-design.md`：设计决策（数据模型、提取、i18n、导出）
- `docs/superpowers/plans/2026-08-30-cti-tracker-v1.md`：已完成的实施计划（历史）

## v2 待办（按价值排序）

1. **中文来源抓取器**：奇安信/微步/安天/CNCERT/CVERC/FreeBuf/绿盟 无可用 RSS，需网页抓取或 rss-bridge——补上才有 `to_cn` 方向数据（当前 10 起全是 `from_cn`）。
2. Google TI / CISA feed 修复（JS 渲染 / 403）。
3. 跨文章事件去重（同一事件多来源报道会重复入库）。
4. IOC（IP/域名/哈希）提取；历史回填；Twitter/Telegram。
