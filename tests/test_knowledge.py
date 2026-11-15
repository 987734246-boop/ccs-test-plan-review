import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import review as r
import knowledge as k
import catalog
import run
import demo


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.pack=self.root/'pack'; self.pack.mkdir()
        (self.pack/'guide.txt').write_text('2.7 Vibration\n2.7.4 no resonance 90 min\n2.6 Inclination\n2.11 Steady damp',encoding='utf-8')
        (self.pack/'notice.html').write_text('<p>2026 notice test: 新增尾句. Synthetic fixture only.</p>',encoding='utf-8')
        guide=r.extract_document(self.pack/'guide.txt'); notice=r.extract_document(self.pack/'notice.html')
        r.write(self.pack/'index.json',guide); r.write(self.pack/'notice-index.json',notice)
        rules=[]
        for clause,line in [('2.7',0),('2.6',2),('2.11',3),('4.1',0),('4.2',0)]:
            rules.append({'id':'GD019-'+clause,'clause':clause,'title':catalog.TITLES[clause], 'anchors':[k.source_anchor(guide['blocks'][line],clause=clause)],'block_ids':[guide['blocks'][line]['id']],'pages':[]})
        param=next(p for p in catalog.parameters() if p['id']=='no_resonance_minutes')
        param.update(source_clause='2.7.4',source_blocks=['line1'])
        r.write(self.pack/'rules.json',{'rules':rules,'parameters':[param]})
        (self.pack/'pages').mkdir(); (self.pack/'pages/01.png').write_bytes(b'synthetic preview fixture')
        sources={}
        for sid,path,index in [(k.GUIDE_ID,'guide.txt','index.json'),(k.NOTICE_ID,'notice.html','notice-index.json')]:
            sources[sid]={'path':path,'index_path':index,'sha256':r.sha(self.pack/path),'document_id':sid,'edition':'test fixture','official_url':'https://www.ccs.org.cn/','retrieved_at':'2026-01-01T00:00:00Z'}
        manifest={'pack_id':k.PACK_ID,'source_snapshot_date':'2026-01-01','update_scope':'Synthetic fixtures, no regulatory claims','sources':sources,'files':{p.relative_to(self.pack).as_posix():r.sha(p) for p in self.pack.rglob('*') if p.is_file()}}
        r.write(self.pack/'manifest.json',manifest)
        self.lock={'pack_id':k.PACK_ID,'manifest_sha256':r.sha(self.pack/'manifest.json')}
        self.mock=patch.object(k,'lock_config',return_value=self.lock); self.mock.start()
        self.submission=demo.make_project(self.root/'source-demo','docx')/'input.docx'

    def tearDown(self): self.mock.stop(); self.temp.cleanup()

    def conditions(self,**kwargs):
        device={'name':'Controller','equipment_type':'electronic','environment':'B','other_ccs_requirement':False,'resonance_found':False,'control_or_computer':True,'emc_type':'electronic_controller','battery_only':False}
        device.update(kwargs)
        value={'equipment':[device]}; r.write(self.root/'conditions.json',value)
        return self.root/'conditions.json'

    def prepare(self,**conditions):
        project=self.root/'project'
        run.prepare(self.submission,project,self.conditions(**conditions),self.pack)
        return project

    def one_item(self,project,**overrides):
        data=r.read(project/'review.json')
        item={'id':'TA-001','equipment':'Controller','test':'Vibration','rule_id':'GD019-2.7','parameter_id':'no_resonance_minutes',
              'proposed_status':'deviation','applicability':{'confirmed':True,'reason':'Synthetic fixture only'},'anchor':{'quote':'30 min'},
              'finding':'Fixture duration is 30 min','action':'Fixture requests 90 min','numeric':{'actual':30,'actual_unit':'min','values_verified':True}}
        item.update(overrides); data['items']=[item]; r.write(project/'review.json',data)

    def test_prepare_finish_offline_without_regulation_parser(self):
        original=r.extract_document
        def submission_only(path,*a,**kw):
            if Path(path).name not in ('input.docx',): raise AssertionError('Unexpected regulatory parsing')
            return original(path,*a,**kw)
        with patch.object(r,'extract_document',side_effect=submission_only), patch('baseline.get',side_effect=AssertionError('No network')),patch('baseline.retrieve',side_effect=AssertionError('No network')):
            project=self.prepare(); self.one_item(project)
            result=run.finish(project)
        self.assertTrue(result['automated_checks_pass']); self.assertEqual(result['written_count'],1)
        checked=r.read(project/'checked.json'); self.assertEqual(checked['items'][0]['numeric']['min'] if 'min' in checked['items'][0]['numeric'] else checked['items'][0]['numeric']['expected'],90)
        self.assertEqual(checked['items'][0]['status'],'deviation')

    def test_sealed_source_never_reextracts_pdf(self):
        project=self.prepare(); data=r.read(project/'review.json')
        with patch.object(r,'extract_document',side_effect=AssertionError('Regulation reparse is forbidden')):
            self.assertIsNone(r.validate_source(project,data['sources'][0],False))

    def test_unreviewed_checklist_is_not_sent_as_manufacturer_defects(self):
        project=self.prepare(); result=run.finish(project)
        self.assertTrue(result['automated_checks_pass']); self.assertEqual(result['written_count'],0)
        self.assertEqual(result['summary_count'],0); self.assertGreater(len(result['unreviewed']),0)
        self.assertIn(result['primary_document'],result['outputs'])
        from docx import Document
        self.assertEqual(len(Document(result['primary_document']).comments),1)  # Original manufacturer's note only.

    def test_manifest_tampering_stops_prepare(self):
        path=self.pack/'manifest.json'; path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'清单'): self.prepare()
        self.assertFalse((self.root/'project/extraction.json').exists())

    def test_full_text_or_rules_tampering_is_detected(self):
        for filename in ('guide.txt','rules.json','notice.html'):
            with self.subTest(filename=filename):
                p=self.pack/filename; old=p.read_bytes(); p.write_bytes(old+b' ')
                with self.assertRaisesRegex(ValueError,'文件变化'): k.load(self.pack)
                p.write_bytes(old)

    def test_project_knowledge_change_stops_later_commands(self):
        project=self.prepare(); self.one_item(project); r.check(project)
        p=project/'sources'/k.PACK_ID/'rules.json'; p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'依据内容已变化'): r.annotate(project)

    def test_unknown_context_is_pending_not_a_pass(self):
        project=self.prepare(resonance_found=None); self.one_item(project,proposed_status='pass')
        result=r.check(project)['items'][0]
        self.assertEqual(result['status'],'pending'); self.assertTrue(any('resonance_found' in e for e in result['evidence_errors']))

    def test_model_limit_cannot_override_fixed_parameter(self):
        project=self.prepare(); self.one_item(project,numeric={'actual':30,'actual_unit':'min','expected':30,'operator':'equal','required_unit':'min','values_verified':True})
        result=r.check(project)['items'][0]
        self.assertEqual(result['numeric']['expected'],90); self.assertEqual(result['status'],'deviation')

    def test_unknown_parameter_and_unbound_numeric_are_pending(self):
        project=self.prepare()
        for pid in ('made-up',None):
            self.one_item(project,parameter_id=pid)
            self.assertEqual(r.check(project)['items'][0]['status'],'pending')

    def test_fixed_mode_does_not_claim_current_rules(self):
        project=self.prepare(); self.one_item(project)
        data=r.read(project/'review.json'); data['rule_mode']='current'; r.write(project/'review.json',data)
        self.assertEqual(r.check(project)['items'][0]['status'],'pending')

    def test_inclination_date_does_not_block_other_tests(self):
        project=self.prepare(moving_parts=True,free_liquid_surface=False)
        self.one_item(project); data=r.read(project/'review.json')
        second=copy.deepcopy(data['items'][0]); second.update(id='TA-002',rule_id='GD019-2.6',parameter_id=None,numeric=None,test='Inclination')
        data['items'].append(second); r.write(project/'review.json',data)
        items=r.check(project)['items']
        self.assertEqual(items[0]['status'],'deviation'); self.assertEqual(items[1]['status'],'pending')

    def test_receipt_boundary_adds_notice_when_applicable(self):
        project=self.prepare(moving_parts=True,free_liquid_surface=False); self.one_item(project,rule_id='GD019-2.6',parameter_id=None,numeric=None)
        data=r.read(project/'review.json'); data['project'].update(ccs_received_date='2026-01-01',approval_application_type='new_type'); r.write(project/'review.json',data)
        item=r.check(project)['items'][0]
        self.assertTrue(any(c['source_id']==k.NOTICE_ID for c in item['citations']))

    def test_prepare_refuses_overwrite_and_duplicate_equipment(self):
        project=self.prepare()
        with self.assertRaises(ValueError): run.prepare(self.submission,project,pack=self.pack)
        conditions={'equipment':[{'name':'same'},{'name':'same'}]}; r.write(self.root/'duplicate.json',conditions)
        with self.assertRaises(ValueError): run.prepare(self.submission,self.root/'bad-project',self.root/'duplicate.json',self.pack)
        self.assertFalse((self.root/'bad-project/extraction.json').exists())

    def test_navigation_radio_uses_chapter4_route(self):
        items=k.checklist([{'name':'Radio','navigation_radio':True}],self.pack)
        self.assertEqual([i['rule_id'] for i in items],['GD019-4.1','GD019-4.2'])
        self.assertTrue(all(i['proposed_status']=='pending' for i in items))

    def test_environment_and_footnote_cases(self):
        base={'equipment_type':'electronic','environment':'A','other_ccs_requirement':False}
        self.assertFalse(catalog.applicability('2.8',base)[0]); self.assertTrue(catalog.applicability('2.11',base)[0])
        base['environment']='E'; self.assertTrue(catalog.applicability('2.12',base)[0]); self.assertFalse(catalog.applicability('2.13',base)[0])
        base.update(moving_parts=False,free_liquid_surface=False); self.assertFalse(catalog.applicability('2.6',base)[0])
        base['nonmetal_enclosure']=None; self.assertIsNone(catalog.applicability('2.16',base)[0])
        base.update(nonmetal_enclosure=True); self.assertTrue(catalog.applicability('2.16',base)[0])
        base.update(emc_type='electronic_controller',battery_only=True); self.assertFalse(catalog.applicability('3.8',base)[0])

    def test_report_cannot_relabel_pack_as_a_different_snapshot(self):
        project=self.prepare(); self.one_item(project)
        data=r.read(project/'review.json'); data['knowledge_pack']['snapshot_date']='2099-01-01'; r.write(project/'review.json',data)
        self.assertEqual(r.check(project)['items'][0]['status'],'pending')

    def test_comment_shows_each_clause_once_with_full_evidence_retained(self):
        project=self.prepare(); self.one_item(project)
        data=r.check(project); item=data['items'][0]
        item['citations']=item['citations']*3
        text=r.comment_text(item,data)
        self.assertEqual(text.count('2.7.4'),1)
        self.assertGreater(len(item['citations']),1)

    def test_preview_integrity_is_checked_when_preview_is_used(self):
        image=self.pack/'pages/01.png'; image.write_bytes(b'changed preview')
        with self.assertRaisesRegex(ValueError,'文件变化'): k.lookup('2.7',self.pack)
        # Daily calculations use the original PDF/text and rules, never the cached PNG.
        self.assertEqual(k.load(self.pack,verify_assets=False)[0]['pack_id'],k.PACK_ID)

    def test_runtime_uses_tables_in_the_sealed_pack(self):
        data=r.read(self.pack/'rules.json')
        tables={'environment':copy.deepcopy(catalog.ENVIRONMENT),'equipment':catalog.EQUIPMENT,'emc':catalog.EMC}
        tables['environment']['B'].remove(7)  # Deliberately different synthetic fixture.
        data['tables']=tables; r.write(self.pack/'rules.json',data)
        manifest=r.read(self.pack/'manifest.json'); manifest['files']['rules.json']=r.sha(self.pack/'rules.json'); r.write(self.pack/'manifest.json',manifest)
        self.lock['manifest_sha256']=r.sha(self.pack/'manifest.json')
        project=self.prepare(); self.one_item(project,proposed_status='pass')
        checked=r.check(project)['items'][0]
        self.assertFalse(checked['rule_applicability']['required']); self.assertEqual(checked['status'],'pending')

    def test_invalid_conditions_fail_before_submission_is_written(self):
        r.write(self.root/'bad.json',{'equipment':'invalid'})
        with self.assertRaisesRegex(ValueError,'设备对象数组'):
            run.prepare(self.submission,self.root/'invalid-project',self.root/'bad.json',self.pack)
        self.assertFalse((self.root/'invalid-project/extraction.json').exists())


if __name__=='__main__': unittest.main()
