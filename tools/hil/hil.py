"""Hardware in the loop: this PC plays the Axpert inverter for the CYD running the HIL build
(inverter-cyd-hil.yaml), over the board's USB serial port (PI30, 2400 baud).

  - answers QPIGS / QPIRI / QMOD / QPIWS / QFLAG / QT / QMN from a small world model (house load,
    PV by the time of day, battery, grid), the same model as the PC simulator (tools/sim)
  - accepts POP / PCP / MUCHGC / PBFT / PBCV / PBDV / PSDV with (ACK), or (NAK) when a scenario
    says the inverter refuses
  - sets the board's clock and forecast through the web API, reads its log (web page events)
  - checks what the controller did against the scenario's expectations

The board runs everything (screen, touch, sounds, web page): you can watch and touch it while a
scenario runs. Battery energy can run faster than real time (speed), the clock cannot.

  python3 tools/hil/hil.py --host 192.168.x.y list
  python3 tools/hil/hil.py --host 192.168.x.y run boot_low[,high_load,...] [--port /dev/ttyUSB0]
  python3 tools/hil/hil.py --host 192.168.x.y all
  python3 tools/hil/hil.py --host 192.168.x.y idle          # just be the inverter (manual testing)

Password: --password, or $HIL_PASSWORD (web_password in config/secrets.yaml).
"""
import argparse
import json
import math
import re
import os
import random
import sys
import threading
import time
import urllib.parse
import urllib.request

import serial

# ---------------------------------------------------------------- PI30 framing
def crc_pi30(data: bytes) -> bytes:
    crc = 0
    for b in data:   # CRC-16/XMODEM
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    hi, lo = crc >> 8, crc & 0xFF
    if hi in (0x28, 0x0D, 0x0A):   # never ( CR LF inside the frame
        hi += 1
    if lo in (0x28, 0x0D, 0x0A):
        lo += 1
    return bytes([hi, lo])


def frame(payload: str) -> bytes:
    b = payload.encode()
    return b + crc_pi30(b) + b"\r"


# ---------------------------------------------------------------- world (as tools/sim/sim.cpp)
SUNRISE, SUNSET = 410, 1060           # minutes, early November at 36 N, UTC+3
CAP_WH, CUTOFF = 4500.0, 3.0
TZ_OFFSET = 3 * 3600                  # Asia/Damascus, UTC+3 all year


def between(m, a, b):
    m %= 1440
    return a <= m < b


def house_load(m, rng):
    w = 150
    if m % 35 < 15:
        w += 110                       # fridge
    if between(m, 17.5 * 60, 23 * 60):
        w += 180                       # lights + TV
    if between(m, 6.5 * 60, 8 * 60):
        w += 250
    return w + rng.uniform(-15, 15)


def pv_power(m, peak, cloud, rng):
    d = m % 1440
    if d <= SUNRISE or d >= SUNSET:
        return 0.0
    p = peak * math.sin(math.pi * (d - SUNRISE) / (SUNSET - SUNRISE)) ** 1.3
    c = cloud * (0.6 + 0.4 * (0.5 + 0.5 * math.sin(m / 23) * math.sin(m / 7))) + (0.1 * rng.random() if cloud else 0)
    return max(0.0, p * (1 - min(0.95, c)))


class Inverter:
    """The Axpert as the board sees it, plus the battery and the house behind it."""

    def __init__(self, sc):
        self.sc = sc
        self.rng = random.Random(42)
        self.energy = CAP_WH * sc["soc0"] / 100
        self.out_prio = 2                # SBU
        self.chg_src = 3                 # solar only
        self.ac_amps = 10
        self.float_v, self.recharge_v, self.redischarge_v, self.under_v = 27.0, 23.0, 27.0, 21.0
        self.load = self.pv = 0.0
        self.grid = True
        self.unmet_wh = self.grid_wh = 0.0
        self.writes = []                 # (t, command, accepted)
        self.lock = threading.Lock()

    def soc(self):
        return 100 * self.energy / CAP_WH

    def step(self, t, dt, clock_min):
        """t: seconds since start, dt: seconds of real time."""
        sc = self.sc
        k = sc.get("speed", 1.0)         # battery runs k x faster than real time
        with self.lock:
            self.grid = sc["grid"](t)
            self.load = house_load(clock_min, self.rng) + sc["extra"](t, clock_min)
            self.pv = pv_power(clock_min, 2000, sc["cloud"], self.rng)
            sub = self.out_prio == 1
            surplus, from_grid = self.pv - self.load, 0.0
            if surplus >= 0:
                self.energy += min(surplus, 1500) * 0.95 * dt * k / 3600
            else:
                need = -surplus
                if sub and self.grid:
                    from_grid = need
                elif self.soc() > CUTOFF:
                    self.energy -= need / 0.92 * dt * k / 3600
                elif self.grid:
                    from_grid = need
                else:
                    self.unmet_wh += need * dt / 3600
            if self.grid and sub and self.chg_src == 2:     # "Solar and utility": AC charging
                p = self.ac_amps * 27.0
                self.energy += p * 0.9 * dt * k / 3600
                from_grid += p
            self.energy = min(max(self.energy, 0.0), CAP_WH)
            self.grid_wh += from_grid * dt / 3600

    # ---- PI30 replies
    def qpigs(self, t):
        soc = self.sc.get("soc_reading", lambda s, t: s)(self.soc(), t)
        v = 23.0 + 4.0 * soc / 100                     # 24 V battery
        chg_w = max(0.0, self.pv - self.load) + (self.ac_amps * 27 if self.grid and self.out_prio == 1
                                                 and self.chg_src == 2 else 0)
        dis_w = max(0.0, self.load - self.pv) if not (self.grid and self.out_prio == 1) else 0.0
        gv = 230.0 if self.grid else 0.0
        status1 = "00010" + ("1" if chg_w > 0 else "0") + ("1" if self.pv > 0 else "0") + (
            "1" if self.grid and self.out_prio == 1 and self.chg_src == 2 else "0")
        floating = "1" if soc >= 99.5 else "0"
        return (f"({gv:05.1f} {50.0 if self.grid else 0:04.1f} 230.0 50.0 {self.load:04.0f} {self.load:04.0f} "
                f"{min(999, self.load / 40):03.0f} 380 {v:05.2f} {chg_w / v:03.0f} {soc:03.0f} 0035 "
                f"{self.pv / 100:04.1f} {100 if self.pv else 0:05.1f} {v:05.2f} {dis_w / v:05.0f} {status1} 00 00 "
                f"{self.pv:05.0f} {floating}10")

    def qpiri(self):
        return (f"(230.0 21.7 230.0 50.0 21.7 4000 4000 24.0 {self.recharge_v:04.1f} {self.under_v:04.1f} 28.2 "
                f"{self.float_v:04.1f} 2 {self.ac_amps:02d} 060 0 {self.out_prio} {self.chg_src} 1 01 0 0 "
                f"{self.redischarge_v:04.1f} 0 1")

    def qmod(self):
        return "(L" if self.grid and self.out_prio == 1 else "(B"

    def command(self, t, cmd):
        """A setting command from the board: (ACK) or (NAK)."""
        ok = not self.sc.get("nak", lambda t, c: False)(t, cmd)
        if ok:
            with self.lock:
                try:
                    if cmd.startswith("POP"):
                        self.out_prio = int(cmd[3:])
                    elif cmd.startswith("PCP"):
                        self.chg_src = int(cmd[3:])
                    elif cmd.startswith("MUCHGC"):
                        self.ac_amps = int(cmd[6:])
                    elif cmd.startswith("PBFT"):
                        self.float_v = float(cmd[4:])
                    elif cmd.startswith("PBCV"):
                        self.recharge_v = float(cmd[4:])
                    elif cmd.startswith("PBDV"):
                        self.redischarge_v = float(cmd[4:])
                    elif cmd.startswith("PSDV"):
                        self.under_v = float(cmd[4:])
                    else:
                        ok = False
                except ValueError:
                    ok = False
        self.writes.append((t, cmd, ok))
        return "(ACK" if ok else "(NAK"


# ---------------------------------------------------------------- the board's web API
class Board:
    def __init__(self, host, password):
        self.base = f"http://{host}"
        pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        pm.add_password(None, self.base, "admin", password)
        self.opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))
        self.logs = []                   # (t, text)
        self.states = {}                 # entity id -> last state event
        self.t0 = time.monotonic()

    def _post(self, path):
        req = urllib.request.Request(self.base + path, data=b"", method="POST")
        with self.opener.open(req, timeout=10) as r:
            return r.status

    def get(self, domain, name):
        with self.opener.open(self.base + self.entity(domain, name), timeout=10) as r:
            return json.loads(r.read()).get("value")

    def wait_up(self, seconds):
        t = time.monotonic()
        while time.monotonic() - t < seconds:
            try:
                self.get("binary_sensor", "Inverter Link")
                return True
            except Exception:  # noqa: BLE001 - still booting / joining WiFi
                time.sleep(3)
        return False

    def entity(self, domain, name):
        return f"/{domain}/{urllib.parse.quote(name)}"

    def set_text(self, name, value):
        return self._post(self.entity("text", name) + "/set?value=" + urllib.parse.quote(str(value)))

    def set_number(self, name, value):
        return self._post(self.entity("number", name) + f"/set?value={value}")

    def switch(self, name, on):
        return self._post(self.entity("switch", name) + ("/turn_on" if on else "/turn_off"))

    def listen(self, stop):
        """Event stream of the web page: log lines and state changes (runs in a thread)."""
        while not stop.is_set():
            try:
                with self.opener.open(self.base + "/events", timeout=30) as r:
                    ev = None
                    for raw in r:
                        if stop.is_set():
                            return
                        line = raw.decode(errors="replace").rstrip("\r\n")
                        if line.startswith("event:"):
                            ev = line[6:].strip()
                        elif line.startswith("data:") and ev:
                            data = line[5:].strip()
                            t = time.monotonic() - self.t0
                            if ev == "log":
                                self.logs.append((t, data))
                            elif ev == "state":
                                try:
                                    d = json.loads(data)
                                    self.states[d.get("id", d.get("name", "?"))] = d
                                except ValueError:
                                    pass
            except Exception as e:  # noqa: BLE001 - reconnect on anything
                if not stop.is_set():
                    self.logs.append((time.monotonic() - self.t0, f"[hil] event stream: {e}"))
                    time.sleep(3)


# ---------------------------------------------------------------- scenarios (real time!)
CMD = re.compile(r"(QPIGS|QPIRI|QMOD|QPIWS|QFLAG|QMN|QT|POP\d+|PCP\d+|MUCHGC\d+|PBFT[\d.]+|PBCV[\d.]+"
                 r"|PBDV[\d.]+|PSDV[\d.]+|[QPM][A-Z]+[\d.]*)$")
WARMUP = 120                          # s of calm world before each scenario
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def at(h, m=0):
    return h * 60 + m


NONE = lambda t, m: 0.0   # noqa: E731
ALWAYS = lambda t: True   # noqa: E731

SCENARIOS = {
    "boot_low": dict(
        desc="night 21:00, SOC 12 %, grid on: LOW -> grid (SUB), emergency grid-charge at fast current",
        start=at(21), minutes=6, soc0=12, cloud=0.2, fc=(9, 9), grid=ALWAYS, extra=NONE,
        expect=[("write", "POP01", 0, 240), ("write", "PCP02", 0, 300), ("write", "MUCHGC020", 0, 330),
                ("log", "tune to_grid_low", 0, 240)]),
    "emergency_charge": dict(
        desc="SOC 14 % at 21:00, grid on, battery x40 speed: charge to 25 % then back to solar only",
        start=at(21), minutes=12, soc0=14, cloud=0.2, fc=(9, 9), grid=ALWAYS, extra=NONE, speed=40,
        expect=[("write", "PCP02", 0, 300), ("write", "PCP03", 120, 720), ("write", "MUCHGC010", 120, 720)]),
    "high_load": dict(
        desc="14:00 overcast, SOC 45 %: 2.8 kW for 2 min -> grid within ~15 s, back 45 s after (min 3 min)",
        start=at(14), minutes=8, soc0=45, cloud=0.8, fc=(3, 3), grid=ALWAYS,
        extra=lambda t, m: 2800.0 if 60 <= t < 180 else 0.0,
        expect=[("write", "POP01", 60, 90), ("write", "POP02", 240, 300), ("nowrite", "POP02", 0, 239)]),
    "grid_outage": dict(
        desc="20:00, SOC 25 %: grid lost for 4 min -> alarm (SOC < 30 %), grid back sound after",
        start=at(20), minutes=8, soc0=25, cloud=0.2, fc=(9, 9), grid=lambda t: not (90 <= t < 330),
        extra=NONE,
        expect=[("log", "tune alarm_no_grid", 100, 200), ("log", "tune grid_back", 330, 420)]),
    "write_refused": dict(
        desc="night, SOC 15 %: the inverter refuses POP for 3 min -> retry, fault message, recovers",
        start=at(21), minutes=8, soc0=15, cloud=0.2, fc=(9, 9), grid=ALWAYS, extra=NONE,
        nak=lambda t, c: c.startswith("POP") and t < 180,
        expect=[("log", "did not accept the output priority", 60, 240), ("accepted", "POP01", 180, 480)]),
    "link_loss": dict(
        desc="night, SOC 22 %: the inverter stops answering for 3 min -> nothing written meanwhile",
        start=at(21), minutes=7, soc0=22, cloud=0.2, fc=(9, 9), grid=ALWAYS, extra=NONE,
        silent=lambda t: 60 <= t < 240,
        expect=[("nowrite", "", 60, 240)]),
    "soc_glitch": dict(
        desc="11:00, SOC 60 %: the SOC reading jumps to 0 % for 30 s -> no grid, no charging",
        start=at(11), minutes=5, soc0=60, cloud=0.3, fc=(9, 9), grid=ALWAYS, extra=NONE,
        soc_reading=lambda s, t: 0 if 60 <= t < 90 else s,
        expect=[("nowrite", "POP01", 0, 300), ("nowrite", "PCP02", 0, 300)]),
}


def local_epoch(start_min):
    """Epoch of today's local clock at start_min (UTC+3)."""
    now = time.time()
    midnight = now - ((now + TZ_OFFSET) % 86400)
    return int(midnight + start_min * 60)


# ---------------------------------------------------------------- serial loop
class Session:
    """What the serial loop answers with; run() swaps the scenario, the port stays open
    (opening the port resets the board through its auto-reset circuit)."""

    def __init__(self, inv):
        self.inv = inv
        self.silent = lambda t: False
        self.t0 = time.monotonic()

    def clock(self):
        return time.monotonic() - self.t0


def serve(port, session, stop, log):
    """Be the inverter on the serial port until stop is set. session.clock(): seconds into the
    scenario (negative during the warm-up)."""
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, 2400, 0.1
    ser.dtr = ser.rts = False            # do not reset the ESP32 (auto-reset circuit)
    ser.open()
    buf = b""
    try:
        while not stop.is_set():
            buf += ser.read(64)
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                if len(line) < 3:
                    continue
                m = CMD.search(line[:-2].decode("ascii", errors="replace"))   # drop CRC, skip boot noise
                if not m:
                    continue
                cmd = m.group(1)
                t = session.clock()
                inv = session.inv
                if session.silent(t):
                    continue
                if cmd == "QPIGS":
                    reply = inv.qpigs(t)
                elif cmd == "QPIRI":
                    reply = inv.qpiri()
                elif cmd == "QMOD":
                    reply = inv.qmod()
                elif cmd == "QPIWS":
                    reply = "(" + "0" * 32
                elif cmd == "QFLAG":
                    reply = "(EakxyzDbjuv"
                elif cmd == "QT":
                    reply = time.strftime("(%Y%m%d%H%M%S")
                elif cmd == "QMN":
                    reply = "(VMIII-4000"
                elif cmd[:1] in "PM":
                    reply = inv.command(t, cmd)
                    log(f"{t:6.0f}s  board wrote {cmd} -> {reply[1:]}")
                else:
                    reply = "(NAK"
                ser.write(frame(reply))
    finally:
        ser.close()


# ---------------------------------------------------------------- run + check
def run(board, session, name, log):
    sc = dict(SCENARIOS[name])
    inv = Inverter(sc)
    stop = threading.Event()
    print(f"\n== {name}: {sc['desc']}")
    epoch = local_epoch(sc["start"])
    board.logs.clear()
    board.set_text("HIL Clock", epoch - WARMUP)
    board.set_number("HIL Forecast Today", sc["fc"][0])
    board.set_number("HIL Forecast Tomorrow", sc["fc"][1])
    board.switch("Auto Control", True)
    board.switch("Observe Only", False)          # restored when the session ends
    # warm-up: a calm world (SOC 60 %, grid on, no refusals), so the board releases what the last
    # run latched; then the scenario's world from t = 0
    real = {k: sc[k] for k in ("grid", "extra", "nak", "soc_reading") if k in sc}
    sc.update(grid=ALWAYS, extra=NONE, nak=lambda t, c: False, soc_reading=lambda s, t: s)
    inv.energy = CAP_WH * 0.6
    session.t0 = board.t0 = time.monotonic() + WARMUP
    session.silent = lambda t: False
    session.inv = inv
    clock = session.clock
    threading.Thread(target=board.listen, args=(stop,), daemon=True).start()
    print(f"   warm-up {WARMUP} s (calm world)...", flush=True)
    while clock() < 0:
        inv.energy = CAP_WH * 0.6
        inv.step(clock(), 1.0, sc["start"] + clock() / 60)
        time.sleep(1.0)
    sc.update(real)
    session.silent = sc.get("silent", lambda t: False)
    inv.energy = CAP_WH * sc["soc0"] / 100
    print("   scenario starts", flush=True)
    end = sc["minutes"] * 60
    last_clock, last_print = 0, -30
    try:
        while (t := clock()) < end:
            inv.step(t, 1.0, sc["start"] + t / 60)
            if t - last_clock >= 300:            # keep the board's clock on the scenario's clock
                board.set_text("HIL Clock", epoch + int(t))
                last_clock = t
            if t - last_print >= 30:
                last_print = t
                print(f"{t:6.0f}s  SOC {inv.soc():5.1f} %  load {inv.load:5.0f} W  PV {inv.pv:5.0f} W  "
                      f"grid {'on ' if inv.grid else 'off'}  {'SUB' if inv.out_prio == 1 else 'SBU'}  "
                      f"charger {inv.chg_src} {inv.ac_amps} A", flush=True)
            time.sleep(1.0)
    finally:
        stop.set()
    tags = re.compile(r"\[(ctl|notify|buzzer|hil)[:\]]")
    for t, text in board.logs:
        if tags.search(text):
            print(f"{t:6.0f}s  log {ANSI.sub('', text)}")
    return check(sc, inv, board)


def check(sc, inv, board):
    fails = 0
    for kind, what, a, b in sc["expect"]:
        if kind == "write":
            hit = [t for t, c, ok in inv.writes if c == what and a <= t <= b]
        elif kind == "accepted":
            hit = [t for t, c, ok in inv.writes if c == what and ok and a <= t <= b]
        elif kind == "nowrite":
            bad = [t for t, c, ok in inv.writes if c.startswith(what) and a <= t <= b]
            hit = [] if bad else [0]
        else:   # log text
            hit = [t for t, text in board.logs if what in text and a <= t <= b]
        ok = bool(hit)
        fails += not ok
        when = f" at {hit[0]:.0f} s" if ok and kind != "nowrite" else ""
        print(f"   [{'PASS' if ok else 'FAIL'}] {kind} {what!r} within {a}-{b} s{when}")
    done = [f"{t:.0f}s {c}" + ("" if ok else " (NAK)") for t, c, ok in inv.writes if t >= 0]
    print("   writes:", ", ".join(done) or "none")
    return fails


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True, help="board IP (web page)")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--password", default=os.environ.get("HIL_PASSWORD", ""))
    ap.add_argument("what", choices=["list", "run", "all", "idle"])
    ap.add_argument("scenario", nargs="?")
    args = ap.parse_args()
    if args.what == "list":
        for k, v in SCENARIOS.items():
            print(f"{k:18} {v['minutes']:3d} min  {v['desc']}")
        return 0
    calm = dict(desc="idle", start=0, minutes=10 ** 6, soc0=60, cloud=0.3, fc=(9, 9), grid=ALWAYS, extra=NONE)
    session = Session(Inverter(calm))
    stop = threading.Event()
    threading.Thread(target=serve, args=(args.port, session, stop, print), daemon=True).start()
    if args.what == "idle":   # be a steady inverter for manual testing on the screen
        while True:
            t = session.clock()
            session.inv.step(t, 1.0, ((time.time() + TZ_OFFSET) % 86400) / 60)
            time.sleep(1)
    board = Board(args.host, args.password)
    print("port open (the board may restart); waiting for its web page...", flush=True)
    if not board.wait_up(180):
        print("the board's web page did not answer within 3 min")
        return 2
    saved = {n: board.get("switch", n) for n in ("Auto Control", "Observe Only")}
    names = list(SCENARIOS) if args.what == "all" else args.scenario.split(",")
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        print("unknown scenario:", ", ".join(unknown))
        return 2
    fails = 0
    try:
        for n in names:
            fails += run(board, session, n, print)
    finally:
        for n, v in saved.items():               # the switches as they were before the session
            board.switch(n, bool(v))
        print(f"restored: {saved}")
    print(f"\nTOTAL: {'all passed' if fails == 0 else f'{fails} failed'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
