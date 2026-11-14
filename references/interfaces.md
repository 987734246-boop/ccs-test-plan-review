# CLI 与项目接口 v1

所有 JSON 使用 UTF-8。命令成功返回 0；输入错误返回 2；verify 自动检查失败返回 1。标准输出是简短 JSON，错误写标准错误。

```text
review.py extract --project PROJECT --input FILE [--output INDEX.json] [--ocr auto|off|on] [--ocr-sidecar SIDECAR.json]
review.py check --project PROJECT [--demo]
review.py annotate --project PROJECT
review.py export --project PROJECT
review.py verify --project PROJECT
fetch_source.py --project PROJECT --id ID --url URL --official-page URL
demo.py --output DIRECTORY
baseline.py [--library LIBRARY] download [--refresh]
baseline.py [--library LIBRARY] verify
baseline.py [--library LIBRARY] attach --project PROJECT --reason REASON
baseline.py [--library LIBRARY] search --query TEXT [--limit 20]
baseline.py [--library LIBRARY] page --page NUMBER [--render PAGE.png]
```

extract 默认写 extraction.json；提取法规时必须指定 `--output sources/ID.index.json`，避免覆盖送审提取结果。输入允许绝对路径；依据文件、依据索引及链接证明文件必须在项目目录内。ZIP 仅收录明确允许留存的法规正文和索引，不打包送审原件。

## review.json

以 `templates/review.json` 为起点。schema_version=1；input_sha256 必须来自 extraction.json。project 保存产品型号、认可类别、安装位置、设备用途、日期、送审版本及待确认条件，不能用默认值伪造缺失条件。每个 items 元素代表一个设备的一项要求；同一试验多个参数可分多行。

sources：

- id：唯一来源编号；kind=`regulation`、`project_approval` 或 `synthetic`。
- document_id、edition、published_date、effective_date、trigger、applicability_reason、official_url、download_url、retrieved_at：版本及来源信息。日期不明写 null，并在适用理由说明影响；不得自行补日期。
- fulltext、edition_confirmed：读取正文并核实版次后才置 true；发布说明页和搜索摘要不算全文。
- path、sha256、index_path：项目内原文及 extract 生成的索引；不支持以编辑索引替代原文。
- retain_allowed：能否把全文和提取索引收进证据 ZIP。
- 官方外部下载：link_proof={path,sha256,official_url}，须保存来自 official_url 的落地 HTML 且包含完整下载 URL。不能仅填写“已确认”。
- 项目批准文件：kind=project_approval，必须记录 approval_verified=true 和 signatory，逐条引用批准范围；其真实性仍由验船师负责核实。
- GD019本地基准：由baseline.py attach填写baseline={profile_id,manifest_path}，按已核验的原文SHA-256校验。PDF/索引/发布页/清单复制到项目目录，后续不读取共享基准来替换该项目证据。
- attach创建的update_review默认为pending。实际查完本项目的修订、通告及版次适用性后填写 `{status:"verified",checked_at:"带时区的ISO时间",official_urls:["实际查阅的官方URL"],note:"检索范围、找到的文件及采用该版的具体理由"}`。只下载正文或打开发布页不能宣称完整核查已完成。未知/离线保持pending，check将相关结论降为待核实；重新采用其他版本时须另立来源。
- 已知2026年UR E10 Rev.10通告：project.ccs_received_date为CCS收到相关申请文件的日期（YYYY-MM-DD），approval_application_type记录新类型申请/实质性修改后重新申请/过期证书更新等实际情形。update_review.known_updates逐条填 `{id:"CCS-UR-E10-REV10-2026",disposition:"applies或not_applicable",reason:"具体理由",anchor:{block_id:"通告原文块",quote:"通告原文字串"}}`，并将同ID的官方通告独立加入sources。日期达到2026-01-01时须结合通告；原文日期和申请情形不明时不得猜测。工具不检查所有语义，因此理由和申请情形仍须验船师复核。

items：

- id、equipment、test、finding、action；proposed_status 取 pass/deviation/incomplete/pending/exempt/not_applicable。
- applicability={confirmed:true,reason:"具体项目适用理由"}，有条件不清时 confirmed=false。
- anchor={block_id,quote}；重复文字可加 start（段落或行内 0 起始字符偏移），PDF 可加 page（1 起始）。DOCX 以 XML 主文段落序号定位，含嵌套表格；不提供未验证的 Word 页码。
- 扫描锚点加 visual_confirmed=true、confirmation_note="核对人及原页核对说明"；置信度不代替原页确认。
- citations=[{source_id,clause,block_id,quote}]；规范脚注、表格及正文分别引用。OCR 依据引用同样需要核对说明。quote 必须是实际原文子串。
- missing_item=true 时 whole_document_checked=true 才能确认为整项漏试；anchor 指向总表/章节。附件缺失时不得声称全文已审。
- exemption={equipment,tests:[具体试验名称],conditions,approval_source_id}；equipment/test 必须匹配当前项，批准文件也必须加入 citations。
- numeric 可选：actual（数或双端点数组）、actual_unit、required_unit、operator、values_verified。只有确认原文数值、限值和工况后置 values_verified=true。

numeric 操作符：`ge` 配 min；`le` 配 max；`between` 配 min/max；`range_contains` 比较实际区间是否覆盖 min/max；`equal` 配 expected、abs_tolerance、rel_tolerance（比例小数，0.05=5%）。边界均包含端点；相等容差取 max(绝对容差,|目标值|×相对容差)。不支持单位或工况不等价时返回待核实。所有数值用 Decimal，原值和换算过程保存于 calculation。

## OCR 坐标文件

```json
{"input_sha256":"原PDF哈希","blocks":[{"page":1,"text":"识别文字","bbox":[10,20,100,40],"coordinate_space":"unrotated_pdf_points","confidence":0.99}]}
```

坐标单位是原 PDF 未旋转页面的 point。自动 PaddleOCR 在 2 倍渲染图上识别后，经缩放和去旋转矩阵映射到原页；不得将图片像素直接当 PDF 坐标。人工导入必须带原件哈希。OCR 锚点在批注前仍须逐项原页确认。

## 派生结果

checked.json 保存证据降级原因及数值记录。annotated.json 额外保存 annotation_status=written/unlocated/not_required、批注 ID、原页位置和批注文件哈希。export 生成 review.xlsx、basis-and-gaps.md、evidence-manifest.json、evidence.zip。verification.json 列自动检查结果、待定位项和仍需人工完成的验收；其本身不作为“全部验收通过”的证明。
