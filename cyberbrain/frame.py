from __future__ import annotations

from collections import defaultdict
from copy import copy
from typing import Any

from deepdiff import DeepDiff, Delta

from . import value_stack, utils
from .basis import Event, InitialValue, Creation, Mutation, Deletion, EventType

_INITIAL_STATE = -1


class _EventsDict(defaultdict):
    def __contains__(self, name):
        events = self[name]
        if not events:
            return False

        if isinstance(events[-1], Deletion):
            # If last event is a deletion, the name should be considered non-existent.
            return False

        return True


class Frame:
    """Stores frame state events and checkpoints.

    Two major functionalities this class provide:
    1. Tells the value of an identifier given a code location.
    2. Easier back tracing.

    TODO: corner cases to be handled:
        - delete, then create again
    """

    def __init__(self, filename, offset_to_lineno):
        # ################### Frame attribute ####################
        self.filename = filename
        self.offset_to_lineno = offset_to_lineno

        self.value_stack = value_stack.create_value_stack()

        # ################### Frame state ####################
        self.raw_events: dict[str, list[Event]] = _EventsDict(list)
        self.snapshots: list[Snapshot] = [
            # The initial state, where pointer points to zero for every identifier.
            Snapshot(events_pointer=defaultdict(lambda: _INITIAL_STATE))
        ]
        self._latest_snapshot = self.snapshots[0]

        # ################### Relevant frames ####################
        # Frame that generated this frame. Could be empty if this frame is the outermost
        # frame.
        self.parent: Optional[Frame] = None
        # Frames derived from this frame.
        self.children: list[Frame] = []

    @property
    def latest_snapshot(self):
        return self._latest_snapshot

    def log_initial_value_events(self, frame: FrameType, instr: Instruction):
        from .api import Tracer

        target = instr.argval
        # Ignore events generated by tracer.register() and builtins like "range"
        if (
            isinstance(frame.f_locals.get(target, None), Tracer)
            or target in frame.f_builtins
        ):
            return
        # Logs InitialValue event if it hasn't been recorded yet.
        if utils.name_exist_in_frame(target, frame) and not self._knows(target):
            self._add_new_event(
                InitialValue(
                    target=target,
                    value=utils.deepcopy_value_from_frame(target, frame),
                    lineno=self.offset_to_lineno[instr.offset],
                    filename=self.filename,
                )
            )

    def log_events(self, frame: FrameType, instr: Instruction, jumped: bool = False):
        """Logs changed values by the given instruction, if any."""
        event_info = self.value_stack.emit_event_and_update_stack(
            instr=instr, frame=frame, jumped=jumped
        )
        if not event_info:
            del frame
            return

        target = event_info.target

        if event_info.type is EventType.Mutation:
            if self._knows(target):
                # TODO: If event is a mutation, compare new value with old value
                #  , discard event if target's value hasn't change.
                # noinspection PyArgumentList
                event = Mutation(
                    target=target,
                    filename=self.filename,
                    lineno=self.offset_to_lineno[instr.offset],
                    delta=Delta(
                        diff=DeepDiff(
                            self._latest_value_of(target),
                            utils.get_value_from_frame(target, frame),
                        )
                    ),
                    sources=event_info.sources,
                )
            else:
                event = Creation(
                    target=target,
                    value=utils.deepcopy_value_from_frame(target, frame),
                    sources=event_info.sources,
                    filename=self.filename,
                    lineno=self.offset_to_lineno[instr.offset],
                )
        elif event_info.type is EventType.Deletion:
            event = Deletion(
                target=target,
                filename=self.filename,
                lineno=self.offset_to_lineno[instr.offset],
            )

        # print(cyan(str(change)))
        self._add_new_event(event)

        del frame

    def _add_new_event(self, event: Event):
        assert event.target
        assert not (
            self.raw_events[event.target] and isinstance(event, InitialValue)
        ), "InitialValue shouldn't be added twice"
        self.raw_events[event.target].append(event)

        # Creates a new snapshot by incrementing the target index.
        new_events_pointer = self.snapshots[-1].events_pointer.copy()
        new_events_pointer[event.target] += 1
        new_snapshot = Snapshot(events_pointer=new_events_pointer)
        self._latest_snapshot = new_snapshot
        self.snapshots.append(new_snapshot)

    def _knows(self, name: str) -> bool:
        return name in self.raw_events

    def _latest_value_of(self, name: str) -> Any:
        """Returns the latest value of an identifier.

        This method is *only* used during the logging process.
        """
        if name not in self.raw_events:
            raise AttributeError(f"'{name}' does not exist in frame.")

        relevant_events = self.raw_events[name]
        assert type(relevant_events[0]) in {InitialValue, Creation}

        value = relevant_events[0].value  # initial value
        for mutation in relevant_events[1:]:
            assert type(mutation) is Mutation, repr(mutation)
            value += mutation.delta

        return value

    @property
    def accumulated_events(self) -> dict[str, list[Event]]:
        """Returns events with accumulated value.

        Now that FrameState only stores delta for Mutation event, if we need to know
        the value after a certain Mutation event (like in tests), the value has to be
        re-calculated. This method serves this purpose. Other events are kept unchanged.

        e.g.

        raw events:
            {'a': [Creation(value=[]), Mutation(delta="append 1")]

        Returned accumulated events:
            {'a': [Creation(value=[]), Mutation(delta="append 1", value=[1])]
        """
        result: dict[str, list[Event]] = defaultdict(list)
        for name, raw_events in self.raw_events.items():
            for raw_event in raw_events:
                if not isinstance(raw_event, Mutation):
                    result[name].append(raw_event)
                    continue
                event = copy(raw_event)
                event.value = result[name][-1].value + raw_event.delta
                result[name].append(event)

        return result

    def get_tracing_result(self) -> dict[str, list[str]]:
        """Do tracing.

        Given code like:

        x = "foo"
        y = "bar"
        x, y = y, x

        which has events:
            {
                "x": [
                    Creation(target="x", value="foo", uid='1'),
                    Mutation(target="x", value="bar", sources={"y"}, uid='2'),
                ],
                "y": [
                    Creation(target="y", value="bar", uid='3'),
                    Mutation(target="y", value="foo", sources={"x"}, uid='4'),
                ]
            }

        Tracing result would be:

            {
                '2': ['3'],
                '4': ['1']
            }

        However if we use the most naive method, which look at all identifiers in
        sources and find its previous event, we would end up with:

            {
                '2': ['3'],
                '4': ['2']
            }

        Prerequisite: 需要区分 mutation 和 binding. Binding 的话就不更新 value stack，
        mutation 的话需要更新

        TODO: 可以这样解决。value stack 中不仅记录 identifier，还记录 snapshot
            就这个例子而言，在
            Mutation(target="x", value="bar", sources={"y"}, uid='2')
            发生之后，应该更新 value stack 中所有的 'x'
            原来是 'x', 现在变成 ('x', snapshot=get_latest_snapshot())
            然后再记录 mutation 并添加 snapshot。
            这样的好处是，之后从 value stack 弹出的时候，就可以知道具体是哪个 snapshot 里的 x
            比如
            Mutation(target="y", value="foo", sources={("x", snapshot=...)}, uid='4')
            我们就知道，y 的变化来源于发生变动之前的 x，而不是变动之后的 x
            这样才能生成正确的 tracing result.

        frame_tree 查询逻辑可以先不实现，直接返回唯一一个 frame

        现有的 test 可以沿用，在 assert tracing_result 的时候，因为 event.uid 没办法获知，需要实现
        从 event 信息反查，即
        tracing_result = {
          get_uid(Mutation(target='x', lineno=2)): [
            get_uid(Creation(target='y', lineno=1)
          ]
        }
        这其实也不难做到
        """


class Snapshot:
    """Represents a frame's state at a certain moment.

    Given an event, Snapshot can help you find other variable's value at the same
    point of program execution.
    e.g. What's `b`'s value when `a` is set to 1
    """

    # TODO: Snapshot should contain, but not keyed by code location, because code
    #  location can duplicate.

    __slots__ = ["events_pointer", "location"]

    def __init__(self, events_pointer, location=None):
        self.location = location
        self.events_pointer: dict[str, int] = events_pointer
