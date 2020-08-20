/*
If we need to migrate tests to TS, see:
https://dev.to/daniel_werner/testing-typescript-with-mocha-and-chai-5cl8
 */

import pkg from "chai";
import {
  generateNodeUpdate,
  getVisibleEventsAndUpdateLoops,
  Loop,
} from "../src/loop.js";
import chaiSubset from "chai-subset";

const { assert, use } = pkg;
use(chaiSubset);

describe("Test nested loops", function () {
  let events = [
    {
      type: "Binding",
      index: 0,
      offset: 0,
    },
    {
      type: "Binding",
      index: 1,
      offset: 2,
    },
    {
      type: "Binding",
      index: 2,
      offset: 4,
    },
    {
      type: "JumpBackToLoopStart",
      index: 3,
      offset: 6,
      jump_target: 2,
    },
    {
      type: "Binding",
      index: 4,
      offset: 2,
    },
    {
      type: "Binding",
      index: 5,
      offset: 4,
    },
    {
      type: "JumpBackToLoopStart",
      index: 6,
      offset: 6,
      jump_target: 2,
    },
    {
      type: "Binding",
      index: 7,
      offset: 8,
    },
    {
      type: "JumpBackToLoopStart",
      index: 8,
      offset: 10,
      jump_target: 0,
    },
    {
      type: "Binding",
      index: 9,
      offset: 0,
    },
    {
      type: "Binding",
      index: 10,
      offset: 2,
    },
    {
      type: "Binding",
      index: 11,
      offset: 4,
    },
    {
      type: "JumpBackToLoopStart",
      index: 12,
      offset: 6,
      jump_target: 2,
    },
    {
      type: "Binding",
      index: 13,
      offset: 2,
    },
    {
      type: "Binding",
      index: 14,
      offset: 4,
    },
    {
      type: "JumpBackToLoopStart",
      index: 15,
      offset: 6,
      jump_target: 2,
    },
    {
      type: "Binding",
      index: 16,
      offset: 8,
    },
    {
      type: "JumpBackToLoopStart",
      index: 17,
      offset: 10,
      jump_target: 0,
    },
    {
      type: "Binding",
      index: 18,
      offset: 12,
    },
  ];
  let loops = [new Loop(0, 10), new Loop(2, 6)];
  let visibleEvents = getVisibleEventsAndUpdateLoops(events, loops);

  it("Test getVisibleEventsAndUpdateLoops", function () {
    assert.deepEqual(visibleEvents, [
      { type: "Binding", index: 0, offset: 0 },
      { type: "Binding", index: 1, offset: 2 },
      { type: "Binding", index: 2, offset: 4 },
      { type: "JumpBackToLoopStart", index: 3, offset: 6, jump_target: 2 },
      { type: "Binding", index: 7, offset: 8 },
      { type: "JumpBackToLoopStart", index: 8, offset: 10, jump_target: 0 },
      { type: "Binding", index: 18, offset: 12 },
    ]);
    assert.containSubset(loops, [
      {
        startOffset: 0,
        endOffset: 10,
        counter: 0,
        parent: undefined,
        _iterationStarts: new Map([
          ["0", 0],
          ["1", 9],
        ]),
      },
      {
        startOffset: 2,
        endOffset: 6,
        counter: 0,
        parent: {
          endOffset: 10,
        },
        _iterationStarts: new Map([
          ["0,0", 1],
          ["0,1", 4],
          ["1,0", 10],
          ["1,1", 13],
        ]),
      },
    ]);
  });

  it("Test generateNodeUpdate", function () {
    loops[0].counter = 1;
    const [eventsToHide, eventsToShow] = generateNodeUpdate(
      events,
      visibleEvents,
      loops[0]
    );
    assert.deepEqual(Array.from(eventsToHide.values()), [
      { type: "Binding", index: 0, offset: 0 },
      { type: "Binding", index: 1, offset: 2 },
      { type: "Binding", index: 2, offset: 4 },
      {
        type: "JumpBackToLoopStart",
        index: 3,
        offset: 6,
        jump_target: 2,
      },
      { type: "Binding", index: 7, offset: 8 },
      {
        type: "JumpBackToLoopStart",
        index: 8,
        offset: 10,
        jump_target: 0,
      },
    ]);

    assert.deepEqual(Array.from(eventsToShow.values()), [
      { type: "Binding", index: 9, offset: 0 },
      { type: "Binding", index: 10, offset: 2 },
      { type: "Binding", index: 11, offset: 4 },
      {
        type: "JumpBackToLoopStart",
        index: 12,
        offset: 6,
        jump_target: 2,
      },
      { type: "Binding", index: 16, offset: 8 },
      {
        type: "JumpBackToLoopStart",
        index: 17,
        offset: 10,
        jump_target: 0,
      },
    ]);
  });
});