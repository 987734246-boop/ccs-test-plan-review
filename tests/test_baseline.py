import copy
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import baseline as b
import review as r
import demo


class BaselineTests(unittest.TestCase):
    def setUp(self):
        import pymupdf as fitz
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.pdf = self.root / "synthetic-baseline.pdf"
        with fitz.open() as pdf:
            p = pdf.new_page()
            p.insert_text((50, 60), "GD019-2024", fontsize=12)
            p.insert_text((50, 90), "电气电子产品型式认可试验指南", fontname="china-s", fontsize=12)
            p.insert_text((50, 120), "2024年10月1日生效", fontname="china-s", fontsize=12)
            pdf.new_page().insert_text((50, 60), "Synthetic requirement. NOT regulatory text.")
            pdf.save(self.pdf)
        self.spec = copy.deepcopy(b.profile())
        self.known_updates = copy.deepcopy(self.spec.get("known_updates", []))
        self.spec["known_updates"] = []
        self.spec.update(verified_sha256=r.sha(self.pdf), page_count=2,
                         navigation=[{"clause":"Example", "pdf_pages":[2], "purpose":"synthetic"}])
        self.url = self.spec["observed_download_url"]
        self.landing = f'<a href="{self.url}">《电气电子产品型式认可试验指南》2024.pdf</a>'
        self.library = self.root / "library"
        self.mock = patch.object(b, "profile", return_value=self.spec); self.mock.start()

    def tearDown(self):
        self.mock.stop(); self.temp.cleanup()

    def install(self):
        return b.install_pdf(self.pdf, self.landing, self.url, self.library)

    def test_official_link_discovery_and_ambiguity(self):
        relative = '<a href="/ccswz/file/download?fileid=202409130920006728"><span>《电气电子产品型式认可试验指南》2024.pdf</span></a>'
        self.assertEqual(b.resolve_download(relative, self.spec["official_url"], self.spec), self.url)
        for html in ("publication only", self.landing + self.landing.replace("202409130920006728", "other"), self.landing.replace("2024.pdf", "2015.pdf")):
            with self.assertRaises(ValueError): b.resolve_download(html, self.spec["official_url"], self.spec)

    def test_download_cache_and_explicit_refresh(self):
        responses=[(self.landing.encode(),"text/html",self.spec["official_url"]), (self.pdf.read_bytes(),"application/pdf",self.url)]
        with patch.object(b,"get",side_effect=responses) as get:
            first=b.download(self.library); self.assertEqual(get.call_count,2)
        with patch.object(b,"get",side_effect=AssertionError("cache must avoid network")):
            second=b.download(self.library)
        self.assertEqual(first["sha256"],second["sha256"])
        with patch.object(b,"get",side_effect=responses) as get:
            b.download(self.library,refresh=True); self.assertEqual(get.call_count,2)

    def test_changed_official_pdf_does_not_overwrite_baseline(self):
        self.install(); original=b.load(self.library)[0]
        with patch.object(b,"get",side_effect=[(self.landing.encode(),"text/html",self.spec["official_url"]), (self.pdf.read_bytes()+b"changed","application/pdf",self.url)]):
            with self.assertRaisesRegex(ValueError,"哈希"): b.download(self.library,refresh=True)
        self.assertEqual(b.load(self.library)[0],original)

    def test_html_cannot_be_accepted_as_pdf(self):
        with patch.object(b,"get",side_effect=[(self.landing.encode(),"text/html",self.spec["official_url"]),(b"<html>Login</html>","text/html",self.url)]):
            with self.assertRaisesRegex(ValueError,"PDF"): b.download(self.library)

    def test_pinned_hash_not_enough_for_wrong_cover(self):
        self.spec["title"]="wrong title"
        with self.assertRaisesRegex(ValueError,"封面"): b.inspect_pdf(self.pdf,self.spec)

    def test_cached_file_tampering_is_detected(self):
        for key in ("path","index_path","landing_path"):
            with self.subTest(key=key):
                folder=self.root/key; b.install_pdf(self.pdf,self.landing,self.url,folder)
                manifest, directory, _=b.load(folder)
                target=directory/manifest[key]; target.write_bytes(target.read_bytes()+b"changed")
                with self.assertRaisesRegex(ValueError,"已变化"): b.load(folder)

    def test_attach_snapshots_and_preserves_existing_items(self):
        self.install(); project=demo.make_project(self.root/"project","docx")
        before=r.read(project/"review.json"); source=b.attach(project,self.library,"Explicit 2024 project choice; synthetic test")
        self.assertEqual(r.read(project/"review.json")["items"],before["items"])
        self.assertEqual(r.sha(project/source["path"]),self.spec["verified_sha256"])
        self.assertEqual(source["update_review"]["status"],"pending")
        self.assertIsNotNone(r.validate_source(project,source,True))
        b.attach(project,self.library,"Repeated attach")
        self.assertEqual(len(r.read(project/"review.json")["sources"]),2)
        _, cached, _=b.load(self.library)
        (cached/"GD019-2024.pdf").write_bytes(b"changed")
        self.assertEqual(r.sha(project/source["path"]),self.spec["verified_sha256"])

    def test_verified_project_update_review_and_snapshot_integrity(self):
        self.install(); project=demo.make_project(self.root/"project","docx")
        source=b.attach(project,self.library,"Project has selected the 2024 edition")
        source["update_review"]={"status":"verified","checked_at":datetime.now(timezone.utc).isoformat(),"official_urls":[self.spec["official_url"]],"note":"Synthetic test of actual-review recording, not a real update search"}
        self.assertIsNone(r.validate_source(project,source,True))
        index=r.read(project/source["index_path"]); index["blocks"][0]["text"]="Invented"; r.write(project/source["index_path"],index)
        self.assertIsNotNone(r.validate_source(project,source,True))

    def test_missing_or_invalid_update_record_stays_pending(self):
        self.install(); project=demo.make_project(self.root/"project","docx")
        source=b.attach(project,self.library,"2024 edition selected")
        for record in ({}, {"status":"verified"}, {"status":"verified","checked_at":"bad","official_urls":[self.spec["official_url"]],"note":"test"}, {"status":"verified","checked_at":"2026-01-01T00:00:00Z","official_urls":["https://untrusted.example/"],"note":"test"}):
            source["update_review"]=record
            self.assertIsNotNone(r.validate_source(project,source,True))

    def test_project_source_manifest_in_change_detection(self):
        self.install(); project=demo.make_project(self.root/"project","docx")
        source=b.attach(project,self.library,"2024 edition selected")
        r.check(project,True)
        path=project/source["baseline"]["manifest_path"]; path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError,"依据内容已变化"): r.annotate(project)

    def test_attach_requires_reason_and_refuses_conflicting_source(self):
        self.install(); project=demo.make_project(self.root/"project","docx")
        with self.assertRaises(ValueError): b.attach(project,self.library," ")
        b.attach(project,self.library,"2024 selected")
        data=r.read(project/"review.json"); data["sources"][-1]["sha256"]="different"; r.write(project/"review.json",data)
        with self.assertRaisesRegex(ValueError,"禁止覆盖"): b.attach(project,self.library,"reason")

    def test_search_page_and_render_use_physical_pages(self):
        self.install()
        found=b.search(self.library,"Syntheticrequirement")
        self.assertEqual(found["matches"],1); self.assertEqual(found["hits"][0]["page"],2)
        output=self.root/"preview.png"; page=b.page(self.library,2,output)
        self.assertTrue(output.is_file()); self.assertEqual(page["pdf_page"],2)
        self.assertEqual(page["blocks"][0]["text"],"Synthetic requirement. NOT regulatory text.")
        with self.assertRaises(ValueError): b.page(self.library,3)

    def test_transient_download_retry_is_bounded(self):
        from urllib.error import HTTPError
        error=HTTPError(self.url,502,"Bad Gateway",{},None)
        with patch.object(b,"get",side_effect=[error,(b"ok","text/html",self.url)]) as get, patch.object(b.time,"sleep"):
            self.assertEqual(b.retrieve(self.url)[0],b"ok"); self.assertEqual(get.call_count,2)
        with patch.object(b,"get",side_effect=error) as get, patch.object(b.time,"sleep"):
            with self.assertRaises(HTTPError): b.retrieve(self.url)
            self.assertEqual(get.call_count,3)

    def test_known_notice_receipt_date_boundary_and_citation(self):
        self.spec["known_updates"]=self.known_updates
        self.install(); project=demo.make_project(self.root/"project","docx")
        source=b.attach(project,self.library,"2024 edition selected")
        notice=self.known_updates[0]; file=project/"sources/notice-fixture.txt"
        file.write_text("Synthetic notice date fixture, not a real regulatory requirement",encoding="utf-8")
        r.write(project/"sources/notice-fixture.index.json",r.extract_document(file))
        notice_source={"id":notice["id"],"kind":"regulation","document_id":"Synthetic notice","edition":"2026-03-23","official_url":notice["official_url"],"retrieved_at":datetime.now(timezone.utc).isoformat(),"applicability_reason":"Unit test fixture only","fulltext":True,"edition_confirmed":True,"path":"sources/notice-fixture.txt","sha256":r.sha(file),"index_path":"sources/notice-fixture.index.json"}
        data=r.read(project/"review.json"); data["sources"].append(notice_source)
        source["update_review"].update(status="verified",checked_at=datetime.now(timezone.utc).isoformat(),official_urls=[self.spec["official_url"],notice["official_url"]],note="Testing only")
        for date,disposition in (("2025-12-31","not_applicable"),("2026-01-01","applies"),("2026-04-01","applies")):
            with self.subTest(date=date):
                data["project"]["ccs_received_date"]=date
                source["update_review"]["known_updates"]=[{"id":notice["id"],"disposition":disposition,"reason":"Test of receipt-date routing","anchor":{"block_id":"line0","quote":file.read_text(encoding="utf-8")}}]
                r.write(project/"review.json",data)
                self.assertIsNone(r.validate_source(project,source,True))
        source["update_review"]["known_updates"][0]["disposition"]="not_applicable"
        self.assertIn("收件日期",r.validate_source(project,source,True))
        data["project"]["ccs_received_date"]=None; r.write(project/"review.json",data)
        self.assertIn("缺少CCS",r.validate_source(project,source,True))
        data["project"]["ccs_received_date"]="2026-01-01"; data["sources"].pop(); r.write(project/"review.json",data)
        source["update_review"]["known_updates"][0]["disposition"]="applies"
        self.assertIn("缺少已知",r.validate_source(project,source,True))


if __name__=="__main__": unittest.main()
