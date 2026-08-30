# CTI Tracker 设计文档 / Design Spec

日期 / Date: 2026-08-30
状态 / Status: v1 设计已由 Bo 逐段确认 (approved section by section)
修订 / Revision: 2026-08-30 新增 §13 多语言 Web 展示层(Bo 确认);§8 的 Datasette 降级为原始数据浏览备用

## 1. 目标 / Goal

一个个人用的威胁情报追踪工具,持续收集公开报告和新闻,提取出与中华人民共和国相关的网络攻击活动,存成结构化数据,在本地 Web 仪表盘上浏览。

A personal threat-intel tracker that continuously collects public reports and news, extracts PRC-related cyber attack activity into structured data, and presents it on a local web dashboard.

### 1.1 覆盖方向 / Direction (both)

- `from_cn`: 被归因于中国的攻击组织(APT41、Volt Typhoon、Salt Typhoon 等)对外发起的攻击
- `to_cn`: 以中国境内机构/企业/基础设施为目标的攻击,无论攻击者来自哪里
- `unclear`: 提取时无法判断

### 1.2 用途 / Purpose

安全研究与分析,个人使用。不是防御告警系统,不做 SIEM 对接。

### 1.3 v1 要回答的四个核心问题 / Four core questions

1. 组织档案: "某组织最近做了什么?用了哪些 TTP?打了哪些行业?"
2. 事件时间线: "某时间段内中国相关的重大攻击事件有哪些?"(可按方向/受害国/行业/组织筛选)
3. 趋势统计: "哪些行业被打得最多?哪些 TTP 在上升?"
4. 每日新增: "今天有什么新报告/新事件?"

### 1.4 v1 验收标准 / Acceptance

跑完 `cti init && cti fetch && cti extract && cti serve` 后,浏览器里能:
- 看到组织列表和单个组织的档案查询结果
- 看到事件列表,并按 `direction` 等字段筛选
- 看到趋势页面上的图表(即使数据很少)
- 全文搜索文章并命中
- 从事件行点回原文

"能看到数据"即算成功;页面美观不在 v1 范围。

## 2. 约束 / Constraints

- **不使用 Claude API / API key。** 所有 LLM 调用通过 `claude -p`(Claude Code CLI 非交互模式),走 Bo 的 Claude 订阅登录。
- 提取失败**不自动重试**(订阅有用量上限,自动重试可能烧光额度)。手动 `cti extract --retry-failed` 重跑。
- 真实调用 Claude 的冒烟测试每个阶段最多一次,失败即停止报告。
- 单元测试不得依赖网络或真实 Claude。
- 从现在开始抓取,不回填历史。
- 中英双语来源。
- 优先现成工具,不自研展示层。

## 3. 架构 / Architecture

方案 A: Python 抓取管线 + SQLite + Datasette 仪表盘。

```
sources.yaml ──► cti fetch ──► articles (SQLite) ──► cti extract ──► actors / incidents / incident_ttps / article_actors
                 (feedparser                          (claude -p, JSON schema)
                  + trafilatura
                  + 关键词粗筛)
                                        cti serve ──► Datasette (metadata.yaml: canned queries, facets, dashboards)
```

三个独立命令,可单独跑也可串起来。展示层完全由 Datasette + 插件承担,不写前端代码。

备选方案及升级路径(已评估,v1 不采用):
- B: 同管线 + 自写 FastAPI/HTMX 仪表盘 —— 页面可控但 v1 代码量大;将来替换展示层即可,管线不变。
- C: 部署 OpenCTI —— 功能完整但 Docker 六七个容器、8–16 GB 内存,对个人研究过重;数据模型对齐 STIX 概念,将来可导出导入。

## 4. 数据模型 / Data model

单个 SQLite 文件 `data/cti.db`。

| 表 | 作用 | 字段 |
|---|---|---|
| `sources` | 来源清单(从 sources.yaml 同步) | `id` PK, `name`, `url` UNIQUE (RSS/Atom), `lang` (zh/en), `type` (vendor_report / news / gov_advisory), `enabled` (0/1) |
| `articles` | 原始文章 | `id` PK, `source_id` FK, `url` UNIQUE, `title`, `published_at`, `fetched_at`, `lang`, `text`, `relevance` (pending / candidate / skip), `extract_status` (pending / done / failed), `extract_error` (nullable), `extracted_at` (nullable) |
| `actors` | 攻击组织档案 | `id` PK, `canonical_name` UNIQUE, `aliases` (JSON 数组), `attributed_country` (nullable), `mitre_id` (nullable, 如 G0096), `description` (nullable) |
| `incidents` | 一次攻击事件 | `id` PK, `title`, `summary`, `occurred_at` (nullable, 允许只到月份,如 `2026-08`), `reported_at` (取文章 `published_at`), `direction` (from_cn / to_cn / unclear), `actor_id` FK nullable, `victim_country` (ISO 3166-1 alpha-2, nullable), `victim_sector` (自由文本,提取时要求用小写英文短语), `confidence` (high / medium / low), `article_id` FK, `created_at` |
| `incident_ttps` | 事件使用的 MITRE 技术 | `incident_id` FK, `technique_id` (如 T1566.001), `technique_name`; PK (incident_id, technique_id) |
| `article_actors` | 文章提到的组织 | `article_id` FK, `actor_id` FK; PK (article_id, actor_id) |

补充:
- `articles.text` 建 FTS5 虚拟表 `articles_fts`(title + text),供 Datasette 搜索。
- 一篇文章可产生 0..N 个事件。
- 每个事件必须带 `article_id`,仪表盘可回链原文。
- 组织去重靠 `aliases`:提取出的名字先在 canonical_name 与 aliases 中做不区分大小写匹配,命中挂旧 ID,否则新建。
- 初始组织与别名从 MITRE ATT&CK Enterprise STIX 数据导入(筛选描述/别名中归因于中国的 intrusion-set,约 40 个),由 `cti init` 生成 `data/mitre_china_actors.json` 并写入 `actors` 表。

## 5. 来源 / Sources

配置文件 `sources.yaml`,每条: `name`, `url`, `lang`, `type`, `enabled`。RSS 地址在实施时逐个验证;无 RSS 的站点用 rss-bridge 或页面抓取兜底,验证不通过的先 `enabled: false` 并注明原因。

英文 — 厂商报告 / 政府通告: Google Threat Intelligence (Mandiant), Microsoft Security Blog, CrowdStrike Blog, Palo Alto Unit 42, Recorded Future Insikt Group, CISA Cybersecurity Advisories, ESET WeLiveSecurity, Trend Micro Research, Check Point Research, SentinelOne Labs

英文 — 新闻: The Record, BleepingComputer, The Hacker News, Krebs on Security

中文 — 厂商报告: 奇安信威胁情报中心, 微步在线, 安天, 360 威胁情报中心, 绿盟科技

中文 — 新闻 / 社区 / 官方: 安全客, FreeBuf, CNCERT 通告, CVERC(国家计算机病毒应急处理中心)

v1 不做: Twitter/X、Telegram(无免费稳定抓取途径)。

## 6. 粗筛规则 / Pre-filter

`cti fetch` 抓到文章后立即打标:
- 关键词集合 = MITRE 导入的中国系组织全部别名 ∪ Microsoft `*Typhoon` 命名 ∪ 地域词 {China, Chinese, PRC, Beijing, 中国, 我国, 境外, 境外黑客, 美国国家安全局, NSA, CIA}
- 标题或正文命中任一(不区分大小写)→ `relevance = candidate`,否则 `skip`
- 宁可多送不可漏送;Claude 判断无关时返回 `relevant: false`,事件列表为空。
- 关键词集合可通过 `keywords.yaml` 增删,不改代码。

## 7. 提取流程 / Extraction

`cti extract [--batch N] [--retry-failed] [--limit M]`:

1. 选取 `relevance = candidate AND extract_status = pending`(`--retry-failed` 时改为 `failed`)的文章,按 `published_at` 升序,每批 N 篇(默认 5),最多 M 篇(默认 20)。
2. 每篇正文截断到 12,000 字符。
3. 拼 prompt = `prompts/extract.md`(系统指令)+ 已知组织 canonical_name/aliases 列表 + 文章元数据与正文。每篇文章单独调用一次(而不是多篇合并),便于失败隔离。
4. 调用 `claude -p --model sonnet --output-format json --json-schema schema/extract.json`,通过 stdin 传 prompt,超时 180 秒。
5. 解析输出,用 `jsonschema` 二次校验。输出结构:

```json
{
  "relevant": true,
  "actors_mentioned": [{"name": "APT41", "aliases_in_text": ["Brass Typhoon"]}],
  "incidents": [
    {
      "title": "...",
      "summary": "...",
      "occurred_at": "2026-08",
      "direction": "from_cn",
      "actor": "APT41",
      "victim_country": "TW",
      "victim_sector": "semiconductor",
      "confidence": "high",
      "ttps": [{"id": "T1566.001", "name": "Spearphishing Attachment"}]
    }
  ]
}
```

6. 写库:单事务内 —— 组织别名解析/新建 → 写 incidents → 写 incident_ttps → 写 article_actors → 文章 `extract_status = done`, `extracted_at = now`。
7. 失败(claude 非零退出 / 超时 / JSON 不合法 / schema 校验不过)→ 文章 `extract_status = failed`, `extract_error` 记录摘要;**不重试**,继续下一篇。
8. 每篇之间 sleep 3 秒。
9. 命令结束打印统计: 处理 / 成功 / 失败 / 新增事件数 / 新增组织数。

用量预估: 每天候选 5–15 篇,每篇约 15k 输入 tokens。建议每天手动跑 1–2 次。

prompt 文件 `prompts/extract.md` 可直接编辑;`tests/fixtures/` 附 3–5 篇样本文章(含一篇无关、一篇中文报告、一篇多事件报告)及对应期望输出,用于回归。

## 8. Datasette 原始数据浏览(备用) / Datasette raw-data view (fallback)

> 修订:主展示层改为 §13 的自建 Web UI。Datasette 保留为 `cti datasette [--port 8002]`,用于原始表浏览与 SQL 查询;以下配置照旧。

`cti datasette [--port 8002]` 启动 Datasette 挂载 `data/cti.db`,读取 `metadata.yaml`。

- 组织档案: `actors` 表页 + canned query `actor_profile(:actor)`—— 返回该组织事件列表、TTP 频次、受害行业分布(三个 query)。
- 事件时间线: `incidents` 表默认 `reported_at desc`,facets: `direction`, `victim_country`, `victim_sector`, `actor_id`(通过 label_column 显示组织名), `confidence`。
- 趋势统计: `datasette-dashboards` 一页四图 —— 按月事件数、方向占比、受害行业 Top 10、TTP Top 10。
- 每日新增: canned query `new_today` —— 今日 `created_at` 的事件 + 今日 `fetched_at` 的候选文章。
- 全文搜索: `articles` 表启用 FTS(`fts_table: articles_fts`)。
- 事件行 `article_id` 通过外键自动链接到 `articles` 行。

## 9. 目录结构 / Layout

```
~/repos/cti-tracker/
├── pyproject.toml            # 依赖: feedparser, trafilatura, datasette, datasette-dashboards, pyyaml, click, jsonschema, requests
├── sources.yaml
├── keywords.yaml
├── prompts/extract.md
├── schema/extract.json
├── metadata.yaml             # Datasette 配置
├── data/                     # gitignore: cti.db;  提交: mitre_china_actors.json(init 生成后提交,便于离线测试)
├── cti/
│   ├── __init__.py
│   ├── cli.py                # click: init / fetch / extract / serve
│   ├── db.py                 # 建表、写入、别名查找
│   ├── fetch.py              # RSS + 正文 + 粗筛
│   ├── extract.py            # prompt 拼装、claude -p 调用、校验、写库
│   └── mitre.py              # 拉 ATT&CK STIX,筛中国系组织
├── tests/
│   ├── fixtures/
│   ├── test_db.py
│   ├── test_fetch.py
│   ├── test_extract.py       # mock claude 子进程
│   └── test_mitre.py         # 用本地缩减版 STIX fixture
└── docs/superpowers/{specs,plans}/
```

## 10. 错误处理 / Error handling

- fetch: 单个来源失败(网络/解析)记录日志并跳过,不影响其他来源;正文抽取失败则存 RSS 摘要作为 `text`。
- extract: 见第 7 节;所有失败原因写入 `extract_error`,可在 Datasette 里筛 `extract_status = failed` 查看。
- init: MITRE 下载失败则报错退出,并提示可用本地缓存文件 `--mitre-file`。
- 所有命令幂等:重复 fetch 靠 `url UNIQUE` 去重,重复 init 不重复插入组织。

## 11. 测试策略 / Testing

- pytest 单元测试,无网络、无真实 Claude:
  - `test_fetch`: 本地 RSS fixture 解析、去重、粗筛打标
  - `test_db`: 建表、别名匹配(大小写、别名命中、未命中新建)、事务回滚
  - `test_extract`: mock `subprocess.run` 返回 fixture JSON;测 prompt 包含别名表、schema 校验失败标 failed、成功写库计数
  - `test_mitre`: 缩减版 STIX fixture 筛出中国系组织
- 两次真实冒烟(各最多一次,失败即停):
  1. 实施开始: `echo "reply with {\"ok\":true}" | claude -p --output-format json` 确认订阅登录可用
  2. 实施结束: 3 篇真实文章跑 `fetch → extract → serve`,人工检查仪表盘

## 12. v1 不做 / Out of scope

- 定时自动运行(v2: cron)
- Twitter/X、Telegram
- 历史回填
- IOC(IP/域名/哈希)提取
- 多用户 / 认证
- 提取内容(title/summary)的翻译;Datasette 自身界面的翻译

## 13. 多语言 Web 展示层 / i18n web UI (2026-08-30 增补)

### 13.1 要求 / Requirements
- 主语言英文;界面可在浏览器内切换 `en` / `zh_Hans` / `zh_Hant`。
- i18n 必须使用主流、专业的现成工具链,**禁止手搓任何 i18n 组件**(目录格式、解析、协商、转换均用现成库)。
- 只翻译界面字符串;提取出的 incident title/summary 保持英文。
- 繁体目录由 OpenCC 从简体目录自动生成后人工审校,两份目录独立维护。

### 13.2 技术选型 / Stack
| 需求 | 工具 |
|---|---|
| Web 框架 | FastAPI + Uvicorn |
| 模板 | Jinja2 + `jinja2.ext.i18n` |
| 目录与工作流 | GNU gettext + Babel (`pybabel extract/init/update/compile`),`babel.cfg` 声明 python + jinja2 提取器 |
| 语言协商 | `babel.negotiate_locale`;优先级 `?lang=` → cookie(`lang`,30 天)→ `Accept-Language` |
| 日期格式 | `babel.dates.format_date` |
| 简→繁 | OpenCC(`s2twp`),通过 `babel.messages.pofile` 读写 `.po`,只转换 `msgstr` |
| 图表 | Chart.js(vendored 到 `cti/web/static/vendor/`),标签由服务端翻译后注入 |

### 13.3 页面 / Pages
| 路径 | 内容 |
|---|---|
| `/` | 今日新增(事件 + 候选文章)+ 统计数字(文章/候选/事件/组织) |
| `/actors` | 组织列表(名称、别名、MITRE ID、事件数) |
| `/actors/{id}` | 档案:别名、描述、事件列表、TTP 频次、受害行业分布 |
| `/incidents` | 时间线;筛选 `direction` / `victim_country` / `victim_sector` / `actor` / `q`(FTS 关键词);按 `reported_at` 倒序,分页 50 |
| `/trends` | 四图:按月事件数、方向占比、受害行业 Top 10、TTP Top 10 |
| `/articles/{id}` | 原文正文、来源、外链、从该文提取的事件 |

枚举显示名(`direction`、`confidence`、`relevance`、`extract_status`、`source.type`)经 gettext 翻译;存库值不变。

### 13.4 命令 / Commands
- `cti serve [--port 8001]`:启动 FastAPI UI(uvicorn)。
- `cti datasette [--port 8002]`:原 Datasette。
- `cti i18n extract | update | compile | gen-hant`:分别包装 `pybabel extract`、`pybabel update`、`pybabel compile`、OpenCC 生成 `zh_Hant`。

### 13.5 文件 / Layout
```
babel.cfg
cti/web/app.py            # FastAPI 应用、路由、locale 依赖
cti/web/i18n.py           # 加载 Translations、协商、enum 标签
cti/web/queries.py        # 各页面 SQL
cti/web/templates/        # base.html + index/actors/actor/incidents/trends/article
cti/web/static/           # style.css, vendor/chart.umd.js
cti/translations/messages.pot
cti/translations/{zh_Hans,zh_Hant}/LC_MESSAGES/messages.{po,mo}
scripts/gen_zh_hant.py
tests/test_web.py, tests/test_i18n.py
```
`.mo` 一并提交,保证 clone 后 `cti serve` 直接可用。

### 13.6 测试 / Testing
- `fastapi.testclient`:每页在三种语言下 200 且含该语言的页面标题;`?lang=zh_Hant` 设置 cookie 后后续请求生效;`/incidents?direction=to_cn` 只含该方向;`Accept-Language: zh-TW` 协商到 `zh_Hant`。
- 目录完整性(机械化检查,缺译即失败):用 `babel.messages.pofile` 读取,断言 `zh_Hans`、`zh_Hant` 无空 `msgstr`、无 fuzzy,且 msgid 集合与 `messages.pot` 一致。
