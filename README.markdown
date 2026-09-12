MorseWriter
-----------

<p align="center">
  <img src="https://github.com/willwade/MorseWriter/raw/main/res/MorseWriterLogo.jpeg" height="128" width="128"  />
  <img src="https://github.com/willwade/MorseWriter/raw/main/screenshot1.png" height="111" width="194" />
  <img src="https://github.com/willwade/MorseWriter/raw/main/screenshot2.png" height="106" width="131" />
</p>


This is a small system tray app designed in Python to interpret one or two key presses pressed in a set way (morse) and convert them to the key equivalent. This should mean that a user who has good timing can access the entire computer to write and control their machine - potentially with one or two keys or switches. Mouse implementation is flaky right now.  

For code, bug tracking and feature requests see [https://github.com/willwade/MorseWriter/](https://github.com/willwade/MorseWriter/)

**Requirements**

Pretty multiplatform. Well should be..although hideous problem on MacOS. 

**Install with virtualenv (windows)**

```bash
# tested on py 3.11.4
pip install -r requirements.txt
python MorseCodeGUI.py
```

**Make executable with pyinstaller**

```bash
pip install pyinstaller
pyinstaller MorseCodeGUI.spec
```

**使用说明**

本分支使用简体中文界面和默认深色主题。

* 选择单键、双键或三键模式，再点击“开始输入”。双键模式的第一个键输入点，第二个键输入划；三键模式额外使用第三个键结束当前字符。
* 只有当前模式选定的输入键用于摩斯输入，其他按键和数字小键盘仍可正常使用。
* 设置窗口和码表窗口点击 × 后最小化，正在进行的摩斯输入会继续运行。
* 点击系统托盘图标或选择“显示窗口”可恢复窗口。
* 托盘菜单中的“暂停输入”恢复普通键盘输入，“继续输入”重新启用摩斯输入。“打开设置”会停止输入并返回设置窗口。
* 需要关闭程序时，在托盘菜单中选择“退出”，程序会释放键盘监听。
* 码表窗口获得焦点时，Ctrl+Shift+P 可返回设置。
* 码表默认打开完整的“主键盘”页，包含字母、数字、标点、F1–F12、方向键及控制键；可使用页面选择器或切页编码进入“字母”“鼠标”“数字”页。相同编码在不同页面可能表示不同动作，请按当前页面的引导输入。
* 单次组合键：先输入 Ctrl，再输入 V，执行一次 Ctrl+V 后自动释放 Ctrl；Shift、Alt 和 Windows 键同样可与后续按键组合。
* 缩写仅在字母与候选页输入空格完成单词后展开；主键盘和数字页保持原字符输出。候选词和缩写保留原有大小写。
* 连续组合键：先输入“修饰键锁定”，再输入 Ctrl 和 V，可保持 Ctrl 继续操作；再次输入“修饰键锁定”会关闭锁定并释放修饰键。该开关不自动重复上一个动作。
* “左向Tab”执行 Shift+Tab；“开始菜单”打开开始菜单，“应用菜单”打开当前项目的上下文菜单。

**Tips for first use**

* 使用 [完整码表](codechart.md) 或软件内的码表引导查看当前页面的编码。
* Use notepad to test your typing skills
* To get used to typing you have to first get used to the speed of things. Just try a e and a t for starters. 
* Getting auditory feedback on the key entered may be useful. In this case you may find [this additional program](https://github.com/willwade/Scripting-Recipes-for-AT/tree/master/Autohotkey/SoundingKeyboardMouse#keyboard-sounder) of use. 

**Issues:**

* Debug window needs to be minimised even if debug switched off
* 1 & 2 input keys relate to the keys above the letters on the keyboard - not a numeric keypad

**Tips for Building yourself**

You will need Python 2.6 or earlier for [pyinstaller](http://www.pyinstaller.org/). You will also need to install some extra libraries - notably [PyHook](http://sourceforge.net/projects/uncassist/), [PyWin32](http://sourceforge.net/projects/pywin32/) and [PyQt](http://www.riverbankcomputing.com/software/pyqt/intro)

    python Configure.py
    python Makespec.py --onefile path_to_your_morsecodegui.py 
    python Build.py path_to_the_Morsecodegui.spec

**Getting Involved**

In order to start contributing code to the project, follow the steps below:

1. Fork this repo. For detailed instructions visit [http://help.github.com/fork-a-repo/](http://help.github.com/fork-a-repo/)
2. Hack away! but please make sure you follow [this branching model] (http://nvie.com/posts/a-successful-git-branching-model/). That means, make your pull requests against the **develop** branch, not the **master** branch. 

**Research**

For further research and reading material on the use of Morse in assistive technology see [http://www.citeulike.org/user/willwade/tag/morse](http://www.citeulike.org/user/willwade/tag/morse) as a starting point

**Credits**

* DavidDW for coding geniusness
* [Darci USB for code conversion](http://www.westest.com/darci/index.html) 
* Andy/Lisa/[ACE North](http://www.ace-north.org.uk/) for original thoughts 
* [Jim Lubin and others](http://www.makoa.org/jlubin/morsecode.htm)
* [The Noun Project](http://thenounproject.com/) for the icon 

Please contact me if you intend to fork this or do anything fun with it - will AT e-wade.net   

Enjoy!

**完整摩斯码表**

[查看与软件同步的中文完整码表](codechart.md)。码表从软件实际使用的配置和动作名称自动生成，覆盖主键盘、字母、鼠标、数字四个页面。

维护时执行 `python tools/generate_codechart.py` 更新码表，执行 `python tools/generate_codechart.py --check` 检查是否与软件一致。

## License

MorseWriter is licensed under the MIT License:

  Copyright (c) 2024 Will Wade (http://acecentre.org.uk/)

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
  THE SOFTWARE.
