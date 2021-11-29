from copy import deepcopy
from typing import Callable, Generic, List, Optional, Tuple, TypeVar, Union

import rx
from lenses import UnboundLens
from rx import operators
from rx.core.typing import Observable as ObservableT, Observer as ObserverT
from rx.disposable.disposable import Disposable

S = TypeVar("S")
T = TypeVar("T")
A = TypeVar("A")
B = TypeVar("B")

StateTransform = Tuple[UnboundLens[S, T, A, B], Callable[[A], B]]
StateChange = Tuple[UnboundLens[S, T, A, B], T]


def focus(s: StateChange):
    lens, state = s
    return lens.get()(state)


def select(lens_match: UnboundLens[S, T, A, B]):
    def select_(s: StateChange[S, T, A, B]):
        lens, _ = s
        return lens is lens_match

    return select_


class State(Generic[S, T, A, B]):
    def __init__(self, initial_state: S, *, scheduler) -> None:
        self.__state: Union[S, T] = deepcopy(initial_state)
        self.__change_observer: Optional[ObserverT[StateChange[S, T, A, B]]] = None
        self.__state_changes: ObservableT[StateChange[S, T, A, B]] = rx.create(
            self.__register_change_observer
        ).pipe(operators.share())
        self.__command_streams: List[ObservableT[StateTransform[S, T, A, B]]] = []
        self.__scheduler = scheduler

    def __deregister_change_observer(self):
        self.__change_observer = None

    def __register_change_observer(
        self, o: ObserverT[StateChange[S, T, A, B]], scheduler
    ) -> Disposable:
        self.__change_observer = o

        return Disposable(self.__deregister_change_observer)

    def __apply_change(self, cmd: StateChange[S, T, A, B]):
        lens, f = cmd

        new_state = lens.modify(f)(self.__state)
        # Note: __state reference never leaks outstide the state function
        if self.__change_observer is not None:
            self.__change_observer.on_next((lens, new_state))
        self.__state = new_state

    def save(
        self, commands: ObservableT[StateTransform[S, T, A, B]]
    ) -> ObservableT[StateChange[S, T, A, B]]:
        self.__command_streams.append(commands)
        return self.changes()

    def changes(self) -> ObservableT[StateChange[S, T, A, B]]:
        return self.__state_changes

    def run(self) -> Disposable:
        return rx.merge(*self.__command_streams).subscribe(
            self.__apply_change, scheduler=self.__scheduler
        )


def state(initial_state, *, scheduler):
    change_observer = None
    __state = deepcopy(initial_state)

    def deregister_change_observer():
        nonlocal change_observer
        change_observer = None

    def register_change_observer(observer, scheduler):
        nonlocal change_observer
        change_observer = observer

        return Disposable(deregister_change_observer)

    def run(cmd: StateChange):
        lens, f = cmd
        nonlocal __state

        new_state = lens.modify(f)(__state)
        # Note: __state reference never leaks outstide the state function
        if change_observer is not None:
            change_observer.on_next((lens, new_state))
        __state = new_state

    def focus(s: StateChange):
        lens, state = s
        return lens.get()(state)

    def select(lens_match: UnboundLens[S, T, A, B]):
        def select_(s: StateChange):
            lens, _ = s
            return lens is lens_match

        return select_

    def changes(xforms: ObservableT[StateChange]) -> ObservableT[StateChange]:
        xforms.subscribe(run, scheduler=scheduler)
        return rx.create(register_change_observer).pipe(operators.share())

    return (changes, focus, select)


def fast_api(scheduler, loop):
    responses = {}
    request_observer = None

    async def on_request(request_object):
        respose_fut = loop.create_future()
        responses[id(request_object)] = respose_fut
        if request_observer:
            request_observer.on_next(request_object)
        response = await respose_fut
        del responses[id(request_object)]
        return response

    def unsubscribe():
        nonlocal request_observer
        request_observer = None

    def on_request_subscribe(observer, scheduler):
        nonlocal request_observer
        request_observer = observer

        return Disposable(unsubscribe)

    def on_incoming_response(item):
        (request_object, response) = item
        response_fut = responses[id(request_object)]
        response_fut.set_result(response)

    def produce_output(inputs):
        inputs.subscribe(on_incoming_response, scheduler=scheduler)
        return rx.create(on_request_subscribe).pipe(operators.share())

    return (produce_output, on_request)
