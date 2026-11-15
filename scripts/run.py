#!/usr/bin/env python3
"""Two everyday commands: prepare a submission, then finish its reviewed findings."""
import argparse
import json
import sys
import time
from pathlib import Path

import review as r
import knowledge as k


def prepare(file,project,conditions=None,pack=k.DEFAULT_PACK):
    root=Path(project).resolve(); file=Path(file).resolve()
    k.load(pack)  # Fail before creating a project if the installed pack is missing or changed.
    if (root/'review.json').exists() or (root/'extraction.json').exists():
        raise ValueError('项目已有审查记录；请为新送审版本使用独立目录，避免覆盖')
    if file.suffix.lower() not in ('.docx','.pdf'): raise ValueError('送审件仅支持DOCX/PDF')
    project_conditions=r.read(conditions) if conditions else {}
    if not isinstance(project_conditions,dict): raise ValueError('项目条件须为JSON对象')
    devices=project_conditions.get('equipment',[])
    if not isinstance(devices,list) or any(not isinstance(e,dict) for e in devices): raise ValueError('equipment须为设备对象数组')
    names=[e.get('name') for e in devices]
    if any(not isinstance(n,str) or not n.strip() for n in names) or len(set(names))!=len(names):
        raise ValueError('设备名称不能为空或重复')
    root.mkdir(parents=True,exist_ok=True)
    extraction=r.extract_document(file,ocr='auto'); r.write(root/'extraction.json',extraction)
    review={'schema_version':1,'demo':False,'input_sha256':extraction['input']['sha256'],'project':project_conditions,
            'rule_mode':'fixed','sources':[],'items':k.checklist(devices,pack)}
    r.write(root/'review.json',review); k.attach(root,pack)
    return {'project':str(root),'items':len(review['items']),'submission_warnings':extraction['warnings'],
            'next':'读取相关规则并填写review.json中的大纲定位、发现及处理要求，然后运行finish。未审核项目保持pending。'}


def finish(project):
    root=Path(project).resolve(); started=time.perf_counter()
    checked=r.check(root); r.annotate(root); r.export(root); result=r.verify(root)
    document=root/r.read(root/'annotated.json')['annotated_file']
    return {'automated_checks_pass':result['automated_checks_pass'],'written_count':result['written_count'],
            'primary_document':str(document),'summary_count':result['summary_count'],
            'unreviewed':result['unreviewed'],
            'pending_count':sum(i['status']=='pending' for i in checked['items']),'unlocated':result['unlocated'],
            'elapsed_seconds':round(time.perf_counter()-started,3),'outputs':[str(document)]+[str(root/n) for n in ('review.xlsx','basis-and-gaps.md','verification.json','evidence.zip')]}


def main():
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare'); p.add_argument('file',type=Path); p.add_argument('--project',type=Path,required=True); p.add_argument('--conditions',type=Path); p.add_argument('--pack',type=Path,default=k.DEFAULT_PACK)
    f=sub.add_parser('finish'); f.add_argument('--project',type=Path,required=True)
    args=parser.parse_args()
    try:
        result=prepare(args.file,args.project,args.conditions,args.pack) if args.command=='prepare' else finish(args.project)
        print(json.dumps(result,ensure_ascii=False)); return 1 if result.get('automated_checks_pass') is False else 0
    except (ValueError,OSError,KeyError,ImportError,TypeError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr); return 2


if __name__=='__main__': sys.exit(main())
