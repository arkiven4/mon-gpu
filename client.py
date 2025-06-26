import pynvml #导包
import socket
import requests
import argparse
import time

import subprocess
import platform
import re
import os

def get_cpu_info_native():
    """
    在不使用第三方库的情况下，获取CPU名称、线程数和主频。
    """
    # 1. 获取线程数 (跨平台)
    thread_count = os.cpu_count()

    cpu_name = "N/A"
    cpu_freq_ghz = "N/A"

    # 2. 根据操作系统获取CPU名称和主频
    system_name = platform.system()

    try:
        if system_name == "Windows":
            # 使用 wmic 命令获取信息
            command = "wmic cpu get Name, MaxClockSpeed /format:list"
            output = subprocess.check_output(command, shell=True, text=True, encoding='utf-8')
            
            # 解析 wmic 输出
            name_match = re.search(r"Name=(.+)", output)
            if name_match:
                cpu_name = name_match.group(1).strip()
            
            freq_match = re.search(r"MaxClockSpeed=(\d+)", output)
            if freq_match:
                # MaxClockSpeed 单位是 MHz
                cpu_freq_ghz = f"{int(freq_match.group(1)) / 1000:.2f} GHz"

        elif system_name == "Linux":
            # 优先尝试 lscpu 命令，信息更规整
            try:
                command = "lscpu"
                output = subprocess.check_output(command, shell=True, text=True, encoding='utf-8')
                
                name_match = re.search(r"Model name:\s+(.+)", output)
                if not name_match:
                    name_match = re.search(r"モデル名:\s+(.+)", output)
                if name_match:
                    cpu_name = name_match.group(1).strip()
                
                # lscpu 可能提供多个频率，我们取 "CPU max MHz"
                freq_match = re.search(r"CPU max MHz:\s+([\d\.]+)", output)
                if not freq_match:
                    freq_match = re.search(r"CPU 最大 MHz:\s+([\d\.]+)", output)
                if freq_match:
                    cpu_freq_ghz = f"{float(freq_match.group(1)) / 1000:.2f}GHz"
                else:
                    # 如果没有 max MHz, 尝试直接找 CPU MHz
                    freq_match = re.search(r"CPU MHz:\s+([\d\.]+)", output)
                    if freq_match:
                        cpu_freq_ghz = f"{float(freq_match.group(1)) / 1000:.2f}GHz"

            except (subprocess.CalledProcessError, FileNotFoundError):
                # 如果 lscpu 失败，回退到解析 /proc/cpuinfo
                with open("/proc/cpuinfo", "r", encoding='utf-8') as f:
                    for line in f:
                        if "model name" in line:
                            cpu_name = line.split(":")[1].strip()
                            break # 通常所有核心的 model name 相同，找到一个即可
                        if "cpu MHz" in line:
                            mhz = float(line.split(":")[1].strip())
                            cpu_freq_ghz = f"{mhz / 1000:.2f}GHz"
                            # 这里可能会找到多个核心的频率，也可以只取第一个

        elif system_name == "Darwin": # macOS
            # 获取CPU名称
            command_name = "sysctl -n machdep.cpu.brand_string"
            cpu_name = subprocess.check_output(command_name, shell=True, text=True).strip()
            
            # 获取CPU最大频率 (单位是 Hz)
            command_freq = "sysctl -n hw.cpufrequency_max"
            max_freq_hz = int(subprocess.check_output(command_freq, shell=True, text=True).strip())
            cpu_freq_ghz = f"{max_freq_hz / 1_000_000_000:.2f}GHz"

    except Exception as e:
        print(f"获取详细信息时出错: {e}")

    return {
        "Name": cpu_name,
        "Threads": thread_count,
        "Freq": cpu_freq_ghz
    }
    
def get_ram_info_native():
    """
    通过读取和解析 /proc/meminfo 文件来获取内存信息 (无需第三方库)
    """
    meminfo = {}
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                # 使用正则表达式匹配键、值和单位
                match = re.match(r'(\w+):\s+(\d+)\s*(\w*)', line)
                if match:
                    key, value, unit = match.groups()
                    # 将所有值统一转换为 KiB (如果单位存在)
                    meminfo[key] = int(value)

    except FileNotFoundError:
        return {"错误": "无法读取 /proc/meminfo，请确认在 Linux 系统上运行。"}

    # --- 数据计算和格式化 ---
    # 创建一个辅助函数来格式化 KiB
    def kib_to_gb(kib_value):
        return round(kib_value / (1024**2), 2)

    total_gb = kib_to_gb(meminfo.get('MemTotal', 0))
    available_gb = kib_to_gb(meminfo.get('MemAvailable', 0))
    # used_gb = total_gb - available_gb
    
    # swap_total_gb = kib_to_gb(meminfo.get('SwapTotal', 0))
    # swap_free_gb = kib_to_gb(meminfo.get('SwapFree', 0))
    # swap_used_gb = swap_total_gb - swap_free_gb
    
    ram_info = {
        "unit": "GB",
        "total": f"{total_gb}",
        "available": f"{available_gb}",
        # "used": f"{round(used_gb, 2)}",
        # "total": f"{swap_total_gb} GB",
        # "used": f"{round(swap_used_gb, 2)} GB",
        # "available": f"{swap_free_gb} GB",
    }
    return ram_info

class GPUMonitor:
    """ get GPU information periodically, and send it to the server """
    def __init__(self, remark, server_ip):
        """
        remark: str, some additional infomation
        server_ip: str, the IP address of the server to send GPU information
        """
        self.hostname = socket.gethostname()
        self.remark = remark
        self.server_ip = server_ip
        self.UNIT = 1024**3  # Unit for memory in GB
        self.SUFFIX = 'GB'
        self.hasNVGPU = True
        try:
            pynvml.nvmlInit()
        except:
            self.hasNVGPU = False
        
        self.device_info = dict({
            "remark": self.remark,
            "last_report": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "hostname" : self.hostname,
            "hasNVGPU": self.hasNVGPU,
            "system": {},
            "gpu": []
        })
        self.get_system_info()
        if self.hasNVGPU:
            self.get_gpu_info()
        
    def __del__(self):
        """ Clean up the NVML resources """
        if self.hasNVGPU:
            pynvml.nvmlShutdown()

    def get_system_info(self):
        """ Get system information """
        cpu_info = get_cpu_info_native()
        self.device_info['system']['cpu'] = {
            "name": cpu_info.get("Name", "N/A"),
            "threads": cpu_info.get("Threads", "N/A"),
            "frequency": cpu_info.get("Freq", "N/A")
        }
        
        ram_info = get_ram_info_native()
        self.device_info['system']['ram'] = {
            "unit": ram_info.get("unit", "N/A"),
            "total": ram_info.get("total", "N/A"),
            "available": ram_info.get("available", "N/A"),
            # "used": ram_info.get("used", "N/A"),
        }

    
    def get_gpu_info(self):
        self.device_info['system']['processes'] = []
        self.device_info['system']['driver_version'] = pynvml.nvmlSystemGetDriverVersion()
        for i in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpu_name = pynvml.nvmlDeviceGetName(handle)
            gpu_temperature = str(pynvml.nvmlDeviceGetTemperature(handle, 0))+'°C'
            try:
                gpu_fan_speed = str(pynvml.nvmlDeviceGetFanSpeed(handle))+'%'
            except pynvml.NVMLError as e:
                gpu_fan_speed = "N/A"
            gpu_power_state = 'level ' + str(pynvml.nvmlDeviceGetPowerState(handle))
            gpu_util_rate = str(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu) + '%'
            gpu_memory_rate = str(pynvml.nvmlDeviceGetUtilizationRates(handle).memory) + '%'
            
            processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
            # print(f"processes: {processes}")
            if processes:
                for process in processes:
                    pid = process.pid
                    used_memory = process.usedGpuMemory / self.UNIT  # 转换为 GB
                    command = self.get_process_command(pid)
                    # print(command)
                    self.device_info['system']['processes'].append({
                        'pid': pid,
                        'cuda': i,
                        'command': command,
                        'used_memory': f"{used_memory}{self.SUFFIX}"
                    })

            used_memory = round(memory_info.used / self.UNIT, 2)
            total_memory = round(memory_info.total / self.UNIT, 2)

            this_gpu_info = {
                "index": i,
                "name": f"{gpu_name}",
                "memory_usage": f"{used_memory}/{total_memory}{self.SUFFIX}",
                "temperature": f"{gpu_temperature}",
                "fan_speed": f"{gpu_fan_speed}",
                "power_state": f"{gpu_power_state}",
                "gpu_utilization": f"{gpu_util_rate}",
                "memory_utilization": f"{gpu_memory_rate}"
            }
            self.device_info['gpu'].append(this_gpu_info)
    
    @staticmethod
    def get_process_command(pid):
        try:
            # 使用 ps 命令获取进程的命令行
            result = subprocess.run(['ps', '-p', str(pid), '-o', 'cmd'], 
                                    capture_output=True, text=True)
            output = result.stdout.strip().split('\n')
            if len(output) > 1:
                return output[1]  # 第一行是标题，第二行是命令
            else:
                return f"进程 {pid} 不存在或无法获取信息"
        except Exception as e:
            return f"获取进程信息时出错: {e}"
    
    def send_device_info(self):
        """ Send GPU information to the server """
        url = f"http://{self.server_ip}/device_info"
        try:
            response = requests.post(url, json=self.device_info)
            if response.status_code == 200:
                print("GPU information sent successfully.")
            else:
                print(f"Failed to send GPU information. Status code: {response.status_code}")
        except requests.RequestException as e:
            print(f"Error sending GPU information: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPU Monitor")
    parser.add_argument("--remark", type=str, default="", help="remark")
    parser.add_argument("--server_ip", type=str, default="163.221.176.232:8081", help="Server IP address to send GPU information")
    args = parser.parse_args()

    gpu_monitor = GPUMonitor(args.remark, args.server_ip)
    gpu_monitor.send_device_info()
