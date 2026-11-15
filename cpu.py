import sys
import json
import struct

# --- 常量定义 ---
AOK, HLT, ADR, INS = 1, 2, 3, 4

RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = 0, 1, 2, 3, 4, 5, 6, 7
R8, R9, R10, R11, R12, R13, R14, RNONE = 8, 9, 10, 11, 12, 13, 14, 15

I_HALT, I_NOP, I_RRMOVQ, I_IRMOVQ = 0, 1, 2, 3
I_RMMOVQ, I_MRMOVQ, I_ALU, I_JMP = 4, 5, 6, 7
I_CALL, I_RET, I_PUSHQ, I_POPQ = 8, 9, 10, 11

class Y86Simulator:
    def __init__(self, mem_size=8192):
        self.REG_NAMES = {
            0: "rax", 1: "rcx", 2: "rdx", 3: "rbx", 4: "rsp", 5: "rbp", 6: "rsi", 7: "rdi",
            8: "r8", 9: "r9", 10: "r10", 11: "r11", 12: "r12", 13: "r13", 14: "r14"
        }
        self.mem_size = mem_size
        self.memory = bytearray(mem_size)
        self.PC = 0
        self.STAT = AOK

        self.REG = {i: 0 for i in range(15)}
        self.REG[RNONE] = 0

        self.CC = {"ZF": 1, "SF": 0, "OF": 0}

        # 数据通路暂存值，在一条指令的六个执行阶段之间传递数据。
        self.icode = I_NOP
        self.ifun = 0
        self.rA = RNONE
        self.rB = RNONE
        self.valC = 0
        self.valP = 0
        self.valA = 0
        self.valB = 0
        self.valE = 0
        self.valM = 0
        self.Cnd = False

        self.trace = []

    # ---------------- 辅助方法 ----------------
    def to_signed64(self, val):
        """将无符号 64 位整数截断并转换为有符号补码整数"""
        val = val & 0xFFFFFFFFFFFFFFFF
        if val & 0x8000000000000000:
            val -= 0x10000000000000000
        return val

    def sign_extend(self, val, bits=64):
        """将指定位数的无符号整数转换为补码有符号整数"""
        sign_bit = 1 << (bits - 1)
        return (val & (sign_bit - 1)) - (val & sign_bit)

    def uint64(self, val):
        """将数值截断为 64 位无符号整数"""
        return val & 0xFFFFFFFFFFFFFFFF

    def read_mem(self, addr, size):
        """从指定内存地址读取指定字节数的数据，若地址越界则触发 ADR 异常"""
        if addr < 0 or addr + size > self.mem_size:
            self.STAT = ADR
            return 0
        data = self.memory[addr : addr+size]
        if size == 1:
            return data[0]
        elif size == 8:
            return struct.unpack('<Q', data)[0]
        return 0

    def write_mem(self, addr, size, val):
        """将数据写入指定的内存地址，若地址越界则触发 ADR 异常"""
        if addr < 0 or addr + size > self.mem_size:
            self.STAT = ADR
            return
        if size == 8:
            self.memory[addr : addr+size] = struct.pack('<Q', self.uint64(val))

    def check_cond(self, ifun):
        """根据当前条件码寄存器，判断跳转或条件传送是否满足"""
        zf, sf, of = self.CC["ZF"], self.CC["SF"], self.CC["OF"]
        if ifun == 0: return True
        if ifun == 1: return (sf ^ of) | zf
        if ifun == 2: return sf ^ of
        if ifun == 3: return zf
        if ifun == 4: return not zf
        if ifun == 5: return not (sf ^ of)
        if ifun == 6: return not (sf ^ of) and not zf
        return False

    # ---------------- 六阶段数据通路 ----------------

    def fetch(self):
        """读取并验证指令，提取寄存器编号、立即数和顺序后继地址。"""
        self.rA = self.rB = RNONE
        self.valC = 0
        self.valP = self.PC
        if self.PC < 0 or self.PC >= self.mem_size:
            self.STAT = ADR
            return

        byte0 = self.read_mem(self.PC, 1)
        if self.STAT != AOK: return

        self.icode = byte0 >> 4
        self.ifun = byte0 & 0x0F

        if self.icode not in range(I_HALT, I_POPQ + 1):
            self.STAT = INS
            return
        max_ifun = 6 if self.icode in (I_RRMOVQ, I_JMP) else 3 if self.icode == I_ALU else 0
        if self.ifun > max_ifun:
            self.STAT = INS
            return
        if self.icode == I_HALT:
            self.STAT = HLT
            return

        need_reg = self.icode in (
            I_RRMOVQ, I_IRMOVQ, I_RMMOVQ, I_MRMOVQ, I_ALU, I_PUSHQ, I_POPQ
        )
        need_valC = self.icode in (I_IRMOVQ, I_RMMOVQ, I_MRMOVQ, I_JMP, I_CALL)
        cursor = self.PC + 1
        if need_reg:
            reg_byte = self.read_mem(cursor, 1)
            if self.STAT != AOK:
                return
            self.rA, self.rB = reg_byte >> 4, reg_byte & 0x0F
            cursor += 1
            if self.icode == I_IRMOVQ:
                valid_regs = self.rA == RNONE and self.rB != RNONE
            elif self.icode in (I_PUSHQ, I_POPQ):
                valid_regs = self.rA != RNONE and self.rB == RNONE
            elif self.icode in (I_RMMOVQ, I_MRMOVQ):
                # rB 为 RNONE 时，使用 valC 进行绝对寻址。
                valid_regs = self.rA != RNONE
            else:
                valid_regs = self.rA != RNONE and self.rB != RNONE
            if not valid_regs:
                self.STAT = INS
                return
        if need_valC:
            self.valC = self.read_mem(cursor, 8)
            if self.STAT != AOK:
                return
            cursor += 8
        self.valP = cursor

    def decode(self):
        """读取源寄存器；栈指令隐式使用 %rsp。"""
        srcA = RNONE
        srcB = RNONE

        if self.icode in (I_RRMOVQ, I_RMMOVQ, I_ALU, I_PUSHQ):
            srcA = self.rA
        elif self.icode in (I_POPQ, I_RET):
            srcA = RSP
        if self.icode in (I_RMMOVQ, I_MRMOVQ, I_ALU):
            srcB = self.rB
        elif self.icode in (I_PUSHQ, I_POPQ, I_CALL, I_RET):
            srcB = RSP
        self.valA = self.REG[srcA] if srcA != RNONE else 0
        self.valB = self.REG[srcB] if srcB != RNONE else 0

    def execute(self):
        """执行 ALU 运算和条件判断；只有 OPq 更新条件码。"""
        self.valE = 0
        self.Cnd = False

        aluA = 0
        aluB = 0

        if self.icode in (I_RRMOVQ, I_ALU):
            aluA = self.valA
        elif self.icode in (I_IRMOVQ, I_RMMOVQ, I_MRMOVQ):
            aluA = self.valC
        elif self.icode in (I_CALL, I_PUSHQ):
            aluA = -8
        elif self.icode in (I_RET, I_POPQ):
            aluA = 8

        if self.icode in (I_RMMOVQ, I_MRMOVQ, I_ALU, I_CALL, I_PUSHQ, I_RET, I_POPQ):
            aluB = self.valB

        if self.icode == I_ALU:
            signed_a, signed_b = self.sign_extend(aluA), self.sign_extend(aluB)
            if self.ifun == 0:
                result = signed_b + signed_a
            elif self.ifun == 1:
                result = signed_b - signed_a
            elif self.ifun == 2:
                result = aluB & aluA
            else:
                result = aluB ^ aluA
            self.valE = self.uint64(result)
            self.CC["ZF"] = int(self.valE == 0)
            self.CC["SF"] = (self.valE >> 63) & 1
            self.CC["OF"] = int(
                self.ifun in (0, 1) and not -(1 << 63) <= result < (1 << 63)
            )
        else:
            self.valE = self.uint64(aluB + aluA)

        if self.icode in (I_RRMOVQ, I_JMP):
            self.Cnd = bool(self.check_cond(self.ifun))

    def memory_stage(self):
        """读写八字节数据，越界由内存访问方法设置 ADR。"""
        self.valM = 0

        if self.icode in (I_RMMOVQ, I_PUSHQ):
            # valA 保留译码时的旧值，因此 pushq %rsp 压入旧栈指针。
            self.write_mem(self.valE, 8, self.valA)
        elif self.icode == I_CALL:
            self.write_mem(self.valE, 8, self.valP)
        elif self.icode == I_MRMOVQ:
            self.valM = self.read_mem(self.valE, 8)
        elif self.icode in (I_POPQ, I_RET):
            self.valM = self.read_mem(self.valA, 8)

    def write_back(self):
        """按 valE、valM 的顺序写回，保证 popq %rsp 的覆盖顺序。"""
        dstE = RNONE
        dstM = RNONE

        if self.icode in (I_IRMOVQ, I_ALU):
            dstE = self.rB
        elif self.icode == I_RRMOVQ and self.Cnd:
            dstE = self.rB
        elif self.icode in (I_CALL, I_RET, I_PUSHQ, I_POPQ):
            dstE = RSP
        if self.icode in (I_MRMOVQ, I_POPQ):
            dstM = self.rA

        if dstE != RNONE:
            self.REG[dstE] = self.valE
        if dstM != RNONE:
            self.REG[dstM] = self.valM

    def update_pc(self):
        """在顺序地址、分支目标和返回地址之间选择下一条 PC。"""
        if self.icode == I_CALL or (self.icode == I_JMP and self.Cnd):
            self.PC = self.valC
        elif self.icode == I_RET:
            self.PC = self.valM
        else:
            self.PC = self.valP

    # ---------------- JSON 序列化输出 ----------------
    def dump_state(self):
        """将当前状态转存为字典"""
        mem_dump = {}
        for addr in range(0, self.mem_size, 8):
            val = struct.unpack('<q', self.memory[addr:addr+8])[0]
            if val != 0:
                mem_dump[str(addr)] = val

        state = {
            "CC": dict(self.CC),
            "MEM": mem_dump,
            "PC": self.PC,
            "REG": {self.REG_NAMES[k]: self.to_signed64(v) for k, v in sorted(self.REG.items()) if k != RNONE},
            "STAT": self.STAT
        }
        self.trace.append(state)

    # ---------------- 入口流转 ----------------
    def load_program(self, file_obj):
        """解析器 Parser"""
        for line in file_obj:
            idx = line.find('|')
            code_part = line[:idx].strip() if idx != -1 else line.strip()
            if not code_part: continue
            if ':' in code_part:
                addr_str, data_str = code_part.split(':', 1)
                addr_str, data_str = addr_str.strip(), data_str.strip()
                if addr_str and data_str:
                    addr = int(addr_str, 16)
                    data_bytes = bytes.fromhex(data_str)
                    for i, b in enumerate(data_bytes):
                        if addr + i < len(self.memory):
                            self.memory[addr + i] = b

    def run(self):
        """主循环：时钟步进"""
        while self.STAT == AOK:
            self.fetch()
            if self.STAT != AOK:
                self.dump_state()
                break

            self.decode()
            self.execute()
            self.memory_stage()

            self.write_back()

            if self.STAT != AOK:
                self.dump_state()
                break

            self.update_pc()
            self.dump_state()

        print(json.dumps(self.trace, indent=4))

if __name__ == "__main__":
    sim = Y86Simulator()
    sim.load_program(sys.stdin)
    sim.run()
