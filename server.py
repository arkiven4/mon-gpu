from flask import Flask, jsonify, request, render_template_string

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

    id = f"{hostname}_{ip}"
    # if hostname not in data_from_servers:
    data_from_servers[id] = {}
    data_from_servers[id]['hostname'] = hostname
    data_from_servers[id]['remark'] = remark
    data_from_servers[id]['ip'] = ip
    data_from_servers[id]['update_time'] = update_time
    data_from_servers[id]['driver_version'] = basic_info.get('driver_version', 'unknown')
    data_from_servers[id]['gpus'] = []
    for gpu_info in gpu_data[1:]:
        data_from_servers[id]['gpus'].append(gpu_info)
        
    # data_from_servers[id].insert(0, {
    #     "hostname": hostname,
    #     "remark": remark,
    #     "ip": ip,
    #     "update_time": update_time
    # })

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
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>GPU Monitor Visualization</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
            th { background: #eee; }
        </style>
    </head>
    <body>
        <h2>GPU Information from Clients</h2>
        {% if data %}
            {% for server, info in data.items() %}
                <h3>{{ server }} {{ info['remark'] }} (driver_version: {{ info['driver_version'] }}) reported at {{ info['update_time'] }}</h3>
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
    </body>
    </html>
    """
    # Sort the data by hostname
    data_sorted = {k: data_from_servers[k] for k in sorted(data_from_servers.keys())}
    return render_template_string(html, data=data_from_servers)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=False)
