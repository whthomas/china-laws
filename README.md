# 中国法律法规语料库

从[国家法律法规数据库](https://flk.npc.gov.cn)（flk.npc.gov.cn）同步的全量中国法律法规文本，覆盖宪法、法律、行政法规、司法解释、地方性法规等的正文与元数据。

数据以按类型/省份组织的 Markdown 文档树维护，**每个法规一个文件**：元数据完整保留在文件头的 YAML frontmatter 中，正文在一级标题下原样写入，既适合直接阅读，也方便脚本批量处理。

## 快速开始

把数据库的最新更新同步到本地，按顺序执行（各脚本参数与注意事项详见 [script/README.md](script/README.md)）：

```bash
python3 script/fetch_new_list.py    # ① 抓取全量法规索引 → new_list.json
python3 script/fetch_new_laws.py    # ② 新法规正文直接写入 markdown/（支持断点续传）
python3 script/update_status.py     # ③ 刷新存量法规的时效性状态
python3 script/verify_all.py        # ④ 校验文档树（可选）
```

- 仅依赖 Python 标准库（≥ 3.8），无需安装第三方包；
- ② 可先用 `--dry-run` 查看待抓取量；大批量耗时较长且容易卡死时，用监督模式 `python3 script/supervise_crawl.py` 自动强杀重启；
- 脚本按自身所在位置定位数据文件，在任意工作目录下执行均可。

## 目录结构

```
china-laws/
├── markdown/              # 主数据：法规文档树，29,926 条
│   ├── 宪法/
│   ├── 法律/
│   ├── 行政法规/
│   ├── 司法解释/
│   ├── 地方性法规/         # 按省份拆分子目录
│   │   ├── 北京市/
│   │   ├── 上海市/
│   │   └── ...
│   └── ...
├── new_list.json          # 远端全量索引快照（流水线维护：判断新增、刷新状态的依据）
├── README.md
└── script/                # 更新流水线脚本（详细使用说明见 script/README.md）
    ├── md_tree.py          # 公共模块：frontmatter 解析/渲染、id 索引、命名与省份规则
    ├── fetch_new_list.py   # ① 抓取全量法规列表
    ├── fetch_new_laws.py   # ② 下载新增法规正文，直接写 md 文件
    ├── supervise_crawl.py  # 爬虫监督（可选）
    ├── update_status.py    # ③ 刷新时效性状态
    ├── verify_all.py       # ④ 全量校验
    └── README.md           # 使用说明
```

## 数据格式

每个法规一个 Markdown 文件，路径为 `markdown/<类型>/<文件名>.md`，地方性法规额外按省份拆分。文件名取法规标题（非法字符替换为下划线；重名追加发布年份，仍重名再追加 id 前缀）。统一 LF 换行。

元数据字段（YAML frontmatter，每文件一条记录，即本语料库的结构化数据格式）：

| 字段 | 说明 |
| --- | --- |
| `id` | `urlencode(base64(bbbs 的 ASCII 十六进制串))`，bbbs 为国家法律法规数据库的法规主键 |
| `title` | 法规标题（同时用作文件名） |
| `office` | 发布机关 |
| `publish` / `effective_date` | 发布 / 施行日期 |
| `type` | 类型（见下方分布） |
| `status` | 时效性：有效 / 已修改 / 已废止 / 尚未生效（决定类无时效性标记时为空） |
| `url` | 详情页链接 |
| `download_link_word` / `download_link_html` / `download_link_pdf` | 官方文档下载链接（部分条目为空） |

文件示例：

```markdown
---
id: "..."
title: "中华人民共和国居民身份证法"
office: "全国人民代表大会常务委员会"
publish: "2011-10-29 00:00:00"
effective_date: "2012-01-01 00:00:00"
type: "法律"
status: "有效"
url: "https://flk.npc.gov.cn/detail2.html?..."
download_link_word: "..."
download_link_html: ""
download_link_pdf: "..."
---

# 中华人民共和国居民身份证法

（正文……）
```

`new_list.json` 为远端索引快照，结构为 `{"total", "fetched", "rows": [...]}`，`rows` 内是新版 API 的原始行（`bbbs` 为法规主键，`zdjgCodeId` 用于地方性法规的省份归属）。

## 数据概况

`markdown/` 截至 2026-08-18 共 29,926 条，按类型分布：

| 类型 | 条数 |
| --- | --- |
| 地方性法规（31 个省份） | 25,515 |
| 修改、废止的决定 | 1,906 |
| 司法解释 | 851 |
| 行政法规 | 811 |
| 法律 | 488 |
| 有关法律问题和重大问题的决定 | 188 |
| 法规性决定 | 129 |
| 法律解释 | 27 |
| 宪法 | 7 |
| 监察法规 | 3 |
| 未分类 | 1 |

## 面向 Agent 的使用

这种"每法规一个 Markdown 文件 + YAML frontmatter"的组织形式天然适合 Agent（如 Claude Code, Codex, Cursor, Zcode 等编码/检索类 Agent）直接读取使用：

- **无需数据库与运行时**：纯文本文件树，Agent 用 `grep`/`glob` 等常规文件工具即可完成检索，标题即文件名，类型/省份即目录路径；
- **结构化元数据**：frontmatter 中时效性、发布机关、施行日期等字段可被精确过滤，避免引用已废止条文；
- **可精准定位**：单文件体量小，Agent 可整篇读入上下文，也可按行区间切片引用，配合 `id` 与官方 `url` 可回溯出处。

典型使用场景：

- **法律咨询与问答**：让 Agent 在库内检索相关法条后作答，回答附带文件名与官方链接作为引用来源；
- **合同审查**：审查合同条款时，由 Agent 比对《民法典》《劳动合同法》等现行有效条文，提示冲突与失效引用；
- **合规检查**：结合地方性法规目录（按省份划分），核查业务文本是否满足属地监管要求；
- **RAG 知识库**：直接将文档树作为检索增强语料，frontmatter 字段可用作过滤维度；
- **条文溯源与比对**：核对文书、论文中引用条文的时效性与原文表述。

## 说明

- 数据来源为国家法律法规数据库公开页面，仅供学习研究使用，请勿用于商业用途；正式引用以官方发布为准。

## 许可

本仓库的脚本与文档以 [MIT License](LICENSE) 开源。法规文本数据来自国家法律法规数据库，其使用遵循来源网站的公开使用条款，不在 MIT 许可范围内。
- 上游标题偶有漂移（如给失效决定追加“（失效）”后缀、修订笔误等），本地标题以实际文档为准，`verify_all.py` 对此仅告警、不自动同步。
- 抓取脚本内置限速与重试，请合理使用，避免对源站造成压力。
