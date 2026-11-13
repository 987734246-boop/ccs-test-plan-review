#!/usr/bin/env python3
"""Create synthetic regression examples; values are NOT regulatory requirements."""
import argparse
import copy
import json
from pathlib import Path
from datetime import datetime, timezone

import review as r


def make_project(root, kind):
    from docx import Document
    import pymupdf as fitz
    root.mkdir(parents=True,exist_ok=True)
    lines = ["Synthetic electrical test plan", "Vibration: 30 min", "Voltage: 1000 mV", "Repeated parameter: 5 V", "Repeated parameter: 5 V", "Test schedule", "Camera inclination: waived", "Controller inclination: waived"]
    if kind=="docx":
        doc=Document(); doc.add_paragraph(lines[0],style="Title")
        for line in lines[1:6]: doc.add_paragraph(line)
        table=doc.add_table(rows=2,cols=1); table.style="Table Grid"
        for cell,line in zip([table.cell(0,0),table.cell(1,0)],lines[6:]): cell.text=line
        doc.add_comment(doc.paragraphs[1].runs,text="Existing manufacturer comment",author="Manufacturer")
        file=root/"input.docx"; doc.save(file)
    else:
        file=root/"input.pdf"
        with fitz.open() as doc:
            page=doc.new_page(width=595,height=842)
            for i,line in enumerate(lines): page.insert_text((50,60+i*55),line,fontsize=12)
            old=page.add_text_annot((500,80),"Existing manufacturer comment"); old.update()
            if kind=="scan":
                pix=page.get_pixmap(matrix=fitz.Matrix(2,2),annots=False)
                with fitz.open() as scan:
                    dest=scan.new_page(width=595,height=842); dest.insert_image(dest.rect,stream=pix.tobytes("png")); scan.save(file)
                sidecar={"input_sha256":r.sha(file),"blocks":[{"page":1,"text":line,"bbox":[49,47+i*55,480,65+i*55],"coordinate_space":"unrotated_pdf_points","confidence":1.0} for i,line in enumerate(lines)]}
                r.write(root/"ocr-sidecar.json",sidecar)
            else: doc.save(file)
    extraction=r.extract_document(file,ocr="off",sidecar=root/"ocr-sidecar.json" if kind=="scan" else None)
    r.write(root/"extraction.json",extraction)
    sources=root/"sources"; sources.mkdir(exist_ok=True)
    rule=sources/"synthetic-rules.txt"
    rule.write_text("SYNTHETIC EXAMPLE ONLY - NOT CCS, IMO OR IACS REQUIREMENTS\nR1: Duration shall be at least 60 min.\nR2: Voltage shall equal 1 V.\nR3: Humidity test shall be listed.\nR4: Camera inclination may be waived for this sample only.\nR5: Controller inclination shall be tested.\n",encoding="utf-8")
    r.write(sources/"synthetic-rules.index.json",r.extract_document(rule))
    source={"id":"DEMO","kind":"synthetic","document_id":"SYNTHETIC-NOT-REGULATION","edition":"Example 1","published_date":None,"effective_date":None,"trigger":"构造案例","applicability_reason":"仅验证工具行为，不能用于合规判断","retrieved_at":datetime.now(timezone.utc).isoformat(),"fulltext":True,"edition_confirmed":True,"retain_allowed":True,"path":"sources/synthetic-rules.txt","sha256":r.sha(rule),"index_path":"sources/synthetic-rules.index.json"}
    def anchor(text,unique=True):
        matching=[b for b in extraction["blocks"] if text in b["text"]]
        a={"quote":text}
        if unique and matching: a["block_id"]=matching[0]["id"]
        if kind=="scan": a.update(visual_confirmed=True,confirmation_note="构造图像与坐标逐项对应，仅用于自动测试")
        return a
    rule_lines=rule.read_text(encoding="utf-8").splitlines()
    def item(id,test,text,n,**extra):
        return {"id":id,"equipment":"Controller","test":test,"proposed_status":"deviation","applicability":{"confirmed":True,"reason":"构造案例匹配"},"anchor":anchor(text),"citations":[{"source_id":"DEMO","clause":f"R{n}","block_id":f"line{n}","quote":rule_lines[n]}],"finding":"构造案例："+test+"存在需处理内容","action":"按构造依据修订；这些数值不是正式法规要求",**extra}
    items=[
        item("TA-001","Duration","30 min",1,numeric={"actual":30,"actual_unit":"min","required_unit":"min","operator":"ge","min":60,"values_verified":True}),
        item("TA-002","Voltage","1000 mV",2,proposed_status="pass",finding="构造案例：1000 mV 换算为 1 V，与示例要求一致",action="本示例项无需修改",numeric={"actual":1000,"actual_unit":"mV","required_unit":"V","operator":"equal","expected":1,"values_verified":True}),
        item("TA-003","Humidity","Test schedule",3,missing_item=True,whole_document_checked=True),
        item("TA-004","Repeated","5 V",2,anchor=anchor("5 V",False)),
        item("TA-005","Inclination","Camera inclination",4,equipment="Camera",proposed_status="exempt",finding="构造案例：仅 Camera 的 Inclination 被示例依据免除",action="仅在所列构造条件内记录免除",exemption={"equipment":"Camera","tests":["Inclination"],"conditions":"仅本构造案例","approval_source_id":"DEMO"}),
        item("TA-006","Inclination","Controller inclination",5,proposed_status="exempt",exemption={"equipment":"Camera","tests":["Inclination"],"conditions":"仅本构造案例","approval_source_id":"DEMO"}),
        item("TA-007","Unavailable basis","Test schedule",3,citations=[{"source_id":"MISSING","clause":"unknown","quote":"unknown"}])
    ]
    review={"schema_version":1,"demo":True,"input_sha256":extraction["input"]["sha256"],"project":{"product_model":"DEMO Controller","submission_version":"Synthetic v1","note":"全部为构造案例；不含真实法规限值"},"sources":[source],"items":items}
    r.write(root/"review.json",review)
    return root


def run(output):
    results={}
    for kind in ("docx","pdf","scan"):
        root=make_project(output/kind,kind); r.check(root,demo=True); r.annotate(root); r.export(root); results[kind]=r.verify(root)
    r.write(output/"demo-summary.json",results)
    return results


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    results=run(args.output.resolve())
    print(json.dumps({k:{"automated_checks_pass":v["automated_checks_pass"],"unlocated":v["unlocated"]} for k,v in results.items()},ensure_ascii=False))
    if not all(v["automated_checks_pass"] for v in results.values()): raise SystemExit(1)
