# GPU Monitor Client & Server

## Server
Since I already deployed the server to `163.221.176.232:8081`, if it's still running, you don't need to deploy it again.

the default port is `8081`.
```bash
sudo apt install python3-flask

sudo nano /etc/systemd/system/gpu-monitor-server.service
```

```config
[Unit]
Description=GPU Monitor Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/server.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable gpu-monitor-server
sudo systemctl start gpu-monitor-server

sudo systemctl restart gpu-monitor-server
sudo systemctl stop gpu-monitor-server

# show status
sudo systemctl status gpu-monitor-server
```

## Client
```bash
sudo apt install python3-requests python3-pynvml

sudo EDITOR=nano crontab -e

# add the following line to crontab; the --remark is optional
* * * * * /usr/bin/python3 /home/viblab/mon-gpu/client.py --server v-planck-pc3.local:5090 --remark Example-remark

# if server 232 is still running:
# * * * * * /usr/bin/python3 /path/to/client.py --server_ip 163.221.176.232:8081 --remark Example-remark
```
