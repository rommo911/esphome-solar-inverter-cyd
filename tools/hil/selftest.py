"""Self-test of the fake inverter (hil.py) without a board: a virtual serial pair, the PI30
frames the board sends, and checks on the replies (CRC, field count and order as pipsolar parses
them, commands taking effect).

  python3 -I tools/hil/selftest.py
"""
import os
import pty
import select
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hil  # noqa: E402

threading.excepthook = lambda a: (traceback.print_exception(a.exc_type, a.exc_value, a.exc_traceback), os._exit(3))

master, slave = pty.openpty()
sc = dict(hil.SCENARIOS["boot_low"])
inv = hil.Inverter(sc)
inv.step(0, 1, 21 * 60)
stop = threading.Event()
session = hil.Session(inv)
session.t0 = time.monotonic() - 1
threading.Thread(target=hil.serve, args=(os.ttyname(slave), session, stop, lambda x: None), daemon=True).start()
time.sleep(0.3)


def ask(cmd, noise=b""):
    os.write(master, noise + hil.frame(cmd))
    buf, t = b"", time.time()
    while b"\r" not in buf:
        if time.time() - t > 5:
            sys.exit(f"FAIL: no reply to {cmd}")
        if select.select([master], [], [], 0.2)[0]:
            buf += os.read(master, 256)
    body, crc = buf[:buf.index(b"\r") - 2], buf[buf.index(b"\r") - 2:buf.index(b"\r")]
    assert hil.crc_pi30(body) == crc, ("CRC", cmd, buf)
    return body.decode()


for cmd, nfields in (("QPIGS", 21), ("QPIRI", 25), ("QMOD", 1), ("QPIWS", 1), ("QFLAG", 1), ("QT", 1), ("QMN", 1)):
    r = ask(cmd, b"\x00\xffboot noise " if cmd == "QPIGS" else b"")
    f = r[1:].split(" ")
    assert r.startswith("(") and len(f) == nfields, (cmd, len(f), r)
    assert len(r) + 3 < 128, (cmd, "longer than pipsolar's 128-byte buffer")
    print(f"{cmd:6} {len(r) + 3:3d} B  {len(f):2d} fields  CRC ok  {r[:60]}")
g = ask("QPIGS")[1:].split(" ")
assert float(g[0]) == 230.0 and int(g[10]) == 12 and len(g[16]) == 8 and len(g[20]) == 3, g   # grid, SOC, flags
q = ask("QPIRI")[1:].split(" ")
assert (q[13], q[16], q[17]) == ("10", "2", "3"), q        # AC current, output (SBU), charger (solar only)
for cmd, check in (("POP01", lambda: inv.out_prio == 1), ("PCP02", lambda: inv.chg_src == 2),
                   ("MUCHGC020", lambda: inv.ac_amps == 20), ("PBFT27.2", lambda: inv.float_v == 27.2)):
    assert ask(cmd) == "(ACK" and check(), cmd
assert ask("QPIRI")[1:].split(" ")[16:18] == ["1", "2"]    # read back what was written
assert ask("QMOD") == "(L"                                 # SUB + grid = line mode
assert ask("QXYZ") == "(NAK"                                 # unknown query
print("commands POP / PCP / MUCHGC / PBFT -> ACK and read back in QPIRI; unknown -> NAK")
stop.set()
print("SELFTEST OK")
