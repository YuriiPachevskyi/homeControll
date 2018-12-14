#!/bin/bash

sleep 1
# restore switches state
/usr/bin/python3 /home/yuso/work/controllService/state_publisher.py ""

curl -I http://localhost:8123/
while [ $? -ne 0 ]; do
    sleep 3
    curl -I http://localhost:8123/
done

echo "done"

# publish switches state
/usr/bin/python3 /home/yuso/work/controllService/state_publisher.py "/status"

