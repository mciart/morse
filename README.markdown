# 摩斯输入（MorseWriter）

用一到三个按键输入摩斯码，完成文字输入、键盘快捷键和鼠标操作。本项目基于 [MorseWriter](https://github.com/willwade/MorseWriter) 改进，提供简体中文界面，主要面向 Windows。

[完整码表](codechart.md) · [问题反馈](https://github.com/mciart/morse/issues)

## 功能

- 统一的虚拟键盘与鼠标引导：按键按常见键盘位置排列，功能键、导航键、符号和鼠标操作同时可见，日常使用无需切页。
- 默认跟随系统切换深色与浅色外观，也可在设置中固定为“浅色”或“深色”。主题选择立即应用并保存。
- 支持单键、双键、三键输入，可调整点划时长、字符间隔、字号和提示音。
- 支持单次组合键、修饰键锁定，以及鼠标移动、点击、双击和拖动。
- 点击窗口的 × 会最小化并继续输入；通过系统托盘暂停、恢复或退出。

中文适配指软件界面；当前不提供中文摩斯编码或中文输入法。

## 快速开始

安装 Python 3 和 Git，在 PowerShell 中执行：

```powershell
git clone https://github.com/mciart/morse.git
cd morse
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe MorseCodeGUI.py
```

已克隆项目时，从项目目录内创建虚拟环境即可。后续启动只需执行最后一行命令。

1. 打开要输入的应用，首次练习建议使用记事本。
2. 在软件中选择按键数量及对应输入键，按需要调整时长、提示音和主题。
3. 点击“开始输入”，将焦点切回目标应用，再输入摩斯码。
4. 先练习 `E（•）` 和 `T（—）`，再参照面板输入其他按键。

只有当前模式选定的输入键用于摩斯输入；其他按键和数字小键盘可照常使用。选择 `1`、`2` 时，对应字母上方的数字键。

## 使用说明

### 输入模式

`•` 表示点，`—` 表示划。

| 模式 | 点与划 | 完成一个字符 |
| --- | --- | --- |
| 单键 | 短按输入点，长按输入划，以“点划分界时长”为界 | 松开后等待“字符间隔” |
| 双键 | 第一个键输入点，第二个键输入划 | 松开后等待“字符间隔” |
| 三键 | 第一个键输入点，第二个键输入划 | 按第三个键立即完成 |

### 键盘与鼠标引导

默认面板按键盘和鼠标布局展示编码，输入过程中会提示仍可匹配的动作。键盘沿用原有编码；鼠标操作及候选选择采用独立的七位编码，与键盘编码共用一个面板。

习惯旧编码时，可在设置的“输入面板”选项中选择兼容主键盘、字母与候选、鼠标短码或数字短码，再开始输入。旧页面中的相同编码可能表示不同动作，请以所选码表为准。全部编码均可在 [完整码表](codechart.md) 中查询。

统一面板支持候选词选择，直接按键保持原字符输出。自动缩写仅在兼容的“字母与候选”页面中生效：输入空格完成单词后展开。

### 组合键

- 单次操作：先输入 `Ctrl`，再输入 `V`，执行一次 `Ctrl+V` 后自动释放 `Ctrl`。`Shift`、`Alt` 和 `Windows` 键的用法相同。
- 连续操作：先开启“修饰键锁定”，再输入 `Ctrl` 和其他按键；再次输入“修饰键锁定”会关闭锁定并释放修饰键。它不会自动重复上一项操作。
- “左向 Tab”执行 `Shift+Tab`；“开始菜单”打开系统开始菜单；“应用菜单”打开当前项目的上下文菜单。

### 窗口与托盘

- 点击 ×：最小化窗口，继续接收摩斯输入。
- 点击托盘图标或选择“显示窗口”：恢复窗口。
- “暂停输入”与“继续输入”：停用或恢复摩斯输入；暂停时释放程序按住的修饰键。
- “打开设置”或面板上的“返回设置”：停止输入并修改配置。码表窗口获得焦点时也可按 `Ctrl+Shift+P` 返回设置。
- “退出”：关闭程序并释放键盘监听及修饰键。

## 开发

软件引导与文档共用 `user_data/layouts.json` 中的编码。修改映射后生成文档，并运行检查与测试：

```powershell
.\.venv\Scripts\python.exe tools/generate_codechart.py
.\.venv\Scripts\python.exe tools/generate_codechart.py --check
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:QT_QPA_PLATFORM
```

测试通过模拟键盘和鼠标输出验证行为，界面测试使用离屏模式。实际输入体验仍需在目标应用中验证。

打包 Windows 程序：

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean MorseCodeGUI.spec
```

构建结果位于 `dist` 目录。问题反馈和改进建议请提交到 [本仓库](https://github.com/mciart/morse)。

## 许可证与致谢

本项目采用 [MIT 许可证](LICENSE)，允许使用、修改与分发，需保留原版权及许可声明。

感谢原作者 Will Wade、DavidDW，提供早期构想的 Andy、Lisa 与 ACE North，以及 Darci USB、Jim Lubin 等人的摩斯输入工作；图标来源于 The Noun Project。
