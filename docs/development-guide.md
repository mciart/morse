# 开发与构建

在项目目录中使用 Python 3 创建虚拟环境并运行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe MorseCodeGUI.py
```

界面、输入引擎、系统监听、音频与 Windows 集成各自独立。结构说明见 [项目说明](../README.markdown)。英文预测功能已移除；构建不需要预测依赖和词库。

## 验证

```powershell
.\.venv\Scripts\python.exe tools/generate_codechart.py --check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

英文码表由 `user_data/layouts.json` 的统一布局、`morse_profiles.py` 的标准化处理和 `MorseCodeGUI.py` 的动作定义共同生成。拼音码表直接使用运行时的 `pinyin_codes.build_pinyin_layout`，声母、韵母及控制码保持同源。保存的基础布局仍只有 `desktop`；拼音层在内存中派生，旧用户布局也在内存中迁移，不覆盖原文件。

修改映射后先执行 `tools/generate_codechart.py`，再用 `--check` 同时检查 `codechart.md` 与 `docs/pinyin-code-chart.md`。`guide_gesture.py` 负责按住／单击切层和双击显隐，`KeyboardOutput.send_pinyin` 输出逐个拉丁按键以进入目标拼音输入法。测试使用模拟键鼠和音频，不能替代实际输入法、设备延迟或游戏兼容性验证。

在 Windows 桌面上额外检查精简码表的真实显示与缩放：

```powershell
.\.venv\Scripts\python.exe tools/check_native_guide.py --report build/native-guide.json
```

此检查会短暂显示测试背景和码表，通过屏幕像素验证顶部切换、边角缩放、移动及隐藏后恢复。它不启动输入监听、不修改个人配置，默认只保存验收报告。CI 在没有可采集桌面时明确记录跳过；窗口消失或 Qt 绘制警告仍会使检查失败。

焦点检查只向本测试进程拥有的窗口发送鼠标激活消息，核对窗口不激活与任务栏样式，并验证右键菜单操作。若 Windows 不允许测试背景获得前台，报告会单独标记前台保持测试不可用；这些检查不替代实际全屏游戏验证。

显示缩放回归会在测试进程中模拟字体尺寸和 DPI 通知，验证放大、缩小及隐藏后恢复；报告会区分模拟事件与实际屏幕绘制。这不替代不同 DPI 显示器之间的硬件切换验证。

## Windows 安装包

```powershell
.\build.ps1 -BootstrapCompiler
.\tools\check_frozen_build.ps1
```

构建脚本执行测试、资源校验、程序打包和中文安装包生成；安装包与 SHA256 校验文件位于 `dist`。编译器解包到项目的 `build/tools`，不安装全局工具。程序包只包含清单内的资源，不带开发者配置、日志或个人数据。

发布前更新根目录 `version` 和 `docs/releases` 中的中文说明。可先在 Actions 中手动运行“构建 Windows 安装包”，验证当前提交后再建立版本标签。发布工作流使用版本标签对应的代码重新构建、验证，再上传到 GitHub Release。
