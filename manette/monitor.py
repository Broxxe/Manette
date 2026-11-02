"""Mesures en direct : processeur, mémoire, carte graphique et applications."""

from __future__ import annotations

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
    return "Processeur"


class CpuSampler:
    def __init__(self):
        self.prev = None

    def sample(self) -> tuple[float, list[float]]:
        """Charge totale puis par cœur, entre 0 et 1, depuis le dernier appel."""
        rows = []
        for line in _read("/proc/stat").splitlines():
            if not line.startswith("cpu"):
                break
            values = [int(v) for v in line.split()[1:9]]
            rows.append((sum(values), values[3] + values[4]))
        prev, self.prev = self.prev, rows
        if prev is None:
            return 0.0, [0.0] * (len(rows) - 1)
        usage = [1 - (idle - p_idle) / (total - p_total) if total > p_total else 0.0
                 for (total, idle), (p_total, p_idle) in zip(rows, prev)]
        return usage[0], usage[1:]


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
        gpu = Gpu("Carte graphique AMD", int(busy) / 100)
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
        return "Bureau GNOME", Gio.ThemedIcon.new("user-desktop")
    if key == OTHERS:
        return "Services et arrière-plan", Gio.ThemedIcon.new("system-run")
    if key == MANETTE:
        return "Manette", Gio.ThemedIcon.new("local.Manette")
    if info := _desktop_info(key):
        return info.get_display_name(), info.get_icon()
    return key, Gio.ThemedIcon.new("application-x-executable")
