# Y86-64 顺序执行模拟器

基于 Python 3 实现 Y86-64 顺序执行处理器。模拟器从标准输入读取 `.yo` 文件，依次完成取指、译码、执行、访存、写回和更新 PC，并向标准输出写出每条指令执行后的 JSON 状态快照。

## 运行与测试

运行环境为 Python 3，无第三方运行依赖。在仓库根目录执行：

```bash
python3 test.py --bin "python3 cpu.py"
python3 -m unittest discover -s tests -v
```

第一条命令使用课程提供的测试程序和标准答案逐状态比较；第二条命令检查条件码、整数溢出、指令编码、取指边界、栈操作和异常写回。

验证结果：21 个课程测试全部通过，29 项边界测试全部通过。GitHub Actions 同时执行这两组检查。

单独运行一个程序：

```bash
python3 cpu.py < test/abs-asum-cmov.yo
```

每条快照包含 `PC`、15 个通用寄存器 `REG`、条件码 `CC`、非零的八字节内存块 `MEM` 和处理器状态 `STAT`。寄存器和内存输出按有符号 64 位整数表示。状态编码为 `AOK=1`、`HLT=2`、`ADR=3`、`INS=4`。

课程评测脚本将测试通过比例显示为 `60.00 / 60.00`；课程项目页面将基础实现部分计为 180 分。保留课程脚本的原始评分显示。

## 指令与数据通路

| 指令类别 | 主要数据通路 |
| --- | --- |
| `rrmovq / cmovXX` | 读取 `rA`，条件成立时把 `valA` 写入 `rB` |
| `irmovq` | 把八字节立即数 `valC` 写入 `rB` |
| `rmmovq` | 计算 `R[rB] + valC`，向该地址写入 `R[rA]` |
| `mrmovq` | 计算 `R[rB] + valC`，将内存值写入 `rA` |
| `OPq` | 对 `valB` 与 `valA` 运算，写回 `rB` 并设置 `ZF/SF/OF` |
| `jXX` | 根据条件码选择 `valC` 或顺序地址 `valP` |
| `call` | 栈指针减 8，压入 `valP`，跳到 `valC` |
| `ret` | 从旧栈顶读取返回地址，栈指针加 8，跳到 `valM` |
| `pushq` | 栈指针减 8，压入译码时读出的 `valA` |
| `popq` | 从旧栈顶读出 `valM`，先更新栈指针，再写目标寄存器 |
| `halt / nop` | 停机并保留 PC，或顺序前进 |

`OPq` 支持 `addq`、`subq`、`andq` 和 `xorq`；条件传送和跳转支持无条件、`le`、`l`、`e`、`ne`、`ge`、`g`。

处理器有 8192 字节内存。指令中的八字节常数和内存中的八字节数据均使用小端字节序。ALU 运算按 64 位截断；加减法分别按有符号运算判断溢出，逻辑运算清零 `OF`。仅 `OPq` 更新条件码，地址计算与栈指针变化保留原条件码。

以下语义与课程要求一致：

- `pushq %rsp` 压入递减前的栈指针。
- `popq %rsp` 先写回递增后的栈指针，再让弹出的内存值覆盖 `%rsp`。
- 取指遇到非法编码或越界时立即停止后续阶段。
- 访存发生 `ADR` 时，非法读返回 0、非法写不改变内存；本条指令仍执行写回，但不更新 PC。
- `halt` 保留当前 PC，记录终止快照后退出。

## 现场演示

```bash
python3 demo.py
python3 demo.py --all
python3 demo.py test/asumr.yo
```

`demo.py` 运行同一份 `cpu.py`，将实际 JSON 结果转换成便于展示的控制流表。默认演示 `abs-asum-cmov.yo`；`--all` 展示每条指令。指令文字来自 `.yo` 的汇编注释，显示地址和状态来自模拟器结果。

`abs-asum-cmov.yo` 对四个数组元素的绝对值求和。主程序设置 `%rdi` 为数组地址、`%rsi` 为元素数量，调用 `absSum`。循环从 `0x77` 读取元素，在 `0x85` 通过 `cmovg` 选择绝对值，在 `0x8d` 根据剩余数量继续或退出；两次 `ret` 最终返回 `0x13` 的 `halt`。

最终 `%rax = 188899839028173 = 0xabcdabcdabcd`，`%rsp = 0x200`，`%rsi = 0`，`PC = 0x13`，`STAT = HLT`。输出共 46 条状态快照，其中包括最后一条 `halt` 快照。

## 文件

```text
cpu.py                  六阶段模拟器与 JSON 输出
demo.py                 现场演示入口
test.py                 课程评测脚本
test/                   课程 .yo 测试程序
answer/                 课程标准状态快照
tests/                  独立边界测试
presentation/           汇报 PPT、讲解提纲与生成文件
.github/workflows/      GitHub 自动评测
```

提交时将包含实现的 GitHub 仓库链接提交到 E-Learning 项目作业；汇报 PPT 按课程安排另行提交。现场汇报需要结合程序运行与源码解释六个阶段。

- [汇报 PPT](presentation/output/Y86-64_项目汇报.pptx)
- [汇报 PDF 预览](presentation/output/Y86-64_项目汇报.pdf)
- [讲稿与六阶段答辩提纲](presentation/讲稿与答辩.md)

## 参考

- [课程项目要求](https://ics-26fall-fdu.github.io/project/pj/)
- [Python 模板仓库](https://github.com/ICS-26Fall-FDU/PJ-Y86-Simulator-py)
- CS:APP 第四章，处理器体系结构。
