#!/bin/sh

### BEGIN INIT INFO
# Provides:          router
# Required-Start:    $local_fs $syslog
# Required-Stop:     $local_fs $syslog
# Default-Start:     2 3 4 5
# Default-Stop:      1
# Short-Description: router
# Description:       router
### END INIT INFO 

WAN=eth0
LAN=enxe46f13f4fad9
LAN_NETWORK=192.168.1.0
LAN_MASK=24

iptables -I FORWARD -i ${LAN} -d ${LAN_NETWORK}/${LAN_MASK} -j DROP
iptables -A FORWARD -i ${LAN} -s ${LAN_NETWORK}/${LAN_MASK} -j ACCEPT
iptables -A FORWARD -i ${WAN} -d ${LAN_NETWORK}/${LAN_MASK} -j ACCEPT
iptables -t nat -A POSTROUTING -s ${LAN_NETWORK}/${LAN_MASK} -o ${WAN} -j MASQUERADE

exit 0

