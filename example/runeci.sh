#sudo systemctl stop ethercat.service
sudo env "HOME=$HOME" PATH=$PATH /home/esrtux/.local/bin/pdm run eci enp2s0 --macros func.py --merge-macros-ns
