import time
import paho.mqtt.client as paho
import smbus2 as smbus

bus = smbus.SMBus(1)
broker="10.42.0.2"

def set_i2c_enabled(register, pin):
    bus.write_byte(register, pin)

def set_i2c_disabled(register, pin):
    bus.write_byte(register, pin)

def on_message(client, userdata, message):
    result = str(message.payload.decode("utf-8"))
    print("received message =", result, client, userdata)
    if result == "ON" :
        set_i2c_enabled(0x20, 0)
    elif result == "OFF" :
        set_i2c_disabled(0x20, 255)
    client.publish("home/bedroom/switch1",result)#publish

client=paho.Client("test-2")
client.on_message=on_message
client.connect(broker)
client.loop_start()
print("subscribing ")
client.subscribe("home/bedroom/switch1/set")
while not 0: time.sleep(0.1)

client.disconnect() #disconnect
client.loop_stop() #stop loop
