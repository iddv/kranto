<script lang="ts">
  // Post's own Write a post: "About what?": this week's news, which
  // goes on to Write a post's question, or an idea, which opens Ideas to pick one (a card's sheet
  // has its own Write a post). Nothing is written from here.
  import DialogFrame from "../../ui/DialogFrame.svelte";
  import { WEEK, writePost } from "./post";

  let { close }: { close: () => void } = $props();
  let what = $state<"week" | "idea">("week");
  function next(): void {
    close();
    if (what === "week") writePost(WEEK);
    else location.hash = "#/ideas";
  }
</script>

<DialogFrame title="Write a post about what?" okText="Next" {close} ok={next}>
  <div class="field" role="radiogroup" aria-label="About what" id="about-what">
    <label class="radio"><input type="radio" name="about-what" value="week" bind:group={what} /> This week's news</label>
    <label class="radio"><input type="radio" name="about-what" value="idea" bind:group={what} /> An idea: pick one on Ideas</label>
  </div>
</DialogFrame>
