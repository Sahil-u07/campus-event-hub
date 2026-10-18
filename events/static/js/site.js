$(function () {
  var csrf = $("input[name=csrfmiddlewaretoken]").first().val();

  $.ajaxSetup({
    beforeSend: function (xhr, settings) {
      if (settings.type === "POST") xhr.setRequestHeader("X-CSRFToken", csrf);
    },
  });

  // ---- home page: live search ----
  var $form = $("#filter-form");
  if ($form.length) {
    var timer;
    var $grid = $("#event-grid");

    function card(e) {
      var $col = $('<div class="col-12 col-md-6 col-lg-4"></div>');
      var $card = $('<article class="card event-card h-100"></article>').appendTo($col);
      var $body = $('<div class="card-body d-flex flex-column"></div>').appendTo($card);

      $('<span class="badge badge-category align-self-start mb-2"></span>').text(e.category).appendTo($body);
      var $title = $('<h2 class="h5 card-title"></h2>').appendTo($body);
      $('<a class="stretched-link"></a>').attr("href", e.url).text(e.title).appendTo($title);
      $('<p class="card-text text-body-secondary mb-1"></p>')
        .append('<i class="bi bi-clock" aria-hidden="true"></i> ').append(document.createTextNode(e.when))
        .appendTo($body);
      $('<p class="card-text text-body-secondary mb-3"></p>')
        .append('<i class="bi bi-geo-alt" aria-hidden="true"></i> ').append(document.createTextNode(e.venue))
        .appendTo($body);

      var $seats = $('<span class="seats"></span>');
      if (e.seats_left > 0) {
        $seats.addClass("seats-ok").text(e.seats_left + (e.seats_left === 1 ? " seat left" : " seats left"));
      } else {
        $seats.addClass("seats-full").text("Full");
      }
      $('<p class="mt-auto mb-0"></p>').append($seats).appendTo($body);
      return $col;
    }

    function load() {
      $.getJSON($form.data("api-url"), $form.serialize())
        .done(function (data) {
          $grid.empty();
          $.each(data.events, function (_, e) { $grid.append(card(e)); });
          var n = data.events.length;
          $("#result-count").text(n + " upcoming event" + (n === 1 ? "" : "s"));
          $("#empty-note").toggleClass("d-none", n > 0);
        })
        .fail(function () {
          $("#result-count").text("Could not load events. Check your connection and try again.");
        });
    }

    $form.on("submit", function (ev) { ev.preventDefault(); load(); });
    $form.on("input change", "#q, #category", function () {
      clearTimeout(timer);
      timer = setTimeout(load, 250);
    });
  }

  // ---- event page: register / cancel ----
  var $btn = $("#register-btn");
  $btn.on("click", function () {
    var registered = $btn.data("registered") === 1;
    var url = registered ? $btn.data("cancel-url") : $btn.data("register-url");
    var $msg = $("#register-msg").removeClass("text-danger text-success").text("");

    $btn.prop("disabled", true);
    $.post(url)
      .done(function (data) {
        $("#seats-left").text(data.seats_left);
        $btn.data("registered", data.registered ? 1 : 0)
          .toggleClass("btn-primary", !data.registered)
          .toggleClass("btn-outline-danger", data.registered)
          .text(data.registered ? "Cancel my registration" : "Register for this event");
        $msg.addClass("text-success").text(data.registered ? "You're in. See you there!" : "Registration cancelled.");
      })
      .fail(function (xhr) {
        var err = xhr.responseJSON && xhr.responseJSON.error;
        $msg.addClass("text-danger").text(err || "Something went wrong. Please try again.");
      })
      .always(function () { $btn.prop("disabled", false); });
  });
});
