from typing import Any, Dict, Tuple

import pytest
import rx
from lenses import lens
from rx import operators
from rx.scheduler.eventloop.asyncioscheduler import AsyncIOScheduler

import effects


@pytest.mark.asyncio
async def test_creating_state_element_dynamically_class(event_loop):
    scheduler = AsyncIOScheduler(event_loop)
    state = effects.State(dict(), scheduler=scheduler)

    state_xform_stream = rx.of((lens, lambda _: {"new": True}))
    changes_stream = state.apply(state_xform_stream)

    results = []
    result_stream = changes_stream.pipe(
        operators.take(1),
    )
    result_stream.subscribe(results.append, scheduler=scheduler)

    state.run()
    await result_stream

    assert results == [{"new": True}]
