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

# 设区的市/自治州/盟 -> 省份。上游 2026-09 起对市级法规改用 zdjgCodeId=9999（无省份码），
# 仅 zdjgName（机关名）可用；本表由存量文档树的城市前缀投票（unanimous）生成，
# 并用全量索引的 "XX人民代表大会常务委员会" 机关名交叉核验（2026-09-19）。
CITY2PROV = {
    "七台河市": "黑龙江省", "三亚市": "海南省", "三明市": "福建省", "三沙市": "海南省",
    "三门峡市": "河南省", "上饶市": "江西省", "东莞市": "广东省", "东营市": "山东省",
    "中卫市": "宁夏回族自治区", "中山市": "广东省", "临夏回族自治州": "甘肃省", "临汾市": "山西省",
    "临沂市": "山东省", "临沧市": "云南省", "丹东市": "辽宁省", "丽水市": "浙江省",
    "丽江市": "云南省", "乌兰察布市": "内蒙古自治区", "乌海市": "内蒙古自治区", "乌鲁木齐市": "新疆维吾尔自治区",
    "乐山市": "四川省", "九江市": "江西省", "云浮市": "广东省", "亳州市": "安徽省",
    "伊宁市": "新疆维吾尔自治区", "伊春市": "黑龙江省", "伊犁哈萨克自治州": "新疆维吾尔自治区", "佛山市": "广东省",
    "佳木斯市": "黑龙江省", "保定市": "河北省", "保山市": "云南省", "信阳市": "河南省",
    "儋州市": "海南省", "克孜勒苏柯尔克孜自治州": "新疆维吾尔自治区", "克拉玛依市": "新疆维吾尔自治区", "六安市": "安徽省",
    "六盘水市": "贵州省", "兰州市": "甘肃省", "内江市": "四川省", "凉山彝族自治州": "四川省",
    "包头市": "内蒙古自治区", "北海市": "广西壮族自治区", "十堰市": "湖北省", "南京市": "江苏省",
    "南充市": "四川省", "南宁市": "广西壮族自治区", "南平市": "福建省",
    "南昌市": "江西省", "南通市": "江苏省", "南阳市": "河南省", "博尔塔拉蒙古自治州": "新疆维吾尔自治区",
    "厦门市": "福建省", "双鸭山市": "黑龙江省", "台州市": "浙江省", "合肥市": "安徽省",
    "吉安市": "江西省", "吐鲁番市": "新疆维吾尔自治区", "吕梁市": "山西省", "吴忠市": "宁夏回族自治区",
    "周口市": "河南省", "呼伦贝尔市": "内蒙古自治区", "呼和浩特市": "内蒙古自治区", "咸宁市": "湖北省",
    "咸阳市": "陕西省", "哈密市": "新疆维吾尔自治区", "哈尔滨市": "黑龙江省", "唐山市": "河北省",
    "商丘市": "河南省", "商洛市": "陕西省", "嘉兴市": "浙江省", "嘉峪关市": "甘肃省",
    "四平市": "吉林省", "固原市": "宁夏回族自治区", "塔城市": "新疆维吾尔自治区", "大同市": "山西省",
    "大庆市": "黑龙江省", "大理白族自治州": "云南省", "大连市": "辽宁省", "天水市": "甘肃省",
    "太原市": "山西省", "威海市": "山东省", "娄底市": "湖南省", "孝感市": "湖北省",
    "宁德市": "福建省", "宁波市": "浙江省", "安庆市": "安徽省", "安康市": "陕西省",
    "安阳市": "河南省", "安顺市": "贵州省", "定西市": "甘肃省", "宜宾市": "四川省",
    "宜昌市": "湖北省", "宜春市": "江西省", "宝鸡市": "陕西省", "宣城市": "安徽省",
    "宿州市": "安徽省", "宿迁市": "江苏省", "山南市": "西藏自治区", "岳阳市": "湖南省",
    "崇左市": "广西壮族自治区", "巴中市": "四川省", "巴彦淖尔市": "内蒙古自治区", "巴音郭楞蒙古自治州": "新疆维吾尔自治区",
    "常州市": "江苏省", "常德市": "湖南省", "平凉市": "甘肃省", "平顶山市": "河南省",
    "广元市": "四川省", "广安市": "四川省", "广州市": "广东省", "庆阳市": "甘肃省",
    "库尔勒市": "新疆维吾尔自治区", "廊坊市": "河北省", "延安市": "陕西省", "延边朝鲜族自治州": "吉林省",
    "开封市": "河南省", "张家口市": "河北省", "张家界市": "湖南省", "张掖市": "甘肃省",
    "徐州市": "江苏省", "德宏傣族景颇族自治州": "云南省", "德州市": "山东省", "德阳市": "四川省",
    "忻州市": "山西省", "怀化市": "湖南省", "怒江傈僳族自治州": "云南省", "恩施土家族苗族自治州": "湖北省",
    "惠州市": "广东省", "成都市": "四川省", "扬州市": "江苏省", "承德市": "河北省",
    "抚州市": "江西省", "抚顺市": "辽宁省", "拉萨市": "西藏自治区", "揭阳市": "广东省",
    "攀枝花市": "四川省", "文山壮族苗族自治州": "云南省", "新乡市": "河南省", "新余市": "江西省",
    "无锡市": "江苏省", "日喀则市": "西藏自治区", "日照市": "山东省", "昆明市": "云南省",
    "昌吉回族自治州": "新疆维吾尔自治区", "昌都市": "西藏自治区", "昭通市": "云南省", "晋中市": "山西省",
    "晋城市": "山西省", "普洱市": "云南省", "景德镇市": "江西省", "曲靖市": "云南省",
    "朔州市": "山西省", "朝阳市": "辽宁省", "本溪市": "辽宁省", "来宾市": "广西壮族自治区",
    "杭州市": "浙江省", "松原市": "吉林省", "林芝市": "西藏自治区", "果洛藏族自治州": "青海省",
    "枣庄市": "山东省", "柳州市": "广西壮族自治区", "株洲市": "湖南省", "桂林市": "广西壮族自治区",
    "梅州市": "广东省", "梧州市": "广西壮族自治区", "楚雄彝族自治州": "云南省", "榆林市": "陕西省",
    "武威市": "甘肃省", "武汉市": "湖北省", "毕节市": "贵州省", "永州市": "湖南省",
    "汉中市": "陕西省", "汕头市": "广东省", "汕尾市": "广东省", "江门市": "广东省",
    "池州市": "安徽省", "沈阳市": "辽宁省", "沧州市": "河北省", "河池市": "广西壮族自治区",
    "河源市": "广东省", "泉州市": "福建省", "泰安市": "山东省", "泰州市": "江苏省",
    "泸州市": "四川省", "洛阳市": "河南省", "济南市": "山东省", "济宁市": "山东省",
    "海东市": "青海省", "海北藏族自治州": "青海省", "海口市": "海南省", "海西蒙古族藏族自治州": "青海省",
    "淄博市": "山东省", "淮北市": "安徽省", "淮南市": "安徽省", "淮安市": "江苏省",
    "深圳市": "广东省", "清远市": "广东省", "温州市": "浙江省", "渭南市": "陕西省",
    "湖州市": "浙江省", "湘潭市": "湖南省", "湘西土家族苗族自治州": "湖南省", "湛江市": "广东省",
    "滁州市": "安徽省", "滨州市": "山东省", "漯河市": "河南省", "漳州市": "福建省",
    "潍坊市": "山东省", "潮州市": "广东省", "濮阳市": "河南省", "烟台市": "山东省",
    "焦作市": "河南省", "牡丹江市": "黑龙江省", "玉林市": "广西壮族自治区", "玉树藏族自治州": "青海省",
    "玉溪市": "云南省", "珠海市": "广东省", "甘南藏族自治州": "甘肃省", "甘孜藏族自治州": "四川省",
    "白城市": "吉林省", "白山市": "吉林省", "白银市": "甘肃省", "百色市": "广西壮族自治区",
    "益阳市": "湖南省", "盐城市": "江苏省", "盘锦市": "辽宁省", "眉山市": "四川省",
    "石嘴山市": "宁夏回族自治区", "石家庄市": "河北省", "福州市": "福建省", "秦皇岛市": "河北省",
    "红河哈尼族彝族自治州": "云南省", "绍兴市": "浙江省", "绥化市": "黑龙江省", "绵阳市": "四川省",
    "聊城市": "山东省", "肇庆市": "广东省", "自贡市": "四川省", "舟山市": "浙江省",
    "芜湖市": "安徽省", "苏州市": "江苏省", "茂名市": "广东省", "荆州市": "湖北省",
    "荆门市": "湖北省", "莆田市": "福建省", "莱芜市": "山东省", "菏泽市": "山东省",
    "萍乡市": "江西省", "营口市": "辽宁省", "葫芦岛市": "辽宁省", "蚌埠市": "安徽省",
    "衡水市": "河北省", "衡阳市": "湖南省", "衢州市": "浙江省", "襄阳市": "湖北省",
    "西双版纳傣族自治州": "云南省", "西宁市": "青海省", "西安市": "陕西省", "许昌市": "河南省",
    "贵港市": "广西壮族自治区", "贵阳市": "贵州省", "贺州市": "广西壮族自治区", "资阳市": "四川省",
    "赣州市": "江西省", "赤峰市": "内蒙古自治区", "辽源市": "吉林省", "辽阳市": "辽宁省",
    "达州市": "四川省", "运城市": "山西省", "连云港市": "江苏省", "迪庆藏族自治州": "云南省",
    "通化市": "吉林省", "通辽市": "内蒙古自治区", "遂宁市": "四川省", "遵义市": "贵州省",
    "邢台市": "河北省", "那曲市": "西藏自治区", "邯郸市": "河北省", "邵阳市": "湖南省",
    "郑州市": "河南省", "郴州市": "湖南省", "鄂尔多斯市": "内蒙古自治区", "鄂州市": "湖北省",
    "酒泉市": "甘肃省", "金华市": "浙江省", "金昌市": "甘肃省", "钦州市": "广西壮族自治区",
    "铁岭市": "辽宁省", "铜仁市": "贵州省", "铜川市": "陕西省", "铜陵市": "安徽省",
    "银川市": "宁夏回族自治区", "锦州市": "辽宁省", "镇江市": "江苏省", "长春市": "吉林省",
    "长沙市": "湖南省", "长治市": "山西省", "阜新市": "辽宁省", "阜阳市": "安徽省",
    "防城港市": "广西壮族自治区", "阳江市": "广东省", "阳泉市": "山西省", "阿勒泰地区": "新疆维吾尔自治区",
    "阿坝藏族羌族自治州": "四川省", "陇南市": "甘肃省", "随州市": "湖北省", "雅安市": "四川省",
    "青岛市": "山东省", "鞍山市": "辽宁省", "韶关市": "广东省", "马鞍山市": "安徽省",
    "驻马店市": "河南省", "鸡西市": "黑龙江省", "鹤壁市": "河南省", "鹤岗市": "黑龙江省",
    "鹰潭市": "江西省", "黄冈市": "湖北省", "黄南藏族自治州": "青海省", "黄山市": "安徽省",
    "黄石市": "湖北省", "黑河市": "黑龙江省", "黔东南苗族侗族自治州": "贵州省", "黔南布依族苗族自治州": "贵州省",
    "黔西南布依族苗族自治州": "贵州省", "齐齐哈尔市": "黑龙江省", "龙岩市": "福建省", "龙港市": "浙江省",
}
_CITY_PAT = re.compile(r"^(.{1,9}?(?:自治州|地区|盟)|.{1,9}?市)")

# 少数市/旗/县级法规无省份线索，手工归属
MANUAL_PROV = {
    "鄂伦春自治旗旅游条例": "内蒙古自治区",
    "鄂州市人民代表大会及其常务委员会立法条例": "湖北省",
    "五峰土家族自治县促进天麻产业发展条例": "湖北省",
    "宽城满族自治县农村公路条例": "河北省",
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
    """地方性法规的省份归属：zdjgCodeId（权威）→ 手工表 → 省份前缀 → 城市归属表。"""
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
    for s in (row.get("zdjgName") or "", title):
        s = s.lstrip("“”\"' 　")
        m = _CITY_PAT.match(s)
        if m and m.group(1) in CITY2PROV:
            return CITY2PROV[m.group(1)]
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
