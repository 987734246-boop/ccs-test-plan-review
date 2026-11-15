import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import review as r
import demo


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def project(self,kind="docx"):
        return demo.make_project(self.root/kind,kind)

    def test_units_and_boundaries(self):
        self.assertEqual(r.convert(1,"h","min"),60)
        self.assertEqual(r.convert(0,"C","K"),r.number("273.15"))
        self.assertEqual(r.convert(1,"g","m/s²"),r.number("9.80665"))
        for actual,expected in [("999",False),("1000",True),("1001",True)]:
            ok,trace=r.numeric_check({"actual":actual,"actual_unit":"mV","required_unit":"V","operator":"ge","min":1})
            self.assertEqual(ok,expected)
        with self.assertRaises(ValueError): r.convert(1,"V","min")
        with self.assertRaises(ValueError): r.convert("NaN","V","V")

    def test_range_and_tolerances(self):
        rule={"actual":[1,10],"actual_unit":"Hz","required_unit":"Hz","operator":"range_contains","min":2,"max":8}
        self.assertTrue(r.numeric_check(rule)[0]); rule["actual"]=[3,10]; self.assertFalse(r.numeric_check(rule)[0])
        rule={"actual":"1.05","actual_unit":"V","required_unit":"V","operator":"equal","expected":1,"rel_tolerance":"0.05"}
        self.assertTrue(r.numeric_check(rule)[0]); rule["actual"]="1.051"; self.assertFalse(r.numeric_check(rule)[0])
        rule["rel_tolerance"]=-1
        with self.assertRaises(ValueError): r.numeric_check(rule)

    def test_all_formats_end_to_end(self):
        for kind in ("docx","pdf","scan"):
            with self.subTest(kind=kind):
                p=self.project(kind); result=r.check(p,True)
                statuses={i["id"]:i["status"] for i in result["items"]}
                self.assertEqual(statuses["TA-001"],"deviation")
                self.assertEqual(statuses["TA-002"],"pass")
                self.assertEqual(statuses["TA-003"],"deviation")
                self.assertEqual(statuses["TA-004"],"pending")
                self.assertEqual(statuses["TA-005"],"exempt")
                self.assertEqual(statuses["TA-006"],"pending")
                self.assertEqual(statuses["TA-007"],"pending")
                data=r.annotate(p); r.export(p); report=r.verify(p)
                self.assertTrue(report["automated_checks_pass"],report)
                self.assertIn("TA-004",report["unlocated"])
                self.assertTrue((p/"evidence.zip").is_file())

    def test_demo_not_accepted_as_production(self):
        p=self.project()
        with self.assertRaises(ValueError): r.check(p)
        data=r.read(p/"review.json"); data["demo"]=False; r.write(p/"review.json",data)
        checked=r.check(p)
        self.assertTrue(all(i["status"]=="pending" for i in checked["items"]))

    def test_actionable_notes_survive_in_both_document_formats(self):
        for kind in ("docx", "pdf"):
            with self.subTest(kind=kind):
                p=self.project(kind); data=r.read(p/"review.json"); item=data["items"][0]
                item.update(finding="大纲仅列30 min，示例依据要求至少60 min。", action="将该项时长修订为至少60 min，并说明试验运行状态。",
                            recipient="厂家", confirmation="请确认所选试验分支是否适用于送审型号。", deliverable="修订大纲及相应试验时间表。", closure_criteria="时长和工况有明确记录并经复核。")
                r.write(p/"review.json",data); r.check(p,True); annotated=r.annotate(p); r.export(p); verified=r.verify(p)
                self.assertTrue(verified["automated_checks_pass"],verified)
                item=annotated["items"][0]; expected=r.comment_text(item,annotated)
                if kind=="docx":
                    from docx import Document
                    actual=Document(p/annotated["annotated_file"]).comments.get(int(item["annotation_id"])).text
                else:
                    import pymupdf as fitz
                    with fitz.open(p/annotated["annotated_file"]) as doc:
                        page=doc[0]; note=page.load_annot(int(item["annotation_id"]))
                        actual=note.info["content"]; self.assertTrue(note.has_popup)
                        self.assertEqual(note.type[0],fitz.PDF_ANNOT_HIGHLIGHT)
                self.assertEqual(actual,expected)
                for value in ("30 min", "60 min", "厂家", "运行状态", "试验分支", "试验时间表", "复核关闭条件"):
                    self.assertIn(value,actual)

    def test_pending_note_requests_confirmation_without_asserting_deviation(self):
        p=self.project("pdf"); data=r.read(p/"review.json"); item=data["items"][0]
        item.update(confirmation="请确认控制器安装位置。",deliverable="安装布置图及适用规范版次。")
        item["citations"][0]["source_id"]="MISSING"; r.write(p/"review.json",data)
        checked=r.check(p,True); text=r.comment_text(checked["items"][0],checked)
        self.assertIn("待核实事项",text); self.assertIn("下一步核实",text)
        self.assertIn("安装布置图",text); self.assertIn("当前不作为确定性不符合结论",text)
        self.assertNotIn("实际问题：",text); self.assertNotIn("修改建议：",text)
        r.annotate(p); r.export(p); self.assertTrue(r.verify(p)["automated_checks_pass"])

    def test_scan_uses_highlight_note_without_altering_image(self):
        import pymupdf as fitz
        p=self.project("scan"); r.check(p,True); data=r.annotate(p); r.export(p)
        with fitz.open(p/data["annotated_file"]) as doc:
            page=doc[0]; note=page.load_annot(int(data["items"][0]["annotation_id"]))
            self.assertEqual(note.type[0],fitz.PDF_ANNOT_HIGHLIGHT); self.assertTrue(note.has_popup)
            self.assertEqual(data["items"][0]["annotation_location"]["scope"],"ocr_line_region")
        report=r.verify(p); self.assertTrue(report["automated_checks_pass"],report)
        self.assertTrue(report["checks"]["body_render_preserved"])

    def test_unlocated_items_are_in_document_summary_without_false_anchor(self):
        for kind in ("docx", "pdf"):
            with self.subTest(kind=kind):
                p=self.project(kind); r.check(p,True); data=r.annotate(p); r.export(p); report=r.verify(p)
                self.assertTrue(report["automated_checks_pass"],report)
                item=next(i for i in data["items"] if i["id"]=="TA-004")
                self.assertEqual(item["annotation_status"],"unlocated")
                self.assertNotIn("annotation_location",item)
                self.assertIn("TA-004",data["unlocated_note"]["item_ids"])
                self.assertIn("本备注位置不是问题发生位置",data["unlocated_note"]["text"])
                self.assertGreater(report["summary_count"],0)

    def test_source_index_cannot_invent_quote(self):
        p=self.project(); data=r.read(p/"review.json"); data["demo"]=False
        source=data["sources"][0]; source["kind"]="regulation"; source["official_url"]="https://www.ccs.org.cn/"
        index=r.read(p/source["index_path"]); index["blocks"][1]["text"]="Invented requirement"
        r.write(p/source["index_path"],index); r.write(p/"review.json",data)
        checked=r.check(p)
        self.assertIn("索引内容",checked["source_errors"]["DEMO"])

    def test_missing_fulltext_downgrades_without_blocking_export(self):
        p=self.project(); data=r.read(p/"review.json")
        data["sources"].append({"id":"GAP","kind":"regulation","official_url":"https://www.imo.org/","document_id":"Missing","edition":"Unknown","retrieved_at":"2026-11-13","applicability_reason":"待查","fulltext":False,"path":"sources/not-available.pdf","sha256":"unknown"})
        data["items"][0]["citations"]=[{"source_id":"GAP","clause":"1","quote":"unknown"}]
        r.write(p/"review.json",data); checked=r.check(p,True)
        self.assertEqual(checked["items"][0]["status"],"pending")
        r.annotate(p); r.export(p); self.assertTrue(r.verify(p)["automated_checks_pass"])

    def test_stale_original_is_rejected(self):
        p=self.project(); r.check(p,True)
        with open(p/"input.docx","ab") as f: f.write(b"changed")
        with self.assertRaises(ValueError): r.annotate(p)

    def test_stale_review_is_rejected(self):
        p=self.project(); r.check(p,True); data=r.read(p/"review.json"); data["project"]["submission_version"]="v2"; r.write(p/"review.json",data)
        with self.assertRaises(ValueError): r.annotate(p)

    def test_stale_source_index_is_rejected(self):
        p=self.project(); r.check(p,True)
        with open(p/"sources/synthetic-rules.index.json","a") as f: f.write(" ")
        with self.assertRaises(ValueError): r.annotate(p)

    def test_ambiguous_anchor_and_explicit_offset(self):
        extraction={"blocks":[{"id":"p0","text":"5 V and 5 V","method":"native"}]}
        self.assertIsNotNone(r.locate(extraction,{"quote":"5 V"})[1])
        found,error=r.locate(extraction,{"quote":"5 V","start":8})
        self.assertIsNone(error); self.assertEqual(found["start"],8)

    def test_ocr_requires_visual_confirmation(self):
        p=self.project("scan"); data=r.read(p/"review.json")
        data["items"][0]["anchor"].pop("visual_confirmed")
        r.write(p/"review.json",data); checked=r.check(p,True)
        self.assertEqual(checked["items"][0]["status"],"pending")
        annotated=r.annotate(p); self.assertEqual(annotated["items"][0]["annotation_status"],"unlocated")

    def test_scan_sidecar_hash_mismatch(self):
        p=self.project("scan"); data=r.read(p/"ocr-sidecar.json"); data["input_sha256"]="bad"; r.write(p/"ocr-sidecar.json",data)
        with self.assertRaises(ValueError): r.extract_document(p/"input.pdf",sidecar=p/"ocr-sidecar.json")

    def test_path_escape_and_official_host(self):
        with self.assertRaises(ValueError): r.local(self.root,"../secret.txt")
        self.assertTrue(r.official("https://www.ccs.org.cn/"))
        for url in ("http://www.ccs.org.cn/","https://ccs.org.cn.evil.test/","https://user@ccs.org.cn/","https://127.0.0.1/","https://ccs.org.cn:8080/"):
            self.assertFalse(r.official(url))

    def test_spreadsheet_formula_injection_is_text(self):
        p=self.project(); data=r.read(p/"review.json"); data["items"][0]["finding"]='=HYPERLINK("https://example.test","x")'; r.write(p/"review.json",data)
        r.check(p,True); r.annotate(p); r.export(p)
        from openpyxl import load_workbook
        wb=load_workbook(p/"review.xlsx"); self.assertNotEqual(wb["审查矩阵"]["E2"].data_type,"f")

    def test_retention_excludes_source_and_index(self):
        p=self.project(); data=r.read(p/"review.json"); data["sources"][0]["retain_allowed"]=False; r.write(p/"review.json",data)
        r.check(p,True); r.annotate(p); manifest=r.export(p)
        with zipfile.ZipFile(p/"evidence.zip") as z:
            self.assertFalse(any(n.startswith("sources/") for n in z.namelist()))
        self.assertEqual(manifest["excluded_sources"],["DEMO"])

    def test_duplicate_ids_rejected(self):
        p=self.project(); data=r.read(p/"review.json"); data["items"][1]["id"]=data["items"][0]["id"]; r.write(p/"review.json",data)
        with self.assertRaises(ValueError): r.check(p,True)

    def test_missing_item_requires_full_document_check(self):
        p=self.project(); data=r.read(p/"review.json"); data["items"][2]["whole_document_checked"]=False; r.write(p/"review.json",data)
        self.assertEqual(r.check(p,True)["items"][2]["status"],"pending")

    def test_manifest_detects_changed_matrix(self):
        p=self.project(); r.check(p,True); r.annotate(p); r.export(p)
        from openpyxl import load_workbook
        wb=load_workbook(p/"review.xlsx"); wb["审查矩阵"]["A2"]="ALTERED"; wb.save(p/"review.xlsx")
        report=r.verify(p); self.assertFalse(report["automated_checks_pass"]); self.assertFalse(report["checks"]["matrix_ids_and_status"])

    def test_complex_docx_anchor_refuses_without_changing_body(self):
        p=self.project()
        from docx import Document
        doc=Document(p/"input.docx"); doc.paragraphs[1].text="Vibration:\t30 min"; doc.save(p/"input.docx")
        extraction=r.extract_document(p/"input.docx"); r.write(p/"extraction.json",extraction)
        data=r.read(p/"review.json"); data["input_sha256"]=r.sha(p/"input.docx"); data["items"][0]["anchor"]={"quote":"Vibration:\t30 min"}; r.write(p/"review.json",data)
        r.check(p,True); annotated=r.annotate(p); r.export(p)
        self.assertEqual(annotated["items"][0]["annotation_status"],"unlocated")
        self.assertTrue(r.verify(p)["checks"]["body_xml_preserved"])

    def test_nested_merged_tables_and_cross_page_pdf(self):
        from docx import Document
        doc=Document(); table=doc.add_table(rows=2,cols=2); table.cell(0,0).merge(table.cell(0,1)).text="Merged label"
        nested=table.cell(1,0).add_table(rows=1,cols=1); nested.cell(0,0).text="Nested parameter"
        file=self.root/"nested.docx"; doc.save(file); ext=r.extract_document(file)
        self.assertEqual(sum(b["text"]=="Merged label" for b in ext["blocks"]),1)
        self.assertEqual(sum(b["text"]=="Nested parameter" for b in ext["blocks"]),1)
        import pymupdf as fitz
        file=self.root/"cross-page.pdf"
        with fitz.open() as pdf:
            pdf.new_page().insert_text((50,50),"Repeated table row")
            pdf.new_page().insert_text((50,50),"Repeated table row")
            pdf.save(file)
        ext=r.extract_document(file)
        self.assertIsNotNone(r.locate(ext,{"quote":"Repeated table row"})[1])
        self.assertIsNone(r.locate(ext,{"quote":"Repeated table row","page":2})[1])

    def test_version_unconfirmed_and_conflict_remain_pending(self):
        p=self.project(); data=r.read(p/"review.json"); data["sources"][0]["edition_confirmed"]=False
        data["items"][0]["applicability"]={"confirmed":False,"reason":"新旧版过渡条件冲突待核实"}; r.write(p/"review.json",data)
        checked=r.check(p,True)
        self.assertEqual(checked["items"][0]["status"],"pending")
        self.assertIn("项目适用性尚未确认",checked["items"][0]["evidence_errors"])

    def test_model_must_verify_numeric_transcription(self):
        p=self.project(); data=r.read(p/"review.json"); data["items"][0]["numeric"]["values_verified"]=False; r.write(p/"review.json",data)
        self.assertEqual(r.check(p,True)["items"][0]["status"],"pending")

    def test_external_download_requires_actual_official_link(self):
        p=self.project(); data=r.read(p/"review.json"); source=data["sources"][0]
        source.update(kind="regulation",official_url="https://www.ccs.org.cn/publication",download_url="https://cdn.example.test/rules.pdf")
        landing=p/"sources/landing.html"; landing.write_text('URL mentioned: https://cdn.example.test/rules.pdf',encoding="utf-8")
        source["link_proof"]={"path":"sources/landing.html","sha256":r.sha(landing),"official_url":source["official_url"]}
        self.assertIn("链接证明",r.validate_source(p,source,False))
        landing.write_text('<a href="https://cdn.example.test/rules.pdf">Download</a>',encoding="utf-8"); source["link_proof"]["sha256"]=r.sha(landing)
        self.assertIsNone(r.validate_source(p,source,False))

    def test_rotated_and_cropped_pdf_coordinates(self):
        import pymupdf as fitz
        file=self.root/"cropped.pdf"
        with fitz.open() as pdf:
            page=pdf.new_page(width=595,height=842); page.insert_text((50,50),"Cropped parameter: 30 min")
            page.set_cropbox(fitz.Rect(10,20,500,700)); page.set_rotation(90); pdf.save(file)
        extraction=r.extract_document(file)
        self.assertEqual(len(extraction["blocks"]),1)
        found,error=r.locate(extraction,{"quote":"30 min"})
        self.assertIsNone(error); self.assertEqual(found["block"]["page"],1)

    def test_string_boolean_does_not_verify_numeric_values(self):
        p=self.project(); data=r.read(p/"review.json"); data["items"][0]["numeric"]["values_verified"]="false"; r.write(p/"review.json",data)
        self.assertEqual(r.check(p,True)["items"][0]["status"],"pending")


if __name__=="__main__": unittest.main()
