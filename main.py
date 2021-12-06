#!env python
import asyncio
from dataclasses import dataclass
from functools import partial
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
        "plustwo": 0,
    },
}

lenses = {}
lenses["counters"] = lens.GetItem("counters")
lenses["plusone"] = lenses["counters"].GetItem("plusone")
lenses["plustwo"] = lenses["counters"].GetItem("plustwo")

loop = asyncio.get_event_loop()
scheduler = AsyncIOScheduler(loop)
api = effects.API(scheduler=scheduler, loop=loop)
state = effects.State(initial_state, scheduler=scheduler)

app = FastAPI()
app.subscriptions = []


@app.get("/plusone")
async def plusone(id: int = Query(...)):
    before = time()
    res = await api.on_request(IncreaseByOne(id=id))
    after = time()
    print(f"request took {(after - before) * 1000000} us")
    return res


@app.get("/plustwo")
async def plustwo(id: int = Query(...)):
    before = time()
    res = await api.on_request(IncreaseByTwo(id=id))
    after = time()
    print(f"request took {(after - before) * 1000000} us")
    return res


@app.get("/counter")
async def get_counter(name: str = Query(...)):
    res = await api.on_request(GetCounter(name=name))
    return res


def map_to(item):
    def operator(input):
        return input.pipe(op.map(lambda *args, **kwargs: item))

    return operator


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

    def pluck(self, state):
        try:
            return state[self.name]
        except KeyError:
            return {"error": "counter not found"}



@app.on_event("startup")
def bind():
    api.requests(IncreaseByOne).pipe(
        op.map(IncreaseByOne.do),
        api.respond,
    )

    api.requests(IncreaseByTwo).pipe(
        op.map(IncreaseByTwo.do),
        api.respond,
    )

    counters_values = state.watch(lenses["counters"])

    api.requests(GetCounter).pipe(
        op.with_latest_from(counters_values),
        op.starmap(GetCounter.pluck),
        api.respond,
    )

    api.requests(IncreaseByOne).pipe(
        map_to((lenses["plusone"], partial(add, 1))),
        state.apply,
    )

    # Bind all streams
    app.subscriptions = [api.run(), state.run()]


@app.on_event("shutdown")
def unbind():
    for s in app.subscriptions:
        s.dispose()
