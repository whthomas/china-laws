# 法律条款更新脚本使用说明

本目录存放法律条款更新流水线的全部脚本，用于把[国家法律法规数据库](https://flk.npc.gov.cn)（flk.npc.gov.cn）的更新同步到本地。

## 设计：markdown/ 文档树是唯一数据源

每条法规的全部元数据都以 YAML frontmatter 保存在对应的 Markdown 文件里，更新流水线直接读写文档树：

- 新法规抓取成功后立即落盘为一个 md 文件，格式与存量文件完全一致；
- 时效性状态变化通过原地改写 frontmatter 的 `status` 行同步；
- 断点续传以文件为单位：某条法规抓取成功 = 文档树中存在对应 md 文件，重跑自动跳过；
- 唯一的辅助状态文件是 `new_list.json`（约 12MB）：远端全量索引快照，用于判断"哪些是新增法规"和刷新时效性状态，不存正文。

### 公共模块 md_tree.py

frontmatter 解析/渲染、id ↔ bbbs 转换、文件命名与省份归属规则、文档树 id 索引扫描等公共逻辑都集中在这里，各脚本 `import md_tree` 复用，保证新增文件与存量树格式逐字节一致。

## 前置条件

- Python ≥ 3.8（仅依赖标准库，无需安装第三方包）
- 可访问 `flk.npc.gov.cn` 的网络环境

脚本通过自身所在位置定位仓库根目录（`script/` 的上一级），**在任意工作目录下执行均可**；下文命令以仓库根目录为执行目录示例。

## 流水线总览

| 顺序 | 脚本 | 输入 | 输出 | 耗时 |
| --- | --- | --- | --- | --- |
| ① | `fetch_new_list.py` | 远端列表 API | `new_list.json` | 数分钟 |
| ② | `fetch_new_laws.py` | `new_list.json` + `markdown/` | 新法规 md 文件直接写入 `markdown/` | 视新增量而定，大批量可达数小时 |
| ③ | `update_status.py` | `new_list.json` + `markdown/` | 原地刷新存量 md 的 status | 1–2 分钟 |
| ④ | `verify_all.py`（可选） | `new_list.json` + `markdown/` | 校验报告 | 1–2 分钟 |

`supervise_crawl.py` 是 ② 的监督包装，可选，适合无人值守场景。

## 快速开始

```bash
python3 script/fetch_new_list.py           # ① 抓取全量列表
python3 script/fetch_new_laws.py --dry-run # ② 先看待抓取量（不下载）
python3 script/fetch_new_laws.py           # ② 实际抓取，直接写入 markdown/
python3 script/update_status.py            # ③ 刷新存量法规时效性状态
python3 script/verify_all.py               # ④ 最终校验（可选）
```

② 耗时过长或经常卡死时，改用监督模式：

```bash
python3 script/supervise_crawl.py
```

## 各脚本详细说明

### ① fetch_new_list.py — 抓取全量法规列表

```bash
python3 script/fetch_new_list.py
```

- 调用 `flk.npc.gov.cn` 的列表 API 分页抓取全量法规索引：每页 500 条，页间限速 0.6s，单页失败自动重试 5 次（退避递增）；
- 按 `bbbs`（法规主键）去重后写入 `new_list.json`（结构为 `{"total", "fetched", "rows": [...]}`）；
- 输出只含元数据，**不含正文**。

### ② fetch_new_laws.py — 下载新增法规正文，直接写入文档树

```bash
python3 script/fetch_new_laws.py [--dry-run]
```

对比 `new_list.json` 与文档树的 id 索引找出新增法规，逐条下载正文并立即写为一个 md 文件：

- **主路线**：`download/pc` 接口换取带签名的 OSS 地址下载 docx，纯标准库解析 `word/document.xml` 提取段落（含表格）；
- **兜底路线**：`flfgDetails` → `previewLink` → flkofd reader 按页提取 OFD 文本；
- 内置网宿 WAF 的 302/JS 质询处理（线程本地 cookie + 重定向路径重放）；2 线程并发，每条随机延时 0.6–1.2s，socket 60s 超时，单条最多重试 4 次；
- 写入采用临时文件 + 原子替换，目录/命名/frontmatter 格式与存量树完全一致（规则见 `md_tree.py`）；
- **断点续传**：已存在于文档树的条目自动跳过，中断后直接重跑；
- `--dry-run` 只统计并展示待抓取条目，不发起下载；
- 存在失败条目时结束时列出明细并以非 0 退出，重跑会自动重试失败项。

### supervise_crawl.py — 爬虫监督（可选，配合 ②）

```bash
python3 script/supervise_crawl.py [target]
```

包裹 `fetch_new_laws.py` 运行：若 10 分钟无新的成功条目则 SIGKILL 强杀，冷却 30s 后重启，直至达到目标条数。

- `target` 为可选的目标条数；缺省时自动取当前待抓取条数（`new_list.json` 中不在文档树里的条数，启动时计算一次）；
- 进度即文档树中的文件数，爬虫被强杀不丢数据；
- 连续 3 轮重启无任何新进展则停止监督并报错，避免对永久性失败无限循环。

### ③ update_status.py — 刷新时效性状态

```bash
python3 script/update_status.py
```

用 `new_list.json` 的最新状态刷新文档树中存量法规的时效性（有效/已修改/已废止/尚未生效；新库无时效性标记的决定类条目置空）：

- 原地更新 frontmatter 的 `status` 行，正文与其余字段原样回写——除该行外与原文件逐字节一致（`verify_all.py` 的回环校验可证实）；
- 同时报告"新库有而本地缺失"的条数（提示运行 ② 补抓）；
- `id` 无法解码/解析失败的文件才判非 0 退出。

### ④ verify_all.py — 一致性校验（可选）

```bash
python3 script/verify_all.py
```

对文档树做全量校验：

- **树自洽**：frontmatter 完整可解析、字段齐全、id 唯一且可解码、重新渲染与原文逐字节一致（防格式漂移）、正文非空；
- **与 `new_list.json` 交叉核对**：status 不一致判失败（③ 可修复）；title 不一致仅告警——上游标题本身存在漂移（如给失效决定追加“（失效）”后缀、修订笔误等），本地标题以实际文档为准，不自动同步；
- 新库有而树中缺失的条目计数并给出示例（告警不判失败，抓取失败/待抓取属正常状态）；
- 全部通过打印 `全部通过 ✓` 并以 0 退出。

## 常见问题

- **② 中断了要重来吗？** 不用。已写成功的文件都在树里，直接重跑只处理缺失项。
- **② 长时间卡住不动？** 改用 `python3 script/supervise_crawl.py` 监督模式，卡死会自动强杀重启。
- **误删了几个 md 文件？** 重跑 ②（该条不在树中即视为待抓取，会自动补抓），随后跑一遍 ③④。
- **status 与官网不一致？** 跑 ① 刷新索引，再跑 ③。
- **想要 JSON 格式的全量数据？** frontmatter 就是结构化元数据（每文件一条记录）；如需单一 JSON，可自行遍历 `markdown/` 用 `md_tree.parse` 聚合导出。

## 注意事项

- 数据来源为国家法律法规数据库公开页面，仅供学习研究使用，请勿用于商业用途；正式引用以官方发布为准。
- 脚本已内置限速与重试，请合理使用，避免对源站造成压力。
