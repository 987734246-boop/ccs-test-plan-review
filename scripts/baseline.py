#!/usr/bin/env python3
"""Download, verify, search and snapshot the pinned official GD 019 baseline."""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError

import review as r
from fetch_source import get

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = SKILL_ROOT / "local-baselines"


def profile():
    return r.read(SKILL_ROOT / "references/gd019-2024.json")


def retrieve(url):
    for attempt in range(3):
        try:
            return get(url, set())
        except (HTTPError, URLError, TimeoutError) as exc:
            transient = not isinstance(exc, HTTPError) or exc.code in (429, 502, 503, 504)
            if not transient or attempt == 2: raise
            time.sleep(attempt + 1)


def compact(text):
    return re.sub(r"\s+", "", text).replace("－", "-")


def resolve_download(html, page_url, spec):
    class Links(HTMLParser):
        def __init__(self):
            super().__init__(); self.active = None; self.matches = []
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.active = [dict(attrs).get("href", ""), ""]
        def handle_data(self, text):
            if self.active is not None: self.active[1] += text
        def handle_endtag(self, tag):
            if tag == "a" and self.active is not None:
                href, label = self.active; self.active = None
                if spec["title"] in compact(label) and spec["edition"] in label:
                    self.matches.append(urljoin(page_url, href))
    links = Links(); links.feed(html)
    matches = sorted(set(u for u in links.matches if r.official(u)))
    if len(matches) != 1:
        raise ValueError("官方页面未找到唯一的指定版次 PDF 附件；保留原基准并人工检查页面")
    return matches[0]


def inspect_pdf(path, spec):
    import pymupdf as fitz
    if r.sha(path) != spec["verified_sha256"]:
        raise ValueError("GD 019 正文哈希与已核验基准不同；不得静默覆盖，须另行核实官方文件变更")
    with fitz.open(path) as pdf:
        if pdf.needs_pass or len(pdf) != spec["page_count"]:
            raise ValueError("GD 019 正文加密或页数不符")
        cover = compact(pdf[0].get_text())
        if "GD019-2024" not in cover or spec["title"] not in cover or "2024年10月1日生效" not in cover:
            raise ValueError("封面编号、标题或生效日期未匹配 GD019-2024")
    index = r.extract_document(path, ocr="off")
    if index["warnings"] or {b["page"] for b in index["blocks"]} != set(range(1, spec["page_count"] + 1)):
        raise ValueError("GD 019 提取不完整；需补齐未读取页后再建立基准")
    return index


def install_pdf(pdf, landing, url, library, retrieved_at=None):
    """Validate in staging, then create an immutable content-addressed baseline."""
    spec = profile(); library = Path(library).resolve()
    if not r.official(url) or resolve_download(landing, spec["official_url"], spec) != url:
        raise ValueError("下载地址未被指定官方发布页的附件链接确认")
    index = inspect_pdf(pdf, spec)
    folder = library / spec["id"] / spec["verified_sha256"][:12]
    if folder.exists():
        return load(library)[0]
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=folder.parent))
    try:
        target = staging / "GD019-2024.pdf"
        shutil.copyfile(pdf, target)
        index["input"]["path"] = "GD019-2024.pdf"
        r.write(staging / "index.json", index)
        (staging / "official-page.html").write_text(landing, encoding="utf-8")
        manifest = {
            "schema_version": 1, "id": spec["id"], "document_id": spec["document_id"],
            "edition": spec["edition"], "title": spec["title"], "official_url": spec["official_url"],
            "download_url": url, "published_date": spec["published_date"], "effective_date": spec["effective_date"],
            "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
            "path": "GD019-2024.pdf", "sha256": r.sha(target), "index_path": "index.json",
            "index_sha256": r.sha(staging / "index.json"), "landing_path": "official-page.html",
            "landing_sha256": r.sha(staging / "official-page.html"), "page_count": spec["page_count"],
            "fulltext": True, "edition_confirmed": True,
            "version_note": "已核对2024版正文身份；不代表已核对本项目所有新通告或自动判定适用性",
            "navigation": spec["navigation"]
        }
        r.write(staging / "baseline.json", manifest)
        staging.rename(folder)
    except Exception:
        # Leave a failed staging directory for inspection; never delete source or existing baselines.
        raise
    return load(library)[0]


def download(library=DEFAULT_LIBRARY, refresh=False):
    spec = profile()
    library = Path(library).resolve()
    existing = library / spec["id"] / spec["verified_sha256"][:12] / "baseline.json"
    if existing.exists() and not refresh:
        return load(library)[0]
    raw, _, final_page = retrieve(spec["official_url"])
    if final_page != spec["official_url"]:
        raise ValueError("官方发布页重定向变化，先人工核对入口")
    landing = raw.decode("utf-8-sig")
    url = resolve_download(landing, final_page, spec)
    content, _, final = retrieve(url)
    if not content.startswith(b"%PDF-") or not r.official(final):
        raise ValueError("官方附件未返回 PDF 正文；不以 HTML/登录页替代")
    library = Path(library).resolve(); library.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gd019-download-", dir=library) as temporary:
        path = Path(temporary) / "download.pdf"; path.write_bytes(content)
        return install_pdf(path, landing, url, library)


def load(library=DEFAULT_LIBRARY):
    spec = profile()
    folder = Path(library).resolve() / spec["id"] / spec["verified_sha256"][:12]
    manifest = r.read(folder / "baseline.json")
    for key in ("id", "edition", "document_id", "page_count"):
        if manifest.get(key) != spec[key]: raise ValueError("本地基准登记信息不符: " + key)
    if manifest.get("sha256") != spec["verified_sha256"]:
        raise ValueError("本地基准登记哈希不符")
    for file_key, hash_key in (("path", "sha256"), ("index_path", "index_sha256"), ("landing_path", "landing_sha256")):
        if r.sha(r.local(folder, manifest[file_key])) != manifest[hash_key]:
            raise ValueError("本地基准文件已变化: " + file_key)
    index = r.read(r.local(folder, manifest["index_path"]))
    if index["input"]["sha256"] != spec["verified_sha256"]:
        raise ValueError("本地提取索引与正文不符")
    return manifest, folder, index


def validate_project_source(root, source):
    """Check the pinned edition and this project's separate update-review record."""
    spec = profile()
    if any(source.get(k) != spec[k] for k in ("id", "document_id", "edition", "official_url")) or source.get("sha256") != spec["verified_sha256"]:
        return "项目本地基准的编号、版次、入口或正文哈希与已核验GD019不符"
    try:
        manifest_path = r.local(root, source["baseline"]["manifest_path"])
        manifest = r.read(manifest_path)
        if source["baseline"].get("profile_id") != spec["id"] or manifest.get("sha256") != spec["verified_sha256"]:
            return "项目基准清单与正文身份不符"
        if r.sha(r.local(root, source["index_path"])) != manifest["index_sha256"]:
            return "项目基准索引哈希不符"
        landing = r.local(manifest_path.parent, manifest["landing_path"])
        if r.sha(landing) != manifest["landing_sha256"]:
            return "项目官方发布页快照哈希不符"
    except (OSError, ValueError, KeyError):
        return "项目缺少可核对的本地基准清单/官方页面"
    update = source.get("update_review", {})
    if update.get("status") != "verified" or not update.get("note") or not update.get("checked_at") or not update.get("official_urls"):
        return "本项目尚未完成GD019修订、通告及适用版次核查（可继续本地对照）"
    try:
        when = datetime.fromisoformat(update["checked_at"].replace("Z", "+00:00"))
        if when.tzinfo is None or when > datetime.now(timezone.utc): raise ValueError("核查时间无效")
        if not all(r.official(url) for url in update["official_urls"]): raise ValueError("非官方核查入口")
    except (ValueError, TypeError, AttributeError):
        return "本项目基准更新核查的时间或官方入口无效"
    known = spec.get("known_updates", [])
    if known:
        review = r.read(Path(root) / "review.json")
        received = review.get("project", {}).get("ccs_received_date")
        try:
            received_date = datetime.strptime(received, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return "缺少CCS收到认可申请相关文件的日期，不能判断2026年UR E10 Rev.10通告适用性"
        decisions = {d.get("id"):d for d in update.get("known_updates", [])}
        all_sources = {s["id"]:s for s in review.get("sources", [])}
        for notice in known:
            decision = decisions.get(notice["id"], {})
            expected = "applies" if received_date >= datetime.strptime(notice["received_on_or_after"], "%Y-%m-%d").date() else "not_applicable"
            if decision.get("disposition") != expected or not decision.get("reason"):
                return "已知UR E10 Rev.10通告尚未按CCS收件日期正确判断或说明适用性"
            notice_source = all_sources.get(notice["id"])
            if not notice_source or notice_source.get("baseline") or notice_source.get("kind") != "regulation" or notice_source.get("official_url") != notice["official_url"]:
                return "缺少已知UR E10 Rev.10通告的正式原文来源"
            if r.validate_source(root, notice_source, False):
                return "已知UR E10 Rev.10通告原文证据未核实"
            notice_index = r.read(r.local(root, notice_source["index_path"]))
            _, error = r.locate(notice_index, decision.get("anchor", {}))
            if error: return "通告适用性记录缺少准确原文引用"
    return None


def attach(project, library, reason):
    """Copy verified local evidence into a project; never reference a mutable shared file."""
    if not reason.strip(): raise ValueError("须提供本项目选用2024版的理由")
    manifest, folder, index = load(library)
    root = Path(project).resolve(); root.mkdir(parents=True, exist_ok=True)
    if (root / "review.json").exists():
        review = r.read(root / "review.json")
    else:
        extraction = r.bind(root)
        review = r.read(SKILL_ROOT / "templates/review.json")
        review["input_sha256"] = extraction["input"]["sha256"]
    previous = next((s for s in review["sources"] if s["id"] == manifest["id"]), None)
    if previous:
        if previous.get("sha256") != manifest["sha256"]:
            raise ValueError("项目中已有同名但不同内容的依据；禁止覆盖")
        if r.source_state(root, previous).get(previous.get("path")) != manifest["sha256"]:
            raise ValueError("项目既有依据文件缺失或变化；禁止覆盖")
        return previous
    destination = root / "sources" / (manifest["id"] + "-" + manifest["sha256"][:12])
    if destination.exists():
        raise ValueError("项目基准目录已存在但未登记；先核对文件，禁止覆盖")
    destination.mkdir(parents=True)
    for key in ("path", "index_path", "landing_path"):
        shutil.copyfile(r.local(folder, manifest[key]), destination / manifest[key])
    index["input"]["path"] = manifest["path"]
    r.write(destination / "index.json", index)
    # Manifest is adjusted for the project's relative index; PDF bytes remain identical.
    project_manifest = copy.deepcopy(manifest)
    project_manifest["index_sha256"] = r.sha(destination / "index.json")
    r.write(destination / "baseline.json", project_manifest)
    relative = destination.relative_to(root).as_posix()
    source = {k: manifest[k] for k in ("id", "document_id", "edition", "title", "published_date", "effective_date", "official_url", "download_url", "retrieved_at", "sha256", "fulltext", "edition_confirmed")}
    source.update(kind="regulation", path=relative + "/" + manifest["path"], index_path=relative + "/index.json",
                  trigger="按项目条件及适用条款核实，不仅依据发布日期", applicability_reason=reason,
                  retain_allowed=False, baseline={"profile_id":manifest["id"], "manifest_path":relative + "/baseline.json"},
                  update_review={"status":"pending", "checked_at":None, "official_urls":[], "note":"待核对本项目修订、通告及过渡要求；离线可对照，确定性结论暂保留为待核实", "known_updates":[{"id":n["id"], "official_url":n["official_url"], "disposition":"pending", "reason":"", "anchor":{}} for n in profile().get("known_updates", [])]})
    review["sources"].append(source)
    r.write(root / "review.json", review)
    return source


def search(library, query, limit=20):
    manifest, _, index = load(library)
    if not query.strip(): raise ValueError("检索词不能为空")
    hits = [b for b in index["blocks"] if compact(query) in compact(b["text"])]
    return {"baseline_id":manifest["id"], "sha256":manifest["sha256"], "matches":len(hits), "hits":hits[:limit],
            "navigation":[n for n in manifest["navigation"] if compact(query) in compact(n["clause"])]}


def page(library, number, render=None):
    manifest, folder, index = load(library)
    if not 1 <= number <= manifest["page_count"]: raise ValueError("PDF 页码越界")
    if render:
        import pymupdf as fitz
        output = Path(render).resolve()
        if output.suffix.lower() != ".png": raise ValueError("原页预览必须输出 PNG")
        if output.is_relative_to(folder): raise ValueError("原页预览不得写入只读基准目录")
        output.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open(r.local(folder, manifest["path"])) as pdf:
            pdf[number - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), annots=False).save(output)
    return {"baseline_id":manifest["id"], "pdf_page":number, "printed_page":number-2 if number>=3 else None,
            "blocks":[b for b in index["blocks"] if b["page"]==number], "render":str(render) if render else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("download"); d.add_argument("--refresh", action="store_true")
    sub.add_parser("verify")
    a = sub.add_parser("attach"); a.add_argument("--project", type=Path, required=True); a.add_argument("--reason", required=True)
    s = sub.add_parser("search"); s.add_argument("--query", required=True); s.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("page"); p.add_argument("--page", type=int, required=True); p.add_argument("--render", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "download": result = download(args.library, args.refresh)
        elif args.command == "verify": result = load(args.library)[0]
        elif args.command == "attach": result = attach(args.project, args.library, args.reason)
        elif args.command == "search":
            if not 1 <= args.limit <= 100: raise ValueError("limit 须为1至100")
            result = search(args.library, args.query, args.limit)
        else: result = page(args.library, args.page, args.render)
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (OSError, ValueError, KeyError, ImportError) as exc:
        print(json.dumps({"error":str(exc), "command":args.command}, ensure_ascii=False), file=sys.stderr); return 2


if __name__ == "__main__": sys.exit(main())
