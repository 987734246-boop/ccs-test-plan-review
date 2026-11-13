#!/usr/bin/env python3
"""Download an explicitly selected public official source; never marks it full text."""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler

from review import official, sha, write, extract_document


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get(url, allowed):
    from urllib.error import HTTPError
    opener = build_opener(NoRedirect())
    for _ in range(6):
        if url not in allowed and not official(url):
            raise ValueError("重定向至未核实的非官方地址，停止下载: " + url)
        u = urlparse(url)
        if u.scheme != "https" or u.username or u.password or u.port not in (None,443):
            raise ValueError("仅允许公开 HTTPS 资源")
        try:
            response = opener.open(Request(url, headers={"User-Agent":"CCS-Test-Plan-Review/1.0 (public document retrieval)"}), timeout=30)
        except HTTPError as e:
            if e.code in (301,302,303,307,308):
                url = urljoin(url,e.headers["Location"]); continue
            raise
        with response:
            content = response.read(50*1024*1024+1)
            if len(content)>50*1024*1024: raise ValueError("文件超过 50 MiB，改用浏览器在授权范围内获取")
            return content, response.headers.get_content_type(), url
    raise ValueError("重定向次数过多")


def fetch(root, sid, url, page_url):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}",sid): raise ValueError("来源编号非法")
    if not official(page_url): raise ValueError("官方入口不在已核实域名表")
    directory = root / "sources"; directory.mkdir(parents=True,exist_ok=True)
    landing, _, final_page = get(page_url,set())
    landing_path = directory / f"{sid}.landing.html"
    landing_path.write_bytes(landing)
    if not official(url):
        # Check parsed links, not arbitrary text merely mentioning a URL.
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self): super().__init__(); self.links=[]
            def handle_starttag(self,tag,attrs):
                if tag=="a": self.links.extend(urljoin(final_page,v) for k,v in attrs if k=="href" and v)
        links=Links(); links.feed(landing.decode("utf-8",errors="replace"))
        if url not in links.links: raise ValueError("官方页面未链接到指定外部下载地址")
    content, content_type, final = get(url,{url})
    suffix = ".pdf" if content.startswith(b"%PDF-") else ".html" if content_type in ("text/html","application/xhtml+xml") else None
    if suffix is None: raise ValueError("下载结果不是可识别的 PDF/HTML；请检查登录或下载入口")
    path = directory / (sid+suffix); path.write_bytes(content)
    index_path = directory / (sid+".index.json")
    index = extract_document(path,ocr="off"); write(index_path,index)
    source = {"id":sid,"kind":"regulation","document_id":None,"edition":None,"published_date":None,"effective_date":None,"trigger":None,"applicability_reason":None,"official_url":final_page,"download_url":final,"retrieved_at":datetime.now(timezone.utc).isoformat(),"fulltext":False,"edition_confirmed":False,"retain_allowed":False,"path":path.relative_to(root).as_posix(),"sha256":sha(path),"index_path":index_path.relative_to(root).as_posix()}
    if not official(final):
        source["link_proof"]={"path":landing_path.relative_to(root).as_posix(),"sha256":sha(landing_path),"official_url":final_page}
    write(directory/(sid+".registration.json"),source)
    return {"source":source,"warnings":index["warnings"],"next":"阅读正文并核实版次、适用性及留存许可，再将注册记录并入 review.json；发布说明页不是全文。"}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--project",type=Path,required=True); p.add_argument("--id",required=True); p.add_argument("--url",required=True); p.add_argument("--official-page",required=True)
    args=p.parse_args()
    try:
        print(json.dumps(fetch(args.project.resolve(),args.id,args.url,args.official_page),ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error":str(exc),"status":"source_gap"},ensure_ascii=False),file=sys.stderr); sys.exit(2)
