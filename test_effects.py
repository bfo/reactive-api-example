from typing import Any, Dict, Tuple
from lenses.ui import UnboundLens

import pytest
import rx
from lenses import lens
from rx import operators
from rx.core.typing import Observable as ObservableT
from rx.scheduler.eventloop.asyncioscheduler import AsyncIOScheduler

import effects


@pytest.mark.asyncio
async def test_creating_state_element_dynamically_class(event_loop):
    scheduler = AsyncIOScheduler(event_loop)
    state = effects.State(dict(), scheduler=scheduler)

    state_xform_stream = rx.of((lens, lambda _: {"new": True}))
    changes_stream = state.save(state_xform_stream)

    results = []
    result_stream = changes_stream.pipe(
        operators.map(effects.focus),
        operators.take(1),
    )
    result_stream.subscribe(results.append, scheduler=scheduler)

    state.run()
    await result_stream

    assert results == [{"new": True}]


@pytest.mark.asyncio
async def test_creating_state_element_dynamically(event_loop):
    scheduler = AsyncIOScheduler(event_loop)
    S = Dict[str, Any]
    StateLens = UnboundLens[S, S, S, S]

    state_xform_stream = rx.of((lens, lambda _: {"new": True}))
    (state, focus, _) = effects.state(dict(), scheduler=scheduler)
    changes_stream: ObservableT[Tuple[StateLens, S]] = state(state_xform_stream)

    results = []
    result_stream: ObservableT[S] = changes_stream.pipe(
        operators.map(focus),
        operators.take(1),
    )
    result_stream.subscribe(results.append, scheduler=scheduler)
    await result_stream

    assert results == [{"new": True}]


@pytest.mark.asyncio
async def test_select_lens(event_loop):
    scheduler = AsyncIOScheduler(event_loop)

    new = lens.GetItem("new")
    old = lens.GetItem("old")

    state_xform_stream = rx.of(
        (new, lambda _: False),
        (old, lambda _: True),
    )
    (state, focus, select) = effects.state(
        {"new": True, "old": False}, scheduler=scheduler
    )
    changes_stream: ObservableT[Tuple[UnboundLens, Dict[str, Any]]] = state(
        state_xform_stream
    )

    results = []
    new_changes: ObservableT[Dict[str, Any]] = changes_stream.pipe(
        operators.filter(select(new)),
        operators.take(1),
    )
    new_changes.subscribe(results.append, scheduler=scheduler)
    old_changes: ObservableT[Dict[str, Any]] = changes_stream.pipe(
        operators.filter(select(old)),
        operators.take(1),
    )
    old_changes.subscribe(results.append, scheduler=scheduler)
    await changes_stream.pipe(operators.take(2))

    assert (new, dict(new=False, old=False)) in results
    assert (old, dict(new=False, old=True)) in results
