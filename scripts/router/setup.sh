#!/bin/bash

# WIKI https://www.shchers.com/wiki/doku.php?id=howto:basic_router_on_debian

echo "Install dnsmasq iptables iptables-persistent"
#sudo apt-get update
#sudo apt-get install dnsmasq iptables iptables-persistent


# Setup DHCP/DNS server
echo "Setup dnsmasq"
sudo cp files/dnsmasq.conf /etc/dnsmasq.d/

sudo sed -i "s/#conf-dir=\/etc\/dnsmasq.d\/\,\*\.conf/conf-dir=\/etc\/dnsmasq.d\/\,\*\.conf/g" /etc/dnsmasq.conf
sudo sed -i "s/#ENABLED=1/ENABLED=1/g" /etc/default/dnsmasq
sudo sed -i "s/#CONFIG_DIR=\/etc\/dnsmasq\.d\,\.dpkg-dist\,\.dpkg-old\,\.dpkg-new/CONFIG_DIR=\/etc\/dnsmasq\.d\,\.dpkg-dist\,\.dpkg-old\,\.dpkg-new/g" /etc/default/dnsmasq
# Run dnsmasq after network-online
sudo sed -i "s/\(Requires=network.target\)/\1\nAfter=network-online.target/g" /lib/systemd/system/dnsmasq.service

# Setup NAT
echo "Setup nating"
sudo cp files/network-nat.sh /usr/bin/
sudo cp files/network-nat.service  /lib/systemd/system
sudo ln -s /lib/systemd/system/network-nat.service /etc/systemd/system/multi-user.target.wants/network-nat.service
sudo chmod +x /usr/bin/network-nat.sh

sudo sed -i "s/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/g" /etc/sysctl.conf

sudo su
#sudo echo "# configuration with static MACK address" >> /etc/network/interfaces
sudo echo "auto eth0" >> /etc/network/interfaces
sudo echo "iface eth0 inet dhcp" >> /etc/network/interfaces
sudo echo "hwaddress ether b8:27:eb:6d:42:7b" >> /etc/network/interfaces

sudo echo "auto enxe46f13f4fad9" >> /etc/network/interfaces
sudo echo "iface enxe46f13f4fad9 inet static" >> /etc/network/interfaces
sudo echo "address 192.168.1.1" >> /etc/network/interfaces
sudo echo "netmask 255.255.255.0" >> /etc/network/interfaces
sudo echo "network 192.168.1.0" >> /etc/network/interfaces

