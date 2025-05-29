from flask import Flask, jsonify, request, render_template_string
from server_utils import generate_ssh_config, ssh_config_to_string

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
@app.route('/', methods=['GET'])
def visual():
    """
    Render a simple HTML page to visualize GPU information.
    """
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>GPU Monitor</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
            th { background: #eee; }
        </style>
    </head>
    <body>
        <h2>GPU Monitor</h2>
        <a href='/ssh_config?proxy=false&username=your_username'>Get SSH Config (No Proxy)</a>
        <a href='/ssh_config?proxy=true&username=your_username'>Get SSH Config (Proxy)</a>
        {% if data %}
            {% for server, info in data.items() %}
                <h3 style="margin-bottom: 0px;">
                {{ info['hostname'] }}
                (<span class="copyText" style="color:blue;user-select: all; cursor: pointer;">{{ info['ip'] }}</span>, {{ info['driver_version'] }})
                @{{ info['update_time'] }}
                <span style="color:orange;">{{ info['remark'] }}</span>
                {% if info['remark2'] %}
                    <span style="color: red;">{{ info['remark2'] }}</span>
                {% endif %}
                </h3>
                
                <table>
                    <tr>
                        {% if info['gpus'] and info['gpus'][0] %}
                            {% for key in info['gpus'][0].keys() %}
                                <th>{{ key }}</th>
                            {% endfor %}
                        {% endif %}
                    </tr>
                    {% for gpu in info['gpus'] %}
                        <tr>
                            {% for value in gpu.values() %}
                                <td>{{ value }}</td>
                            {% endfor %}
                        </tr>
                    {% endfor %}
                </table>
            {% endfor %}
        {% else %}
            <p>No GPU data available.</p>
        {% endif %}
        
        <script>
            setInterval(function() {
                window.location.reload();
            }, 30000); // 60000 毫秒 = 60 秒
            
            const ips = document.querySelectorAll('.copyText');
            ips.forEach(ip => {
                ip.onclick = function() {
                    // need https
                    navigator.clipboard.writeText(this.innerText);
                };
            });
            
        </script>
    </body>
    </html>
    """
    # Sort the data by hostname
    data_sorted = {k: v for k, v in sorted(data_from_servers.items(), key=lambda item: item[1]['hostname'])}
    # search the offline servers by update_time
    return render_template_string(html, data=data_sorted)

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
    app.run(host='0.0.0.0', port=8081, debug=False)
