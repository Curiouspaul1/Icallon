# [Unit]
# Description=ngrok Tunnel Service
# After=network.target

# [Service]
# ExecStart=ngrok http 8000
# Restart=always
# User=momenttrack
# WorkingDirectory=/home/momenttrack
# StandardOutput=append:/var/log/ngrok.log
# StandardError=append:/var/log/ngrok.log
# ExecStartPost=/bin/bash -c 'for i in {1..10}; do curl -s http://127.0.0.1:4040/api/tunnels && break || sleep 1; done; curl -s http://127.0.0.1:4040/api/tunnels | jq -r ".tunnels[0].public_url" > /home/momenttrack/ngrok_url.txt'

# [Install]
# WantedBy=multi-user.target

[Unit]
Description=Monitor Internet Service
After=network.target

[Service]
ExecStart=/bin/sh /home/momenttrack/monitor.sh >> /var/log/monitor.log 2>&1
Restart=always
User=momenttrack
WorkingDirectory=/home/momenttrack
StandardOutput=append:/var/log/monitor.log
StandardError=append:/var/log/monitor.log

[Install]
WantedBy=multi-user.target

# #!/bin/bash

# # API Endpoint and Authorization Header
# API_URL="http://localhost:8000/control_device"
# AUTH_HEADER="Authorization: Bearer fghjkl"
# DEVICE_ID="dmx_001"

# # Function to send DMX color updates
# send_dmx_update() {
#     local red=$1
#     local green=$2
#     local blue=$3
#     local white=$4

#     echo "Sending DMX Color -> RED:$red GREEN:$green BLUE:$blue WHITE:$white"

#     curl -X POST "$API_URL" \
#         -H "Content-Type: application/json" \
#         -H "$AUTH_HEADER" \
#         -d "{
#             \"device_id\": \"$DEVICE_ID\",
#             \"dmx_values\": {
#                 \"red\": $red,
#                 \"green\": $green,
#                 \"blue\": $blue,
#                 \"white\": $white
#             }
#         }" -s -o /dev/null

#     echo "Request sent 🚀"
# }

# # Function to Check Internet
# check_internet() {
#     echo "Checking Internet..."
#     ping -c 2 -q 8.8.8.8 > /dev/null 2>&1
#     return $?
# }

# # Initial Check Before Loop
# if check_internet; then
#     /bin/date "+%Y-%m-%d %H:%M:%S:✅ Internet is UP on startup!"
#     send_dmx_update 0 200 0 0  # Green (Online)
#     was_online=true
# else
#     /bin/date "+%Y-%m-%d %H:%M:%S: ❌ Internet is DOWN on startup!"
#     send_dmx_update 200 0 200 0  # Purple (Offline)
#     was_online=false
# fi

# # Now Start Monitoring Loop
# while true; do
#     if check_internet; then
#         if [ "$was_online" = false ]; then
#             /bin/date "+%Y-%m-%d %H:%M:%S: ✅ Internet is BACK!"
#             send_dmx_update 0 200 0 0  # Green (Online)
#             was_online=true
#         fi
#     else
#         if [ "$was_online" = true ]; then
#             /bin/date "+%Y-%m-%d %H:%M:%S: ❌ Internet LOST!"
#             send_dmx_update 200 0 200 0  # Purple (Offline)
#             was_online=false
#         fi
#     fi

#     echo "Waiting 3 seconds..."
#     sleep 3
# done