import pynvml #导包
import socket
import requests
import argparse
import time

import subprocess

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
        self.UNIT = 1024 * 1024 * 1024  # Unit for memory in GB
        self.SUFFIX = 'GB'
        pynvml.nvmlInit()
        self.gpu_driver_info = pynvml.nvmlSystemGetDriverVersion()
        self.gpu_device_count = pynvml.nvmlDeviceGetCount()
        self.gpu_info = [dict() for _ in range(self.gpu_device_count+1)]
        self.gpu_info[0]["hostname"] = self.hostname
        self.gpu_info[0]["remark"] = self.remark
        self.gpu_info[0]["driver_version"] = self.gpu_driver_info
        self.gpu_info[0]['update_time'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.gpu_info[0]['processes'] = []  # Initialize processes list for the first element
        self.get_gpu_info()

    def __del__(self):
        """ Clean up the NVML resources """
        pynvml.nvmlShutdown()

    def get_gpu_info(self):
        for i in range(1, self.gpu_device_count+1):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i-1)
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpu_name = pynvml.nvmlDeviceGetName(handle)
            gpu_temperature = str(pynvml.nvmlDeviceGetTemperature(handle, 0))+'°C'
            try:
                gpu_fan_speed = str(pynvml.nvmlDeviceGetFanSpeed(handle))+'%'
            except pynvml.NVMLError as e:
                gpu_fan_speed = "N/A"
            gpu_power_state = str(pynvml.nvmlDeviceGetPowerState(handle))
            gpu_util_rate = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            gpu_memory_rate = pynvml.nvmlDeviceGetUtilizationRates(handle).memory
            
            processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
            # print(f"processes: {processes}")
            if processes:
                for process in processes:
                    pid = process.pid
                    used_memory = process.usedGpuMemory // 1024 // 1024 // 1024  # 转换为 GB
                    command = self.get_process_command(pid)
                    # print(command)
                    self.gpu_info[0]['processes'].append({
                        'pid': pid,
                        'cuda': i-1,
                        'command': command,
                        'used_memory': f"{used_memory}GB"
                    })
                
            used_memory = round(memory_info.used / self.UNIT, 2)
            total_memory = round(memory_info.total / self.UNIT, 2)
            self.gpu_info[i]["index"] = i-1
            self.gpu_info[i]['name'] = f"{gpu_name}"
            self.gpu_info[i]['memory_usage'] = f"{used_memory}/{total_memory}{self.SUFFIX}"
            self.gpu_info[i]['temperature'] = f"{gpu_temperature}"
            self.gpu_info[i]['fan_speed'] = f"{gpu_fan_speed}"
            self.gpu_info[i]['power_state'] = f"{gpu_power_state}"
            self.gpu_info[i]['gpu_utilization'] = f"{gpu_util_rate}%"
            self.gpu_info[i]['memory_utilization'] = f"{gpu_memory_rate}%"
    
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
    
    # @staticmethod 
    # def get_process_command(pid):
    #     try:
    #         # 根据 PID 获取进程对象
    #         process = psutil.Process(pid)
    #         # 获取进程的命令行指令
    #         cmdline = process.cmdline()
    #         if cmdline:
    #             return ' '.join(cmdline)
    #         else:
    #             return "无法获取命令行信息（可能是权限问题或进程已结束）"
    #     except psutil.NoSuchProcess:
    #         return f"进程 {pid} 不存在"
    #     except psutil.AccessDenied:
    #         return f"无法访问进程 {pid} 的信息（权限不足）"
    #     except Exception as e:
    #         return f"获取进程信息时出错: {e}"    
    
    def send_gpu_info(self):
        """ Send GPU information to the server """
        url = f"http://{self.server_ip}/gpu_info"
        try:
            response = requests.post(url, json=self.gpu_info)
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
    gpu_monitor.send_gpu_info()
