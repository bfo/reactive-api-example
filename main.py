#!env python
import asyncio
from dataclasses import dataclass
from functools import partial, wraps
from operator import add
from time import time

from fastapi import FastAPI
from fastapi.params import Query
from lenses import lens
from rx import operators as op
from rx.scheduler.eventloop import AsyncIOScheduler

import effects

initial_state = {
    "counters": {
        "plusone": 0,
    },
}

loop = asyncio.get_event_loop()
scheduler = AsyncIOScheduler(loop)
api = effects.API(scheduler=scheduler, loop=loop)
state = effects.State(initial_state, scheduler=scheduler)

app = FastAPI()
app.subscriptions = []


@app.get("/plusone")
async def root(id: int = Query(...)):
    before = time()
    res = await api.on_request(IncreaseByOne(id=id))
    after = time()
    print(f"request took {(after - before) * 1000000} us")
    return res


@app.get("/plustwo")
async def root(id: int = Query(...)):
    before = time()
    res = await api.on_request(IncreaseByTwo(id=id))
    after = time()
    print(f"request took {(after - before) * 1000000} us")
    return res


@app.get("/counter")
async def get_counter(name: str = Query(...)):
    res = await api.on_request(GetCounter(name=name))
    return res


def tagged(f):
    @wraps(f)
    def _(arg):
        return (arg, f(arg))

    return _


def arrowmap(f):
    def _(input):
        return input.pipe(op.map(tagged(f)))

    return _


def map_to(item):
    def _(input):
        return input.pipe(op.map(lambda *args, **kwargs: item))

    return _


@dataclass
class IncreaseByOne:
    id: str

    def do(self):
        return self.id + 1


@dataclass
class IncreaseByTwo:
    id: str

    def do(self):
        return self.id + 2


@dataclass
class GetCounter:
    name: str


@app.on_event("startup")
def bind():
    api.requests.pipe(
        api.select(IncreaseByOne),
        arrowmap(IncreaseByOne.do),
        api.respond,
    )

    api.requests.pipe(
        api.select(IncreaseByTwo),
        arrowmap(IncreaseByTwo.do),
        api.respond,
    )

    plusone_counter_lens = lens.GetItem("counters").GetItem("plusone")
    counter_values = state.changes.pipe(
        op.filter(effects.select(plusone_counter_lens)),
        op.map(effects.focus),
        op.start_with(0),
    )
    api.requests.pipe(
        api.select(GetCounter),
        op.with_latest_from(counter_values),
        api.respond,
    )

    api.requests.pipe(
        api.select(IncreaseByOne),
        map_to((plusone_counter_lens, partial(add, 1))),
        state.apply,
    )

    # Bind all streams
    app.subscriptions = [api.run(), state.run()]


@app.on_event("shutdown")
def unbind():
    for s in app.subscriptions:
        s.dispose()
