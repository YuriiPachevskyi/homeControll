cmake_minimum_required(VERSION 3.5)

install(FILES scripts/hass-io.service DESTINATION /lib/systemd/system)
install(FILES scripts/hass-io-state.service DESTINATION /lib/systemd/system)
install(FILES scripts/hass-io-state.sh PERMISSIONS OWNER_EXECUTE OWNER_WRITE OWNER_READ DESTINATION /usr/bin)
install(FILES scripts/configuration/configuration.yaml DESTINATION /usr/share/hassio/homeassistant/)
install(FILES scripts/configuration/groups.yaml DESTINATION /usr/share/hassio/homeassistant/)
install(FILES scripts/configuration/switches.yaml DESTINATION /usr/share/hassio/homeassistant/)

