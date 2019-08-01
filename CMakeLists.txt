cmake_minimum_required(VERSION 3.5)

install(FILES scripts/homeControll.service DESTINATION /lib/systemd/system)
install(FILES scripts/configuration/configuration.yaml DESTINATION /usr/share/hassio/homeassistant/)
install(FILES scripts/configuration/groups.yaml DESTINATION /usr/share/hassio/homeassistant/)
install(FILES scripts/configuration/switches.yaml DESTINATION /usr/share/hassio/homeassistant/)
install(FILES scripts/configuration/switches_state.yaml DESTINATION /usr/share/hassio/homeassistant/)
install(FILES scripts/configuration/inputs.json DESTINATION /usr/share/hassio/homeassistant/)

