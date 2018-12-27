import time
import threading
import settings
from subprocess import call

class StateThread(threading.Thread):
     def __init__(self):
         super(StateThread, self).__init__()

     def run(self):
         result = None

         while result != 0 :
             result = call(["curl", "-I", settings.serverAddressAndPort])
             time.sleep(3)
