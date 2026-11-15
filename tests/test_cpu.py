"""Y86-64 指令语义、边界值与异常处理测试。"""

import contextlib
import io
import itertools
import json
import random
import struct
import unittest

from cpu import ADR, AOK, HLT, INS, RNONE, RSP, Y86Simulator


MASK = (1 << 64) - 1
MIN_INT = -(1 << 63)
MAX_INT = (1 << 63) - 1


def word(value):
    return struct.pack("<Q", value & MASK)


def signed(value):
    value &= MASK
    return value - (1 << 64) if value >= (1 << 63) else value


def instruction(opcode, registers=None, immediate=None):
    result = bytes([opcode])
    if registers is not None:
        result += bytes([registers])
    if immediate is not None:
        result += word(immediate)
    return result


class SimulatorTests(unittest.TestCase):
    def run_program(self, code, registers=None, cc=None, memory=None):
        sim = Y86Simulator(mem_size=256)
        sim.memory[:len(code)] = code
        if registers:
            sim.REG.update({key: value & MASK for key, value in registers.items()})
        if cc:
            sim.CC.update(cc)
        if memory:
            for address, value in memory.items():
                sim.memory[address:address + 8] = word(value)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sim.run()
        self.assertEqual(json.loads(output.getvalue()), sim.trace)
        self.assertEqual(sim.REG[RNONE], 0)
        return sim

    def test_initial_state_and_halt(self):
        sim = self.run_program(b"\x00")
        self.assertEqual(sim.STAT, HLT)
        self.assertEqual(sim.PC, 0)
        self.assertEqual(sim.CC, {"ZF": 1, "SF": 0, "OF": 0})
        self.assertEqual(len(sim.trace), 1)
        self.assertEqual(set(sim.trace[0]), {"CC", "MEM", "PC", "REG", "STAT"})
        self.assertEqual(len(sim.trace[0]["REG"]), 15)

    def test_nop_preserves_registers_and_condition_codes(self):
        regs = {r: r + 20 for r in range(15)}
        cc = {"ZF": 0, "SF": 1, "OF": 1}
        sim = self.run_program(b"\x10\x00", regs, cc)
        self.assertEqual(sim.PC, 1)
        self.assertEqual({r: sim.REG[r] for r in range(15)}, regs)
        self.assertEqual(sim.CC, cc)

    def test_immediates_to_every_register(self):
        for register, value in itertools.product(range(15), [0, -1, MIN_INT, MAX_INT]):
            with self.subTest(register=register, value=value):
                sim = self.run_program(instruction(0x30, 0xF0 | register, value))
                self.assertEqual(signed(sim.REG[register]), value)
                self.assertEqual(sim.PC, 10)
                self.assertEqual(sim.STAT, HLT)
                self.assertEqual(sim.CC, {"ZF": 1, "SF": 0, "OF": 0})

    def test_register_move_all_source_destination_pairs(self):
        for source, destination in itertools.product(range(15), repeat=2):
            with self.subTest(source=source, destination=destination):
                regs = {r: MASK - r for r in range(15)}
                expected = dict(regs)
                expected[destination] = regs[source]
                sim = self.run_program(instruction(0x20, source * 16 + destination), regs)
                self.assertEqual({r: sim.REG[r] for r in range(15)}, expected)

    def test_condition_table_for_moves_and_jumps(self):
        # 行对应 ZF/SF/OF，列对应 always/le/l/e/ne/ge/g。
        truth_table = {
            (0, 0, 0): (1, 0, 0, 0, 1, 1, 1),
            (0, 0, 1): (1, 1, 1, 0, 1, 0, 0),
            (0, 1, 0): (1, 1, 1, 0, 1, 0, 0),
            (0, 1, 1): (1, 0, 0, 0, 1, 1, 1),
            (1, 0, 0): (1, 1, 0, 1, 0, 1, 0),
            (1, 0, 1): (1, 1, 1, 1, 0, 0, 0),
            (1, 1, 0): (1, 1, 1, 1, 0, 0, 0),
            (1, 1, 1): (1, 1, 0, 1, 0, 1, 0),
        }
        for flags, outcomes in truth_table.items():
            cc = dict(zip(("ZF", "SF", "OF"), flags))
            for function, taken in enumerate(outcomes):
                with self.subTest(flags=flags, function=function):
                    move = self.run_program(instruction(0x20 + function, 0x01), {0: 42, 1: 17}, cc)
                    jump = self.run_program(instruction(0x70 + function, immediate=32), cc=cc)
                    self.assertEqual(move.REG[1], 42 if taken else 17)
                    self.assertEqual(jump.PC, 32 if taken else 9)
                    self.assertEqual(move.CC, cc)
                    self.assertEqual(jump.CC, cc)

    def test_arithmetic_boundaries(self):
        cases = [
            # ifun, src, dst, result, (ZF, SF, OF)
            (0, 1, MAX_INT, MIN_INT, (0, 1, 1)),
            (0, -1, MIN_INT, MAX_INT, (0, 0, 1)),
            (0, 1, -1, 0, (1, 0, 0)),
            (0, MIN_INT, MIN_INT, 0, (1, 0, 1)),
            (0, -2, 1, -1, (0, 1, 0)),
            (1, 1, MIN_INT, MAX_INT, (0, 0, 1)),
            (1, -1, MAX_INT, MIN_INT, (0, 1, 1)),
            (1, MIN_INT, 0, MIN_INT, (0, 1, 1)),
            (1, MIN_INT, MIN_INT, 0, (1, 0, 0)),
            (1, 7, 3, -4, (0, 1, 0)),
            (2, -1, MIN_INT, MIN_INT, (0, 1, 0)),
            (2, 0x55, 0xAA, 0, (1, 0, 0)),
            (3, -1, MAX_INT, MIN_INT, (0, 1, 0)),
            (3, -1, -1, 0, (1, 0, 0)),
        ]
        for function, source, destination, result, flags in cases:
            with self.subTest(function=function, source=source, destination=destination):
                sim = self.run_program(
                    instruction(0x60 + function, 0x01),
                    {0: source, 1: destination},
                    {"ZF": 1, "SF": 1, "OF": 1},
                )
                self.assertEqual(signed(sim.REG[1]), result)
                self.assertEqual(sim.REG[0], source & MASK)
                self.assertEqual(tuple(sim.CC[key] for key in ("ZF", "SF", "OF")), flags)

    def test_arithmetic_against_integer_reference(self):
        rng = random.Random(86)
        for function in range(4):
            for _ in range(64):
                source, destination = (signed(rng.getrandbits(64)) for _ in range(2))
                if function == 0:
                    mathematical = destination + source
                elif function == 1:
                    mathematical = destination - source
                elif function == 2:
                    mathematical = destination & source
                else:
                    mathematical = destination ^ source
                result = signed(mathematical)
                overflow = int(function < 2 and not MIN_INT <= mathematical <= MAX_INT)
                with self.subTest(function=function, source=source, destination=destination):
                    sim = self.run_program(instruction(0x60 + function, 0x01), {0: source, 1: destination})
                    self.assertEqual(signed(sim.REG[1]), result)
                    self.assertEqual(sim.CC, {"ZF": int(result == 0), "SF": int(result < 0), "OF": overflow})

    def test_memory_round_trip_negative_displacement_and_unaligned_address(self):
        code = instruction(0x40, 0x03, -5) + instruction(0x50, 0x23, -5)
        cc = {"ZF": 0, "SF": 1, "OF": 1}
        sim = self.run_program(code, {0: 0xFEDCBA9876543210, 3: 136}, cc)
        self.assertEqual(sim.REG[2], 0xFEDCBA9876543210)
        self.assertEqual(sim.memory[131:139], bytes.fromhex("1032547698badcfe"))
        self.assertEqual(sim.CC, cc)
        self.assertEqual(sim.PC, 20)

    def test_memory_address_addition_wraps_at_64_bits(self):
        code = instruction(0x50, 0x01, 129)
        sim = self.run_program(code, {1: MASK}, memory={128: -123})
        self.assertEqual(signed(sim.REG[0]), -123)
        self.assertEqual(sim.STAT, HLT)

    def test_memory_operand_without_base_register(self):
        code = instruction(0x40, 0x0F, 128) + instruction(0x50, 0x2F, 128)
        sim = self.run_program(code, {0: -123})
        self.assertEqual(sim.STAT, HLT)
        self.assertEqual(signed(sim.REG[2]), -123)
        self.assertEqual(sim.memory[128:136], word(-123))

    def test_push_rsp_uses_old_stack_pointer(self):
        sim = self.run_program(instruction(0xA0, 0x4F), {RSP: 192})
        self.assertEqual(sim.REG[RSP], 184)
        self.assertEqual(struct.unpack("<Q", sim.memory[184:192])[0], 192)

    def test_pop_rsp_memory_value_has_writeback_priority(self):
        sim = self.run_program(instruction(0xB0, 0x4F), {RSP: 184}, memory={184: 0xABCD})
        self.assertEqual(sim.REG[RSP], 0xABCD)
        self.assertEqual(struct.unpack("<Q", sim.memory[184:192])[0], 0xABCD)

    def test_push_pop_round_trip_for_each_register(self):
        for register in range(15):
            if register == RSP:
                continue
            with self.subTest(register=register):
                code = instruction(0xA0, register * 16 + 15) + instruction(0xB0, register * 16 + 15)
                sim = self.run_program(code, {register: MIN_INT + register, RSP: 192})
                self.assertEqual(signed(sim.REG[register]), MIN_INT + register)
                self.assertEqual(sim.REG[RSP], 192)
                self.assertEqual(sim.PC, 4)

    def test_call_and_ret_save_fallthrough_address(self):
        code = bytearray(33)
        code[:9] = instruction(0x80, immediate=32)
        code[32] = 0x90
        sim = self.run_program(code, {RSP: 192})
        self.assertEqual([state["PC"] for state in sim.trace], [32, 9, 9])
        self.assertEqual(sim.REG[RSP], 192)
        self.assertEqual(struct.unpack("<Q", sim.memory[184:192])[0], 9)

    def test_invalid_instruction_codes_stop_before_writeback(self):
        for opcode in (0xC0, 0xD0, 0xE0, 0xFF):
            with self.subTest(opcode=opcode):
                sim = self.run_program(bytes([opcode]), {0: 123})
                self.assertEqual(sim.STAT, INS)
                self.assertEqual(sim.PC, 0)
                self.assertEqual(sim.REG[0], 123)
                self.assertEqual(len(sim.trace), 1)

    def test_invalid_function_codes(self):
        for opcode in (0x01, 0x11, 0x27, 0x31, 0x41, 0x51, 0x64, 0x77, 0x81, 0x91, 0xA1, 0xB1):
            with self.subTest(opcode=opcode):
                sim = self.run_program(bytes([opcode, 0x01]) + word(0))
                self.assertEqual(sim.STAT, INS)
                self.assertEqual(sim.PC, 0)
                self.assertEqual(len(sim.trace), 1)

    def test_invalid_register_encodings(self):
        cases = [
            (0x20, 0xF0), (0x20, 0x0F),
            (0x30, 0x00), (0x30, 0xFF),
            (0x40, 0xF0), (0x50, 0xF0),
            (0x60, 0xF0), (0x60, 0x0F),
            (0xA0, 0x00), (0xA0, 0xFF),
            (0xB0, 0x00), (0xB0, 0xFF),
        ]
        for opcode, registers in cases:
            with self.subTest(opcode=opcode, registers=registers):
                sim = self.run_program(instruction(opcode, registers) + word(0))
                self.assertEqual(sim.STAT, INS)
                self.assertEqual(sim.PC, 0)

    def test_instruction_fetch_outside_memory(self):
        for pc in (-1, 256, MASK):
            with self.subTest(pc=pc):
                sim = Y86Simulator(mem_size=256)
                sim.PC = pc
                with contextlib.redirect_stdout(io.StringIO()):
                    sim.run()
                self.assertEqual(sim.STAT, ADR)
                self.assertEqual(sim.PC, pc)
                self.assertEqual(len(sim.trace), 1)

    def test_truncated_instructions_at_memory_boundary(self):
        encodings = [
            instruction(0x20, 0x01),
            instruction(0x30, 0xF0, 123),
            instruction(0x40, 0x01, 123),
            instruction(0x50, 0x01, 123),
            instruction(0x60, 0x01),
            instruction(0x70, immediate=123),
            instruction(0x80, immediate=123),
            instruction(0xA0, 0x0F),
            instruction(0xB0, 0x0F),
        ]
        for encoding in encodings:
            for available in range(1, len(encoding)):
                with self.subTest(encoding=encoding.hex(), available=available):
                    sim = Y86Simulator(mem_size=256)
                    sim.PC = 256 - available
                    sim.memory[sim.PC:] = encoding[:available]
                    with contextlib.redirect_stdout(io.StringIO()):
                        sim.run()
                    self.assertEqual(sim.STAT, ADR)
                    self.assertEqual(sim.PC, 256 - available)
                    self.assertEqual(list(sim.REG.values()), [0] * 16)

    def test_push_address_error_still_decrements_rsp(self):
        code = instruction(0xA0, 0x0F) + instruction(0x60, 0x00)
        sim = self.run_program(code, {0: 7, RSP: 0})
        self.assertEqual(sim.STAT, ADR)
        self.assertEqual(sim.PC, 0)
        self.assertEqual(sim.REG[RSP], MASK - 7)
        self.assertEqual(sim.REG[0], 7)
        self.assertEqual(sim.memory[:len(code)], code)
        self.assertFalse(any(sim.memory[len(code):]))
        self.assertEqual(sim.CC, {"ZF": 1, "SF": 0, "OF": 0})
        self.assertEqual(len(sim.trace), 1)

    def test_pop_address_error_writes_zero_and_increments_rsp(self):
        sim = self.run_program(instruction(0xB0, 0x0F), {0: 99, RSP: 252})
        self.assertEqual(sim.STAT, ADR)
        self.assertEqual(sim.REG[RSP], 260)
        self.assertEqual(sim.REG[0], 0)
        self.assertEqual(sim.PC, 0)

    def test_pop_rsp_address_error_preserves_writeback_priority(self):
        sim = self.run_program(instruction(0xB0, 0x4F), {RSP: 252})
        self.assertEqual(sim.STAT, ADR)
        self.assertEqual(sim.REG[RSP], 0)
        self.assertEqual(sim.PC, 0)

    def test_call_and_ret_address_errors_keep_faulting_pc(self):
        call = self.run_program(instruction(0x80, immediate=32), {RSP: 0})
        ret = self.run_program(instruction(0x90), {RSP: 252})
        self.assertEqual((call.STAT, call.PC, call.REG[RSP]), (ADR, 0, MASK - 7))
        self.assertEqual((ret.STAT, ret.PC, ret.REG[RSP]), (ADR, 0, 260))

    def test_jump_to_invalid_address_faults_on_next_fetch(self):
        sim = self.run_program(instruction(0x70, immediate=256))
        self.assertEqual([(s["PC"], s["STAT"]) for s in sim.trace], [(256, AOK), (256, ADR)])

    def test_invalid_load_writes_zero_without_advancing_pc(self):
        sim = self.run_program(instruction(0x50, 0x01, 1), {0: 99, 1: 248})
        self.assertEqual(sim.STAT, ADR)
        self.assertEqual(sim.REG[0], 0)
        self.assertEqual(sim.REG[1], 248)
        self.assertEqual(sim.PC, 0)

    def test_invalid_store_does_not_partially_modify_memory(self):
        code = instruction(0x40, 0x01, 1)
        sim = self.run_program(code, {0: -1, 1: 248}, memory={248: 0x11223344})
        self.assertEqual(sim.STAT, ADR)
        self.assertEqual(sim.memory[248:], word(0x11223344))
        self.assertEqual(sim.PC, 0)

    def test_last_valid_eight_byte_memory_access(self):
        code = instruction(0x40, 0x01, 0) + instruction(0x50, 0x21, 0)
        sim = self.run_program(code, {0: -1, 1: 248})
        self.assertEqual(sim.STAT, HLT)
        self.assertEqual(sim.REG[2], MASK)
        self.assertEqual(sim.memory[248:], b"\xff" * 8)
        self.assertEqual(sim.trace[-1]["MEM"]["248"], -1)

    def test_snapshots_do_not_change_after_later_instructions(self):
        code = instruction(0x30, 0xF0, 3) + instruction(0x63, 0x00)
        sim = self.run_program(code)
        self.assertEqual(sim.trace[0]["REG"]["rax"], 3)
        self.assertEqual(sim.trace[1]["REG"]["rax"], 0)
        sim.REG[0] = 123
        sim.CC["ZF"] = 0
        self.assertEqual(sim.trace[-1]["REG"]["rax"], 0)
        self.assertEqual(sim.trace[-1]["CC"]["ZF"], 1)

    def test_yo_loader_keeps_addresses_and_ignores_comments(self):
        source = io.StringIO(
            "                            | .pos 0\n"
            "0x000: 30f0ffffffffffffffff | irmovq $-1, %rax\n"
            "0x00a: 00                   | halt\n"
            "0x080: 0807060504030201     | .quad 0x0102030405060708\n"
        )
        sim = Y86Simulator(mem_size=256)
        sim.load_program(source)
        with contextlib.redirect_stdout(io.StringIO()):
            sim.run()
        self.assertEqual(sim.trace[-1]["REG"]["rax"], -1)
        self.assertEqual(sim.trace[-1]["MEM"]["128"], 0x0102030405060708)
        self.assertEqual(sim.STAT, HLT)


if __name__ == "__main__":
    unittest.main()
