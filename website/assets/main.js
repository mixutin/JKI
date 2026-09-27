(() => {
  const root = document.body.dataset.root;
  const dialog = document.getElementById("search-dialog");
  const input = document.getElementById("docs-search");
  const results = document.getElementById("search-results");
  const status = document.getElementById("search-status");
  let index = null;
  let timer;
  let toastTimer;
  function toast(message) {
    const box = document.getElementById("toast");
    box.textContent = message;
    box.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.remove("show"), 2500);
  }
  async function search() {
    const query = input.value.trim().toLowerCase();
    if (!index) {
      try {
        const response = await fetch(root + "search.json");
        if (!response.ok) throw new Error("Search index unavailable");
        index = await response.json();
      } catch {
        status.textContent =
          "Search is unavailable. Browse the documentation using the navigation.";
        return;
      }
    }
    results.replaceChildren();
    if (!query) {
      status.textContent = "Search installation, controls, models, and more.";
      return;
    }
    const words = query.split(/\s+/);
    const matches = index
      .filter((item) =>
        words.every((word) =>
          (item.title + " " + item.text).toLowerCase().includes(word),
        ),
      )
      .sort(
        (a, b) =>
          Number(b.title.toLowerCase().includes(query)) -
          Number(a.title.toLowerCase().includes(query)),
      )
      .slice(0, 10);
    status.textContent = matches.length
      ? matches.length + " matching pages"
      : "No matches. Try a different word.";
    matches.forEach((item) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      const title = document.createElement("strong");
      const excerpt = document.createElement("span");
      a.href = item.url;
      title.textContent = item.title;
      excerpt.textContent = item.description;
      a.append(title, excerpt);
      li.append(a);
      results.append(li);
    });
  }
  document.querySelectorAll("[data-search-open]").forEach((button) =>
    button.addEventListener("click", () => {
      dialog.showModal();
      input.focus();
      search();
    }),
  );
  document
    .querySelector("[data-search-close]")
    .addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      const b = dialog.getBoundingClientRect();
      if (
        event.clientX < b.left ||
        event.clientX > b.right ||
        event.clientY < b.top ||
        event.clientY > b.bottom
      )
        dialog.close();
    }
  });
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(search, 100);
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (dialog.open) dialog.close();
      else {
        dialog.showModal();
        input.focus();
        search();
      }
    }
  });
  document.querySelectorAll("[data-copy]").forEach((button) =>
    button.addEventListener("click", async () => {
      const source = document.getElementById(button.dataset.copy);
      try {
        await navigator.clipboard.writeText(source.innerText);
        toast("Commands copied.");
      } catch {
        const range = document.createRange();
        range.selectNodeContents(source);
        const selection = getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        toast("Commands selected. Press Ctrl+C or ⌘C to copy.");
      }
    }),
  );
  const demoButton = document.getElementById("demo-next");
  if (demoButton) {
    let step = 0;
    const steps = [
      [
        "Here when you need me",
        "One thought can start something good.",
        "01 / Ready to listen",
        "Try the preview",
        8,
      ],
      [
        "Your words, ready to review",
        "Edit the transcript before sending it.",
        "02 / Review your request",
        "Preview the next step",
        35,
      ],
      [
        "Working on your request",
        "Progress comes from observed task events.",
        "03 / Reading the project",
        "See the final step",
        70,
      ],
      [
        "A little clarity, out loud",
        "Spoken answers. The details stay in your conversation.",
        "04 / Preview complete",
        "Try it again",
        100,
      ],
    ];
    demoButton.addEventListener("click", () => {
      step = (step + 1) % steps.length;
      document.getElementById("demo-state").textContent = steps[step][0];
      document.getElementById("demo-copy").textContent = steps[step][1];
      document.querySelector("#demo-progress span").textContent =
        steps[step][2];
      document
        .getElementById("demo-progress")
        .style.setProperty("--progress", steps[step][4] + "%");
      demoButton.textContent = steps[step][3] + " →";
    });
  }
  const sidebar = document.querySelector(".doc-sidebar details");
  if (sidebar) {
    const mobile = matchMedia("(max-width: 800px)");
    const update = () => {
      sidebar.open = !mobile.matches;
    };
    update();
    mobile.addEventListener("change", update);
  }
})();
