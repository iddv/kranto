// The console's three starters: the page's topic else the newest brief's, the
// idea question, and Write a post about this card or brief, else this week's news; the sentence
// sent names what "this" is.
import { describe, expect, it } from "vitest";
import { newestTopic, starters } from "./starters";

const topics = [{ id: 13, name: "Robotics" }, { id: 7, name: "Padel" }];

describe("the console's starters", () => {
  it("asks about the newest brief's topic on the home, and about this week's news", () => {
    const s = starters({ path: ["home"], topics, newest: "Robotics" });
    expect(s.map((x) => x.label)).toEqual(["What is new in Robotics?", "Which idea should I look at?", "Write a post about this week's news"]);
    expect(s.map((x) => x.says)).toEqual(["the newest from your library, with links", "one card from Ideas, and why", "a draft on Post; nothing is sent"]);
    expect(s[2]!.text).toBe("Write a post about this week's news.");
  });

  it("asks about the topic the page is about", () => {
    expect(starters({ path: ["watch", "topic", "7", "sources"], topics, newest: "Robotics" })[0]!.text).toBe("What is new in Padel?");
    expect(starters({ path: ["topics", "7"], topics })[0]!.text).toBe("What is new in Padel?");
    expect(starters({ path: ["news"], topics: [] })[0]!.text).toBe("What is new in my topics?");
  });

  it("writes a post about the card or the brief that is open, naming it", () => {
    for (const p of [{ path: ["ideas", "143"] }, { path: ["ideas", "card:143"] }, { path: ["ideas"], sel: "icard:143" }]) {
      const s = starters({ ...p, topics });
      expect([s[2]!.label, s[2]!.text]).toEqual(["Write a post about this", "Write a post about idea card #143."]);
    }
    expect(starters({ path: ["news", "b", "26"], topics })[2]!.text).toBe("Write a post about the news at #/news/b/26.");
    expect(starters({ path: ["news", "i", "26", "0"], topics })[2]!.text).toBe("Write a post about the news at #/news/i/26/0.");
  });

  // with no brief today the first starter named the first topic ("Local-first
  // software"); it names the topic of the newest brief of any day
  it("names yesterday's brief's topic when today has none", () => {
    const yesterday = { topics: [], newest: { name: "Padel" } };
    expect(newestTopic(yesterday)).toBe("Padel");
    expect(starters({ path: [], topics: [{ id: 1, name: "Local-first software" }], newest: newestTopic(yesterday) })[0]!.text).toBe("What is new in Padel?");
    expect(newestTopic({ topics: [{ topic: { name: "Robotics" } }] })).toBe("Robotics");
    expect(newestTopic(null)).toBeNull();
  });
});
