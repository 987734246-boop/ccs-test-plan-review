# CCS 电气电子试验大纲审查 Skill

内置固定版次知识，直接审查DOCX/PDF大纲，生成原文批注、Excel审查矩阵及项目证据包。

v1.2.0将GD019-2024的44页正文整理为31个知识条目、29个预置数值检查，并配套2026年UR E10 Rev.10通告。完整原文、表格/脚注、原页图及出处保存在本地知识包，日常无需联网或重新解析规范。

## 使用

安装[本地完整版或按源码构建](references/setup.md)，将技能导入WorkBuddy后说明审查任务即可。手动操作只需：

```powershell
& '.\.venv\Scripts\python.exe' scripts/run.py prepare '大纲.docx' --project '项目目录' --conditions '项目条件.json'
# 阅读规则并填写项目审查意见
& '.\.venv\Scripts\python.exe' scripts/run.py finish --project '项目目录'
```

详见[使用说明](references/setup.md)、[项目接口](references/interfaces.md)、[GD019审查路径](references/gd019-review.md)。条件格式见templates/conditions.json。

## 准确性与范围

每条规则及结论保留原文出处。预置参数从知识包取限值，分支条件未知时保留待核实；完整知识条目不等于所有参数均已自动化。特殊标准、项目免除及第4章路径仍需核对相应材料。缺少事实时不自动生成“通过”。

固定包标注原文快照日期和版本范围，不宣称覆盖此后全部修订。验船师业务签发、真实案件对照及客户端显示验收须单独完成。

公开仓库保留工具、人工整理的规则定义和哈希锁；完整原文和提取材料放在本地knowledge目录。该目录与下载缓存不提交公开仓库。PyMuPDF等依赖按各自许可使用。
