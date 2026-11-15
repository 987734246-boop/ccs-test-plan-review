#!/usr/bin/env python3
"""Build once, then use a hash-pinned, offline regulatory knowledge pack."""
from __future__ import annotations
import argparse
import copy
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import review as r
import baseline
import catalog

ROOT=Path(__file__).resolve().parents[1]
PACK_ID="gd019-2024-e10r10-2026-r1"
DEFAULT_PACK=ROOT/"knowledge"/PACK_ID
LOCK=ROOT/"references/knowledge-lock.json"
GUIDE_ID="CCS-GD019-2024"
NOTICE_ID="CCS-UR-E10-REV10-2026"


def lock_config():
    return r.read(LOCK)


def source_anchor(block, source_id=GUIDE_ID, clause=""):
    return {"source_id":source_id,"clause":clause,"block_id":block["id"],"page":block.get("page"),"quote":block["text"]}


def build(library, notice_file, output=DEFAULT_PACK, seal=False):
    """An explicit authoring operation; never called by prepare/check/finish."""
    import pymupdf as fitz
    manifest, folder, old_index=baseline.load(library)
    index=baseline.inspect_pdf(folder/manifest["path"],baseline.profile())
    if index["blocks"]!=old_index["blocks"]: raise ValueError("基准索引与重新核对的正文不一致")
    output=Path(output).resolve()
    if output.exists(): raise ValueError("知识包目录已存在；请使用新的版本目录，禁止覆盖")
    notice_file=Path(notice_file).resolve()
    notice_index=r.extract_document(notice_file)
    notice_text="\n".join(b["text"] for b in notice_index["blocks"])
    needed=["UR E10 Rev.10", "2026年1月1日", "收到的文件日期", "2024"]
    if not all(baseline.compact(s) in baseline.compact(notice_text) for s in needed):
        raise ValueError("配套通告正文缺少已核对的标题、日期或触发条件")
    output.mkdir(parents=True)
    shutil.copyfile(folder/manifest["path"],output/"original.pdf")
    shutil.copyfile(folder/manifest["landing_path"],output/"official-page.html")
    shutil.copyfile(notice_file,output/"notice.html")
    index["input"]["path"]="original.pdf"; r.write(output/"index.json",index)
    notice_index["input"]["path"]="notice.html"; r.write(output/"notice-index.json",notice_index)
    (output/"pages").mkdir(); (output/"chapters").mkdir()
    with fitz.open(output/"original.pdf") as pdf:
        for number,page in enumerate(pdf,1):
            page.get_pixmap(matrix=fitz.Matrix(1.3,1.3),annots=False).save(output/f"pages/{number:02}.png")
    # PDF object order is not reading order, especially tables continued above a new heading.
    ordered=sorted(index["blocks"],key=lambda b:(b["page"],b["bbox"][1],b["bbox"][0]))
    sections={}; current=None
    for block in ordered:
        if block["page"]<3: continue
        match=re.match(r"^\s*(\d+\.\d+)(?![\d.])\s+",block["text"])
        if match and match[1] in catalog.TITLES: current=match[1]
        if block["page"]==44: current="A"
        if current: sections.setdefault(current,[]).append(block)
    missing=set(catalog.TITLES)-set(sections)
    if missing: raise ValueError("知识章节未完整定位: "+str(sorted(missing)))
    rules=[]
    for clause,title in catalog.TITLES.items():
        blocks=sections[clause]
        subclauses={}; sub=None
        for block in blocks:
            found=re.match(r"^\s*(\d+\.\d+\.\d+)(?![\d.])\s+",block["text"])
            if found: sub=found[1]
            if sub: subclauses.setdefault(sub,[]).append(block)
        filename="chapters/"+clause.replace('.','-')+".md"
        lines=[f"# GD019-2024 {clause} {title}","", "固定版次原文。表格须结合随包原页图；不依据线性文本猜测列关系。", ""]
        for block in blocks:
            lines.extend([f"<!-- {block['id']} | PDF {block['page']} | 印刷 {block['page']-2} -->",block["text"],""])
        (output/filename).write_text("\n".join(lines),encoding="utf-8")
        rules.append({"id":"GD019-"+clause,"clause":clause,"title":title,"review_state":"source_checked",
                      "business_signoff":"not_completed", "chapter_file":filename,
                      "pages":sorted({b['page'] for b in blocks}),"block_ids":[b['id'] for b in blocks],
                      "anchors":[source_anchor(blocks[0],clause=clause)],
                      "subclauses":{k:[b['id'] for b in v] for k,v in subclauses.items()},
                      "compare_fields":["适用条件","方法及引用标准","参数及单位","持续时间","运行与监测","结果判据","脚注/例外"]})
    rule_map={rule['clause']:rule for rule in rules}
    parameters=catalog.parameters()
    special={"vibration_sweep":"2.7.4","vibration_axes":"2.7.4","no_resonance_frequency":"2.7.4","no_resonance_minutes":"2.7.4","resonance_minutes":"2.7.4","clustered_minutes":"2.7.4","static_minutes":"2.6.4"}
    for parameter in parameters:
        clause=parameter['clause']; source_clause=special.get(parameter['id'],clause+('.2' if clause=='2.5' else '.3'))
        ids=rule_map[clause]['subclauses'].get(source_clause)
        if not ids: raise ValueError("参数依据未定位: "+parameter['id'])
        parameter['source_clause']=source_clause; parameter['source_blocks']=ids
    r.write(output/"rules.json",{"rules":rules,"parameters":parameters,
            "tables":{"environment":catalog.ENVIRONMENT,"equipment":catalog.EQUIPMENT,"emc":catalog.EMC},
            "table_pages":[6,7,8,25,42,43],"interpretation_note":"目录/矩阵已作源码核对；业务签发未完成；特殊标准、项目批准和未列参数仍须判读原文"})
    r.write(output/"source-map.json",{"guide_blocks":index['blocks'],"notice_blocks":notice_index['blocks']})
    (output/"notice.md").write_text("# UR E10 Rev.10配套通告\n\n"+notice_text,encoding="utf-8")
    files={p.relative_to(output).as_posix():r.sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    spec=baseline.profile(); notice=spec['known_updates'][0]
    data={"schema_version":1,"pack_id":PACK_ID,"compiler_version":"1.2.0","built_at":datetime.now(timezone.utc).isoformat(),
          "source_snapshot_date":"2026-11-14","update_scope":"GD019-2024及已核对的2026-03-23通告；固定版本，未宣称覆盖之后全部修订",
          "business_signoff":"not_completed","files":files,
          "sources":{
              GUIDE_ID:{"path":"original.pdf","index_path":"index.json","sha256":manifest['sha256'],"document_id":"GD 019","edition":"2024","official_url":spec['official_url'],"download_url":manifest['download_url'],"published_date":spec['published_date'],"effective_date":spec['effective_date'],"retrieved_at":manifest['retrieved_at']},
              NOTICE_ID:{"path":"notice.html","index_path":"notice-index.json","sha256":r.sha(output/'notice.html'),"document_id":notice['title'],"edition":"2026-03-23","official_url":notice['official_url'],"download_url":notice['official_url'],"published_date":"2026-03-23","effective_date":None,"retrieved_at":datetime.now(timezone.utc).isoformat()}
          }}
    r.write(output/"manifest.json",data)
    lock={"pack_id":PACK_ID,"manifest_sha256":r.sha(output/'manifest.json'),"guide_sha256":manifest['sha256'],"rule_count":len(rules),"parameter_count":len(parameters),"source_snapshot_date":data['source_snapshot_date']}
    if seal: r.write(LOCK,lock)
    return lock


def load(folder=DEFAULT_PACK, verify_assets=True):
    folder=Path(folder).resolve(); expected=lock_config()
    if r.sha(folder/'manifest.json')!=expected['manifest_sha256']:
        raise ValueError("知识包清单与发布锁定值不符，停止使用；请恢复已发布版本")
    manifest=r.read(folder/'manifest.json')
    if manifest['pack_id']!=expected['pack_id']: raise ValueError("知识包版本不匹配")
    for path,expected_sha in manifest['files'].items():
        if not verify_assets and Path(path).suffix.lower()=='.png': continue
        if r.sha(r.local(folder,path))!=expected_sha: raise ValueError("知识包文件变化: "+path)
    return manifest,folder,r.read(folder/'rules.json')


def attach(project, pack=DEFAULT_PACK):
    data,folder,_=load(pack); root=Path(project).resolve(); root.mkdir(parents=True,exist_ok=True)
    review=r.read(root/'review.json') if (root/'review.json').exists() else {"schema_version":1,"demo":False,"input_sha256":r.bind(root)['input']['sha256'],"project":{},"sources":[],"items":[]}
    destination=root/'sources'/data['pack_id']
    if destination.exists(): load(destination)
    else: shutil.copytree(folder,destination)
    relative=destination.relative_to(root).as_posix()
    existing={s['id']:s for s in review['sources']}
    for sid,source in data['sources'].items():
        if sid in existing:
            if not existing[sid].get('knowledge') or existing[sid]['sha256']!=source['sha256']:
                raise ValueError("项目已有其他同名依据；请选择独立项目目录，不覆盖既有证据")
            continue
        review['sources'].append({**source,"id":sid,"kind":"regulation","fulltext":True,"edition_confirmed":True,
            "path":relative+'/'+source['path'],"index_path":relative+'/'+source['index_path'],"retain_allowed":False,
            "applicability_reason":"采用项目选定的内置固定版本；逐项适用性另行核实",
            "knowledge":{"pack_id":data['pack_id'],"manifest_path":relative+'/manifest.json'}})
    review['knowledge_pack']={"id":data['pack_id'],"manifest_path":relative+'/manifest.json',"manifest_sha256":r.sha(destination/'manifest.json'),"snapshot_date":data['source_snapshot_date'],"update_scope":data['update_scope']}
    review.setdefault('rule_mode','fixed')
    r.write(root/'review.json',review)
    return review


def validate_source(root,source):
    try:
        file=r.local(root,source['knowledge']['manifest_path']); manifest,folder,_=load(file.parent,verify_assets=False)
        if source['knowledge'].get('pack_id')!=manifest['pack_id']: return '知识包来源版本不符'
        expected=manifest['sources'][source['id']]
        for key in ('sha256','edition','document_id','official_url'):
            if source.get(key)!=expected[key]: return "知识包来源信息不符: "+key
        for key in ('path','index_path'):
            if r.local(root,source[key])!=r.local(folder,expected[key]): return "知识包来源路径不符"
    except (KeyError,OSError,ValueError) as exc: return "固定知识包校验失败: "+str(exc)
    return None


def project_data(root,review):
    manifest=r.local(root,review['knowledge_pack']['manifest_path'])
    data,folder,rules=load(manifest.parent,verify_assets=False)
    selection=review['knowledge_pack']
    if selection.get('id')!=data['pack_id'] or selection.get('manifest_sha256')!=r.sha(manifest) or selection.get('snapshot_date')!=data['source_snapshot_date'] or selection.get('update_scope')!=data['update_scope']:
        raise ValueError('项目知识包版本、快照或锁定信息不符')
    return data,folder,rules


def enrich(root,review):
    """Bind rule IDs and parameter limits to sealed original evidence, no PDF parsing."""
    result=copy.deepcopy(review)
    try: manifest,folder,data=project_data(root,result)
    except (KeyError,OSError,ValueError) as exc:
        for item in result.get('items',[]): item['knowledge_errors']=[str(exc)]
        return result
    index=r.read(folder/'index.json'); blocks={b['id']:b for b in index['blocks']}
    mandatory=[source_anchor(b,clause='1.3.3及表1.3.3a/b脚注') for b in index['blocks'] if b.get('page') in (6,7,8) and any(s in baseline.compact(b['text']) for s in ('1.3.3不同类型','表1.3.3a','表1.3.3b','无运动部件','非金属壳体','仅适用于安装在A','仅适用于用于控制'))]
    rules={rule['id']:rule for rule in data['rules']}; params={p['id']:p for p in data['parameters']}
    equipment={e.get('name'):e for e in result.get('project',{}).get('equipment',[])}
    for item in result.get('items',[]):
        errors=[]; item['knowledge_errors']=errors
        if not item.get('rule_id'):
            errors.append('固定知识包审查项须记录rule_id'); continue
        rule=rules.get(item['rule_id'])
        if not rule: errors.append('未知知识规则编号'); continue
        item['knowledge_version']=manifest['pack_id']; item.setdefault('citations',copy.deepcopy(rule['anchors']))
        if not item['citations']: item['citations']=copy.deepcopy(rule['anchors'])
        context=equipment.get(item.get('equipment'),{})
        if rule['clause'].startswith(('2.','3.')) and rule['clause']!='3.1':
            required,reason=catalog.applicability(rule['clause'],context,data.get('tables'))
            item['rule_applicability']={'required':required,'reason':reason}
            if required is None: errors.append(reason)
            if required is False and item.get('proposed_status') in ('pass','deviation','incomplete'):
                errors.append('所选环境/设备条件未触发本项；请复核适用性')
            if required is True and item.get('proposed_status')=='not_applicable':
                errors.append('规则已触发，不能直接标记不适用；免除须有批准依据')
            if rule['clause'].startswith('2.'):
                item['citations'] += [a for a in mandatory if a not in item['citations']]
        parameter_id=item.get('parameter_id')
        if parameter_id:
            parameter=params.get(parameter_id)
            if not parameter or parameter['clause']!=rule['clause']:
                errors.append('参数编号不属于所选规则'); continue
            for key,expected in parameter['conditions'].items():
                actual=context.get(key)
                match=actual in expected if isinstance(expected,list) else type(actual)==type(expected) and actual==expected
                if not match: errors.append('参数分支条件未确认: '+key)
            supplied=item.get('numeric',{})
            actual=supplied.get('actual',item.get('actual_value'))
            unit=supplied.get('actual_unit',item.get('actual_unit'))
            if actual is None or not unit: errors.append('缺少送审参数原值或单位')
            template={k:parameter[k] for k in ('required_unit','operator','min','max','expected','abs_tolerance','rel_tolerance') if k in parameter}
            item['numeric']={**template,'actual':actual,'actual_unit':unit,'values_verified':supplied.get('values_verified',item.get('values_verified',False))}
            item['citations']=[source_anchor(blocks[i],clause=parameter['source_clause']) for i in parameter['source_blocks']]
            if rule['clause'].startswith('2.'): item['citations'] += copy.deepcopy(mandatory)
        elif item.get('numeric'):
            errors.append('该数值未绑定已固化parameter_id，须补充规则校核后再作确定性判断')
        # The 2026 overlay affects the inclination rule, not every independent test.
        if rule['clause']=='2.6':
            received=result.get('project',{}).get('ccs_received_date')
            try: received_date=datetime.strptime(received,'%Y-%m-%d').date()
            except (ValueError,TypeError): errors.append('倾斜试验须确认CCS收件日期以选择2026通告'); continue
            if received_date>=datetime(2026,1,1).date():
                if result.get('project',{}).get('approval_application_type') not in ('new_type','substantial_modification','expired_certificate_renewal'):
                    errors.append('须确认2026通告所涉认可申请情形')
                notice_index=r.read(folder/'notice-index.json')
                found=[b for b in notice_index['blocks'] if '新增尾句' in b['text']]
                if not found: errors.append('配套通告修订正文未定位')
                else: item['citations'].append(source_anchor(found[0],NOTICE_ID,'UR E10 Rev.10修订内容'))
        if result.get('rule_mode','fixed')!='fixed': errors.append('固定知识包不能证明现行完整性；须另行核查更新并建立相应版本')
    return result


def checklist(equipment,pack=DEFAULT_PACK):
    _,_,data=load(pack); items=[]
    for device in equipment or [{'name':'待确认设备'}]:
        if device.get('navigation_radio') is True:
            selected=[r for r in data['rules'] if r['clause'] in ('4.1','4.2')]
        else: selected=[r for r in data['rules'] if r['clause'].startswith('2.') or r['clause'].startswith('3.') and r['clause']!='3.1']
        for rule in selected:
            required,reason=catalog.applicability(rule['clause'],device,data.get('tables'))
            items.append({'id':f'TA-{len(items)+1:03}', 'equipment':device['name'],'test':rule['title'],'rule_id':rule['id'],
                          'reviewed':False,'proposed_status':'pending','applicability':{'confirmed':False,'reason':reason},
                          'rule_applicability':{'required':required,'reason':reason},'anchor':{},'citations':copy.deepcopy(rule['anchors']),
                          'finding':'待对照本项适用条款与大纲','action':'核实适用条件并完成方法、参数、运行状态和判据对照'})
    return items


def lookup(query,pack=DEFAULT_PACK):
    _,folder,data=load(pack)
    exact=[rule for rule in data['rules'] if query in (rule['id'],rule['clause'])]
    hits=exact or [rule for rule in data['rules'] if query in rule['id'] or query in rule['title']]
    if not hits: return {'matches':0,'rules':[]}
    index=r.read(folder/'index.json'); blocks={b['id']:b for b in index['blocks']}
    return {'matches':len(hits),'rules':[{**rule,'parameters':[p for p in data['parameters'] if p['clause']==rule['clause']],
            'original_blocks':[blocks[i] for i in rule['block_ids']], 'page_images':[str(folder/f'pages/{page:02}.png') for page in rule['pages']]} for rule in hits]}


def main():
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='command',required=True)
    build_parser=sub.add_parser('build'); build_parser.add_argument('--library',type=Path,default=baseline.DEFAULT_LIBRARY); build_parser.add_argument('--notice',type=Path,required=True); build_parser.add_argument('--output',type=Path,default=DEFAULT_PACK); build_parser.add_argument('--seal',action='store_true')
    for command in ('verify','find'):
        p=sub.add_parser(command); p.add_argument('--pack',type=Path,default=DEFAULT_PACK)
        if command=='find': p.add_argument('--query',required=True)
    args=parser.parse_args()
    try:
        if args.command=='build': result=build(args.library,args.notice,args.output,args.seal)
        elif args.command=='find': result=lookup(args.query,args.pack)
        else:
            manifest,_,data=load(args.pack); result={'pack_id':manifest['pack_id'],'rules':len(data['rules']),'parameters':len(data['parameters']),'snapshot_date':manifest['source_snapshot_date'],'verified':True}
        print(json.dumps(result,ensure_ascii=False)); return 0
    except (ValueError,OSError,KeyError,ImportError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr); return 2


if __name__=='__main__': sys.exit(main())
