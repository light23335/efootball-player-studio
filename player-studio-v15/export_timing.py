"""Exclusive wall-clock phases; no guessed percentage attribution."""
import time

class ExportTimings:
    def __init__(self):
        self.started=self.last=time.perf_counter();self.phases={}

    def mark(self,name):
        now=time.perf_counter();self.phases[name]=self.phases.get(name,0.0)+now-self.last;self.last=now

    def snapshot(self):
        return {'clock':'perf_counter','phases_seconds':dict(self.phases),
                'total_to_report_seconds':time.perf_counter()-self.started,
                'scope':'worker start through registry saving; excludes report serialization and temporary-file cleanup'}
