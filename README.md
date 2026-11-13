# CCS 电气电子试验大纲审查 Skill

配合 WorkBuddy 在线检索项目适用的官方法规依据，生成 DOCX/PDF 原生批注、Excel 审查矩阵及项目证据包。

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
```

## 验证状态

25 项自动测试通过；真实 PaddleOCR 构造扫描样例已完成识别、批注和导出。官方 CCS 发布页获取测试通过，发布说明保持为非全文状态。

尚需 WorkBuddy 客户端完整联调、Word/WPS/PDF 阅读器交互检查、DOCX 页面渲染，以及真实人工已审脱敏大纲对照验收。

工具不捆绑法规全文、模型权重或第三方运行时，不建立跨项目法规数据库。PyMuPDF 等依赖按各自许可使用。
