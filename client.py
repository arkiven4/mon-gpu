import argparse
import os
import platform
import re
import socket
import subprocess
import time

import pynvml
import requests


def _get_cpu_info() -> dict:
    cpu_name = "N/A"
    cpu_freq = "N/A"
    system = platform.system()

    try:
        if system == "Windows":
            out = subprocess.check_output(
                "wmic cpu get Name, MaxClockSpeed /format:list",
                shell=True, text=True, encoding='utf-8'
            )
            m = re.search(r"Name=(.+)", out)
            if m:
                cpu_name = m.group(1).strip()
            m = re.search(r"MaxClockSpeed=(\d+)", out)
            if m:
                cpu_freq = f"{int(m.group(1)) / 1000:.2f}GHz"

        elif system == "Linux":
            try:
                out = subprocess.check_output("lscpu", shell=True, text=True, encoding='utf-8')
                m = re.search(r"Model name:\s+(.+)|モデル名:\s+(.+)", out)
                if m:
                    cpu_name = (m.group(1) or m.group(2)).strip()
                m = re.search(r"CPU max MHz:\s+([\d.]+)|CPU 最大 MHz:\s+([\d.]+)", out)
                if not m:
                    m = re.search(r"CPU MHz:\s+([\d.]+)", out)
                if m:
                    mhz = float((m.group(1) or m.group(2)).strip())
                    cpu_freq = f"{mhz / 1000:.2f}GHz"
            except (subprocess.CalledProcessError, FileNotFoundError):
                with open("/proc/cpuinfo", encoding='utf-8') as f:
                    for line in f:
                        if "model name" in line and cpu_name == "N/A":
                            cpu_name = line.split(":", 1)[1].strip()
                        elif "cpu MHz" in line and cpu_freq == "N/A":
                            cpu_freq = f"{float(line.split(':', 1)[1].strip()) / 1000:.2f}GHz"
                        if cpu_name != "N/A" and cpu_freq != "N/A":
                            break

        elif system == "Darwin":
            cpu_name = subprocess.check_output(
                "sysctl -n machdep.cpu.brand_string", shell=True, text=True
            ).strip()
            hz = int(subprocess.check_output(
                "sysctl -n hw.cpufrequency_max", shell=True, text=True
            ).strip())
            cpu_freq = f"{hz / 1e9:.2f}GHz"

    except Exception:
        pass

    return {"name": cpu_name, "threads": os.cpu_count(), "frequency": cpu_freq}


def _get_cpu_usage() -> float | None:
    def _read_stat() -> tuple[int, int]:
        with open('/proc/stat') as f:
            vals = list(map(int, f.readline().split()[1:8]))
        return sum(vals), vals[3] + vals[4]  # total, idle+iowait

    try:
        t1, i1 = _read_stat()
        time.sleep(0.2)
        t2, i2 = _read_stat()
        delta = t2 - t1
        return round((1 - (i2 - i1) / delta) * 100, 1) if delta else 0.0
    except Exception:
        return None


def _get_ram_gb() -> tuple[float, float]:
    try:
        meminfo: dict[str, int] = {}
        with open('/proc/meminfo') as f:
            for line in f:
                m = re.match(r'(\w+):\s+(\d+)', line)
                if m:
                    meminfo[m.group(1)] = int(m.group(2))
        to_gb = lambda kib: round(kib / 1024 ** 2, 2)
        return to_gb(meminfo.get('MemTotal', 0)), to_gb(meminfo.get('MemAvailable', 0))
    except FileNotFoundError:
        return 0.0, 0.0


class GPUMonitor:
    _GB = 1024 ** 3

    def __init__(self, remark: str, server: str):
        self.remark = remark
        self.server = server
        self.hostname = socket.gethostname()

        self.has_gpu = True
        try:
            pynvml.nvmlInit()
        except pynvml.NVMLError:
            self.has_gpu = False

        self.payload = {
            "hostname": self.hostname,
            "remark": self.remark,
            "remark2": "",
            "last_report": time.strftime("%Y-%m-%d %H:%M:%S"),
            "hasNVGPU": self.has_gpu,
            "system": {},
            "gpu": [],
        }
        self._collect_system()
        if self.has_gpu:
            self._collect_gpu()

    def __del__(self):
        if self.has_gpu:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    def _collect_system(self):
        ram_total, ram_avail = _get_ram_gb()
        self.payload['system'] = {
            'cpu': _get_cpu_info(),
            'os': f"{platform.system()} {platform.release()}",
            'ram': {'total': ram_total, 'available': ram_avail, 'unit': 'GB'},
            'cpu_usage': _get_cpu_usage(),
        }

    def _collect_gpu(self):
        processes = []
        gpu_list = []

        self.payload['system']['driver_version'] = pynvml.nvmlSystemGetDriverVersion()

        for i in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)

            try:
                fan = f"{pynvml.nvmlDeviceGetFanSpeed(handle)}%"
            except pynvml.NVMLError:
                fan = "N/A"

            for proc in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
                processes.append({
                    'pid': proc.pid,
                    'cuda': i,
                    'command': self._get_process_cmd(proc.pid),
                    'used_memory': f"{proc.usedGpuMemory / self._GB:.2f}GB",
                })

            gpu_list.append({
                "index": i,
                "name": pynvml.nvmlDeviceGetName(handle),
                "memory_used": round(mem.used / self._GB, 2),
                "memory_total": round(mem.total / self._GB, 2),
                "temperature": f"{pynvml.nvmlDeviceGetTemperature(handle, 0)}°C",
                "fan_speed": fan,
                "power_state": f"level {pynvml.nvmlDeviceGetPowerState(handle)}",
                "gpu_utilization": f"{util.gpu}%",
                "memory_utilization": f"{util.memory}%",
            })

        self.payload['system']['processes'] = processes
        self.payload['gpu'] = gpu_list

    @staticmethod
    def _get_process_cmd(pid: int) -> str:
        try:
            result = subprocess.run(
                ['ps', '-p', str(pid), '-o', 'cmd'],
                capture_output=True, text=True
            )
            lines = result.stdout.strip().split('\n')
            return lines[1] if len(lines) > 1 else f"PID {pid} not found"
        except Exception as e:
            return f"Error: {e}"

    def send(self):
        url = f"http://{self.server}/device_info"
        try:
            r = requests.post(url, json=self.payload, timeout=10)
            print(f"[{self.hostname}] {'OK' if r.status_code == 200 else f'HTTP {r.status_code}'}")
        except requests.RequestException as e:
            print(f"[{self.hostname}] Send failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPU Monitor Client")
    parser.add_argument("--remark", default="")
    parser.add_argument("--server", default="100.101.198.75:5090")
    args = parser.parse_args()

    monitor = GPUMonitor(args.remark, args.server)
    monitor.send()
