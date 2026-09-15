# 开发与构建

在项目目录中使用 Python 3 创建虚拟环境并运行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe MorseCodeGUI.py
```

界面、输入引擎、系统监听、音频与 Windows 集成各自独立。结构说明见 [项目说明](../README.markdown)。英文预测功能已移除；构建不需要预测依赖和词库。

源码运行使用项目中的 `user_data`，不会替换已有个人配置。仓库保留的旧 `config.json` 使用三键（1、2、Space）且静音，源码首次启动会沿用它；安装包不携带该文件，在用户数据目录中生成或迁移配置。

`config_store.py` 逐字段校验配置，无效字段单独使用默认值；无法读取的整份配置回退为默认设置并记录日志，读取过程不重写文件。保存时先序列化、写入并刷新同目录临时文件，再用原子替换更新配置；失败保留原文件，由界面显示提示。

`mouse_output.py` 跟踪程序发出的鼠标按下事件，暂停、返回设置及退出时只释放自己记录的按钮。输出异常后的清理会继续尝试其他按钮，失败的释放保留记录以便后续重试。

`morse_engine.py` 仅在状态或确认进度改变时发出反馈，首次反馈及重置后的反馈仍保留。`tone_audio.py` 以片段处理完全静音区间，同时推进音频时间与相位；点划边沿、渐入渐出、试听及确认音仍按原时间处理，不降低音频时钟频率。

## 验证

```powershell
.\.venv\Scripts\python.exe tools/generate_codechart.py --check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

英文码表由 `user_data/layouts.json` 的统一布局、`morse_profiles.py` 的标准化处理和 `key_catalog.py` 的动作定义共同生成。拼音码表直接使用运行时的 `pinyin_codes.build_pinyin_layout`，声母、韵母及控制码保持同源。保存的基础布局仍只有 `desktop`；拼音层在内存中派生，旧用户布局也在内存中迁移，不覆盖原文件。

修改映射后先执行 `tools/generate_codechart.py`，再用 `--check` 同时检查 `codechart.md` 与 `docs/pinyin-code-chart.md`。`guide_gesture.py` 负责拼音层与码表显隐手势：`toggle` 模式双击切层、单击显隐，`hold` 模式按住拼音、松开英文、双击显隐。新用户默认 `toggle`，旧 `toggle` 配置沿用新手势，已有 `hold` 配置保持不变。单击最多等待 300 毫秒以区分双击；等待期间输入点划会确认显隐，电码仍归属当前层。`KeyboardOutput.send_pinyin` 输出逐个拉丁按键以进入目标拼音输入法。测试使用模拟键鼠和音频，不能替代实际输入法、设备延迟或游戏兼容性验证。

`windows_ime.py` 读取前台输入线程的键盘布局与默认输入法窗口，识别微软拼音并执行有超时限制的定向中／英切换；写入前核对目标，写入后读取状态确认。现代输入法共用键盘布局时，只有能够唯一确定微软拼音才允许同步，不使用调用线程的输入法状态冒充前台状态。`ime_sync.py` 在工作线程中轮询和切换，避免占用界面或音频线程。

切到英文时使用 `IMC_SETOPENSTATUS(0)` 结束微软拼音的当前组词，保留尚未选字内容的原拼音字母；只清除 `IME_CMODE_NATIVE` 可能无法结束组词或被输入法拒绝。切中文时重新打开输入法并设置中文转换模式。两种方向均以目标窗口的状态读回确认结果，不模拟 Enter、Space 或 Shift。界面按窗口变化、访问受限、响应超时及切换未确认分别提示失败；诊断日志记录失败原因与状态，不记录输入文字。

输入法隔离测试覆盖未知身份、权限与超时、目标变化、状态读回及延迟请求；不接触真实输入法。Windows 桌面上可额外运行：

```powershell
# 只读当前输入窗口的输入法状态，不采集输入文字
.\.venv\Scripts\python.exe tools/probe_windows_ime.py
# 在脚本自己创建的空白输入窗口验证切换，并恢复原状态
.\.venv\Scripts\python.exe tools/probe_windows_ime.py --self-test
```

自测不发送键盘输入、不改变系统输入法选择、不向其他窗口写入。只有 Windows 允许自建测试窗口获得前台时才执行切换，否则明确报告测试不可用。本机已验证微软拼音中／英连续切换和原状态恢复；这些结果不代替不同应用、权限或游戏环境的测试。

另用独立测试进程覆盖尚未选字的真实输入：

```powershell
.\.venv\Scripts\python.exe tools/check_native_ime.py --report build/native-ime.json
```

此检查只向自建输入框发送固定的 `nihao`，确认出现组词后切到英文，验证原拼音保留、追加 `e` 后为 `nihaoe`、再次回到中文及原状态恢复。窗口身份通过自有子进程管道确认；测试窗口没有取得前台时报告不可用，不向用户应用发送输入。

在 Windows 桌面上额外检查精简码表的真实显示与缩放：

```powershell
.\.venv\Scripts\python.exe tools/check_native_guide.py --report build/native-guide.json
```

此检查会短暂显示测试背景和码表，通过屏幕像素验证顶部切换、边角缩放、移动及隐藏后恢复。它不启动输入监听、不修改个人配置，默认只保存验收报告。CI 在没有可采集桌面时明确记录跳过；窗口消失或 Qt 绘制警告仍会使检查失败。

焦点检查只向本测试进程拥有的窗口发送鼠标激活消息，核对窗口不激活与任务栏样式，并验证右键菜单操作。若 Windows 不允许测试背景获得前台，报告会单独标记前台保持测试不可用；这些检查不替代实际全屏游戏验证。

显示缩放回归会在测试进程中模拟字体尺寸和 DPI 通知，验证放大、缩小及隐藏后恢复；报告会区分模拟事件与实际屏幕绘制。这不替代不同 DPI 显示器之间的硬件切换验证。

关闭自动适应只作用于英文完整码表；拼音和精简码表始终按窗口适配，精简模式通过窗口缩放保存整体比例。相关界面回归应覆盖这三种情况，不能把关闭选项理解为所有码表停止缩放。

## Windows 安装包

```powershell
.\build.ps1 -BootstrapCompiler
.\tools\check_frozen_build.ps1
```

构建脚本执行测试、资源校验、程序打包和中文安装包生成；安装包与 SHA256 校验文件位于 `dist`。编译器解包到项目的 `build/tools`，不安装全局工具。程序包只包含清单内的资源，不带开发者配置、日志或个人数据。安装包目前未代码签名，Windows SmartScreen 可能提示未知发布者。

不再使用的旧预测数据库、训练资源、WAV 音效、开发试验脚本和 Word 码表已从仓库移除，图标与标识图片保留。安装脚本中删除旧版捆绑词库的规则仍保留，作用于程序安装目录，不删除用户数据目录。

发布前更新根目录 `version` 和 `docs/releases` 中的中文说明。可先在 Actions 中手动运行“构建 Windows 安装包”，验证当前提交后再建立版本标签。发布工作流使用版本标签对应的代码重新构建、验证，再上传到 GitHub Release。
