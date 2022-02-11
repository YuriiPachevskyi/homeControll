cmake_minimum_required(VERSION 3.5)

install(FILES ../scripts/homeControll.service DESTINATION /lib/systemd/system)
install(FILES ../scripts/configuration/configuration.yaml DESTINATION $ENV{HOME}/homeControll/configuration)
install(FILES ../scripts/configuration/groups.yaml DESTINATION $ENV{HOME}/homeControll/configuration)
install(FILES ../scripts/configuration/switches.yaml DESTINATION $ENV{HOME}/homeControll/configuration)

