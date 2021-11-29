#!env python
import asyncio
from dataclasses import dataclass
from functools import partial, wraps
from operator import add
from time import time

import rx
from fastapi import FastAPI
from fastapi.params import Query
from lenses import lens
from rx import operators as op
from rx.scheduler.eventloop import AsyncIOScheduler
from rx.subject import Subject

import effects

initial_state = {
    "plusone_counter": 0,
}

loop = asyncio.get_event_loop()
scheduler = AsyncIOScheduler(loop)
(api, on_request) = effects.fast_api(scheduler, loop)
(state, focus, select) = effects.state(initial_state, scheduler=scheduler)

app = FastAPI()


@app.get("/plusone")
async def root(id: int = Query(...)):
    before = time()
    res = await on_request(IncreaseByOne(id=id))
    after = time()
    print(f"request took {(after - before) * 1000000} us")
    return res


@app.get("/plustwo")
async def root(id: int = Query(...)):
    before = time()
    res = await on_request(IncreaseByTwo(id=id))
    after = time()
    print(f"request took {(after - before) * 1000000} us")
    return res


@app.get("/counter")
async def get_counter(name: str = Query(...)):
    res = await on_request(GetCounter(name=name))
    return res


subscriptions = []


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


def match(t, o):
    return isinstance(o, t)


@app.on_event("startup")
def bind():
    # Initial drivers setup
    api_input_stream_proxy = Subject()
    state_input_stream_proxy = Subject()
    requests = api(api_input_stream_proxy)
    state_changes = state(state_input_stream_proxy)

    plusone_requests = requests.pipe(
        op.filter(partial(match, IncreaseByOne)),
    )
    get_counter_requests = requests.pipe(
        op.filter(partial(match, GetCounter)),
    )
    plusone_responses = plusone_requests.pipe(
        arrowmap(IncreaseByOne.do),
    )
    plustwo_responses = requests.pipe(
        op.filter(partial(match, IncreaseByTwo)),
        arrowmap(IncreaseByTwo.do),
    )

    plusone_counter_lens = lens.GetItem("plusone_counter")

    plusone_counter_increments = plusone_requests.pipe(
        map_to((plusone_counter_lens, partial(add, 1))),
    )

    plusone_counter_value_stream = state_changes.pipe(
        op.filter(select(plusone_counter_lens)),
        op.map(focus),
        op.start_with(initial_state["plusone_counter"]),
    )
    get_counter_responses = get_counter_requests.pipe(
        op.with_latest_from(plusone_counter_value_stream),
        op.do_action(lambda v: print(v)),
    )

    # Form sinks
    api_response_stream = rx.merge(
        plusone_responses, plustwo_responses, get_counter_responses
    )
    state_xform_stream = plusone_counter_increments
    # Bind all streams
    subscriptions.append(
        api_response_stream.subscribe(api_input_stream_proxy, scheduler=scheduler)
    )
    subscriptions.append(
        state_xform_stream.subscribe(state_input_stream_proxy, scheduler=scheduler)
    )


@app.on_event("shutdown")
def unbind():
    for s in subscriptions:
        s.dispose()
