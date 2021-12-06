from contextvars import ContextVar
from copy import deepcopy
from functools import partial

import rx
from rx import operators
from rx.disposable.disposable import Disposable


class Effect:
    def __init__(self):
        self.__source_observer = None
        self.__sinks = []
        self.source = operators.share()(rx.create(self.__set_source_observer))

    def __unset_source_observer(self):
        self.__source_observer = None

    def __set_source_observer(self, obs, scheduler):
        self.__source_observer = obs

        return Disposable(self.__unset_source_observer)

    def add_sink(self, stream):
        self.__sinks.append(stream)

    def source_emit(self, value):
        if self.__source_observer is not None:
            self.__source_observer.on_next(value)

    def run(self, obs, *, scheduler):
        return rx.merge(*self.__sinks).subscribe(obs, scheduler=scheduler)


class State:
    def __init__(self, initial_state, *, scheduler) -> None:
        self.__state = deepcopy(initial_state)
        self.__initial_state = initial_state
        self.__scheduler = scheduler
        self.__effect = Effect()

    def __apply_change(self, cmd):
        lens, f = cmd
        new_state = lens.modify(f)(self.__state)
        # Note: __state reference never leaks outstide the state function
        self.__effect.source_emit(new_state)
        self.__state = new_state
        print(f"New state is {new_state}")

    def apply(self, commands):
        self.__effect.add_sink(commands)

    def watch(self, lens):
        def only_watched(state_history):
            prev_state, current_state = state_history
            old_fragment = lens.get()(prev_state)
            new_fragment = lens.get()(current_state)
            if old_fragment != new_fragment:
                return new_fragment

        return self.__effect.source.pipe(
            operators.pairwise(),
            operators.map(only_watched),
            operators.filter(lambda v: v is not None),
            operators.start_with(lens.get()(self.__initial_state)),
            operators.do_action(print),
        )

    def run(self) -> Disposable:
        return self.__effect.run(self.__apply_change, scheduler=self.__scheduler)


def match(t, o):
    return isinstance(o, t)


class API:
    __response_future = ContextVar("response_future")

    def __init__(self, *, scheduler, loop) -> None:
        self.__scheduler = scheduler
        self.__loop = loop
        self.__effect = Effect()

    def __return_response(self, response):
        response_fut = self.__response_future.get()
        response_fut.set_result(response)

    async def on_request(self, request_object):
        response_fut = self.__loop.create_future()
        token = self.__response_future.set(response_fut)
        self.__effect.source_emit(request_object)
        response = await response_fut
        self.__response_future.reset(token)
        return response

    def respond(self, responses_stream):
        self.__effect.add_sink(responses_stream)

    def requests(self, type_):
        return self.__effect.source.pipe(operators.filter(partial(match, type_)))

    def run(self):
        return self.__effect.run(self.__return_response, scheduler=self.__scheduler)
