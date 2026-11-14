# CCS 电气电子试验大纲审查 Skill

配合 WorkBuddy 以官方 GD019-2024 本地全文为基准，在线核查修订及项目适用性，生成 DOCX/PDF 原生批注、Excel 审查矩阵及项目证据包。

当前为试用版，结论须由验船师复核。示例为构造案例，不包含真实法规限值。

## 安装与使用

需要 Windows 和 Python 3.11/3.12。

```powershell
powershell -NoProfile -File scripts/install.ps1
# 扫描件支持
powershell -NoProfile -File scripts/install.ps1 -WithOCR
```

将本目录作为技能包导入 WorkBuddy。详见 [安装说明](references/setup.md)、[接口说明](references/interfaces.md) 和 [审查覆盖框架](references/review-checklist.md)。

```powershell
& '.\.venv\Scripts\python.exe' scripts/demo.py --output demo-run
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' scripts/baseline.py download
& '.\.venv\Scripts\python.exe' scripts/baseline.py search --query '1.3.3'
```

## 验证状态

39 项自动测试通过；真实 PaddleOCR 构造扫描样例已完成识别、批注和导出。GD019-2024官方PDF已实际下载并完成44页核对、索引、检索及项目快照测试；发布说明HTML仍不当作指南正文。已加入2026年UR E10 Rev.10配套通告的CCS收件日期、原文和适用性核查。

尚需 WorkBuddy 客户端完整联调、Word/WPS/PDF 阅读器交互检查、DOCX 页面渲染，以及真实人工已审脱敏大纲对照验收。

GD 019由[用户指定的CCS官方页面](https://www.ccs.org.cn/ccswz/specialDetail?id=202409090181744120)的PDF附件下载。编号、封面、44页及SHA-256校验通过后，本地复用；每项目复制独立证据并另行核查修订及适用版次。表1.3.3a、1.3.3b及续页脚注须联合阅读，详见[GD019审查路径](references/gd019-review.md)。

公开仓库及技能ZIP不捆绑法规全文、完整提取索引、模型权重或第三方运行时。`local-baselines/`为受Git忽略的本地基准目录，不是跨项目结论数据库。PyMuPDF等依赖按各自许可使用。
