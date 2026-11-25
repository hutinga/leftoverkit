# LeftoverKit

**AI 干完了，仓库里还剩什么？**

一条命令，只读扫描 Git 仓库里的旧工作树、日志、临时脚本、补丁和测试报告。每条发现都带着识别依据和文件体积。

**[在线试玩](../../../actions/runs/45606858091) · [扫我的仓库](#先试只读扫描) · [English](../README.md)**

[![首次扫描在被 Git 忽略的父目录里发现 Playwright 报告，并高亮展示识别依据](media/first-scan-zh.gif)](../../../actions/runs/45606858091)

这份 Playwright 报告藏在 Git 忽略的目录里。LeftoverKit 第一次扫，就从报告内容里找到了识别标记。演示用的是合成仓库，事先登记的文件为零。

## 先试只读扫描

在想检查的项目目录里，复制运行下面这段命令。适用于 macOS 和 Linux，需要 Python 3.11+、Git、`curl` 和 `uv`。

```sh
repo=$(curl -fsSL https://api.github.com/repositories/1471583448 |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["clone_url"])') &&
  uvx --from "git+$repo" leftoverkit scan
```

扫描不会写清理记录，也不会移动文件。安装版可直接运行 `leftoverkit scan`。用 `--json` 可以查看完整结果。

## 清理和恢复

默认的 `clean` 只处理当前 checkout 里符合规则的未分配任务产物。并行使用时，把任务 ID 带到 `scan`、`clean`、`batches` 和 `undo`。其他任务的产物会留在原处。想从主 checkout 清理已合并的闲置工作树或共享 scratch 时，显式加 `--repo`。

如果你已经克隆了 LeftoverKit，从这个工具的源码目录执行：

```sh
uv tool install .
leftoverkit install
```

第二条用于安装 Codex 和 Claude Code 的 skill。隔离中的文件还能恢复，磁盘空间要等明确执行到期的 `purge` 才会释放。工作树隔离期间，Git 分支仍被该工作树占用。

[从零登记的扫描案例](DEMO.md) · [技术边界](DESIGN.md) · [验证记录](VERIFICATION.md)
