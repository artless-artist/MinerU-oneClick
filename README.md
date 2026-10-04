# MinerU 4.0.10 便携版（Windows x64）

MinerU: 把 PDF / 图片 / Word / PPT / Excel 等文档转成结构化 Markdown 等格式，便于AI进行解析的开源项目，源项目地址：[opendatalab/MinerU](https://github.com/opendatalab/MinerU)

本项目为 MinerU的 Windows版本免安装整合包，内置一键启动、环境自检，**首次启动时自动补齐缺失组件**（Python 依赖 + 模型权重），不含任何对 MinerU 源码的修改。

本整合包具体特性如下：


* **便携版**：不自带安装程序，双击 `启动MinerU.bat` 就能用；整包可搬移，自带环境无须配置；不写注册表，删除文件夹即可卸载
* **自动配置**： 首次启动会自动下载所需环境与模型（优先使用国内的镜像源以加速下载），如果检查到已经就绪就跳过，不会重复下载（如果需要在无网环境下使用，可以先在有网电脑上启动一次，待下载就绪后将整个整合包的文件夹复制到无网电脑上）

---

## 快速开始

1. 下载并解压本包到任意目录（**路径使用纯英文，不要包含中文字符**，因为项目中的 VLM 依赖 llama.cpp 的 Windows 原生库，无法在中文路径下使用，路径含中文时本包不会使用VLM解析版面，虽然仍能正常工作，且对于纯文本 PDF 效果差不多，但要用完整质量就请放英文路径
2. 双击 **`启动MinerU.bat`**（或 `Start-MinerU.bat`，两者等价）
3. 首次启动若缺组件会自动下载，等它跑完
4. 弹出菜单后输入1再回车，打开对应网址即可使用

```
  [1] 打开网页界面 (WebUI)      ← 推荐，拖拽文件即可解析
  [2] 解析文件（命令行向导）
  [3] 打开 MinerU 命令行
  [4] 环境自检 / 模型校验
  [5] 检查并补齐缺失组件（依赖 + 模型）
  [0] 退出
```

也可以直接把 PDF 拖到 `启动MinerU.bat` 上，跳过菜单直接解析。

---


## 目录结构

```text
MinerU/
├─ 启动MinerU.bat            # 一键入口（中文名，方便双击）
├─ Start-MinerU.bat          # 同上（ASCII 名，方便命令行/脚本调用）
├─ README.md                 # 本文件
├─ LICENSE-MinerU.md         # MinerU 官方许可证（再分发请保留）
├─ .gitignore               # 分发用忽略规则，避免模型文件入库
├─ requirements.lock.txt     # 112 个依赖的版本锁定表，供首启精确复现
│
├─ app/                      # 启动器与自检（纯 Python，可读可改）
│  ├─ launcher.py            #   交互菜单、横幅、自检 [4]、补齐 [5]
│  ├─ bootstrap.py           #   首启自举：装依赖 + 下模型
│  ├─ pkg_info.py            #   所需环境与模型的检查结果
│  ├─ env_setup.py           #   环境隔离：所有可写路径重定向进包内
│  ├─ cli.py                 #   命令行转发壳
│  └─ bin/*.bat              #   mineru / mineru-kit / mineru-api 等命令外壳
│
├─ scripts/
│  └─ bootstrap_python.ps1   # 步骤 0：下载便携 CPython（纯 ASCII，只输出英文）
│
├─ runtime/python/           # 便携解释器（首启自动下载，不入库）
├─ data/                     # 全部可写数据（模型/日志/临时/缓存，不入库）
│  └─ models/                #   模型权重（首启自动下载，不入库）
└─ output/                   # 解析结果默认输出到这里（不入库）
```

---

## 高级用法

包内已经为你准备好命令外壳（`app\bin\` 优先于 `Scripts\`，保证整包搬移后仍可用）。
从菜单 **[3] 打开 MinerU 命令行** 进入交互式 shell 后：

```bat
:: 解析单个文件，指定档位与输出格式
mineru-kit parse 文档.pdf -o D:\out --tier standard -f markdown

:: 核对模型状态
mineru-kit models verify --tier standard

:: 起 WebUI，指定端口
mineru-kit webui --server-name 127.0.0.1 --server-port 7860 --api-server-tier standard

:: 查看完整帮助
mineru-kit --help
```

也可以不进 shell，直接用包内解释器调用：

```bat
runtime\python\python.exe app\cli.py mineru-kit parse 文档.pdf -o output --tier basic
```

---

## 如何自己构建

1. 从 [PyPI](https://pypi.org/project/mineru/) 或 [官方仓库](https://github.com/opendatalab/MinerU) 取 `mineru-4.0.10-py3-none-any.whl`
2. 用 `scripts\bootstrap_python.ps1` 下载便携 CPython 3.12.15
3. `runtime\python\python.exe -m pip install -r requirements.lock.txt`（国内先加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`）
4. `runtime\python\python.exe app\bootstrap.py --tier standard` 预下模型
5. 手工清理 `__pycache__` / `*.pdb` / `data\{logs,temp,gradio,...}` 后再分发包

---

## 许可证与致谢

- **MinerU**  [MinerU Open Source License](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md) 基于 Apache 2.0 开源，并带有如下附加条款：

	- 商业使用：MAU ≤ 1 亿 **且** 月收入 ≤ 2000 万美元时免费；
	- **署名义务**：若基于 MinerU 向第三方提供在线服务，必须在界面或公开文档显著位置标明使用了 MinerU。

- **便携 CPython** 由 [astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone) 提供，遵循 PSF Python 许可证。
- **模型权重**来自 ModelScope：
  - `OpenDataLab/MinerU-4_models_onnx`（ONNX：版面/OCR/公式/表格）
  - `jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF`（版面 VLM，GGUF）
- 本便携外壳（`app/` + `scripts/`）不修改 MinerU 任何源码。
