"""Bind existing native domain operations into a worker's SQL transaction."""
import copy
from contextlib import contextmanager
class BoundEngine:
    def __init__(self,engine,connection):self.url,self.connection=engine.url,connection
    @contextmanager
    def begin(self):
        with self.connection.begin_nested():yield self.connection
    @contextmanager
    def connect(self):yield self.connection
def bound_store(store,connection):
    bound=copy.copy(store);bound.engine=BoundEngine(store.engine,connection);return bound
