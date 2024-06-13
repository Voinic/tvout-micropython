from machine import Pin
from tvout import TVOut

PIN_H = Pin(36)
PIN_L = Pin(37)

tv = TVOut(PIN_L, PIN_H)
tv.fill(0)
tv.text("hello", 5, 5, 255)
tv.text("from TVOut", 5, 15, 255)
tv.text("on ESP32-S3", 5, 25, 255)
tv.text("running", 5, 35, 255)
tv.text("micropython", 5, 45, 255)
tv.show()
tv.begin()
