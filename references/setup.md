# 安装与试用

## Windows 安装

1. 解压技能 ZIP，保持 `ccs-test-plan-review/SKILL.md` 和 scripts、references 的相对位置。
2. 在 PowerShell 中从技能目录运行 `powershell -NoProfile -File scripts/install.ps1`。需 Python 3.11 或 3.12；脚本创建目录内 `.venv`，不会改系统 Python。
3. 如需扫描件 OCR，运行 `powershell -NoProfile -File scripts/install.ps1 -WithOCR`。首次 PaddleOCR 运行需下载官方模型；OCR 在本地推理。离线环境须事先准备依赖及模型。
4. WorkBuddy 技能入口上传整个技能包。若客户端只支持文件夹安装，选择解压后的技能目录。按客户端实际入口完成安装，不将安装步骤完成视为脚本调用成功。
5. 将安装脚本打印的 Python 完整路径告知 WorkBuddy，要求先运行 CLI `--help` 和演示。

## 下载并使用GD 019本地基准

```powershell
& '.\.venv\Scripts\python.exe' scripts/baseline.py download
& '.\.venv\Scripts\python.exe' scripts/baseline.py verify
& '.\.venv\Scripts\python.exe' scripts/baseline.py search --query '1.3.3'
& '.\.venv\Scripts\python.exe' scripts/baseline.py page --page 7 --render 'demo-run/gd019-page7.png'
# 先 extract 送审文件，再复制基准到该项目并登记选版理由
& '.\.venv\Scripts\python.exe' scripts/baseline.py attach --project '项目目录' --reason '填写本项目采用2024版的具体理由'
```

默认基准目录为技能根目录的 `local-baselines/`，该目录不提交Git。也可在子命令前传 `--library '其他基准目录'`，例如 `scripts/baseline.py --library 'D:\CCS-baselines' verify`。`download`已有有效副本时直接复用；`download --refresh`主动访问官方原版附件核对正文是否变化，但不自动替代本项目的修订/通告检索。首次下载失败会报告原因，已有基准不会被覆盖。

attach 默认将更新核查标记为pending。WorkBuddy完成本项目实际官方检索后，才按接口填写 `update_review`；工具验证正文身份和项目核查记录，不自动作出设备适用性判断。离线也能搜索/查看本地原文，但缺少更新核查的正式结论保持待核实。

示例（路径请换成实际解压位置）：

```powershell
& '.\.venv\Scripts\python.exe' scripts/review.py --help
& '.\.venv\Scripts\python.exe' scripts/demo.py --output '.\demo-run'
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

向 WorkBuddy 发送：

> 使用 ccs-test-plan-review 审查这份电气电子产品型式认可试验大纲。以本地官方GD019-2024正文为基准，本次核查修订和项目适用性，结合表1.3.3a/1.3.3b及脚注建立应试清单；缺证据的项目列为待核实；输出原格式批注副本、审查矩阵和证据包。解释器为【填写完整路径】，项目目录为【填写路径】。

## 安装说明

- 核心依赖与 OCR 直接依赖锁定到本次已测试的版本，见 requirements.txt、requirements-ocr.txt。OCR 单独安装，避免普通文字文件用户安装大型运行时。
- OCR 默认 CPU 推理并关闭 MKL-DNN，避免已在 Windows PaddlePaddle 3.3.1 上复现的 oneDNN/PIR 兼容错误；不要求 GPU。
- PyMuPDF 按其 AGPL/商业许可发布；单位集成和再分发时按实际部署选择适用许可。本包不捆绑其二进制。
- 不修改 WorkBuddy 全局配置，不配置模型密钥，不自动发送邮件或上传文档。
- 运行 `verify` 仅完成结构和完整性检查。WorkBuddy、Word、WPS、阅读器及真实人工已审案例的结果需在项目验收记录中单独留存。
- 修改原件、review.json 或依据后从 extract/check 重跑。输出固定写在项目目录，重复运行会更新派生结果；不同送审版本应分开目录。

官方技能包格式：https://open.workbuddy.cn/docs/skill
