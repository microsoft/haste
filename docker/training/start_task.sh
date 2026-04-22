sudo systemctl stop docker
sudo sed -i 's|ExecStart=/usr/bin/docker daemon -H fd://|ExecStart=/usr/bin/docker daemon -g /new/path/docker -H fd://|' /lib/systemd/system/docker.service
sudo systemctl daemon-reload
sudo systemctl start docker
