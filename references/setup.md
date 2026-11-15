# 安装与使用

## 本地完整版

解压带knowledge目录的完整技能包，保持目录结构。在PowerShell中从技能目录运行：

```powershell
powershell -NoProfile -File scripts/install.ps1
# 只有处理扫描送审件才需要OCR依赖
powershell -NoProfile -File scripts/install.ps1 -WithOCR
```

需要Python 3.11或3.12。脚本创建目录内.venv并打印解释器完整路径。在WorkBuddy技能入口导入技能目录或ZIP，将解释器路径告诉WorkBuddy。正常审查不需要下载规范、OCR规范或重新提取规范PDF。

向WorkBuddy发送：

> 使用ccs-test-plan-review和内置固定知识包审查这份大纲。在Word/PDF原文处批注实际问题、具体修改建议或需进一步确认的问题，写清厂家/验船师下一步应提供什么。原格式批注副本作为主要交付，矩阵和证据作配套。解释器为【完整路径】，项目目录为【独立路径】。

## 常用两条命令

```powershell
& '.\.venv\Scripts\python.exe' scripts/run.py prepare '送审大纲.docx' --project '项目目录' --conditions '项目条件.json'
# WorkBuddy逐项核对原文并填写review.json
& '.\.venv\Scripts\python.exe' scripts/run.py finish --project '项目目录'
```

条件格式见templates/conditions.json。conditions可省略；未确认的类型/环境/用途不会自动补默认值。prepare生成待审清单，不直接产生合规结论。finish可处理部分已审项目，其余明确保留待核实；不覆盖原件。

finish返回primary_document及完整输出路径。Word在“审阅→显示批注”中查看；PDF点击高亮或打开“注释/备注”面板。扫描页仅在原页核对后高亮已确认的文字区域。无法原位定位的意见写入首处“待定位事项汇总”备注，不冒充问题所在位置。不要将PDF批注扁平化，否则会失去交互备注；普通打印可能不显示备注全文。

只读查看规则：`python scripts/knowledge.py find --query '2.7'`；校验安装包：`python scripts/knowledge.py verify`。检索结果含完整相关原文、预置参数、精确引用和随包原页图，无须重新渲染或识别规范。

## 从公开源码首次构建（只执行一次）

公开仓库保留工具、规则定义和发布锁定信息；本地完整版另含完整规范材料。源码安装者可用官方文件构建自己的固定版本：

```powershell
& '.\.venv\Scripts\python.exe' scripts/baseline.py download
& '.\.venv\Scripts\python.exe' scripts/fetch_source.py --project 'build-sources' --id CCS-UR-E10-REV10-2026 --url 'https://www.ccs.org.cn/ccswz/specialDetail?id=202603230333226752&type=1' --official-page 'https://www.ccs.org.cn/ccswz/specialDetail?id=202603230333226752&type=1'
& '.\.venv\Scripts\python.exe' scripts/knowledge.py build --notice 'build-sources/sources/CCS-UR-E10-REV10-2026.html' --seal
```

build读取官方基准并生成章节Markdown、原页PNG、规则JSON、原文映射和哈希清单。--seal明确写入本次构建的发布锁；不是日常自动动作。已有目录禁止覆盖，换版使用新的输出目录和版本标识，保留历史项目证据。仅有源码、没有knowledge目录时会明确提示安装或构建，不自动联网。

## 验证边界

知识条目的source_checked表示源码/参数整理已核对，不代表验船师已签发。每个项目仍确认对象、工况、申请日期、免除、外部标准以及大纲参数转录。源码未含完整IEC等外部标准时，细节保持待核实。工具默认固定版次离线对照，报告列包版本和原文快照范围；“核查最新”是单独的维护/业务步骤。

PyMuPDF按其AGPL/商业许可发布。本包不捆绑第三方二进制或模型权重。OCR默认CPU并关闭MKL-DNN。Word/WPS/阅读器显示与真实人工已审案例对照仍需在试点中验证。
