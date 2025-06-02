from flask import Flask, jsonify, request, render_template_string, render_template

app = Flask(__name__)
data_from_servers = dict()  # Store GPU data in memory

@app.route('/gpu_info', methods=['POST'])
def receive_gpu_info():
    """
    Receive GPU information from clients and store it in memory.
    """
    global data_from_servers
    gpu_data = request.json
    if not isinstance(gpu_data, list):
        return jsonify({"error": "Invalid data format"}), 400
    if len(gpu_data) == 0:
        return jsonify({"error": "No GPU data provided"}), 400
    basic_info = gpu_data[0] if gpu_data else {}
    hostname = basic_info.get("hostname", "unknown")
    remark = basic_info.get("remark", "")
    ip = request.remote_addr

    update_time = basic_info.get('update_time', 'unknown')

    sid = ip
    # if hostname not in data_from_servers:
    data_from_servers[sid] = {}
    data_from_servers[sid]['hostname'] = hostname
    data_from_servers[sid]['remark'] = remark
    data_from_servers[sid]['ip'] = ip
    data_from_servers[sid]['update_time'] = update_time
    data_from_servers[sid]['driver_version'] = basic_info.get('driver_version', 'unknown')
    if data_from_servers[sid]['driver_version'].startswith('b\''):
        data_from_servers[sid]['driver_version'] = data_from_servers[sid]['driver_version'][2:-1]
    
    data_from_servers[sid]['processes'] = basic_info.get('processes', [])
    
    data_from_servers[sid]['gpus'] = []
    for gpu_info in gpu_data[1:]:
        if gpu_info['name'].startswith('b\''):
            gpu_info['name'] = gpu_info['name'][2:-1]
        data_from_servers[sid]['gpus'].append(gpu_info)

    return jsonify({"status": "success"}), 200

@app.route('/raw_data', methods=['GET'])
def index():
    """
    Display the GPU information received from clients.
    """
    return jsonify(data_from_servers)

@app.route('/', methods=['GET'])
def visual():
    """
    Render a simple HTML page to visualize GPU information.
    """
    # Sort the data by hostname
    data_sorted = {k: v for k, v in sorted(data_from_servers.items(), key=lambda item: item[1]['hostname'])}
    return render_template('index.html', data=data_sorted)

@app.route('/processes', methods=['GET'])
def show_processes():
    """
    Display the processes running on the specified Server.
    """
    server_id = request.args.get('id')
    if not server_id or server_id not in data_from_servers.keys():
        return jsonify({"error": "Server ID not found"}), 404
    
    processes = data_from_servers[server_id].get('processes', [])
    return render_template('processes.html', server_id=server_id, processes=processes)

    
# search the offline servers by update_time periodically
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
        offline_servers_id = [k for k, v in data_from_servers.items() if current_time - datetime.strptime(v.get('update_time', 0),"%Y-%m-%d %H:%M:%S").timestamp() >= 120]
        for server_id in offline_servers_id:
            data_from_servers[server_id]['remark2'] = 'OFFLINE'
        threading.Event().wait(60)  # Wait for 30s before checking again


if __name__ == '__main__':
    # Start the thread to search for offline servers
    threading.Thread(target=search_offline_servers, daemon=True).start()
    app.run(host='0.0.0.0', port=8082, debug=False)
