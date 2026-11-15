// Watch's scope (WT): where an address is in topic-first Watch, the pages' addresses, the old
// ?topic= forms and the Watch door landing on the last topic looked at (per browser).
import { afterEach, describe, expect, it } from "vitest";
import { parse } from "../router";
import { frame, unframe } from "./testing";
import { lastTopic, rememberedTopic, rememberTopic, scopeOf, watchPath, watchRedirect } from "./watchscope";

afterEach(() => {
  localStorage.removeItem("kranto.watch.topic");
  unframe();
});

describe("Watch's scope", () => {
  it("reads a topic and its page, All topics' pages, or the Topics list from the address", () => {
    expect(scopeOf(["watch", "topic", "13", "sources"])).toEqual({ topic: "13", page: "sources" });
    expect(scopeOf(["watch", "topic", "13"])).toEqual({ topic: "13", page: "" });
    expect(scopeOf(["watch", "evidence"])).toEqual({ topic: null, page: "evidence" });
    expect(scopeOf(["watch"])).toEqual({ topic: null, page: null });
    expect(scopeOf(["build"])).toBeNull();
    expect(watchPath(13, "map")).toBe("watch/topic/13/map");
    expect(watchPath("13", "")).toBe("watch/topic/13");
    expect(watchPath(null, "sources")).toBe("watch/sources");
    expect(watchPath(null, "")).toBe("watch");
  });

  it("sends the old ?topic= forms to the topic's page, other filters kept", () => {
    expect(watchRedirect(parse("#/watch/sources?topic=13&status=proposed"))).toEqual({ path: "watch/topic/13/sources", q: { status: "proposed" } });
    expect(watchRedirect(parse("#/watch/map?topic=13"))).toEqual({ path: "watch/topic/13/map", q: {} });
    expect(watchRedirect(parse("#/watch?topic=13"))).toEqual({ path: "watch/topic/13", q: {} });
    expect(watchRedirect(parse("#/watch/topic/13/sources"))).toBeNull();
    expect(watchRedirect(parse("#/watch/sources"))).toBeNull();
  });

  it("remembers the last topic looked at, while it is still one of yours; else the first", async () => {
    await frame(); // the testing host's topics: Clinics (1), Local-first (2)
    expect(rememberedTopic()).toBeNull();
    expect(lastTopic()?.id).toBe(1);
    expect(watchRedirect(parse("#/topics"))).toBeNull(); // nothing remembered: #/topics is Watch's Topics
    rememberTopic(2);
    expect(lastTopic()?.name).toBe("Local-first");
    expect(watchRedirect(parse("#/topics"))).toEqual({ path: "watch/topic/2", q: {} });
    rememberTopic(77); // gone: the first again
    expect(rememberedTopic()).toBeNull();
    expect(lastTopic()?.id).toBe(1);
  });
});
