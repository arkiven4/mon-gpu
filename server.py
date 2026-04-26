import argparse
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

app = Flask(__name__, static_folder='static', template_folder='templates')
servers: dict = {}


def _sorted_by_hostname() -> dict:
    return dict(sorted(servers.items(), key=lambda kv: kv[1]['hostname']))


def _build_ssh_config(data: dict, username: str, use_proxy: bool) -> str:
    entries = []
    for s in data.values():
        try:
            entry = f"Host {s['hostname']}\n  HostName {s['ip']}\n  User {username}\n"
            if use_proxy:
                entry += "  ProxyCommand ssh -W %h:%p sh.naist.jp\n"
            entries.append(entry)
        except KeyError:
            continue
    if use_proxy:
        entries.append(
            f"Host sh.naist.jp\n  HostName sh.naist.jp\n  User {username}\n  ForwardAgent yes\n"
        )
    return "\n\n".join(entries)


def _offline_watchdog():
    while True:
        cutoff = time.time() - 120
        for sid, info in list(servers.items()):
            try:
                ts = datetime.strptime(info['last_report'], "%Y-%m-%d %H:%M:%S").timestamp()
                if ts < cutoff:
                    servers[sid]['remark2'] = 'OFFLINE'
            except (ValueError, KeyError):
                pass
        time.sleep(30)


@app.route('/device_info', methods=['POST'])
def receive_device_info():
    data = request.json
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "Invalid or empty payload"}), 400

    ip = request.remote_addr
    sid = data.get('hostname', ip)
    servers[sid] = data
    servers[sid]['ip'] = ip

    if not (data.get('hasNVGPU') or data.get('gpu')):
        servers[sid]['remark2'] = 'CPU ONLY'

    return jsonify({"status": "ok"}), 200


@app.route('/api/raw_data')
def raw_data():
    return jsonify(_sorted_by_hostname())


@app.route('/')
def dashboard():
    return render_template('index.html', data=_sorted_by_hostname())


@app.route('/ssh_config')
def ssh_config():
    username = request.args.get('username', 'your_username')
    use_proxy = request.args.get('proxy', 'false').lower() == 'true'
    config = _build_ssh_config(_sorted_by_hostname(), username, use_proxy)
    return config, 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/processes')
def show_processes():
    sid = request.args.get('id')
    if not sid or sid not in servers:
        return jsonify({"error": "Server not found"}), 404
    processes = servers[sid]['system'].get('processes', [])
    return render_template('processes.html', server_id=sid, processes=processes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='GPU Monitor Server')
    parser.add_argument('--port', type=int, default=8081)
    args = parser.parse_args()

    threading.Thread(target=_offline_watchdog, daemon=True).start()
    app.run(host='0.0.0.0', port=args.port, debug=False)
