# LeftoverKit

**AI 写完代码，也把它留下的临时文件清一下。**

装好以后就可以让 Codex 或 Claude Code 清理。

> 把你刚才生成、现在用不到的文件清一下。

也可以在 Git 项目里运行 `leftoverkit clean`。符合规则的截图、日志、测试报告、复现脚本和闲置工作树会移入隔离区。清理结束会给你恢复命令。

**991 → 0 → 991。** 一个合成项目真实跑过清理和恢复。可以在 [交互演示](demo.html) 里自己点，也可以看 [AI 会留下哪些东西](SCENARIOS.md)。

## 安装

适用于 macOS 和 Linux，需要 Python 3.11+、Git 和 `lsof`。克隆或下载源码后，在项目根目录运行下面的命令。

```sh
uv tool install . && leftoverkit install
```

`leftoverkit install` 为 Codex 和 Claude Code 安装 skill。只用命令行时，运行 `uv tool install .` 即可。

## 清理与恢复

```sh
leftoverkit clean
leftoverkit undo
leftoverkit scan
```

清理前会核对文件和 Git 状态。正在使用的文件、未合并的工作树、已跟踪的源码、来源不明的旧 `tmp/` 会留在原处。工作树处在隔离区时会继续占用对应分支，恢复或清除后按 Git 的正常规则处理。

隔离满 14 天后，运行 `leftoverkit purge` 可以回收磁盘空间。只想让它每天自己清理，可以定时运行 `leftoverkit -C /你的项目目录 clean`。

[复现案例](DEMO.md) · [英文 README](../README.md)
