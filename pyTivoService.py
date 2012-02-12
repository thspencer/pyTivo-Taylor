import os
import select
import sys
import time
import win32event
import win32service 
import win32serviceutil 

import pyTivo

class PyTivoService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'pyTivo'
    _svc_display_name_ = 'pyTivo'
    
    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
    
    def mainloop(self):
        httpd = pyTivo.setup(True)
 
        while True:
            sys.stdout.flush()
            (rx, tx, er) = select.select((httpd,), (), (), 5)
            for sck in rx:
                sck.handle_request()
            rc = win32event.WaitForSingleObject(self.stop_event, 5)
            if rc == win32event.WAIT_OBJECT_0 or httpd.stop:
                break

        httpd.beacon.stop()
        return httpd.restart

    def SvcDoRun(self): 
        p = os.path.dirname(__file__)
    
        f = open(os.path.join(p, 'log.txt'), 'w')
        sys.stdout = f
        sys.stderr = f

        while self.mainloop():
            time.sleep(5)

    def SvcStop(self):
        win32event.SetEvent(self.stop_event)

if __name__ == '__main__': 
    win32serviceutil.HandleCommandLine(PyTivoService) 
