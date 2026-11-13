---
name: add-topic
description: Add a topic for Kranto to watch from a few words, in the owner's style, and offer the scout for its sources.
argument-hint: "[what to watch]"
---

Add a topic to Kranto's Watch for: $ARGUMENTS

1. Read the owner's topics (`kranto_read` with path `/api/topics`) and match how they write a
   topic's one sentence.
2. Call `kranto_topic_add` with the name and that one sentence.
3. Offer the scout for its sources (`kranto_topic_scout` with the new topic's id): say its cost
   first and run it only if the owner says yes.
4. Answer in two sentences with the page from the tool's answer as the link.
