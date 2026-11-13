# 安装与试用

## Windows 安装

1. 解压技能 ZIP，保持 `ccs-test-plan-review/SKILL.md` 和 scripts、references 的相对位置。
2. 在 PowerShell 中从技能目录运行 `powershell -NoProfile -File scripts/install.ps1`。需 Python 3.11 或 3.12；脚本创建目录内 `.venv`，不会改系统 Python。
3. 如需扫描件 OCR，运行 `powershell -NoProfile -File scripts/install.ps1 -WithOCR`。首次 PaddleOCR 运行需下载官方模型；OCR 在本地推理。离线环境须事先准备依赖及模型。
4. WorkBuddy 技能入口上传整个技能包。若客户端只支持文件夹安装，选择解压后的技能目录。按客户端实际入口完成安装，不将安装步骤完成视为脚本调用成功。
5. 将安装脚本打印的 Python 完整路径告知 WorkBuddy，要求先运行 CLI `--help` 和演示。

示例（路径请换成实际解压位置）：

```powershell
& '.\.venv\Scripts\python.exe' scripts/review.py --help
& '.\.venv\Scripts\python.exe' scripts/demo.py --output '.\demo-run'
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

向 WorkBuddy 发送：

> 使用 ccs-test-plan-review 审查这份电气电子产品型式认可试验大纲。每次从官方来源查询适用版次；先读取 Skill 和接口说明，缺证据的项目列为待核实；输出原格式批注副本、审查矩阵和证据包。解释器为【填写完整路径】，项目目录为【填写路径】。

## 安装说明

- 核心依赖与 OCR 直接依赖锁定到本次已测试的版本，见 requirements.txt、requirements-ocr.txt。OCR 单独安装，避免普通文字文件用户安装大型运行时。
- OCR 默认 CPU 推理并关闭 MKL-DNN，避免已在 Windows PaddlePaddle 3.3.1 上复现的 oneDNN/PIR 兼容错误；不要求 GPU。
- PyMuPDF 按其 AGPL/商业许可发布；单位集成和再分发时按实际部署选择适用许可。本包不捆绑其二进制。
- 不修改 WorkBuddy 全局配置，不配置模型密钥，不自动发送邮件或上传文档。
- 运行 `verify` 仅完成结构和完整性检查。WorkBuddy、Word、WPS、阅读器及真实人工已审案例的结果需在项目验收记录中单独留存。
- 修改原件、review.json 或依据后从 extract/check 重跑。输出固定写在项目目录，重复运行会更新派生结果；不同送审版本应分开目录。

官方技能包格式：https://open.workbuddy.cn/docs/skill
