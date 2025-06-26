from flask import Flask, jsonify, request, render_template_string, render_template
import argparse
import json
import os
from server_utils import generate_ssh_config, ssh_config_to_string

app = Flask(__name__, static_folder='static', template_folder='templates')
data_from_servers = dict()  # Store GPU data in memory

# Load existing data from pickle file if it exists
pickle_file = 'data_from_servers.json'
if os.path.exists(pickle_file):
    with open(pickle_file, 'rb') as f:
        data_from_servers = json.load(f)
        print(f"Loaded existing data from {pickle_file}")

@app.route('/device_info', methods=['POST'])
def receive_gpu_info():
    """
    Receive GPU information from clients and store it in memory.
    """
    global data_from_servers
    device_info = request.json
    if not isinstance(device_info, dict):
        return jsonify({"error": "Invalid data format"}), 400
    if len(device_info.keys()) == 0:
        return jsonify({"error": "No device_info data provided"}), 400

    ip = request.remote_addr

    sid = ip
    # if hostname not in data_from_servers:
    data_from_servers[sid] = device_info
    data_from_servers[sid]['ip'] = ip

    
    if device_info.get('hasNVGPU', False) or len(device_info.get('gpu', [])) > 0:
        if data_from_servers[sid]['system']['driver_version'].startswith('b\''):
            data_from_servers[sid]['system']['driver_version'] = data_from_servers[sid]['driver_version'][2:-1]
            
        for gpu_info in data_from_servers[sid]['gpu']:
            if gpu_info['name'].startswith('b\''):
                gpu_info['name'] = gpu_info['name'][2:-1]
    else:
        data_from_servers[sid]['remark'] += 'CPU ONLY'
        
    # print(data_from_servers)
    return jsonify({"status": "success"}), 200

@app.route('/api/raw_data', methods=['GET'])
def index():
    """
    Display the GPU information received from clients.
    """
    data_sorted = {k: v for k, v in sorted(data_from_servers.items(), key=lambda item: item[1]['hostname'])}
    return jsonify(data_sorted)

@app.route('/', methods=['GET'])
def visual():
    """
    Render a simple HTML page to visualize GPU information.
    """
    # Sort the data by hostname
    # data_sorted = {k: v for k, v in sorted(data_from_servers.items(), key=lambda item: print(item))}
    data_sorted = {k: v for k, v in sorted(data_from_servers.items(), key=lambda item: item[1]['hostname'])}
    return render_template('index.html', data=data_sorted)

@app.route('/ssh_config', methods=['GET'])
def ssh_config():
    """
    Generate SSH config entries for the servers and return them as a string.
    """
    username = request.args.get('username', 'your_username')
    useNaistProxy = request.args.get('proxy', 'false').lower() == 'true'

    data_sorted = {k: v for k, v in sorted(data_from_servers.items(), key=lambda item: item[1]['hostname'])}
    ssh_config_entries = generate_ssh_config(data_sorted, username, useNaistProxy)
    ssh_config_string = ssh_config_to_string(ssh_config_entries)
    
    return str(ssh_config_string), 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/processes', methods=['GET'])
def show_processes():
    """
    Display the processes running on the specified Server.
    """
    server_id = request.args.get('id')
    if not server_id or server_id not in data_from_servers.keys():
        return jsonify({"error": "Server ID not found"}), 404
    
    processes = data_from_servers[server_id]['system'].get('processes', [])
    return render_template('processes.html', server_id=server_id, processes=processes)

    
# search the offline servers by last_report periodically
import threading
import time
from datetime import datetime
def search_offline_servers():
    """
    Periodically check for offline servers and remove them from the data.
    """
    global data_from_servers
    while True:
        # Check for servers that haven't updated in the last 30s
        current_time = time.time()
        offline_servers_id = [k for k, v in data_from_servers.items() if current_time - datetime.strptime(v.get('last_report', 0),"%Y-%m-%d %H:%M:%S").timestamp() >= 120]
        for server_id in offline_servers_id:
            data_from_servers[server_id]['remark2'] = 'OFFLINE'
            
        # save the updated data
        json_file = 'data_from_servers.json'
        with open(json_file, 'w') as f:
            json.dump(data_from_servers, f, indent=4)
        threading.Event().wait(30)  # Wait for 30s before checking again


if __name__ == '__main__':
    # Start the thread to search for offline servers
    praser = argparse.ArgumentParser(description='GPU Monitoring Server')
    praser.add_argument('--port', type=int, default=8081, help='Port to run the server on')

    port = praser.parse_args().port
    threading.Thread(target=search_offline_servers, daemon=True).start()
    app.run(host='0.0.0.0', port=port, debug=False)
