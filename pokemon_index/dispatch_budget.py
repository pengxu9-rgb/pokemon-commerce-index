"""Shared, thread-safe source request budget; disabled until constructed explicitly.

Controls dispatch admission and checks deadline after return. It does not
interrupt blocked DNS/TLS/socket calls. Individual transports retain their own
timeouts; a hard cross-transport deadline requires a cancellation-aware client.
"""
import threading
import time

class DispatchDenied(ValueError): pass
class DispatchBudget:
    def __init__(self, *, max_requests, seconds, cancelled=lambda:False, clock=time.monotonic):
        if type(max_requests) is not int or not 1<=max_requests<=100 or not isinstance(seconds,(int,float)) or isinstance(seconds,bool) or not 0<seconds<=3600 or not callable(cancelled) or not callable(clock): raise ValueError('invalid dispatch budget')
        self.remaining=max_requests;self.clock=clock;self.cancelled=cancelled;self.deadline=clock()+seconds;self.lock=threading.RLock()
    def check(self):
        with self.lock:
            if self.cancelled():raise DispatchDenied('cancelled')
            remaining=self.deadline-self.clock()
            if remaining<=0:raise DispatchDenied('deadline exceeded')
            return remaining
    def consume(self):
        with self.lock:
            self.check()
            if self.remaining<=0:raise DispatchDenied('budget exhausted')
            self.remaining-=1
