"""以紧凑的指令轨迹演示 Y86-64 程序，cpu.py 仍输出完整 JSON。"""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
STATUS_NAMES = {1: "AOK", 2: "HLT", 3: "ADR", 4: "INS"}
CONTROL_OPS = {"call", "ret", "halt", "jmp", "jle", "jl", "je", "jne", "jge", "jg"}


def read_listing(path):
    """提取 .yo 中的源代码注释，作为机器执行轨迹的显示标签。"""
    listing = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        code, separator, source = line.partition("|")
        match = re.match(r"\s*(0x[0-9a-fA-F]+):\s*([0-9a-fA-F]+)\s*$", code)
        if not match:
            continue
        address = int(match.group(1), 16)
        instruction = source.split("#", 1)[0].strip() if separator else ""
        if ":" in instruction:
            instruction = instruction.split(":", 1)[1].strip()
        listing[address] = instruction or match.group(2)
    return listing


def format_changes(previous, current):
    changes = []
    for register, value in current["REG"].items():
        if value != previous["REG"].get(register, 0):
            bits = value & 0xFFFFFFFFFFFFFFFF
            changes.append(f"%{register}=0x{bits:x}")
    if current["CC"] != previous["CC"]:
        cc = current["CC"]
        changes.append(f"ZF/SF/OF={cc['ZF']}/{cc['SF']}/{cc['OF']}")
    if current["STAT"] != 1:
        changes.append(STATUS_NAMES.get(current["STAT"], str(current["STAT"])))
    return ", ".join(changes) or "—"


def main():
    parser = argparse.ArgumentParser(description="运行 .yo 程序并展示控制流及寄存器变化")
    parser.add_argument(
        "program", nargs="?", type=Path, default=ROOT / "test" / "abs-asum-cmov.yo"
    )
    parser.add_argument("--all", action="store_true", help="显示每条指令；默认仅显示控制转移")
    args = parser.parse_args()
    try:
        listing = read_listing(args.program)
        with args.program.open(encoding="utf-8") as source:
            result = subprocess.run(
                [sys.executable, str(ROOT / "cpu.py")],
                stdin=source, capture_output=True, text=True, timeout=10, check=True,
            )
        states = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"无法完成演示：{error}\n")
    if not states:
        parser.exit(1, "模拟器没有输出状态快照。\n")

    print(f"程序：{args.program.name}")
    print("轨迹中的 PC 为执行前地址，next PC 为执行后状态；终止指令保留 PC。")
    print(f"{'序号':>4}  {'PC':>6}  {'next PC':>7}  {'指令':<26}  状态变化")
    previous = {"PC": 0, "REG": {}, "CC": {"ZF": 1, "SF": 0, "OF": 0}, "STAT": 1}
    for index, state in enumerate(states, 1):
        pc = previous["PC"]
        instruction = listing.get(pc, "(无源代码标签)")
        mnemonic = instruction.split()[0]
        if args.all or mnemonic in CONTROL_OPS or state["STAT"] != 1:
            print(
                f"{index:>4}  0x{pc:04x}  0x{state['PC']:04x}  "
                f"{instruction:<28}  {format_changes(previous, state)}"
            )
        previous = state
    final = states[-1]
    registers = final["REG"]
    print(f"\n状态快照：{len(states)} 条（包含最后一次停机或异常快照）")
    print(f"STAT={STATUS_NAMES.get(final['STAT'], final['STAT'])}, PC=0x{final['PC']:x}")
    print(f"%rax={registers['rax']} (0x{registers['rax'] & 0xFFFFFFFFFFFFFFFF:x})")
    print(f"%rsp=0x{registers['rsp'] & 0xFFFFFFFFFFFFFFFF:x}, %rsi={registers['rsi']}")
    print(f"CC={final['CC']}")
    return 0 if final["STAT"] == 2 else 1


if __name__ == "__main__":
    sys.exit(main())
