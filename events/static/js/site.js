$(function () {
  var isAuth = $("body").data("auth") === 1;

  function cookie(name) {
    var m = document.cookie.match("(?:^|; )" + name + "=([^;]*)");
    return m ? decodeURIComponent(m[1]) : "";
  }

  $.ajaxSetup({
    beforeSend: function (xhr, settings) {
      if (settings.type === "POST") {
        xhr.setRequestHeader("X-CSRFToken", cookie("csrftoken") || $("input[name=csrfmiddlewaretoken]").first().val());
      }
    },
  });

  // ---- toasts ----
  var $stack = $("#toasts");
  function toast(text, level, link) {
    var $t = $('<div class="toast-lite"></div>').addClass(level || "info");
    $("<span></span>").text(text).appendTo($t);
    if (link) $("<a></a>").attr("href", link.href).text(link.label).appendTo($t);
    var $close = $('<button type="button" aria-label="Dismiss"><i class="bi bi-x-lg" aria-hidden="true"></i></button>').appendTo($t);
    function dismiss() {
      $t.addClass("leaving");
      setTimeout(function () { $t.remove(); }, 200);
    }
    $close.on("click", dismiss);
    $stack.append($t);
    setTimeout(dismiss, 5000);
  }
  $("#flash li").each(function () { toast($(this).text(), $(this).data("level")); });

  function errorText(xhr) {
    return (xhr.responseJSON && xhr.responseJSON.error) || "Something went wrong. Please try again.";
  }
  function loginToast(message) {
    toast(message, "info", { href: $("body").data("login-url"), label: "Log in" });
  }

  // ---- theme toggle ----
  var $toggle = $("#theme-toggle");
  function syncToggle() {
    var dark = document.documentElement.dataset.theme === "dark";
    $toggle.attr("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  }
  syncToggle();
  $toggle.on("click", function () {
    var next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    document.documentElement.dataset.bsTheme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    syncToggle();
  });

  // ---- save (heart) buttons, on cards and on the event page ----
  $(document).on("click", ".save-btn, #detail-save", function (ev) {
    ev.preventDefault();
    var $b = $(this);
    if (!isAuth) { loginToast("Log in to save events."); return; }
    $b.prop("disabled", true);
    $.post($b.data("save-url"))
      .done(function (data) {
        $b.attr("aria-pressed", data.saved);
        $b.find("i").toggleClass("bi-heart", !data.saved).toggleClass("bi-heart-fill", data.saved);
        if ($b.is("#detail-save")) $b.find("span").text(data.saved ? "Saved" : "Save");
        $b.addClass("pop");
        setTimeout(function () { $b.removeClass("pop"); }, 350);
        toast(data.saved ? "Saved to your list." : "Removed from saved.", "success");
        if (!data.saved && $("body").data("page") === "saved_events") {
          $b.closest(".col-12").fadeOut(200, function () { $(this).remove(); });
        }
      })
      .fail(function (xhr) { toast(errorText(xhr), "error"); })
      .always(function () { $b.prop("disabled", false); });
  });

  // ---- home page: live search, filters, load more ----
  var $form = $("#filter-form");
  if ($form.length) {
    var $grid = $("#event-grid"), $more = $("#load-more"), $moreWrap = $("#load-more-wrap");
    var timer, latest = 0, page = 1;

    function card(e) {
      var $col = $('<div class="col-12 col-md-6 col-xl-4"></div>');
      var $card = $('<article class="card event-card h-100"></article>').attr("style", "--h: " + Number(e.hue)).appendTo($col);
      var $body = $('<div class="card-body d-flex flex-column"></div>').appendTo($card);

      var $top = $('<div class="d-flex justify-content-between align-items-start mb-2"></div>').appendTo($body);
      $('<span class="badge badge-category"></span>').text(e.category).appendTo($top);
      $('<button class="save-btn" type="button"></button>')
        .attr({ "aria-pressed": e.saved, "aria-label": "Save " + e.title, "data-save-url": "/api/events/" + e.id + "/save/" })
        .append($("<i></i>").addClass("bi").addClass(e.saved ? "bi-heart-fill" : "bi-heart").attr("aria-hidden", "true"))
        .appendTo($top);

      var $title = $('<h2 class="h5 card-title"></h2>').appendTo($body);
      $('<a class="stretched-link"></a>').attr("href", e.url).text(e.title).appendTo($title);
      $('<p class="meta mb-1"></p>').append('<i class="bi bi-clock" aria-hidden="true"></i> ').append(document.createTextNode(e.when)).appendTo($body);
      $('<p class="meta mb-3"></p>').append('<i class="bi bi-geo-alt" aria-hidden="true"></i> ').append(document.createTextNode(e.venue)).appendTo($body);

      var $foot = $('<div class="mt-auto"></div>').appendTo($body);
      var taken = e.capacity - e.seats_left;
      $('<div class="seat-bar" role="img"></div>')
        .attr("aria-label", taken + " of " + e.capacity + " seats taken")
        .append($("<span></span>").css("width", e.fill_percent + "%"))
        .appendTo($foot);
      var $label = $('<span class="seat-label"></span>').appendTo($foot);
      if (e.seats_left > 0) {
        if (e.seats_left <= 5) $label.addClass("seat-low").text("Only " + e.seats_left + " left");
        else $label.text(e.seats_left + " seats left");
      } else {
        $label.addClass("seat-full").text("Full · " + (e.waitlist_count ? e.waitlist_count + " on waitlist" : "waitlist open"));
      }
      return $col;
    }

    function skeletons() {
      $grid.empty().attr("aria-busy", "true");
      for (var i = 0; i < 6; i++) {
        $('<div class="col-12 col-md-6 col-xl-4"><div class="skeleton"></div></div>').appendTo($grid);
      }
    }

    function syncUrl() {
      var qs = new URLSearchParams();
      $form.serializeArray().forEach(function (f) {
        if (f.value && !(f.name === "sort" && f.value === "soonest")) qs.append(f.name, f.value);
      });
      var s = qs.toString();
      history.replaceState(null, "", location.pathname + (s ? "?" + s : ""));
    }

    function load(p, replace) {
      var mine = ++latest;
      if (replace) skeletons();
      else $more.prop("disabled", true).text("Loading…");
      $.getJSON($form.data("api-url"), $form.serialize() + "&page=" + p)
        .done(function (data) {
          if (mine !== latest) return;
          if (replace) $grid.empty();
          $.each(data.events, function (_, e) { $grid.append(card(e)); });
          $grid.attr("aria-busy", "false");
          page = data.page;
          $("#result-count").text(data.total + " upcoming event" + (data.total === 1 ? "" : "s"));
          $("#empty-note").toggleClass("d-none", $grid.children().length > 0);
          $moreWrap.toggleClass("d-none", !data.has_next);
          if (replace) syncUrl();
        })
        .fail(function () {
          if (mine !== latest) return;
          $grid.empty().attr("aria-busy", "false");
          toast("Could not load events. Check your connection and try again.", "error");
        })
        .always(function () { $more.prop("disabled", false).text("Load more events"); });
    }

    $form.on("submit", function (ev) { ev.preventDefault(); load(1, true); });
    $form.on("input", "#q", function () { clearTimeout(timer); timer = setTimeout(function () { load(1, true); }, 250); });
    $form.on("change", "input[type=radio], input[type=checkbox], select", function () { load(1, true); });
    $more.on("click", function () { load(page + 1, false); });
  }

  // ---- event page: register, join waitlist, cancel ----
  var $box = $("#register-box"), $btn = $("#register-btn");
  if ($btn.length) {
    var state = String($box.data("state")), position = Number($box.data("position"));
    var full = $box.data("full") === 1, capacity = Number($box.data("capacity"));

    function paint() {
      var label, cls, icon;
      if (state === "confirmed") { label = "Cancel my registration"; cls = "btn-outline-danger"; icon = "bi-x-circle"; }
      else if (state === "waitlisted") { label = "Leave the waitlist (you are #" + position + ")"; cls = "btn-outline-danger"; icon = "bi-hourglass-split"; }
      else if (full) { label = "Join the waitlist"; cls = "btn-accent"; icon = "bi-hourglass-split"; }
      else { label = "Register for this event"; cls = "btn-primary"; icon = "bi-check2-circle"; }
      $btn.attr("class", "btn w-100 " + cls).empty()
        .append($("<i></i>").addClass("bi " + icon).attr("aria-hidden", "true")).append(document.createTextNode(" " + label));
      $box.attr("data-state", state);
    }
    paint();

    $btn.on("click", function () {
      var before = state;
      var url = state === "none" ? $box.data("register-url") : $box.data("cancel-url");
      $btn.prop("disabled", true);
      $.post(url)
        .done(function (data) {
          state = data.state; position = data.position; full = data.seats_left === 0;
          $("#seats-left").text(data.seats_left);
          $("#seat-fill").css("width", Math.round((capacity - data.seats_left) * 100 / capacity) + "%");
          paint();
          if (state === "confirmed") toast("You're in. See you there!", "success");
          else if (state === "waitlisted") toast("You're #" + position + " on the waitlist. We'll move you up automatically.", "info");
          else toast(before === "waitlisted" ? "You left the waitlist." : "Registration cancelled.", "success");
        })
        .fail(function (xhr) {
          if (xhr.status === 401) loginToast(errorText(xhr));
          else toast(errorText(xhr), "error");
        })
        .always(function () { $btn.prop("disabled", false); });
    });
  }

  // ---- share ----
  $("#share-btn").on("click", function () {
    var title = $(this).data("title");
    if (navigator.share) {
      navigator.share({ title: title, url: location.href }).catch(function () {});
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(location.href).then(
        function () { toast("Link copied to your clipboard.", "success"); },
        function () { toast("Could not copy the link. Copy it from the address bar.", "warning"); }
      );
    } else {
      toast("Copy the link from the address bar to share it.", "info");
    }
  });

  // ---- host dashboard: check-in switches ----
  $(document).on("change", ".checkin-box", function () {
    var $c = $(this), want = $c.prop("checked");
    $c.prop("disabled", true);
    $.post($c.data("url"))
      .done(function (data) {
        $c.prop("checked", data.checked_in);
        $("#checked-count").text($(".checkin-box:checked").length);
      })
      .fail(function (xhr) { $c.prop("checked", !want); toast(errorText(xhr), "error"); })
      .always(function () { $c.prop("disabled", false); });
  });
});
