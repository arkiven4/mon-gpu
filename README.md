# GPU Monitor Client & Server

## Server
the default port is `8081`
```bash
sudo apt install python3-flask

sudo vim /etc/systemd/system/gpu-monitor-server.service
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

# show status
sudo systemctl status gpu-monitor-server
```

## Client
```bash
sudo apt install python3-requests python3-pynvml

sudo crontab -e

# add the following line to crontab
* * * * * /usr/bin/python3 /path/to/client.py --server_ip serverIP:Port --remark Example-remark
```
