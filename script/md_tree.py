#!/usr/bin/env python3
"""markdown 文档树的公共工具：路径/命名规则、frontmatter 解析与渲染、id 索引扫描。

文档树结构:
    markdown/<类型>/<文件名>.md            一般类型
    markdown/地方性法规/<省份>/<文件名>.md   地方性法规按省份拆分

markdown/ 是唯一数据源：每条法规的全部元数据都在其文件的 YAML frontmatter 中，
更新流水线直接读写文档树。

各脚本以 ``python3 script/xxx.py`` 方式运行时 sys.path[0] 即本目录，可直接 ``import md_tree``。
"""
import base64
import json
import os
import re
import tempfile
import urllib.parse
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根目录 = script/ 的上一级
MD_ROOT = os.path.join(ROOT, "markdown")
NEW_LIST = os.path.join(ROOT, "new_list.json")

META_FIELDS = [
    "id", "title", "office", "publish", "effective_date",
    "type", "status", "url",
    "download_link_word", "download_link_html", "download_link_pdf",
]

STATUS_MAP = {1: "已废止", -1: "已废止", 2: "已修改", 3: "有效", 4: "尚未生效", None: ""}
TYPE_MAP = {
    "地方法规": "地方性法规",
    "修正案": "法律",
    "有关法律问题和重大问题的决定（部分）": "有关法律问题和重大问题的决定",
}

# flk.npc.gov.cn /law-search/search/enumData 中地方人大(165)分支的 codeId -> 省份
CODE2PROV = {
    170: "北京市", 180: "天津市", 190: "河北省", 200: "山西省", 210: "内蒙古自治区",
    220: "辽宁省", 230: "吉林省", 240: "黑龙江省", 250: "上海市", 260: "江苏省",
    270: "浙江省", 280: "安徽省", 290: "福建省", 300: "江西省", 310: "山东省",
    320: "河南省", 330: "湖北省", 340: "湖南省", 350: "广东省", 360: "广西壮族自治区",
    370: "海南省", 380: "重庆市", 390: "四川省", 400: "贵州省", 410: "云南省",
    420: "西藏自治区", 430: "陕西省", 440: "甘肃省", 450: "青海省", 460: "宁夏回族自治区",
    470: "新疆维吾尔自治区",
}
PROV_PREFIXES = [(p[:-1], p) for p in CODE2PROV.values()]  # 简称/全称前缀

# 少数市/旗级法规无省份线索，手工归属
MANUAL_PROV = {
    "鄂伦春自治旗旅游条例": "内蒙古自治区",
    "鄂州市人民代表大会及其常务委员会立法条例": "湖北省",
}

_ILLEGAL = re.compile(r'[/\\:*?"<>|\r\n\t\x00-\x1f]')


def sanitize(title: str) -> str:
    name = _ILLEGAL.sub("_", title).strip().rstrip(". ")
    return name[:80].rstrip(". ") or "untitled"


def yaml_str(value) -> str:
    return json.dumps(value if value is not None else "", ensure_ascii=False)


def law_type_of(row) -> str:
    return TYPE_MAP.get(row.get("flxz") or "", row.get("flxz") or "") or "未分类"


def province_for_row(row) -> str:
    """地方性法规的省份归属：zdjgCodeId（权威）→ 手工表 → 机关名/标题前缀推断。"""
    p = CODE2PROV.get(row.get("zdjgCodeId"))
    if p:
        return p
    title = row.get("title") or ""
    if title in MANUAL_PROV:
        return MANUAL_PROV[title]
    for short, full in PROV_PREFIXES:
        for s in (row.get("zdjgName") or "", title):
            if s.startswith(short) or s.startswith(full):
                return full
    return "未识别省份"


def id_for_bbbs(bbbs: str) -> str:
    # id 格式 = urlencode(base64(bbbs 的 ASCII 十六进制串))，与历史数据保持一致
    return urllib.parse.quote(base64.b64encode(bbbs.encode("ascii")).decode(), safe="")


def bbbs_of_id(law_id):
    try:
        return base64.b64decode(unquote(law_id)).decode("ascii")
    except Exception:
        return None


def entry_from_row(row, content: str) -> dict:
    """由 new_list 行 + 正文构造一条完整法规记录（META_FIELDS + content）。"""
    bbbs = row["bbbs"]
    gbrq = row.get("gbrq") or ""
    sxrq = row.get("sxrq") or ""
    return {
        "id": id_for_bbbs(bbbs),
        "title": row.get("title") or "",
        "office": row.get("zdjgName") or "",
        "publish": f"{gbrq} 00:00:00" if gbrq else "",
        "effective_date": f"{sxrq} 00:00:00" if sxrq else "",
        "type": law_type_of(row),
        "status": STATUS_MAP.get(row.get("sxx"), ""),
        "url": f"https://flk.npc.gov.cn/detail?id={bbbs}&fileId=&type=&title={urllib.parse.quote(row.get('title') or '')}",
        "download_link_word": "",
        "download_link_html": "",
        "download_link_pdf": "",
        "content": content,
    }


def render(law: dict, body: str = None) -> str:
    """渲染法规记录为 md 全文。

    body 给定时为 frontmatter 结束标记之后的原文（以 ``\\n# 标题`` 开头），
    此时忽略 content 字段、正文原样回写——用于只改元数据的原地更新，
    保证除被修改字段外与原文件逐字节一致。
    """
    lines = ["---"]
    for field in META_FIELDS:
        lines.append(f"{field}: {yaml_str(law.get(field, ''))}")
    lines.append("---")
    if body is not None:
        return "\n".join(lines) + "\n" + body
    lines.append("")
    lines.append(f"# {law.get('title', '')}")
    lines.append("")
    content = (law.get("content") or "").replace("\r\n", "\n").replace("\r", "\n")
    lines.append(content.rstrip())
    return "\n".join(lines) + "\n"


def parse(text: str):
    """解析 md 全文 -> (frontmatter dict, body)。格式不符时返回 (None, None)。"""
    if not text.startswith("---\n"):
        return None, None
    head, sep, body = text.partition("\n---\n")
    if not sep:
        return None, None
    fm = {}
    for line in head.splitlines():
        if not line or line == "---":
            continue
        k, _, v = line.partition(": ")
        try:
            fm[k] = json.loads(v)
        except Exception:
            return None, None
    return fm, body


def write_atomic(path: str, text: str) -> None:
    """先写同目录临时文件再原子替换，避免中断产生半截文件。"""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def unique_path(type_dir: str, law: dict) -> str:
    """在目标目录内为法规挑选不冲突的文件路径（存量文件与新增文件遵循同一命名规则）。"""
    base = sanitize(law.get("title", ""))
    year = (law.get("publish") or "")[:4]
    taken = {fn[:-3] for fn in os.listdir(type_dir)} if os.path.isdir(type_dir) else set()
    name = base
    if name in taken:
        name = f"{base}（{year}）" if year else f"{base}_1"
    if name in taken:
        stem = f"{base}_{law.get('id', '')[:8]}"
        name, seq = stem, 2
        while name in taken:  # 同名同年且 id 前缀也相同时继续追加序号
            name = f"{stem}_{seq}"
            seq += 1
    return os.path.join(type_dir, name + ".md")


def law_path(row, law: dict, md_root: str = MD_ROOT) -> str:
    """为一条来自 new_list 的新法规计算目标路径（含省份归属与命名去重）。"""
    law_type = law["type"]
    if law_type == "地方性法规":
        type_dir = os.path.join(md_root, law_type, province_for_row(row))
    else:
        type_dir = os.path.join(md_root, law_type)
    return unique_path(type_dir, law)


def scan_ids(md_root: str = MD_ROOT) -> dict:
    """扫描文档树 frontmatter，返回 {bbbs: path} 索引。

    只读每个文件头部即可拿到 id（找不到 frontmatter 结束标记时退化为读全文）；
    id 缺失或无法解码的条目不计入，读取失败的文件跳过。
    """
    index = {}
    for dirpath, _, filenames in os.walk(md_root):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "rb") as f:
                    chunk = f.read(4096)
                if b"\n---\n" not in chunk:
                    with open(path, "rb") as f:
                        chunk = f.read()
                fm, _ = parse(chunk.decode("utf-8", errors="ignore"))
                if not fm or not fm.get("id"):
                    continue
                bbbs = bbbs_of_id(fm["id"])
                if bbbs:
                    index[bbbs] = path
            except OSError:
                continue
    return index
