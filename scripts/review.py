#!/usr/bin/env python3
"""Project-scoped extraction, evidence gating, annotation and export. No LLM calls."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import re
import sys
import zipfile
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

VERSION = "1.3.0"
OFFICIAL = ("ccs.org.cn", "ccs-service.net", "imo.org", "iacs.org.uk", "iacs.org", "iec.ch", "iso.org")
STATUS = {"pass": "已核查", "deviation": "明确偏差", "incomplete": "描述不完整", "pending": "待核实", "exempt": "有依据免除", "not_applicable": "不适用"}
ANNOTATION_STATUS = {"written":"已写入", "unlocated":"待定位", "not_required":"无需批注", "pending":"待写入", "not_reviewed":"尚未审查"}
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def fail(message):
    raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def local(root, relative):
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()):
        fail("项目证据路径越界: " + str(relative))
    return p


def official(url):
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and not u.username and not u.password and u.port in (None, 443) and any(host == d or host.endswith("." + d) for d in OFFICIAL)


def paragraphs(doc):
    """Body paragraphs in XML order, including nested tables, no merged-cell repeats."""
    from docx.text.paragraph import Paragraph
    return [Paragraph(e, doc._body) for e in doc.element.body.iter(f"{{{W}}}p")]


def extract_document(path, ocr="off", sidecar=None):
    path = Path(path).resolve()
    result = {"schema_version": 1, "input": {"path": str(path), "sha256": sha(path), "format": path.suffix.lower()}, "blocks": [], "warnings": []}
    if path.suffix.lower() == ".docx":
        from docx import Document
        doc = Document(path)
        for i, p in enumerate(paragraphs(doc)):
            result["blocks"].append({"id": f"p{i}", "paragraph": i, "text": p.text, "method": "native", "in_table": bool(p._p.xpath("ancestor::w:tc"))})
        with zipfile.ZipFile(path) as z:
            unsupported = [n for n in z.namelist() if re.match(r"word/(footnotes|endnotes|header\d+|footer\d+)\.xml", n)]
            if unsupported:
                result["warnings"].append("页眉、页脚及脚注/尾注未作为主文批注锚点: " + ", ".join(unsupported))
            if b"<w:txbxContent" in z.read("word/document.xml") or b"<w:ins " in z.read("word/document.xml") or b"<w:del " in z.read("word/document.xml"):
                result["warnings"].append("存在文本框或修订记录；需人工检查其覆盖范围")
    elif path.suffix.lower() == ".pdf":
        import pymupdf as fitz
        with fitz.open(path) as pdf:
            if pdf.needs_pass:
                fail("PDF 已加密，须先提供可读取的授权副本")
            imported = read(sidecar) if sidecar else None
            if imported and imported.get("input_sha256") != result["input"]["sha256"]:
                fail("OCR 坐标文件与原件哈希不符")
            engine = None
            for n, page in enumerate(pdf):
                native = []
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        text = "".join(s["text"] for s in line["spans"])
                        if text.strip():
                            native.append({"text": text, "bbox": list(line["bbox"]), "method": "native"})
                lines = native
                if native and page.get_images() and ocr == "auto" and not imported:
                    result["warnings"].append(f"第 {n+1} 页含图像及原生文字，图像中文字未自动 OCR；须原页检查或使用 --ocr on")
                if ocr == "on" or (not native and ocr == "auto") or (not native and imported):
                    if imported:
                        lines = [b for b in imported.get("blocks", []) if b.get("page") == n + 1]
                        if any(b.get("coordinate_space") != "unrotated_pdf_points" for b in lines):
                            fail("OCR 坐标必须是 unrotated_pdf_points")
                        lines = [{**b, "method": "ocr"} for b in lines]
                    else:
                        try:
                            if engine is None:
                                from paddleocr import PaddleOCR
                                engine = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, lang="ch", device="cpu", enable_mkldnn=False)
                            import numpy as np
                            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                            prediction = next(iter(engine.predict(arr)))
                            # PaddleOCR 3.x result supports a dict-like .json property.
                            raw = prediction.json
                            raw = json.loads(raw) if isinstance(raw, str) else raw
                            raw = raw.get("res", raw)
                            lines = []
                            for text, score, poly in zip(raw["rec_texts"], raw["rec_scores"], raw["rec_polys"]):
                                points = [fitz.Point(float(x) / 2, float(y) / 2) * page.derotation_matrix for x, y in poly]
                                lines.append({"text": text, "confidence": float(score), "bbox": [min(p.x for p in points), min(p.y for p in points), max(p.x for p in points), max(p.y for p in points)], "method": "ocr", "visual_confirmed": False})
                        except ImportError:
                            result["warnings"].append(f"第 {n+1} 页需要 OCR；请安装 OCR 依赖后重提取")
                            lines = []
                        except Exception as exc:
                            result["warnings"].append(f"第 {n+1} 页 OCR 失败: {type(exc).__name__}: {exc}")
                            lines = []
                if not lines:
                    result["warnings"].append(f"第 {n+1} 页未提取文字，不得视为已完成审查")
                for i, line in enumerate(lines):
                    box = line.get("bbox", [])
                    unrotated_bounds = page.rect * page.derotation_matrix
                    if len(box) != 4 or not all(math.isfinite(float(v)) for v in box) or fitz.Rect(box).is_empty or not unrotated_bounds.contains(fitz.Rect(box)):
                        fail(f"第 {n+1} 页 OCR/文字区域坐标无效")
                    result["blocks"].append({**line, "id": f"page{n+1}-line{i}", "page": n+1, "coordinate_space": "unrotated_pdf_points"})
            result["page_count"] = len(pdf)
    elif path.suffix.lower() in (".txt", ".md", ".html", ".htm"):
        text = path.read_text(encoding="utf-8-sig")
        if path.suffix.lower() in (".html", ".htm"):
            from html.parser import HTMLParser
            class Text(HTMLParser):
                def __init__(self):
                    super().__init__(); self.parts = []; self.skip = 0
                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style"): self.skip += 1
                def handle_endtag(self, tag):
                    if tag in ("script", "style"): self.skip = max(0, self.skip-1)
                def handle_data(self, data):
                    if not self.skip: self.parts.append(data)
            parser = Text(); parser.feed(text); text = "\n".join(parser.parts)
        result["blocks"] = [{"id": f"line{i}", "text": t, "method": "native"} for i, t in enumerate(text.splitlines()) if t.strip()]
    else:
        fail("仅支持 DOCX、PDF 及作为依据的 UTF-8 TXT/MD/HTML")
    return result


def bind(root):
    extraction = read(root / "extraction.json")
    path = Path(extraction["input"]["path"])
    if sha(path) != extraction["input"]["sha256"]:
        fail("送审原件已变化，请重新 extract 后审查")
    return extraction


def locate(extraction, anchor):
    quote = anchor.get("quote", "")
    if not quote:
        return None, "缺少锚点原文"
    matches = []
    for b in extraction["blocks"]:
        if anchor.get("block_id") and b["id"] != anchor["block_id"]: continue
        if anchor.get("page") and b.get("page") != anchor["page"]: continue
        starts = [m.start() for m in re.finditer(re.escape(quote), b["text"])]
        if "start" in anchor: starts = [s for s in starts if s == anchor["start"]]
        matches.extend((b, s) for s in starts)
    if len(matches) != 1:
        return None, "原文定位不唯一或未匹配"
    b, start = matches[0]
    if b["method"] == "ocr" and not (anchor.get("visual_confirmed") is True and anchor.get("confirmation_note")):
        return None, "OCR 锚点须记录人工原页核对说明"
    return {"block": b, "start": start, "end": start + len(quote)}, None


def validate_source(root, source, demo):
    if source.get("kind") == "synthetic":
        if not demo: return "演示依据不能用于正式审查"
    elif source.get("kind") == "project_approval":
        if source.get("approval_verified") is not True or not source.get("signatory"):
            return "项目批准文件尚未核实"
    else:
        if not official(source.get("official_url", "")):
            return "依据入口不是受支持的官方 HTTPS 来源"
        download = source.get("download_url", source["official_url"])
        if not official(download):
            proof = source.get("link_proof", {})
            try:
                landing = local(root, proof["path"])
                from html.parser import HTMLParser
                from urllib.parse import urljoin
                class Links(HTMLParser):
                    def __init__(self): super().__init__(); self.links=[]
                    def handle_starttag(self, tag, attrs):
                        if tag=="a": self.links.extend(urljoin(source["official_url"],v) for k,v in attrs if k=="href" and v)
                links=Links(); links.feed(landing.read_text(encoding="utf-8"))
                if sha(landing) != proof["sha256"] or proof.get("official_url") != source["official_url"] or download not in links.links:
                    return "外部下载渠道缺少可核对的官方链接证明"
            except (KeyError, OSError, ValueError):
                return "外部下载渠道缺少可核对的官方链接证明"
    for key in ("document_id", "edition", "retrieved_at", "applicability_reason"):
        if not source.get(key): return "依据元数据缺失: " + key
    if source.get("fulltext") is not True or source.get("edition_confirmed") is not True:
        return "尚缺适用版次全文或版次核实"
    # Only a release-pinned knowledge pack may skip native PDF extraction.
    if source.get("knowledge"):
        from knowledge import validate_source as validate_knowledge_source
        return validate_knowledge_source(root,source)
    try:
        file = local(root, source["path"])
        if sha(file) != source["sha256"]: return "依据文件哈希不符"
        index = read(local(root, source["index_path"]))
        if index["input"]["sha256"] != source["sha256"]: return "依据提取结果与全文不符"
        # Re-extract native evidence rather than trusting an edited text index.
        if not any(b.get("method") == "ocr" for b in index["blocks"]):
            actual = extract_document(file)
            if [(b["id"], b["text"]) for b in actual["blocks"]] != [(b["id"], b["text"]) for b in index["blocks"]]:
                return "依据索引内容与原文不符"
    except (KeyError, OSError, ValueError):
        return "缺少可读取的依据原文及定位索引"
    if source.get("baseline"):
        from baseline import validate_project_source
        return validate_project_source(root, source)
    return None


def source_state(root, source):
    state = {}
    paths = [source.get(k) for k in ("path", "index_path")]
    if source.get("link_proof"): paths.append(source["link_proof"].get("path"))
    if source.get("knowledge"):
        path=source['knowledge'].get('manifest_path'); paths.append(path)
        try:
            manifest_file=local(root,path); manifest=read(manifest_file)
            paths += [(manifest_file.parent / p).relative_to(root).as_posix() for p in manifest['files'] if Path(p).suffix.lower()!='.png']
        except (KeyError,OSError,ValueError,TypeError): pass
    if source.get("baseline"):
        path = source["baseline"].get("manifest_path")
        paths.append(path)
        try:
            manifest_file = local(root, path)
            manifest = read(manifest_file)
            paths.append((manifest_file.parent / manifest["landing_path"]).relative_to(root).as_posix())
        except (KeyError, OSError, ValueError, TypeError):
            pass
    for path in filter(None, paths):
        try:
            file = local(root, path)
            state[path] = sha(file) if file.is_file() else "missing"
        except ValueError:
            state[path] = "invalid_path"
    return state


def citation_errors(root, item, sources, source_errors):
    errors = []
    if not item.get("citations"): return ["缺少正式依据引用"]
    for citation in item["citations"]:
        sid = citation.get("source_id")
        if sid not in sources:
            errors.append("未知依据编号: " + str(sid)); continue
        if source_errors[sid]:
            errors.append(source_errors[sid]); continue
        if not citation.get("clause"):
            errors.append("缺少条款/表格/脚注编号")
        index = read(local(root, sources[sid]["index_path"]))
        _, error = locate(index, citation)
        if error: errors.append("依据引用: " + error)
    return errors


# Dimension, scale to base unit, offset to base unit. No eval or expression parsing.
UNITS = {"s": ("time", "1", "0"), "min": ("time", "60", "0"), "h": ("time", "3600", "0"),
         "ms": ("time", ".001", "0"), "Hz": ("frequency", "1", "0"), "kHz": ("frequency", "1000", "0"), "MHz": ("frequency", "1000000", "0"),
         "V": ("voltage", "1", "0"), "mV": ("voltage", ".001", "0"), "kV": ("voltage", "1000", "0"),
         "A": ("current", "1", "0"), "mA": ("current", ".001", "0"), "°C": ("temperature", "1", "273.15"), "C": ("temperature", "1", "273.15"), "K": ("temperature", "1", "0"),
         "mm": ("length", ".001", "0"), "m": ("length", "1", "0"), "g": ("acceleration", "9.80665", "0"), "m/s²": ("acceleration", "1", "0"), "%": ("ratio", ".01", "0"), "1": ("ratio", "1", "0")}
UNITS.update({"deg":("angle","1","0"),"°":("angle","1","0"),"oct/min":("octave_rate","1","0"),"dec/s":("decade_rate","1","0")})


def number(value):
    n = Decimal(str(value))
    if not n.is_finite(): fail("数值必须有限")
    return n


def convert(value, unit, target):
    a, b = UNITS[unit], UNITS[target]
    if a[0] != b[0]: fail("单位量纲不匹配")
    return (number(value) * Decimal(a[1]) + Decimal(a[2]) - Decimal(b[2])) / Decimal(b[1])


def numeric_check(rule):
    unit = rule["required_unit"]
    values = rule["actual"] if isinstance(rule["actual"], list) else [rule["actual"]]
    converted = [convert(v, rule["actual_unit"], unit) for v in values]
    op = rule["operator"]
    lo = number(rule["min"]) if "min" in rule else None
    hi = number(rule["max"]) if "max" in rule else None
    if lo is not None and hi is not None and lo > hi: fail("范围上下限颠倒")
    if op == "range_contains":
        if len(converted) != 2 or converted[0] > converted[1]: fail("实际区间须有两个有序端点")
        ok = converted[0] <= lo and converted[1] >= hi
    elif op == "between": ok = all(lo <= v <= hi for v in converted)
    elif op == "ge": ok = all(v >= lo for v in converted)
    elif op == "le": ok = all(v <= hi for v in converted)
    elif op == "equal":
        expected = number(rule["expected"])
        absolute = number(rule.get("abs_tolerance", 0))
        relative = number(rule.get("rel_tolerance", 0))
        if absolute < 0 or relative < 0: fail("容差不能为负")
        tolerance = max(absolute, abs(expected) * relative)
        ok = all(abs(v - expected) <= tolerance for v in converted)
    else: fail("未知数值操作符")
    return ok, {"original": values, "original_unit": rule["actual_unit"], "converted": [str(v) for v in converted], "unit": unit, "rule": rule}


def check(root, demo=False):
    extraction = bind(root)
    review = read(root / "review.json")
    if review.get("schema_version") != 1: fail("schema_version 必须为 1")
    if review.get("input_sha256") != extraction["input"]["sha256"]: fail("审查记录与送审原件不符")
    if bool(review.get("demo")) != demo: fail("演示项目须显式使用 --demo；正式项目不能使用该参数")
    if review.get('knowledge_pack'):
        from knowledge import enrich
        review=enrich(root,review)
    sources = {s["id"]: s for s in review.get("sources", [])}
    if len(sources) != len(review.get("sources", [])): fail("依据编号重复")
    source_errors = {sid: validate_source(root, s, demo) for sid, s in sources.items()}
    items = copy.deepcopy(review.get("items", []))
    if not items: fail("审查矩阵不能为空")
    ids = [i.get("id") for i in items]
    if any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", i) for i in ids) or len(set(ids)) != len(ids): fail("审查项编号为空、重复或含非法字符")
    for item in items:
        for field in ("recipient", "confirmation", "deliverable", "closure_criteria"):
            if field in item and not isinstance(item[field], str): fail(field + " 须为文字")
        status = item.get("proposed_status", "pending")
        if status not in STATUS: fail("未知审查状态: " + str(status))
        errors = citation_errors(root, item, sources, source_errors)
        errors += item.get('knowledge_errors',[])
        if item.get("applicability", {}).get("confirmed") is not True or not item.get("applicability", {}).get("reason"):
            errors.append("项目适用性尚未确认")
        if not item.get("finding") or not item.get("action") or not item.get("test"):
            errors.append("缺少试验名称、发现或处理要求")
        item["status"] = status
        if item.get("numeric"):
            try:
                ok, trace = numeric_check(item["numeric"])
                item["calculation"] = trace
                if status not in ("pending", "incomplete", "exempt", "not_applicable"):
                    item["status"] = "pass" if ok else "deviation"
                # Model must confirm both actual and limit against cited originals.
                if item["numeric"].get("values_verified") is not True:
                    errors.append("数值与原文尚未核对")
            except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
                errors.append("数值校核失败: " + str(exc))
        if status == "exempt":
            scope = item.get("exemption", {})
            if not all(scope.get(k) for k in ("equipment", "tests", "conditions", "approval_source_id")) or scope.get("equipment") != item.get("equipment") or item.get("test") not in scope.get("tests", []):
                errors.append("免除缺少与本设备、本试验匹配的批准范围")
            elif scope["approval_source_id"] not in sources or source_errors.get(scope["approval_source_id"]):
                errors.append("免除批准依据未核实")
            elif scope["approval_source_id"] not in [c.get("source_id") for c in item.get("citations", [])]:
                errors.append("免除批准文件缺少具体原文引用")
        if item.get("missing_item") and item.get("whole_document_checked") is not True:
            errors.append("整项遗漏尚未完成全文核查")
        located, location_error = locate(extraction, item.get("anchor", {}))
        # Every conclusion on an actual passage requires a reliable submitted-text anchor.
        if location_error and not item.get("missing_item"):
            errors.append("送审文本: " + location_error)
        item["location_error"] = location_error
        item["evidence_errors"] = sorted(set(errors))
        if item.get("reviewed") is False: item["evidence_errors"].append("尚未逐项审查")
        item["evidence_status"] = "pending" if item["evidence_errors"] else "verified"
        if item["evidence_errors"]: item["status"] = "pending"
        item["annotation_status"] = "not_required" if item["status"] in ("pass", "exempt", "not_applicable") else "pending"
        if item.get("reviewed") is False: item["annotation_status"] = "not_reviewed"
    output = {**review, "items": items, "version": VERSION, "review_sha256": sha(root / "review.json"), "extraction_sha256": sha(root / "extraction.json"), "source_errors": source_errors, "source_state": {sid:source_state(root,s) for sid,s in sources.items()}, "extraction_warnings": extraction["warnings"], "created_at": datetime.now(timezone.utc).isoformat()}
    write(root / "checked.json", output)
    return output


def current(root, filename):
    bind(root)
    data = read(root / filename)
    if data["review_sha256"] != sha(root / "review.json") or data["extraction_sha256"] != sha(root / "extraction.json"):
        fail("输入或审查记录已变化，请从 check 重新运行")
    for s in data.get("sources", []):
        if source_state(root,s) != data["source_state"][s["id"]]:
            fail("依据内容已变化，请从 check 重新运行")
    return data


def comment_text(item, data):
    """A self-contained instruction to the recipient, also used for verification."""
    pending = item["evidence_status"] != "verified" or item["status"] == "pending"
    prefix = "演示数据｜" if data.get("demo") else ""
    lines = [f"{prefix}{item['id']}｜{STATUS[item['status']]}"]
    if item.get("recipient"): lines.append("请处理：" + item["recipient"])
    quote = item.get("anchor", {}).get("quote")
    if quote: lines.append(("相关标题/总表：" if item.get("missing_item") else "原文：") + quote)
    lines.append(("待核实事项：" if pending else "实际问题：") + item.get("finding", "尚缺具体问题描述"))
    if item.get("missing_item"):
        lines.append("定位说明：本版大纲中未见列明该项；备注锚点为相关标题或总表。")
    sources = {s["id"]: s for s in data["sources"]}
    refs = list(dict.fromkeys(f"{sources[c['source_id']]['document_id']} {sources[c['source_id']]['edition']} {c['clause']}" for c in item.get("citations", []) if c.get("source_id") in sources))
    if refs: lines.append(("候选依据（尚待核实）：" if pending else "依据：") + "；".join(refs))
    if item.get("calculation"):
        lines.append(("待复核数值：" if pending else "参数对比：") + calculation_text(item))
    lines.append(("下一步核实：" if pending else "修改建议：") + item.get("action", "请补充具体处理要求"))
    for key, label in (("confirmation", "请确认"), ("deliverable", "请提供"), ("closure_criteria", "复核关闭条件")):
        if item.get(key): lines.append(label + "：" + item[key])
    if item.get("evidence_errors"):
        lines.append("尚缺证据：" + "；".join(item["evidence_errors"]))
        lines.append("结论边界：补齐上述资料后复核，当前不作为确定性不符合结论。")
    return "\n".join(lines)


def calculation_text(item):
    trace = item.get("calculation")
    if not trace: return ""
    rule = trace["rule"]
    operation = {"ge":">=", "le":"<=", "equal":"=", "between":"区间内", "range_contains":"覆盖区间"}.get(rule["operator"], rule["operator"])
    target = rule.get("expected", rule.get("min", rule.get("max")))
    if rule["operator"] in ("between", "range_contains"): target = f"{rule['min']} 至 {rule['max']}"
    return f"送审 {', '.join(map(str, trace['original']))} {trace['original_unit']}，换算为 {', '.join(trace['converted'])} {trace['unit']}；要求 {operation} {target} {trace['unit']}"


def unlocated_text(items, data):
    return "待定位事项汇总（本备注位置不是问题发生位置）\n请结合所列原文及问题编号确认实际位置，再处理以下事项。\n\n" + "\n\n".join(
        comment_text(i, data) + "\n定位待办：" + i.get("annotation_error", "原位待确认") for i in items)


def split_anchor(paragraph, start, end):
    """Split simple text runs only, preserving formatting; refuse fields/drawings/etc."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.text.run import Run
    pos, selected = 0, []
    for run in list(paragraph.runs):
        text = run.text
        a, b = pos, pos + len(text)
        pos = b
        if b <= start or a >= end: continue
        if any(child.tag not in (qn("w:rPr"), qn("w:t")) for child in run._r):
            fail("锚点包含域、图片、制表符或复杂内容，须人工定位")
        left, right = max(0, start-a), min(len(text), end-a)
        pieces = [(text[:left], False), (text[left:right], True), (text[right:], False)]
        for value, chosen in pieces:
            if not value: continue
            element = OxmlElement("w:r")
            if run._r.rPr is not None: element.append(copy.deepcopy(run._r.rPr))
            t = OxmlElement("w:t"); t.set(qn("xml:space"), "preserve"); t.text = value; element.append(t)
            run._r.addprevious(element)
            if chosen: selected.append(Run(element, paragraph))
        paragraph._p.remove(run._r)
    if pos < end or not selected or "".join(r.text for r in selected) != paragraph.text[start:end]:
        fail("复杂段落的字符偏移不受支持，须人工定位")
    return selected


def annotate(root):
    data = current(root, "checked.json")
    extraction = bind(root)
    source = Path(extraction["input"]["path"])
    output = root / ("annotated" + source.suffix.lower())
    if output.resolve() == source.resolve(): fail("输出不能覆盖原件")
    data["annotation_input_sha256"] = sha(root / "checked.json")
    if source.suffix.lower() == ".docx":
        from docx import Document
        doc = Document(source)
        for item in data["items"]:
            if item["annotation_status"] in ("not_required", "not_reviewed"): continue
            loc, error = locate(extraction, item.get("anchor", {}))
            if error:
                item.update(annotation_status="unlocated", annotation_error=error); continue
            # Roll back a failed split so it cannot affect later annotations.
            saved = copy.deepcopy(doc.element.body)
            try:
                p = paragraphs(doc)[loc["block"]["paragraph"]]
                runs = split_anchor(p, loc["start"], loc["end"])
                comment = doc.add_comment(runs, text=comment_text(item, data), author="CCS Review Draft", initials="CR")
                item.update(annotation_status="written", annotation_id=str(comment.comment_id), annotation_location={"block_id": loc["block"]["id"], "quote": item["anchor"]["quote"]})
            except ValueError as exc:
                doc.element.replace(doc.element.body, saved)
                item.update(annotation_status="unlocated", annotation_error=str(exc))
        unresolved = [i for i in data["items"] if i["annotation_status"] == "unlocated"]
        if unresolved:
            first = next((p for p in paragraphs(doc) if p.text.strip() and p.runs), None)
            if first is not None:
                text = unlocated_text(unresolved, data)
                summary = doc.add_comment(first.runs, text=text, author="CCS Review Draft", initials="CR")
                data["unlocated_note"] = {"id": str(summary.comment_id), "text": text, "item_ids": [i["id"] for i in unresolved]}
            else: data["unlocated_summary_error"] = "文档无可用正文锚点，无法写入待定位汇总备注"
        buffer = io.BytesIO(); doc.save(buffer); buffer.seek(0)
        # Preserve all untouched package parts byte-for-byte, including existing modern comments.
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(buffer) as changed, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as dest:
            mutable = {"word/document.xml", "word/comments.xml", "word/_rels/document.xml.rels", "[Content_Types].xml"}
            for name in original.namelist():
                dest.writestr(name, changed.read(name) if name in mutable and name in changed.namelist() else original.read(name))
            for name in changed.namelist():
                if name not in original.namelist(): dest.writestr(name, changed.read(name))
    elif source.suffix.lower() == ".pdf":
        import pymupdf as fitz
        with fitz.open(source) as pdf:
            for item in data["items"]:
                if item["annotation_status"] in ("not_required", "not_reviewed"): continue
                loc, error = locate(extraction, item.get("anchor", {}))
                if error:
                    item.update(annotation_status="unlocated", annotation_error=error); continue
                block = loc["block"]; page = pdf[block["page"]-1]
                if block["method"] == "ocr":
                    box = fitz.Rect(block["bbox"])
                    annotation = page.add_highlight_annot(fitz.Quad(box.tl, box.tr, box.bl, box.br))
                else:
                    rects = page.search_for(item["anchor"]["quote"], clip=fitz.Rect(block["bbox"]) + (-1, -1, 1, 1), quads=True)
                    if len(rects) != 1:
                        item.update(annotation_status="unlocated", annotation_error="PDF 精确文本区域不唯一或跨行"); continue
                    annotation = page.add_highlight_annot(rects)
                annotation.set_colors(stroke=(1, 0.85, 0)); annotation.set_opacity(0.35)
                pdf_popup(annotation, page, item["id"], comment_text(item, data))
                item.update(annotation_status="written", annotation_id=str(annotation.xref), annotation_location={"page": block["page"], "rect": list(annotation.rect), "scope": "ocr_line_region" if block["method"] == "ocr" else "exact_text"})
            unresolved = [i for i in data["items"] if i["annotation_status"] == "unlocated"]
            if unresolved and len(pdf):
                page = pdf[0]; bounds = page.rect * page.derotation_matrix
                summary = page.add_text_annot((max(bounds.x0, bounds.x1-28), bounds.y0+12), "", icon="Comment")
                text = unlocated_text(unresolved, data)
                pdf_popup(summary, page, "待定位事项汇总", text)
                data["unlocated_note"] = {"id": str(summary.xref), "page": 1, "text": text, "item_ids": [i["id"] for i in unresolved]}
            elif unresolved: data["unlocated_summary_error"] = "PDF无页面，无法写入待定位汇总备注"
            pdf.save(output, garbage=0, deflate=False)
    else: fail("送审批注仅支持 DOCX/PDF")
    data["annotated_file"] = output.name; data["annotated_sha256"] = sha(output)
    write(root / "annotated.json", data)
    return data


def pdf_popup(annotation, page, subject, text):
    import pymupdf as fitz
    bounds = page.rect * page.derotation_matrix
    annotation.set_info(title="CCS Review Draft", subject=subject, content=text)
    annotation.set_popup(fitz.Rect(bounds.x0+8, bounds.y0+8, bounds.x0+min(400, bounds.width-8), bounds.y0+min(320, bounds.height-8)))
    annotation.set_open(False)  # Native review pane / click-to-open note; keep the page readable.
    annotation.update()


def safe_cell(value):
    if isinstance(value, (dict, list)): value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
        if value.startswith(("=", "+", "-", "@")): value = "'" + value
    return value


def export(root):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    data = current(root, "annotated.json")
    if data["annotation_input_sha256"] != sha(root / "checked.json"): fail("批注与校核结果不一致")
    if sha(root / data["annotated_file"]) != data["annotated_sha256"]: fail("批注文件已变化")
    wb = Workbook(); wb.remove(wb.active)
    def sheet(name, headers, rows, widths):
        ws = wb.create_sheet(name); ws.append(headers)
        for row in rows: ws.append([safe_cell(v) for v in row])
        ws.freeze_panes = "C2"; ws.auto_filter.ref = ws.dimensions; ws.sheet_view.showGridLines = False
        for cell in ws[1]:
            cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="24445C"); cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 30
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font = Font(name="Microsoft YaHei", size=10); c.alignment = Alignment(vertical="top", wrap_text=True)
            max_lines = max((sum(max(1, math.ceil(len(line)*1.65 / widths[min(c.column-1,len(widths)-1)])) for line in str(c.value or "").splitlines()) for c in row), default=1)
            ws.row_dimensions[row[0].row].height = min(400, max(36, max_lines*16))
        for i, width in enumerate(widths, 1): ws.column_dimensions[get_column_letter(i)].width = width
        ws.sheet_properties.pageSetUpPr.fitToPage = True; ws.page_setup.orientation = "landscape"; ws.page_setup.paperSize = ws.PAPERSIZE_A3; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0; ws.print_title_rows = "1:1"
        return ws
    sources_by_id={s["id"]:s for s in data["sources"]}
    blocks={b["id"]:b for b in read(root/"extraction.json")["blocks"]}
    def location(item):
        anchor=item.get("anchor",{}); block=blocks.get(anchor.get("block_id"),{})
        prefix=f"第{block['page']}页" if block.get("page") else f"主文第{block['paragraph']+1}段" if "paragraph" in block else "位置待核实"
        return prefix+"："+anchor.get("quote", "无原文锚点")
    def refs(item):
        return "\n".join(dict.fromkeys(f"{c.get('source_id','?')} / {sources_by_id.get(c.get('source_id'),{}).get('edition','待核实')} / {c.get('clause','待核实')}" for c in item.get("citations",[])))
    rows = [[i["id"], i.get("equipment", ""), i.get("test", ""), STATUS[i["status"]], i["finding"], i["action"], location(i), refs(i), "；".join(i["evidence_errors"]), ANNOTATION_STATUS[i["annotation_status"]], i.get("annotation_error", ""), calculation_text(i), "演示数据" if data.get("demo") else "验船师复核草稿", i.get("recipient", ""), i.get("confirmation", ""), i.get("deliverable", ""), i.get("closure_criteria", "")] for i in data["items"]]
    sheet("审查矩阵", ["编号", "设备", "试验项目", "结论", "发现", "修改要求", "送审定位", "规范引用", "证据缺口", "批注状态", "定位说明", "数值校核", "性质", "处理方", "需确认事项", "需提交材料", "复核关闭条件"], rows, [15, 18, 22, 16, 48, 48, 35, 30, 38, 18, 35, 32, 20, 20, 45, 45, 45])
    def date_value(value, timestamp=False):
        if not value: return None
        try:
            dt=datetime.fromisoformat(value.replace("Z","+00:00"))
            return dt.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None) if timestamp and dt.tzinfo else dt
        except (ValueError,AttributeError): return value
    basis=sheet("适用依据", ["编号", "文件", "版次", "发布日期", "实施日期", "触发条件", "适用理由", "官方链接", "获取时间（北京时间）", "哈希", "资料缺口"], [[s["id"],s.get("document_id"),s.get("edition"),date_value(s.get("published_date")),date_value(s.get("effective_date")),s.get("trigger"),s.get("applicability_reason"),s.get("official_url"),date_value(s.get("retrieved_at"),True),s.get("sha256"),data["source_errors"].get(s["id"])] for s in data["sources"]], [14,30,18,18,18,36,45,55,30,30,45])
    for row in basis.iter_rows(min_row=2):
        for col in (3,4): row[col].number_format="yyyy-mm-dd"
        row[8].number_format="yyyy-mm-dd hh:mm"
    pack=data.get('knowledge_pack',{})
    pack_rows=[["知识包版次",pack.get('id')],["原文快照日期",pack.get('snapshot_date')],["固定版次范围",pack.get('update_scope')],["审查模式",data.get('rule_mode','fixed')]] if pack else []
    sheet("项目条件", ["条件", "内容"], [[k,v] for k,v in data.get("project",{}).items()] + pack_rows + [["提取待办", w] for w in data["extraction_warnings"]] + [["状态", "演示数据，禁止用于实际合规判断" if data.get("demo") else "验船师复核草稿"]], [30,110])
    wb.save(root / "review.xlsx")
    lines = ["# 适用依据与资料缺口", "", "演示数据，禁止用于实际合规判断。" if data.get("demo") else "验船师复核草稿。", ""]
    if pack: lines += [f"知识包：{pack.get('id')}；原文快照日期：{pack.get('snapshot_date')}。",pack.get('update_scope',''),""]
    for s in data["sources"]:
        lines += [f"## {s['id']} {s.get('document_id','')} {s.get('edition','')}", s.get("applicability_reason", "待确认适用性"), f"官方来源：{s.get('official_url','无（演示或项目批准文件）')}", f"缺口：{data['source_errors'].get(s['id']) or '无已记录缺口'}", ""]
    lines += ["## 待办", *[f"- {w}" for w in data["extraction_warnings"]]]
    for i in data["items"]:
        if i["evidence_errors"] or i.get("annotation_error"):
            lines.append(f"- {i['id']}：{'；'.join(i['evidence_errors'])} {i.get('annotation_error','')}")
    (root / "basis-and-gaps.md").write_text("\n".join(lines), encoding="utf-8")
    files = ["review.json", "extraction.json", "checked.json", "annotated.json", data["annotated_file"], "review.xlsx", "basis-and-gaps.md"]
    for s in data["sources"]:
        if s.get("retain_allowed") is True:
            files += [p for p, value in data["source_state"][s["id"]].items() if value not in ("missing", "invalid_path")]
    files = sorted(set(files))
    manifest = {"version": VERSION, "demo": bool(data.get("demo")), "input_sha256": data["input_sha256"], "files": [{"path": n, "sha256": sha(local(root,n))} for n in files], "excluded_sources": [s["id"] for s in data["sources"] if not s.get("retain_allowed")]}
    write(root / "evidence-manifest.json", manifest)
    with zipfile.ZipFile(root / "evidence.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for n in files + ["evidence-manifest.json"]: z.write(local(root,n), n)
    return manifest


def canonical_document(xml):
    from lxml import etree
    root = etree.fromstring(xml)
    for tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
        for node in list(root.iter(f"{{{W}}}{tag}")):
            parent = node.getparent(); parent.remove(node)
    # Recombine only pure text runs with equal formatting, undoing safe splits.
    for p in root.iter(f"{{{W}}}p"):
        previous = None
        for node in list(p):
            if node.tag != f"{{{W}}}r": previous = None; continue
            content = [x for x in node if x.tag != f"{{{W}}}rPr"]
            if not content:
                p.remove(node); continue
            if any(x.tag != f"{{{W}}}t" for x in content): previous = None; continue
            props = node.find(f"{{{W}}}rPr")
            props = etree.tostring(props, method="c14n") if props is not None else b""
            text = "".join(x.text or "" for x in content)
            if previous and previous[1] == props:
                previous[0].text = (previous[0].text or "") + text; p.remove(node)
            else:
                for x in content: node.remove(x)
                t = etree.SubElement(node, f"{{{W}}}t"); t.text = text
                previous = (t, props)
            if previous: previous[0].attrib.clear()
    return etree.tostring(root, method="c14n")


def verify(root):
    from openpyxl import load_workbook
    data = current(root, "annotated.json"); extraction = bind(root)
    source, output = Path(extraction["input"]["path"]), root / data["annotated_file"]
    checks = {"input_hash_unchanged": sha(source) == data["input_sha256"], "annotated_hash": sha(output) == data["annotated_sha256"], "checked_binding": sha(root/"checked.json") == data["annotation_input_sha256"]}
    written = [i for i in data["items"] if i["annotation_status"] == "written"]
    unresolved = [i for i in data["items"] if i["annotation_status"] == "unlocated"]
    note = data.get("unlocated_note", {})
    if source.suffix.lower() == ".docx":
        from docx import Document
        from lxml import etree
        with zipfile.ZipFile(source) as a, zipfile.ZipFile(output) as b:
            checks["body_xml_preserved"] = canonical_document(a.read("word/document.xml")) == canonical_document(b.read("word/document.xml"))
            mutable = {"word/document.xml", "word/comments.xml", "word/_rels/document.xml.rels", "[Content_Types].xml"}
            checks["untouched_parts_preserved"] = all(n in b.namelist() and a.read(n)==b.read(n) for n in a.namelist() if n not in mutable)
            document = etree.fromstring(b.read("word/document.xml"))
            comments = etree.fromstring(b.read("word/comments.xml")) if "word/comments.xml" in b.namelist() else []
            by_id = {c.get(f"{{{W}}}id"): c for c in comments}
            old = etree.fromstring(a.read("word/comments.xml")) if "word/comments.xml" in a.namelist() else []
            checks["old_comments_preserved"] = all(c.get(f"{{{W}}}id") in by_id and etree.tostring(c,method="c14n")==etree.tostring(by_id[c.get(f"{{{W}}}id")],method="c14n") for c in old)
            checks["comment_ids_and_anchors"] = all(i["annotation_id"] in by_id and i["id"] in "".join(by_id[i["annotation_id"]].itertext()) and all(len(document.findall(f".//{{{W}}}{tag}[@{{{W}}}id='{i['annotation_id']}']")) == 1 for tag in ("commentRangeStart", "commentRangeEnd", "commentReference")) for i in written)
            checks["docx_comment_relationship"] = not written or (b"comments" in b.read("word/_rels/document.xml.rels") and b"comments+xml" in b.read("[Content_Types].xml"))
        comments = {str(c.comment_id): c.text for c in Document(output).comments}
        checks["actionable_comment_contents"] = all(comments.get(i["annotation_id"]) == comment_text(i, data) for i in written)
        checks["unlocated_summary_in_document"] = not unresolved or (set(note.get("item_ids", [])) == {i["id"] for i in unresolved} and comments.get(note.get("id")) == unlocated_text(unresolved, data))
        checks["native_layout_review"] = None
    else:
        import pymupdf as fitz
        with fitz.open(source) as a, fitz.open(output) as b:
            checks["page_count"] = len(a)==len(b)
            # Transparent highlights change MuPDF's blending path even with
            # annots=False. Render fresh annotation-free in-memory copies of
            # BOTH documents to compare page content under the same conditions.
            with fitz.open() as clean_a, fitz.open() as clean_b:
                clean_a.insert_pdf(a, annots=False, links=False, widgets=False)
                clean_b.insert_pdf(b, annots=False, links=False, widgets=False)
                checks["body_render_preserved"] = len(a)==len(b) and all(x.get_pixmap(annots=False).samples==y.get_pixmap(annots=False).samples for x,y in zip(clean_a,clean_b))
            checks["pdf_content_streams_preserved"] = len(a)==len(b) and all([a.xref_stream(c) for c in x.get_contents()]==[b.xref_stream(c) for c in y.get_contents()] for x,y in zip(a,b))
            def annotation_snapshot(pdf):
                result = []
                for page in pdf:
                    result.append([{"xref":str(an.xref),"info":an.info,"type":an.type,"rect":list(an.rect)} for an in page.annots() or []])
                return result
            before, after = annotation_snapshot(a), annotation_snapshot(b)
            checks["old_annotations_preserved"] = len(a)==len(b) and all(all(any({k:v for k,v in x.items() if k!="xref"}=={k:v for k,v in y.items() if k!="xref"} for y in after[n]) for x in before[n]) for n in range(len(a)))
            checks["annotation_ids_and_locations"] = all(any(an["xref"]==i["annotation_id"] and an["info"].get("subject")==i["id"] and an["rect"]==i["annotation_location"]["rect"] for an in after[i["annotation_location"]["page"]-1]) for i in written)
            checks["actionable_comment_contents"] = all(any(an.info.get("content") == comment_text(i, data) and an.type[0] == fitz.PDF_ANNOT_HIGHLIGHT and an.has_popup and an.vertices and an.opacity > 0 for an in b[i["annotation_location"]["page"]-1].annots() or [] if str(an.xref) == i["annotation_id"]) for i in written)
            checks["unlocated_summary_in_document"] = not unresolved or (set(note.get("item_ids", [])) == {i["id"] for i in unresolved} and note.get("page") == 1 and any(str(an.xref) == note.get("id") and an.info.get("content") == unlocated_text(unresolved, data) for an in b[0].annots() or []))
    wb = load_workbook(root / "review.xlsx", data_only=False)
    rows = list(wb["审查矩阵"].iter_rows(min_row=2, values_only=True))
    checks["matrix_ids_and_status"] = [(r[0],r[3],r[9]) for r in rows] == [(i["id"],STATUS[i["status"]],ANNOTATION_STATUS[i["annotation_status"]]) for i in data["items"]]
    checks["matrix_follow_up_matches_comments"] = [tuple(row[13:17]) for row in rows] == [tuple(i.get(k) or None for k in ("recipient", "confirmation", "deliverable", "closure_criteria")) for i in data["items"]]
    checks["no_spreadsheet_formulas"] = all(c.data_type != "f" for ws in wb for row in ws for c in row)
    manifest = read(root/"evidence-manifest.json")
    checks["manifest_hashes"] = all(sha(local(root,f["path"]))==f["sha256"] for f in manifest["files"])
    with zipfile.ZipFile(root/"evidence.zip") as z:
        checks["evidence_archive"] = all(hashlib.sha256(z.read(f["path"])).hexdigest()==f["sha256"] for f in manifest["files"])
    report = {"automated_checks_pass": all(v is not False for v in checks.values()), "checks": checks, "written_count": len(written), "summary_count": len(note.get("item_ids", [])), "unlocated": [i["id"] for i in unresolved], "unreviewed": [i["id"] for i in data["items"] if i["annotation_status"] == "not_reviewed"], "pending_evidence": [i["id"] for i in data["items"] if i["evidence_status"]=="pending"], "manual_acceptance": {"WorkBuddy": "not_run", "Word": "not_run", "WPS": "not_run", "PDF_reader": "not_run", "real_reviewed_case": "not_run"}, "release_status": "pilot_only"}
    write(root / "verification.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("extract", "check", "annotate", "export", "verify"):
        p = sub.add_parser(command); p.add_argument("--project", type=Path, required=True)
        if command == "extract":
            p.add_argument("--input", type=Path, required=True); p.add_argument("--output", type=Path)
            p.add_argument("--ocr", choices=("off","auto","on"), default="auto"); p.add_argument("--ocr-sidecar", type=Path)
        if command == "check": p.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    try:
        root = args.project.resolve(); root.mkdir(parents=True, exist_ok=True)
        if args.command == "extract":
            target = args.output or root / "extraction.json"
            if target.resolve() == args.input.resolve(): fail("提取输出不能覆盖输入")
            from contextlib import redirect_stdout
            with redirect_stdout(sys.stderr):
                data = extract_document(args.input, args.ocr, args.ocr_sidecar)
            write(target, data)
            result = {"output": str(target), "blocks": len(data["blocks"]), "warnings": data["warnings"]}
        else:
            result = check(root,args.demo) if args.command == "check" else globals()[args.command](root)
            result = {"command": args.command, "project": str(root), **({"automated_checks_pass":result["automated_checks_pass"]} if args.command=="verify" else {"completed":True})}
        print(json.dumps(result, ensure_ascii=False))
        if args.command == "verify" and not result["automated_checks_pass"]: return 1
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error":str(exc), "command":args.command}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
