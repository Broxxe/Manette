"""Mesures en direct : processeur, mémoire, carte graphique et applications."""

from __future__ import annotations

from .i18n import _ as tr

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from gi.repository import Gio

CLK_TCK = os.sysconf("SC_CLK_TCK")
NCPU = os.cpu_count() or 1
OWN_PID = os.getpid()


def _read(path: str | Path) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


# --- Processeur -----------------------------------------------------------

@cache
def cpu_model() -> str:
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            return re.sub(r"\s+\d+-Core Processor$", "", line.split(":", 1)[1].strip())
    return tr('Processeur')


@dataclass(frozen=True)
class CpuTopology:
    # Each group contains the Linux CPU IDs belonging to one exposed core.
    groups: tuple[tuple[int, ...], ...]
    known: bool

    @property
    def physical_count(self):
        return len(self.groups) if self.known else None


def _cpu_list(text):
    """Linux cpulist format: 0-3,8,10-11. Invalid metadata stays unknown."""
    result = set()
    try:
        for part in text.split(','):
            bounds = part.split('-')
            if not part or len(bounds) > 2:
                return set()
            first, last = int(bounds[0]), int(bounds[-1])
            if not 0 <= first <= last < 2**20:
                return set()
            result.update(range(first, last + 1))
    except ValueError:
        return set()
    return result


def cpu_topology(cpu_ids):
    """Use kernel topology, never CPU numbering or an assumed SMT factor."""
    ids = tuple(cpu_ids)
    online = set(ids)
    siblings, keys = {}, {}
    for ident in ids:
        root = Path(f'/sys/devices/system/cpu/cpu{ident}/topology')
        package, core, die = (_read(root / name) for name in ('physical_package_id', 'core_id', 'die_id'))
        if package.isdigit() and core.isdigit():
            keys[ident] = (int(package), int(die) if die.isdigit() else -1, int(core))
        members = _cpu_list(_read(root / 'core_cpus_list') or _read(root / 'thread_siblings_list'))
        if ident in members and (len(members) > 1 or ident in keys):
            siblings[ident] = tuple(sorted(members & online))
    if ids and all(ident in siblings and all(siblings.get(member) == siblings[ident]
                  for member in siblings[ident]) for ident in ids):
        return CpuTopology(tuple(sorted(set(siblings.values()), key=lambda group: group[0])), True)
    if len(keys) != len(ids):
        # Older kernels/architectures may expose topology only in /proc/cpuinfo.
        proc_keys = {}
        for block in _read('/proc/cpuinfo').split('\n\n'):
            fields = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
            fields = {key.strip(): value.strip() for key, value in fields.items()}
            ident, package, core = (fields.get(key, '') for key in ('processor', 'physical id', 'core id'))
            if ident.isdigit() and int(ident) in online and package.isdigit() and core.isdigit():
                proc_keys[int(ident)] = (int(package), -1, int(core))
        keys = proc_keys if len(proc_keys) == len(ids) else {}
    if ids and len(keys) == len(ids):
        groups = {}
        for ident in ids:
            groups.setdefault(keys[ident], []).append(ident)
        return CpuTopology(tuple(tuple(sorted(group)) for group in groups.values()), True)
    return CpuTopology(tuple((ident,) for ident in ids), False)


class CpuSampler:
    def __init__(self):
        self.prev = None
        self.cpu_ids = ()
        self.topology = CpuTopology((), False)

    def sample(self) -> tuple[float, list[float]]:
        """Charge totale puis par processeur logique, entre 0 et 1."""
        rows = {}
        for line in _read("/proc/stat").splitlines():
            if not line.startswith("cpu"):
                break
            fields = line.split()
            if fields[0] != 'cpu' and not fields[0][3:].isdigit():
                continue
            try:
                values = [int(v) for v in fields[1:9]]
            except ValueError:
                continue
            if len(values) < 4:
                continue
            rows[fields[0]] = (sum(values), values[3] + (values[4] if len(values) > 4 else 0))
        ids = tuple(sorted(int(key[3:]) for key in rows if key != 'cpu'))
        if ids != self.cpu_ids:
            self.cpu_ids = ids
            self.topology = cpu_topology(ids)
        prev, self.prev = self.prev, rows
        def usage(key):
            if prev is None or key not in prev or key not in rows:
                return 0.0
            total, idle = rows[key]
            p_total, p_idle = prev[key]
            return max(0.0, min(1.0, 1 - (idle - p_idle) / (total - p_total))) if total > p_total else 0.0
        return usage('cpu'), [usage(f'cpu{ident}') for ident in ids]


def cpu_frequency() -> float | None:
    """Fréquence moyenne des cœurs, en GHz."""
    values = [int(v) for p in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq")
              if (v := _read(p)).isdigit()]
    return sum(values) / len(values) / 1e6 if values else None


@cache
def _cpu_temp_file() -> Path | None:
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        if _read(hwmon / "name") not in ("k10temp", "zenpower", "coretemp"):
            continue
        for label in sorted(hwmon.glob("temp*_label")):
            if _read(label) in ("Tctl", "Tdie", "Package id 0"):
                return label.with_name(label.name.replace("_label", "_input"))
        if (hwmon / "temp1_input").exists():
            return hwmon / "temp1_input"
    return None


def cpu_temperature() -> float | None:
    path = _cpu_temp_file()
    value = _read(path) if path else ""
    return int(value) / 1000 if value.lstrip("-").isdigit() else None


# --- Mémoire --------------------------------------------------------------

@dataclass
class Memory:
    total: int
    available: int
    swap_total: int
    swap_used: int

    @property
    def used(self) -> int:
        return self.total - self.available


def memory() -> Memory:
    info = {}
    for line in _read("/proc/meminfo").splitlines():
        key, value = line.split(":", 1)
        info[key] = int(value.split()[0]) * 1024
    return Memory(info.get("MemTotal", 0), info.get("MemAvailable", 0), info.get("SwapTotal", 0),
                  info.get("SwapTotal", 0) - info.get("SwapFree", 0))


# --- Carte graphique ------------------------------------------------------

@dataclass
class Gpu:
    name: str
    usage: float | None = None  # 0 à 1
    mem_used: int | None = None
    mem_total: int | None = None
    temperature: float | None = None
    power: float | None = None
    power_limit: float | None = None
    fan: float | None = None
    clock: int | None = None


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:  # « [N/A] », « [Not Supported] »
        return None


def gpus() -> list[Gpu]:
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--format=csv,noheader,nounits", "--query-gpu=name,utilization.gpu,"
                                  "memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed,clocks.gr"],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        result = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 9:
                continue
            usage, used, total, temp, power, limit, fan, clock = map(_number, parts[1:])
            result.append(Gpu(parts[0], usage / 100 if usage is not None else None,
                              int(used * 2**20) if used is not None else None,
                              int(total * 2**20) if total is not None else None,
                              temp, power, limit, fan / 100 if fan is not None else None,
                              int(clock) if clock is not None else None))
        if result:
            return result
    return _amd_gpus()


def _amd_gpus() -> list[Gpu]:
    result = []
    for device in sorted(Path("/sys/class/drm").glob("card[0-9]/device")):
        busy = _read(device / "gpu_busy_percent")
        if not busy.isdigit():
            continue
        gpu = Gpu(tr('Carte graphique AMD'), int(busy) / 100)
        used, total = _read(device / "mem_info_vram_used"), _read(device / "mem_info_vram_total")
        if used.isdigit() and total.isdigit():
            gpu.mem_used, gpu.mem_total = int(used), int(total)
        for hwmon in (device / "hwmon").glob("hwmon*"):
            if (temp := _read(hwmon / "temp1_input")).isdigit():
                gpu.temperature = int(temp) / 1000
            if (power := _read(hwmon / "power1_average")).isdigit():
                gpu.power = int(power) / 1e6
        result.append(gpu)
    return result


# --- Applications ---------------------------------------------------------

SHELL, OTHERS, MANETTE = "gnome-shell", "autres", "manette"

# app-gnome-steam-6517.scope, app-flatpak-org.x.Y-123.scope, app-vesktop-9815.scope…
APP_SCOPE = re.compile(r"^app-(?:gnome-|flatpak-)?(.+?)-(\d+)\.scope$")
SNAP_SCOPE = re.compile(r"^snap\.([^.]+)\.")


@dataclass
class AppUsage:
    key: str
    name: str
    icon: Gio.Icon | None
    memory: int
    cpu: float  # part de toute la machine, 0 à 1
    processes: int
    units: list[str]  # scopes systemd à arrêter pour fermer l'app ; vide si on ne doit pas


@cache
def _desktop_info(app_id: str) -> Gio.DesktopAppInfo | None:
    for desktop_id in (f"{app_id}.desktop", f"{app_id}_{app_id}.desktop"):
        try:
            if info := Gio.DesktopAppInfo.new(desktop_id):
                return info
        except TypeError:
            pass
    return None


class AppSampler:
    def __init__(self):
        self.prev_ticks: dict[str, int] = {}
        self.prev_time: float | None = None

    def sample(self) -> list[AppUsage]:
        now = time.monotonic()
        elapsed = now - self.prev_time if self.prev_time else None
        self.prev_time = now

        processes = []  # (unit, pid, pss, ticks)
        ticks_now = {}
        for pid in filter(str.isdigit, os.listdir("/proc")):
            try:
                unit = Path(f"/proc/{pid}/cgroup").read_text().strip().rsplit("/", 1)[-1]
                stat = Path(f"/proc/{pid}/stat").read_text()
                rollup = Path(f"/proc/{pid}/smaps_rollup").read_text()  # illisible pour les autres utilisateurs
            except OSError:
                continue
            fields = stat.rsplit(")", 1)[1].split()
            ticks_now[pid] = int(fields[11]) + int(fields[12])
            pss = re.search(r"^Pss:\s+(\d+)", rollup, re.M)
            if pss:
                processes.append((unit.replace("\\x2d", "-"), unit, int(pid), int(pss.group(1)) * 1024,
                                  ticks_now[pid] - self.prev_ticks.get(pid, ticks_now[pid])))
        self.prev_ticks = ticks_now

        # Une app peut éclater en plusieurs scopes (ChatGPT + son Chromium partagent le même numéro) :
        # on retient pour chaque numéro l'identifiant qui correspond à un vrai lanceur.
        best_id = {}
        for clean, *_ in processes:
            if m := APP_SCOPE.match(clean):
                app_id, number = m.groups()
                if number not in best_id or (_desktop_info(app_id) and not _desktop_info(best_id[number])):
                    best_id[number] = app_id

        groups: dict[str, list] = {}
        for clean, unit, pid, pss, ticks in processes:
            units = []
            if pid == OWN_PID:
                key = MANETTE
            elif m := APP_SCOPE.match(clean):
                key, units = best_id[m.group(2)], [unit]
            elif (m := SNAP_SCOPE.match(clean)) and clean.endswith(".scope"):
                key, units = m.group(1), [unit]
            elif clean.startswith("org.gnome.Shell"):
                key = SHELL
            else:
                key = OTHERS
            group = groups.setdefault(key, [0, 0, 0, set()])
            group[0] += pss
            group[1] += ticks
            group[2] += 1
            group[3].update(units)

        result = []
        for key, (pss, ticks, count, units) in groups.items():
            name, icon = _describe(key)
            cpu = ticks / (elapsed * CLK_TCK * NCPU) if elapsed else 0.0
            result.append(AppUsage(key, name, icon, pss, min(cpu, 1.0), count, sorted(units)))
        result.sort(key=lambda a: a.memory, reverse=True)
        return result


def _describe(key: str) -> tuple[str, Gio.Icon | None]:
    if key == SHELL:
        return tr('Bureau GNOME'), Gio.ThemedIcon.new("user-desktop")
    if key == OTHERS:
        return tr('Services et arrière-plan'), Gio.ThemedIcon.new("system-run")
    if key == MANETTE:
        return "Manette", Gio.ThemedIcon.new("local.Manette")
    if info := _desktop_info(key):
        return info.get_display_name(), info.get_icon()
    return key, Gio.ThemedIcon.new("application-x-executable")
