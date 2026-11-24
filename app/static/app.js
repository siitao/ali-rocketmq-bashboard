(function () {
  "use strict";

  // Dismiss flash messages.
  document.querySelectorAll("[data-dismiss]").forEach(function (button) {
    button.addEventListener("click", function () {
      var flash = button.closest(".flash");
      if (flash) flash.remove();
    });
  });

  // Auto-dismiss success / info flashes after a few seconds.
  document.querySelectorAll(".flash-success, .flash-info").forEach(function (flash) {
    window.setTimeout(function () {
      flash.style.transition = "opacity .3s ease";
      flash.style.opacity = "0";
      window.setTimeout(function () { flash.remove(); }, 320);
    }, 6000);
  });

  // Instance switcher submits immediately.
  document.querySelectorAll("[data-instance-select]").forEach(function (select) {
    select.addEventListener("change", function () {
      if (select.form) select.form.submit();
    });
  });

  // Destructive actions ask for confirmation (message supplied by the template).
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var message = form.getAttribute("data-confirm") || "确认执行该操作？";
      if (!window.confirm(message)) event.preventDefault();
    });
  });

  // Prevent double submission once the user confirms.
  document.querySelectorAll("form[data-once]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var button = form.querySelector("button[type=submit]");
      if (button) {
        window.setTimeout(function () {
          if (event.defaultPrevented) return;
          button.disabled = true;
          button.textContent = button.getAttribute("data-busy-text") || "处理中…";
        }, 0);
      }
    });
  });

  // Copy-to-clipboard buttons.
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = document.querySelector(button.getAttribute("data-copy"));
      var text = target ? (target.value || target.textContent) : "";
      if (!text) return;
      var done = function () {
        var original = button.textContent;
        button.textContent = "已复制";
        window.setTimeout(function () { button.textContent = original; }, 1400);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done);
      } else {
        var area = document.createElement("textarea");
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
        done();
      }
    });
  });

  // Back links that do not require inline handlers (CSP friendly).
  document.querySelectorAll("[data-back]").forEach(function (button) {
    button.addEventListener("click", function () {
      window.history.back();
    });
  });

  // Searchable combobox for the Topic field (native datalist cannot be styled).
  document.querySelectorAll("[data-combobox]").forEach(function (root) {
    var input = root.querySelector("[data-combobox-input]");
    var menu = root.querySelector("[data-combobox-menu]");
    var toggle = root.querySelector("[data-combobox-toggle]");
    var empty = root.querySelector("[data-combobox-empty]");
    var options = Array.prototype.slice.call(root.querySelectorAll("[data-combobox-option]"));
    var visible = options.slice();
    var activeIndex = -1;

    if (!input || !menu) return;

    function setActive() {
      options.forEach(function (option) {
        var isActive = visible[activeIndex] === option;
        option.classList.toggle("active", isActive);
        option.setAttribute("aria-selected", isActive ? "true" : "false");
      });
    }

    function filter() {
      var query = input.value.trim().toLowerCase();
      visible = options.filter(function (option) {
        return !query || option.getAttribute("data-value").toLowerCase().indexOf(query) !== -1;
      });
      options.forEach(function (option) {
        option.hidden = visible.indexOf(option) === -1;
      });
      if (empty) empty.hidden = visible.length !== 0;
      activeIndex = -1;
      setActive();
    }

    function open() {
      filter();
      menu.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }

    function close() {
      menu.hidden = true;
      input.setAttribute("aria-expanded", "false");
      activeIndex = -1;
      setActive();
    }

    function choose(option) {
      input.value = option.getAttribute("data-value");
      close();
      input.focus();
    }

    function move(delta) {
      if (menu.hidden) open();
      if (!visible.length) return;
      if (activeIndex === -1) {
        activeIndex = delta > 0 ? 0 : visible.length - 1;
      } else {
        activeIndex = (activeIndex + delta + visible.length) % visible.length;
      }
      setActive();
      visible[activeIndex].scrollIntoView({ block: "nearest" });
    }

    input.addEventListener("focus", open);
    input.addEventListener("input", open);
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        move(1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        move(-1);
      } else if (event.key === "Enter") {
        if (!menu.hidden && activeIndex >= 0 && visible[activeIndex]) {
          event.preventDefault();
          choose(visible[activeIndex]);
        }
      } else if (event.key === "Escape" || event.key === "Tab") {
        close();
      }
    });
    input.addEventListener("blur", function () {
      window.setTimeout(close, 120);
    });

    if (toggle) {
      toggle.addEventListener("mousedown", function (event) {
        event.preventDefault();
      });
      toggle.addEventListener("click", function () {
        if (menu.hidden) {
          input.focus();
          open();
        } else {
          close();
        }
      });
    }

    options.forEach(function (option) {
      option.addEventListener("mousedown", function (event) {
        event.preventDefault();
      });
      option.addEventListener("click", function () {
        choose(option);
      });
    });

    document.addEventListener("mousedown", function (event) {
      if (!root.contains(event.target)) close();
    });
  });

  // Custom datetime picker: the native control's popup cannot be styled.
  var WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"];

  function pad2(value) {
    return value < 10 ? "0" + value : String(value);
  }

  function parseDateValue(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value || "");
    if (!match) return null;
    return new Date(
      Number(match[1]),
      Number(match[2]) - 1,
      Number(match[3]),
      Number(match[4]),
      Number(match[5]),
      0,
      0
    );
  }

  function formatDateValue(date) {
    return (
      date.getFullYear() + "-" + pad2(date.getMonth() + 1) + "-" + pad2(date.getDate()) +
      "T" + pad2(date.getHours()) + ":" + pad2(date.getMinutes())
    );
  }

  function formatDateLabel(date) {
    return (
      date.getFullYear() + "-" + pad2(date.getMonth() + 1) + "-" + pad2(date.getDate()) +
      " " + pad2(date.getHours()) + ":" + pad2(date.getMinutes())
    );
  }

  function dateKey(date) {
    return date.getFullYear() + "-" + pad2(date.getMonth() + 1) + "-" + pad2(date.getDate());
  }

  function sameDay(left, right) {
    return dateKey(left) === dateKey(right);
  }

  function closeDatetimePopovers(exceptRoot) {
    document.querySelectorAll("[data-datetime-picker]").forEach(function (picker) {
      if (picker === exceptRoot) return;
      var popover = picker.querySelector("[data-datetime-popover]");
      var trigger = picker.querySelector("[data-datetime-trigger]");
      if (popover && !popover.hidden) {
        popover.hidden = true;
        if (trigger) trigger.setAttribute("aria-expanded", "false");
      }
    });
  }

  document.querySelectorAll("[data-datetime-picker]").forEach(function (root) {
    var trigger = root.querySelector("[data-datetime-trigger]");
    var label = root.querySelector("[data-datetime-label]");
    var hidden = root.querySelector("[data-datetime-value]");
    var popover = root.querySelector("[data-datetime-popover]");
    if (!trigger || !label || !hidden || !popover) return;

    var draft = new Date();
    var viewYear = draft.getFullYear();
    var viewMonth = draft.getMonth();
    var monthLabel;
    var daysGrid;
    var hourSelect;
    var minuteSelect;

    popover.innerHTML =
      '<div class="datetime-head">' +
        '<button type="button" class="datetime-nav" data-prev aria-label="上个月">‹</button>' +
        '<span class="datetime-month" data-month></span>' +
        '<button type="button" class="datetime-nav" data-next aria-label="下个月">›</button>' +
      '</div>' +
      '<div class="datetime-weekdays">' +
        WEEKDAY_LABELS.map(function (day) { return "<span>" + day + "</span>"; }).join("") +
      '</div>' +
      '<div class="datetime-days" data-days></div>' +
      '<div class="datetime-footer">' +
        '<button type="button" class="datetime-now" data-now>现在</button>' +
        '<select class="datetime-select" data-hour aria-label="小时"></select>' +
        '<span>:</span>' +
        '<select class="datetime-select" data-minute aria-label="分钟"></select>' +
        '<span class="spacer"></span>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-cancel>取消</button>' +
        '<button type="button" class="btn btn-primary btn-sm" data-apply>确定</button>' +
      '</div>';

    monthLabel = popover.querySelector("[data-month]");
    daysGrid = popover.querySelector("[data-days]");
    hourSelect = popover.querySelector("[data-hour]");
    minuteSelect = popover.querySelector("[data-minute]");

    for (var hour = 0; hour < 24; hour += 1) {
      hourSelect.appendChild(new Option(pad2(hour), pad2(hour)));
    }
    for (var minute = 0; minute < 60; minute += 1) {
      minuteSelect.appendChild(new Option(pad2(minute), pad2(minute)));
    }

    function render() {
      monthLabel.textContent = viewYear + "年" + (viewMonth + 1) + "月";
      hourSelect.value = pad2(draft.getHours());
      minuteSelect.value = pad2(draft.getMinutes());

      var firstOfMonth = new Date(viewYear, viewMonth, 1);
      var offset = (firstOfMonth.getDay() + 6) % 7; // Monday-first grid
      var cells = [];
      var previousMonthDays = new Date(viewYear, viewMonth, 0).getDate();
      for (var index = 0; index < offset; index += 1) {
        cells.push({
          date: new Date(viewYear, viewMonth - 1, previousMonthDays - offset + index + 1),
          outside: true
        });
      }
      var daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
      for (var day = 1; day <= daysInMonth; day += 1) {
        cells.push({ date: new Date(viewYear, viewMonth, day), outside: false });
      }
      var nextMonthDay = 1;
      while (cells.length < 42) {
        cells.push({ date: new Date(viewYear, viewMonth + 1, nextMonthDay), outside: true });
        nextMonthDay += 1;
      }

      var today = new Date();
      daysGrid.innerHTML = cells.map(function (cell) {
        var classes = ["datetime-day"];
        if (cell.outside) classes.push("outside");
        if (sameDay(cell.date, today)) classes.push("today");
        if (sameDay(cell.date, draft)) classes.push("selected");
        return (
          '<button type="button" class="' + classes.join(" ") + '" data-day="' +
          dateKey(cell.date) + '"' +
          (sameDay(cell.date, draft) ? ' aria-pressed="true"' : "") + ">" +
          cell.date.getDate() + "</button>"
        );
      }).join("");
    }

    function positionPopover() {
      var rect = trigger.getBoundingClientRect();
      var width = popover.offsetWidth;
      var height = popover.offsetHeight;
      var margin = 12;
      var gap = 6;
      var spaceBelow = window.innerHeight - rect.bottom - margin - gap;
      var spaceAbove = rect.top - margin - gap;
      var openUp = spaceBelow < height && spaceAbove > spaceBelow;
      var maxHeight = Math.max(220, openUp ? spaceAbove : spaceBelow);
      popover.style.maxHeight = maxHeight + "px";
      height = Math.min(height, maxHeight);
      var top = openUp ? Math.max(margin, rect.top - gap - height) : rect.bottom + gap;
      var left = Math.min(Math.max(margin, rect.left), window.innerWidth - width - margin);
      popover.style.top = top + "px";
      popover.style.left = left + "px";
    }

    function open() {
      closeDatetimePopovers(root);
      draft = parseDateValue(hidden.value) || new Date();
      viewYear = draft.getFullYear();
      viewMonth = draft.getMonth();
      render();
      popover.hidden = false;
      popover.style.visibility = "hidden";
      trigger.setAttribute("aria-expanded", "true");
      positionPopover();
      popover.style.visibility = "";
      popover.focus();
    }

    function close() {
      popover.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }

    function apply() {
      hidden.value = formatDateValue(draft);
      label.textContent = formatDateLabel(draft);
      label.classList.remove("empty");
      close();
      hidden.dispatchEvent(new Event("change", { bubbles: true }));
      trigger.focus();
    }

    trigger.addEventListener("click", function () {
      if (popover.hidden) {
        open();
      } else {
        close();
      }
    });

    popover.addEventListener("click", function (event) {
      var button = event.target.closest("button");
      if (!button) return;

      if (button.hasAttribute("data-prev") || button.hasAttribute("data-next")) {
        viewMonth += button.hasAttribute("data-prev") ? -1 : 1;
        if (viewMonth < 0) {
          viewMonth = 11;
          viewYear -= 1;
        } else if (viewMonth > 11) {
          viewMonth = 0;
          viewYear += 1;
        }
        render();
      } else if (button.hasAttribute("data-day")) {
        var parts = button.getAttribute("data-day").split("-");
        draft.setFullYear(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
        viewYear = draft.getFullYear();
        viewMonth = draft.getMonth();
        render();
      } else if (button.hasAttribute("data-now")) {
        draft = new Date();
        viewYear = draft.getFullYear();
        viewMonth = draft.getMonth();
        render();
      } else if (button.hasAttribute("data-cancel")) {
        close();
        trigger.focus();
      } else if (button.hasAttribute("data-apply")) {
        apply();
      }
    });

    popover.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        trigger.focus();
      }
    });

    hourSelect.addEventListener("change", function () {
      draft.setHours(Number(hourSelect.value));
    });
    minuteSelect.addEventListener("change", function () {
      draft.setMinutes(Number(minuteSelect.value));
    });

    document.addEventListener("mousedown", function (event) {
      if (!popover.hidden && !root.contains(event.target)) close();
    });

    window.addEventListener("scroll", function (event) {
      if (popover.hidden) return;
      if (event.target && event.target.nodeType === 1 && popover.contains(event.target)) return;
      positionPopover();
    }, true);
    window.addEventListener("resize", function () {
      if (!popover.hidden) positionPopover();
    });

    var initialValue = parseDateValue(hidden.value);
    if (initialValue) {
      label.textContent = formatDateLabel(initialValue);
      label.classList.remove("empty");
    } else {
      label.textContent = "请选择时间";
      label.classList.add("empty");
    }
  });

  // Keep message query time range within the server-side limit.
  var rangeForm = document.querySelector("form[data-range-form]");
  var rangeHint = document.querySelector("[data-max-query-hours]");
  var maxHours = rangeHint ? Number(rangeHint.getAttribute("data-max-query-hours")) : null;
  if (rangeForm && maxHours) {
    var startInput = rangeForm.querySelector("[data-range-start]");
    var endInput = rangeForm.querySelector("[data-range-end]");
    var rangeError = rangeForm.querySelector("[data-range-error]");

    var validateRange = function (showError) {
      if (!startInput || !endInput || !startInput.value || !endInput.value) return true;
      var start = new Date(startInput.value);
      var end = new Date(endInput.value);
      var message = "";
      if (isNaN(start.getTime()) || isNaN(end.getTime())) {
        message = "时间格式不正确";
      } else if (end <= start) {
        message = "结束时间必须晚于开始时间";
      } else if (end - start > maxHours * 3600 * 1000) {
        message = "查询时间范围不能超过 " + maxHours + " 小时";
      }
      if (rangeError) {
        rangeError.textContent = message;
        rangeError.hidden = !message || !showError;
      }
      return !message;
    };

    startInput.addEventListener("change", function () { validateRange(false); });
    endInput.addEventListener("change", function () { validateRange(false); });
    rangeForm.addEventListener("submit", function (event) {
      if (!validateRange(true)) {
        event.preventDefault();
        if (rangeError) rangeError.scrollIntoView({ block: "nearest" });
      }
    });
  }
})();
