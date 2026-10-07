document.addEventListener("DOMContentLoaded", function () {
  // ---- Mobile menu ----
  const toggle = document.querySelector(".menu-toggle");
  const nav = document.getElementById("site-nav");
  if (toggle && nav) {
    const closeMenu = function () {
      nav.classList.remove("is-open");
      document.body.classList.remove("menu-open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Open menu");
    };

    toggle.addEventListener("click", function () {
      const open = nav.classList.toggle("is-open");
      document.body.classList.toggle("menu-open", open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    });

    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", closeMenu);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        const wasOpen = nav.classList.contains("is-open");
        closeMenu();
        if (wasOpen) toggle.focus();
      }
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 900) closeMenu(); // keep in step with the CSS breakpoint
    });
  }

  // ---- Home: tap a common problem to fill in the box ----
  const problem = document.getElementById("problem");
  const quick = document.querySelector(".quick");
  if (problem && quick) {
    quick.addEventListener("click", function (event) {
      const button = event.target.closest("button[data-text]");
      if (!button) return;
      problem.value = button.dataset.text;
      problem.focus();
      problem.setSelectionRange(problem.value.length, problem.value.length);
    });

    // some problems only make sense for one kind of device (a desktop has no battery)
    const showFor = function (kind) {
      quick.querySelectorAll("[data-only]").forEach(function (button) {
        button.hidden = Boolean(kind) && button.dataset.only !== kind;
      });
    };
    document.querySelectorAll('input[name="device_kind"]').forEach(function (radio) {
      radio.addEventListener("change", function () { showFor(radio.value); });
    });
  }

  // ---- Header gets a soft shadow once the page scrolls ----
  const header = document.querySelector(".site-header");
  if (header) {
    const onScroll = function () { header.classList.toggle("is-scrolled", window.scrollY > 4); };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  // ---- Admin tabs: on a phone, scroll the current tab into view ----
  const currentTab = document.querySelector('.admin-nav [aria-current="page"]');
  if (currentTab) {
    const bar = currentTab.parentElement;
    bar.scrollLeft += currentTab.getBoundingClientRect().left - bar.getBoundingClientRect().left - (bar.clientWidth - currentTab.offsetWidth) / 2;
  }
});
