[Unit]
Description=ngrok Tunnel Service
After=network.target

[Service]
ExecStart=ngrok http 8000
Restart=always
User=momenttrack
WorkingDirectory=/home/momenttrack
StandardOutput=append:/var/log/ngrok.log
StandardError=append:/var/log/ngrok.log
ExecStartPost=/bin/bash -c 'for i in {1..10}; do curl -s http://127.0.0.1:4040/api/tunnels && break || sleep 1; done; curl -s http://127.0.0.1:4040/api/tunnels | jq -r ".tunnels[0].public_url" > /home/momenttrack/ngrok_url.txt'

[Install]
WantedBy=multi-user.target