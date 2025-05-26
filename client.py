import pynvml #导包
import socket
import requests
import argparse
import time

class GPUMonitor:
    """ get GPU information periodically, and send it to the server """
    def __init__(self, remark, server_ip):
        """
        remark: str, the name of the local machine
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
        self.get_gpu_info()

    def __del__(self):
        """ Clean up the NVML resources """
        pynvml.nvmlShutdown()

    def get_gpu_info(self):
        for i in range(1, self.gpu_device_count+1):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i-1)
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpu_name = str(pynvml.nvmlDeviceGetName(handle))
            gpu_temperature = pynvml.nvmlDeviceGetTemperature(handle, 0)
            gpu_fan_speed = pynvml.nvmlDeviceGetFanSpeed(handle)
            gpu_power_state = pynvml.nvmlDeviceGetPowerState(handle)
            gpu_util_rate = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            gpu_memory_rate = pynvml.nvmlDeviceGetUtilizationRates(handle).memory

            used_memory = round(memory_info.used / self.UNIT, 2)
            total_memory = round(memory_info.total / self.UNIT, 2)
            self.gpu_info[i]["index"] = i-1
            self.gpu_info[i]['name'] = f"{gpu_name}"
            self.gpu_info[i]['memory_usage'] = f"{used_memory}/{total_memory}{self.SUFFIX}"
            self.gpu_info[i]['temperature'] = f"{gpu_temperature}°C"
            self.gpu_info[i]['fan_speed'] = f"{gpu_fan_speed}"
            self.gpu_info[i]['power_state'] = f"{gpu_power_state}"
            self.gpu_info[i]['gpu_utilization'] = f"{gpu_util_rate}%"
            self.gpu_info[i]['memory_utilization'] = f"{gpu_memory_rate}%"

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
    parser.add_argument("--server_ip", type=str, required=True, help="Server IP address to send GPU information")
    args = parser.parse_args()

    gpu_monitor = GPUMonitor(args.remark, args.server_ip)
    gpu_monitor.send_gpu_info()
